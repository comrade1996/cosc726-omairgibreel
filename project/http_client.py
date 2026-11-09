"""Second, independent MCP client: Streamable HTTP + bearer session token, scripted (no LLM).

    python -m project.http_client --spawn --case AMB-002            # starts a local HTTP server for you
    python -m project.http_client --url http://127.0.0.1:8765/mcp --case AMB-002   # server already running

It shares no tool definitions with the stdio agent host: everything it calls is
discovered from the server at runtime. It also proves that an unauthenticated HTTP
request and a forbidden Origin are rejected.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
import uuid

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .agent.host import ApprovalGate, Keys, MCPExecutor, crew_for_case
from .dataset import crews
from .envfile import REPO, load_env
from .security import issue_session_token


@contextlib.asynccontextmanager
async def http_session(url: str, token: str):
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30) as hc, \
            streamable_http_client(url, http_client=hc) as (r, w, _), ClientSession(r, w) as session:
        await session.initialize()
        yield session


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def spawn_http_server(keys: Keys, port: int, audit_path: str | None = None):
    env = {**os.environ, "AMBULANCE_SESSION_KEY": keys.session.hex(), "AMBULANCE_APPROVAL_KEY": keys.approval.hex(),
           "AMBULANCE_GATES": "on", "PYTHONPATH": str(REPO)}
    if audit_path:
        env["AMBULANCE_AUDIT_PATH"] = audit_path
    proc = subprocess.Popen([sys.executable, "-m", "project.server", "--transport", "http", "--port", str(port)],
                            cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            try:
                if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            raise RuntimeError(f"HTTP server did not start: {proc.stderr.read().decode() if proc.stderr else ''}")
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def probe_http_security(url: str, token: str) -> dict:
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "probe", "version": "0"}}}
    hdr = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    no_token = httpx.post(url, json=init, headers=hdr).status_code
    bad_token = httpx.post(url, json=init, headers={**hdr, "Authorization": "Bearer forged.token"}).status_code
    evil_origin = httpx.post(url, json=init, headers={**hdr, "Authorization": f"Bearer {token}",
                                                      "Origin": "http://evil.example"}).status_code
    return {"no_token": no_token, "forged_token": bad_token, "foreign_origin": evil_origin}


async def discover(session: ClientSession) -> dict:
    caps = await MCPExecutor(session).discover()
    caps.pop("_tools")
    return caps


def _data(result) -> dict:
    text = "\n".join(getattr(c, "text", "") for c in result.content)
    return json.loads(text[text.index("{"):]) if "{" in text else {"error": text}


async def scripted_handoff(url: str, token: str, keys: Keys, case_id: str, approve: str = "auto", verbose: bool = True) -> dict:
    gate = ApprovalGate(keys, approve)
    async with http_session(url, token) as session:
        caps = await discover(session)
        say = print if verbose else (lambda *a, **k: None)
        say(f"[http] discovered tools: {', '.join(caps['tools'])}")
        steps = {}
        for tool, args in (("validate_fhir_bundle", {"case_id": case_id}), ("check_handoff_completeness", {"case_id": case_id}),
                           ("create_handoff_draft", {"case_id": case_id, "format": "SBAR"})):
            if tool not in caps["tools"]:
                raise SystemExit(f"server does not advertise {tool}")
            steps[tool] = _data(await session.call_tool(tool, args))
            say(f"[http] {tool}: stop_condition={steps[tool].get('stop_condition')}")
        draft = steps["create_handoff_draft"]
        outcome = {"case_id": case_id, "capabilities": caps, "stop_condition": draft.get("stop_condition")}
        if draft.get("confirmable"):
            ok, approval, why = gate.review(draft, {"case_id": case_id, "receiving_org": draft["receiving_org"]})
            say(f"[http] clinician gate: {why}")
            if ok:
                key = f"{case_id}-{uuid.uuid4().hex[:8]}"
                res = _data(await session.call_tool("confirm_handoff", {
                    "case_id": case_id, "case_version": draft["case_version"], "receiving_org": draft["receiving_org"],
                    "idempotency_key": key, "clinician_confirmation": approval}))
                say(f"[http] confirm_handoff: {res.get('status') or res.get('error')}")
                outcome["stop_condition"] = "sent" if res.get("status") == "sent" else res.get("error")
        return outcome


async def amain(args) -> None:
    keys = Keys.from_env_or_new()
    crew_id = args.crew or crew_for_case(args.case)
    crew = crews()[crew_id]
    token = issue_session_token(keys.session, crew_id, crew["tenant"], crew["cases"])
    with (spawn_http_server(keys, free_port()) if args.spawn else contextlib.nullcontext(args.url)) as url:
        print(f"[http] server {url} as {crew_id}")
        print(f"[http] transport security probe (expect 401/401/403): {probe_http_security(url, token)}")
        outcome = await scripted_handoff(url, token, keys, args.case, args.approve)
        print(json.dumps({k: v for k, v in outcome.items() if k != "capabilities"}))


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8765/mcp")
    ap.add_argument("--spawn", action="store_true", help="start a local HTTP server with ephemeral keys")
    ap.add_argument("--case", default="AMB-002")
    ap.add_argument("--crew")
    ap.add_argument("--approve", choices=["ask", "auto", "deny"], default="auto")
    asyncio.run(amain(ap.parse_args()))


if __name__ == "__main__":
    main()
