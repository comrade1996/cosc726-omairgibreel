"""ModelClient seam: the loop talks to any model through `next_action(messages, tools)`.

- MockModel: deterministic policy that reads tool observations (offline default; no key).
- FaultyMockModel: MockModel plus scripted faults (hallucinated tool, invented number) for
  the controlled failure/recovery demo and tests.
- OpenAICompatibleModel: any OpenAI-compatible /chat/completions endpoint (OpenAI, Ollama,
  LM Studio, vLLM...) configured through .env. Tool schemas come from MCP discovery.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Action:
    kind: str  # "tool" | "final"
    name: str | None = None
    arguments: dict = field(default_factory=dict)
    text: str = ""
    rationale: str = ""
    call_id: str = ""
    usage: dict = field(default_factory=dict)


class ModelClient(Protocol):
    name: str

    def next_action(self, messages: list[dict], tools: list[dict]) -> Action: ...


def _observations(messages: list[dict]) -> list[tuple[str, dict]]:
    """(tool_name, parsed JSON) for every tool message, in order."""
    names = {}
    out = []
    for m in messages:
        for tc in m.get("tool_calls") or []:
            names[tc["id"]] = tc["function"]["name"]
        if m["role"] == "tool":
            content = m["content"]
            try:
                data = json.loads(content[content.index("{"):]) if "{" in content else {"text": content}
            except json.JSONDecodeError:
                data = {"text": content}
            out.append((names.get(m["tool_call_id"], "?"), data))
    return out


class MockModel:
    """A deterministic stand-in for the LLM that follows the system prompt's workflow."""

    name = "mock-policy-v1"

    def __init__(self) -> None:
        self._n = 0

    def _call(self, name: str, args: dict, why: str) -> Action:
        self._n += 1
        return Action("tool", name, args, rationale=why, call_id=f"call_{self._n}")

    def next_action(self, messages: list[dict], tools: list[dict]) -> Action:
        case_id = messages[1]["content"].split("case ")[1].split()[0].strip(".")
        obs = _observations(messages)
        last = {name: data for name, data in obs}
        if "get_ambulance_case" not in last:
            return self._call("get_ambulance_case", {"case_id": case_id}, "Sense: load the authorised source event first.")
        if last["get_ambulance_case"].get("ok") is False or "error" in last["get_ambulance_case"]:
            return Action("final", text=f"Cannot access {case_id}: {last['get_ambulance_case'].get('error', 'error')}. Escalating to the crew.",
                          rationale="Access failed; stop.")
        if "validate_fhir_bundle" not in last:
            return self._call("validate_fhir_bundle", {"case_id": case_id}, "Reason: the Bundle must validate before any draft.")
        if "check_handoff_completeness" not in last:
            return self._call("check_handoff_completeness", {"case_id": case_id}, "Reason: deterministic completeness, not my judgement.")
        stop = last["check_handoff_completeness"].get("stop_condition")
        if stop and stop.startswith("blocked"):
            errors = sorted({i["code"] for i in last["validate_fhir_bundle"].get("issues", []) if i["severity"] == "error"})
            missing = last["check_handoff_completeness"].get("missing", [])
            return Action("final", rationale="A gate is closed; escalate rather than guess.",
                          text=f"Handoff {case_id} NOT sent ({stop}). Issues: {', '.join(errors) or 'none'}. "
                               f"Missing (crew must supply): {', '.join(missing) or 'none'}.")
        if "create_handoff_draft" not in last:
            return self._call("create_handoff_draft", {"case_id": case_id, "format": "MIST"}, "Act: build the grounded MIST draft.")
        draft = last["create_handoff_draft"]
        if "confirm_handoff" not in last:
            if not draft.get("confirmable"):
                return Action("final", text=f"Draft for {case_id} is not confirmable; escalating.", rationale="Gate closed.")
            return self._call("confirm_handoff", {
                "case_id": case_id, "case_version": draft["case_version"], "receiving_org": draft["receiving_org"],
                "idempotency_key": f"{case_id}-{draft['draft_sha256'][:8]}", "clinician_confirmation": "REQUEST_APPROVAL"},
                "Act: request clinician approval via the host gate, then confirm.")
        result = last["confirm_handoff"]
        if result.get("status") != "sent":
            return Action("final", rationale="Confirmation refused; report it.",
                          text=f"Handoff {case_id} NOT sent: {result.get('error', 'declined')} {result.get('detail', '')}".strip())
        return Action("final", rationale="Observe: sent; summarise only grounded lines.",
                      text=self._summary(case_id, draft, result))

    def _summary(self, case_id: str, draft: dict, result: dict) -> str:
        order = ("Patient", "M - Mechanism/illness", "I - Information/impression", "S - Signs", "T - Treatment")
        keep = []
        for section in order:
            rows = [l for l in draft["lines"] if l["section"] == section]
            keep += rows[-1:] if section == "S - Signs" else rows  # latest vital-sign set only
        body = "\n".join(f"{l['section'].split(' - ')[0]}: {l['text']}" for l in keep)
        return f"Handoff {case_id} sent as {result['handoff_id']}.\n{body}"


class FaultyMockModel(MockModel):
    """Injects two classic agent faults so the controls can be demonstrated and tested."""

    name = "faulty-mock-v1"

    def __init__(self, hallucinate_tool: bool = True, invent_number: bool = True) -> None:
        super().__init__()
        self.hallucinate_tool, self.invent_number = hallucinate_tool, invent_number

    def next_action(self, messages: list[dict], tools: list[dict]) -> Action:
        if self.hallucinate_tool:
            self.hallucinate_tool = False
            self._n += 1
            return Action("tool", "lookup_full_medical_history", {"patient": "any"}, call_id=f"call_{self._n}",
                          rationale="(fault) calls a tool that was never advertised")
        action = super().next_action(messages, tools)
        if action.kind == "final" and self.invent_number and "sent as" in action.text:
            self.invent_number = False
            action.text += "\nS: BP 120/80 mm[Hg] (estimated)"
            action.rationale = "(fault) adds a value that no tool returned"
        return action


class OpenAICompatibleModel:
    def __init__(self, base_url: str, api_key: str, model: str, temperature: float = 0.0, timeout: float = 60.0):
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.temperature, self.timeout = temperature, timeout
        self.name = f"openai-compatible:{model}"

    @classmethod
    def from_env(cls) -> "OpenAICompatibleModel":
        base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
        key = os.environ.get("LLM_API_KEY", "")
        model = os.environ.get("LLM_MODEL", "")
        if not model:
            raise SystemExit("Set LLM_MODEL (and LLM_BASE_URL / LLM_API_KEY) in .env to use --model openai.")
        return cls(base, key, model, float(os.environ.get("LLM_TEMPERATURE", "0")))

    def next_action(self, messages: list[dict], tools: list[dict]) -> Action:
        import httpx

        payload = {"model": self.model, "messages": messages, "tools": tools, "tool_choice": "auto",
                   "temperature": self.temperature, "parallel_tool_calls": False}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        for attempt in range(3):
            r = httpx.post(f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self.timeout)
            if r.status_code == 400 and "parallel_tool_calls" in payload:
                payload.pop("parallel_tool_calls")
                continue
            if r.status_code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            break
        data = r.json()
        msg = data["choices"][0]["message"]
        usage = data.get("usage", {})
        calls = msg.get("tool_calls") or []
        if calls:
            tc = calls[0]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_unparseable_arguments": tc["function"].get("arguments")}
            return Action("tool", tc["function"]["name"], args, rationale=msg.get("content") or "", call_id=tc["id"], usage=usage)
        return Action("final", text=msg.get("content") or "", usage=usage)


def make_model(kind: str) -> ModelClient:
    if kind == "mock":
        return MockModel()
    if kind == "faulty":
        return FaultyMockModel()
    if kind == "openai":
        return OpenAICompatibleModel.from_env()
    raise SystemExit(f"unknown model {kind}")
