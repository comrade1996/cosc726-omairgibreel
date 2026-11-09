"""MCP host + ReAct agent loop for the ambulance handoff server.

    python -m project.agent.host --case AMB-001                 # offline mock model, interactive approval
    python -m project.agent.host --case AMB-001 --approve auto  # simulated clinician approves
    python -m project.agent.host --case AMB-019                 # incomplete case -> safe block
    python -m project.agent.host --case AMB-001 --model faulty  # controlled failure + recovery demo
    python -m project.agent.host --case AMB-001 --model openai  # real LLM via .env

The host owns everything the model must not: the signing keys, the session token, the
human approval gate, the turn/token budgets and the grounding critic.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError

from .. import PROMPT_VERSION
from ..dataset import crews
from ..envfile import REPO, load_env
from ..security import issue_clinician_approval, issue_session_token, new_key
from .model import Action, ModelClient, make_model

SYSTEM_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "agent_system_v1.txt").read_text()
TRACE_DIR = REPO / "project" / "runtime" / "traces"
CONSEQUENTIAL = {"confirm_handoff"}
FORBIDDEN_CLAIMS = re.compile(r"\b(diagnosed with|(the |final |likely )diagnosis is|i recommend|recommended (treatment|dose)|"
                              r"should (receive|be given|be treated)|consider (giving|administering)|give \d+ ?(mg|ug|ml|g)\b)",
                              re.I)

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        return len(_ENC.encode(text))
    TOKENIZER = "tiktoken cl100k_base"
except Exception:  # offline or not installed
    def count_tokens(text: str) -> int:
        return max(1, len(text) // 4)
    TOKENIZER = "chars/4 estimate"


@dataclass
class Keys:
    session: bytes
    approval: bytes

    @classmethod
    def from_env_or_new(cls) -> "Keys":
        s, a = os.environ.get("AMBULANCE_SESSION_KEY"), os.environ.get("AMBULANCE_APPROVAL_KEY")
        return cls(bytes.fromhex(s), bytes.fromhex(a)) if s and a else cls(new_key(), new_key())


@dataclass
class RunResult:
    case_id: str
    stop_reason: str
    final_text: str
    turns: int
    tool_calls: list[str]
    context_tokens: int
    latency_ms: float
    critic_rejections: int = 0
    unknown_tool_calls: int = 0
    approvals_requested: int = 0
    sent: bool = False
    trace_path: str | None = None
    trace: list[dict] = field(default_factory=list)


def mcp_tools_to_openai(tools) -> list[dict]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                              "parameters": t.inputSchema}} for t in tools]


def _content_text(result) -> str:
    parts = [getattr(c, "text", "") for c in result.content]
    return "\n".join(p for p in parts if p)


@dataclass
class WorkflowState:
    """What the host has observed so far; used by the policy critic."""

    stop_condition: str | None = None
    confirm_attempted: bool = False
    gaps: list[str] = field(default_factory=list)
    case_id: str = ""

    def observe(self, tool: str, observation: str) -> None:
        try:
            data = json.loads(observation[observation.index("{"):])
        except (ValueError, json.JSONDecodeError):
            return
        self.stop_condition = data.get("stop_condition", self.stop_condition)
        if tool == "check_handoff_completeness":
            self.gaps += [m for m in data.get("missing", []) if m not in self.gaps]
        if tool == "validate_fhir_bundle":
            self.gaps += sorted({i["code"] for i in data.get("issues", []) if i["severity"] == "error"} - set(self.gaps))
        if tool == "confirm_handoff":
            self.confirm_attempted = True


def policy_check(text: str, state: WorkflowState) -> list[str]:
    """Reject a final answer that ends the workflow early or hides a gap."""
    problems = []
    if state.stop_condition == "ready_for_confirmation" and not state.confirm_attempted:
        problems.append(f"workflow incomplete: the draft is confirmable, so call confirm_handoff(case_id='{state.case_id}', "
                        f"...) with clinician_confirmation='REQUEST_APPROVAL' (the clinician decides, not you) before "
                        f"the final answer")
    if state.stop_condition and state.stop_condition.startswith("blocked"):
        unnamed = [g for g in state.gaps if g not in text]
        if unnamed:
            problems.append(f"escalation must name every issue exactly as returned; missing: {', '.join(unnamed)}")
    return problems


def critic(text: str, evidence: str, state: WorkflowState | None = None) -> list[str]:
    """Reject final answers with numbers that no tool returned, advice the system must not give,
    or (with a workflow state) an early stop / unnamed gap."""
    problems = policy_check(text, state) if state else []
    for num in set(re.findall(r"(?<![\w.-])\d+(?:\.\d+)?(?![\w.])", text)):
        if num not in evidence:
            problems.append(f"unsupported number {num}")
    if FORBIDDEN_CLAIMS.search(text):
        problems.append("contains diagnosis/treatment advice")
    if re.search(r"\(estimated\)|\bestimate[ds]?\b|\bassum(e|ed)\b", text, re.I):
        problems.append("contains an estimated/assumed value")
    return problems


class ApprovalGate:
    """Human-in-the-loop gate for consequential tools. `mode`: ask | auto | deny."""

    def __init__(self, keys: Keys, mode: str = "ask", clinician_id: str = "ED-CLIN-SIM-01", out=sys.stdout):
        self.keys, self.mode, self.clinician_id, self.out = keys, mode, clinician_id, out
        self.log: list[dict] = []

    def review(self, draft: dict | None, args: dict) -> tuple[bool, str | None, str]:
        if draft is None:
            return False, None, "no draft has been shown to the clinician"
        if draft.get("case_id") != args.get("case_id") or draft.get("receiving_org") != args.get("receiving_org"):
            return False, None, "request does not match the draft the clinician saw"
        if self.mode == "ask":
            print("\n" + "=" * 70 + "\nCLINICIAN APPROVAL REQUIRED (consequential action: confirm_handoff)\n" + "-" * 70, file=self.out)
            print(draft["text"], file=self.out)
            print("-" * 70 + f"\ncase {args['case_id']} v{draft['case_version']} -> {draft['receiving_org']}  "
                  f"draft sha256 {draft['draft_sha256'][:16]}", file=self.out)
            answer = input("Approve sending this handoff? [y/N] ").strip().lower()
            approved = answer in ("y", "yes")
        else:
            approved = self.mode == "auto"
        self.log.append({"case_id": args.get("case_id"), "approved": approved, "draft_sha256": draft["draft_sha256"][:16],
                         "mode": self.mode})
        if not approved:
            return False, None, "clinician declined"
        token = issue_clinician_approval(self.keys.approval, case_id=args["case_id"], case_version=draft["case_version"],
                                         draft_sha256=draft["draft_sha256"], receiving_org=draft["receiving_org"],
                                         clinician_id=self.clinician_id)
        return True, token, "approved"


class MCPExecutor:
    """Tool executor over a live MCP ClientSession (stdio or Streamable HTTP)."""

    def __init__(self, session: ClientSession):
        self.session = session

    async def discover(self) -> dict:
        tools = (await self.session.list_tools()).tools
        templates = (await self.session.list_resource_templates()).resourceTemplates
        static = (await self.session.list_resources()).resources
        prompts = (await self.session.list_prompts()).prompts
        return {"_tools": tools, "tools": sorted(t.name for t in tools),
                "resources": sorted([r.uriTemplate for r in templates] + [str(r.uri) for r in static]),
                "prompts": sorted(p.name for p in prompts)}

    async def call(self, name: str, args: dict) -> tuple[bool, str]:
        result = await self.session.call_tool(name, args)
        if result.structuredContent and not result.isError:
            return False, json.dumps(result.structuredContent)
        return result.isError, _content_text(result)


class Agent:
    """ReAct loop. `session` is an MCP ClientSession or any executor with discover()/call()."""

    def __init__(self, session, model: ModelClient, gate: ApprovalGate, *, max_turns: int = 12,
                 token_budget: int = 60000, max_critic_rejections: int = 2, verbose: bool = True, out=sys.stdout):
        self.executor = session if hasattr(session, "call") else MCPExecutor(session)
        self.model, self.gate = model, gate
        self.max_turns, self.token_budget, self.max_critic = max_turns, token_budget, max_critic_rejections
        self.verbose, self.out = verbose, out
        self.tools: list = []

    def say(self, text: str) -> None:
        if self.verbose:
            print(text, file=self.out)

    async def discover(self) -> dict:
        caps = await self.executor.discover()
        self.tools = caps.pop("_tools")
        return caps

    async def run(self, case_id: str) -> RunResult:
        if not self.tools:
            await self.discover()
        start = time.perf_counter()
        tool_schemas = mcp_tools_to_openai(self.tools)
        names = {t.name for t in self.tools}
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Prepare the ambulance handoff for case {case_id} to the receiving emergency department."}]
        schema_tokens = count_tokens(json.dumps(tool_schemas))
        context_tokens = 0
        trace: list[dict] = []
        calls: list[str] = []
        seen_calls: dict[str, int] = {}
        evidence = ""
        draft: dict | None = None
        state = WorkflowState(case_id=case_id)
        res = RunResult(case_id, "turn_cap", "", 0, calls, 0, 0.0)
        for turn in range(1, self.max_turns + 1):
            res.turns = turn
            prompt_tokens = schema_tokens + count_tokens(json.dumps(messages))
            context_tokens += prompt_tokens
            if context_tokens > self.token_budget:
                res.stop_reason = "token_budget_exhausted"
                break
            t0 = time.perf_counter()
            action: Action = await asyncio.to_thread(self.model.next_action, messages, tool_schemas)
            step = {"turn": turn, "kind": action.kind, "rationale": action.rationale, "prompt_tokens": prompt_tokens,
                    "model_ms": round((time.perf_counter() - t0) * 1000, 2)}
            if action.kind == "final":
                problems = critic(action.text, evidence, state)
                step.update(final=action.text, critic=problems)
                trace.append(step)
                if problems and res.critic_rejections < self.max_critic:
                    res.critic_rejections += 1
                    self.say(f"[{turn}] CRITIC REJECTED final answer: {problems} -> replan")
                    messages += [{"role": "assistant", "content": action.text},
                                 {"role": "user", "content": f"CRITIC: rejected ({'; '.join(problems)}). Rewrite using only "
                                                             f"values that appear in tool results."}]
                    continue
                if problems:
                    action.text = (draft or {}).get("text", "Escalated: answer failed grounding checks.")
                    step["fallback"] = "server draft used verbatim"
                res.final_text, res.stop_reason = action.text, "final_answer"
                self.say(f"[{turn}] FINAL\n{action.text}")
                break

            args_key = json.dumps([action.name, action.arguments], sort_keys=True)
            seen_calls[args_key] = seen_calls.get(args_key, 0) + 1
            messages.append({"role": "assistant", "content": action.rationale or None,
                             "tool_calls": [{"id": action.call_id, "type": "function",
                                             "function": {"name": action.name, "arguments": json.dumps(action.arguments)}}]})
            self.say(f"[{turn}] THINK {action.rationale}\n[{turn}] ACT   {action.name}({_short(action.arguments)})")
            if seen_calls[args_key] > 2:
                res.stop_reason = "loop_detected"
                step.update(tool=action.name, observation="identical call repeated 3 times; stopping")
                trace.append(step)
                break
            if action.name not in names:
                res.unknown_tool_calls += 1
                observation = json.dumps({"ok": False, "error": "unknown_tool", "detail": f"'{action.name}' is not advertised by "
                                          f"this server. Available: {sorted(names)}"})
                is_error = True
            else:
                args = dict(action.arguments)
                proceed = True
                if action.name in CONSEQUENTIAL:
                    res.approvals_requested += 1
                    approved, token, why = self.gate.review(draft, args)
                    step["approval"] = why
                    self.say(f"[{turn}] GATE  clinician approval: {why}")
                    if approved:
                        args["clinician_confirmation"] = token
                    else:
                        proceed = False
                        observation, is_error = json.dumps({"ok": False, "error": "clinician_declined", "detail": why}), True
                if proceed:
                    t1 = time.perf_counter()
                    is_error, observation = await self.executor.call(action.name, args)
                    step["tool_ms"] = round((time.perf_counter() - t1) * 1000, 2)
                calls.append(action.name)
            if action.name == "create_handoff_draft" and not is_error:
                draft = json.loads(observation)
            if action.name == "confirm_handoff" and not is_error:
                res.sent = json.loads(observation).get("status") == "sent"
            evidence += observation
            if action.name in names:
                state.observe(action.name, observation)
            self.say(f"[{turn}] OBS   {'ERROR ' if is_error else ''}{_short_obs(observation)}")
            step.update(tool=action.name, arguments=_redact(action.arguments), is_error=is_error,
                        observation_tokens=count_tokens(observation))
            trace.append(step)
            messages.append({"role": "tool", "tool_call_id": action.call_id, "content": observation})
        res.context_tokens = context_tokens
        res.latency_ms = round((time.perf_counter() - start) * 1000, 2)
        res.trace = trace
        return res


def _redact(args: dict) -> dict:
    return {k: ("<redacted>" if k == "clinician_confirmation" else v) for k, v in args.items()}


def _short(args: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in _redact(args).items())[:160]


def _short_obs(text: str) -> str:
    try:
        d = json.loads(text[text.index("{"):])
    except (ValueError, json.JSONDecodeError):
        return text[:200]
    keys = ["ok", "error", "detail", "stop_condition", "valid", "error_count", "missing", "confirmable", "status", "handoff_id",
            "replayed"]
    return json.dumps({k: d[k] for k in keys if k in d})[:300]


def server_params(keys: Keys, crew_id: str, *, gates: bool = True, audit_path: Path | None = None) -> StdioServerParameters:
    crew = crews()[crew_id]
    token = issue_session_token(keys.session, crew_id, crew["tenant"], crew["cases"])
    env = {"AMBULANCE_SESSION_KEY": keys.session.hex(), "AMBULANCE_APPROVAL_KEY": keys.approval.hex(),
           "AMBULANCE_SESSION_TOKEN": token, "AMBULANCE_GATES": "on" if gates else "off",
           "PYTHONPATH": str(REPO), "PATH": os.environ.get("PATH", "")}
    if audit_path:
        env["AMBULANCE_AUDIT_PATH"] = str(audit_path)
    return StdioServerParameters(command=sys.executable, args=["-m", "project.server"], env=env, cwd=str(REPO))


def crew_for_case(case_id: str) -> str:
    return next(c for c, v in crews().items() if case_id in v["cases"])


async def run_case(case_id: str, model_kind: str, approve: str, verbose: bool = True, crew_id: str | None = None,
                   keys: Keys | None = None) -> RunResult:
    keys = keys or Keys.from_env_or_new()
    crew_id = crew_id or crew_for_case(case_id)
    params = server_params(keys, crew_id)
    async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
        await session.initialize()
        agent = Agent(session, make_model(model_kind), ApprovalGate(keys, approve), verbose=verbose)
        caps = await agent.discover()
        if verbose:
            print(f"Connected over stdio as {crew_id}. Discovered {len(caps['tools'])} tools, "
                  f"{len(caps['resources'])} resources, {len(caps['prompts'])} prompts.\nTools: {', '.join(caps['tools'])}\n")
        result = await agent.run(case_id)
        if result.sent:
            ack = await session.call_tool("record_ed_acknowledgement", {
                "case_id": case_id, "acknowledgement_id": f"ACK-{uuid.uuid4().hex[:8]}",
                "receiving_org": _receiving_from_trace(result)})
            if verbose:
                print(f"\nSimulated ED acknowledgement: {_short_obs(_content_text(ack))}")
        try:
            audit = await session.read_resource(f"ambulance://cases/{case_id}/audit")
            events = json.loads(audit.contents[0].text)["events"]
        except McpError as e:
            events = [{"subtype": [{"code": "read_audit"}], "outcomeDesc": e.error.message[-60:]}]
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    path = TRACE_DIR / f"{case_id}-{model_kind}-{time.strftime('%Y%m%dT%H%M%S')}.json"
    path.write_text(json.dumps({"case_id": case_id, "model": model_kind, "prompt_version": PROMPT_VERSION,
                                "tokenizer": TOKENIZER, "result": {k: v for k, v in result.__dict__.items() if k != "trace"},
                                "trace": result.trace, "audit": events}, indent=1))
    result.trace_path = str(path)
    if verbose:
        print(f"\nStop reason: {result.stop_reason} | turns {result.turns} | context tokens {result.context_tokens} "
              f"({TOKENIZER}) | {result.latency_ms:.0f} ms | critic rejections {result.critic_rejections} | "
              f"unknown-tool calls {result.unknown_tool_calls}\nAudit events for {case_id}: "
              + ", ".join(f"{e['subtype'][0]['code']}:{e['outcomeDesc']}" for e in events)
              + f"\nTrace saved to {path.relative_to(REPO)}")
    return result


def _receiving_from_trace(result: RunResult) -> str:
    for step in result.trace:
        if step.get("tool") == "confirm_handoff":
            return step["arguments"]["receiving_org"]
    return ""


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", default="AMB-001")
    ap.add_argument("--model", choices=["mock", "faulty", "openai"], default=os.environ.get("AGENT_MODEL", "mock"))
    ap.add_argument("--approve", choices=["ask", "auto", "deny"], default="ask")
    ap.add_argument("--crew", help="override the crew session (e.g. to demonstrate a cross-crew denial)")
    args = ap.parse_args()
    result = asyncio.run(run_case(args.case, args.model, args.approve, crew_id=args.crew))
    sys.exit(0 if result.stop_reason == "final_answer" else 1)


if __name__ == "__main__":
    main()
