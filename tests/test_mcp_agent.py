"""End-to-end over real MCP transports: discovery, agent loop controls, strict schemas, HTTP auth."""

import asyncio
import json

import pytest
from mcp import ClientSession
from mcp.client.stdio import stdio_client

from project.agent.host import Agent, ApprovalGate, Keys, critic, server_params
from project.agent.model import Action, FaultyMockModel, MockModel

EXPECTED_TOOLS = {"get_ambulance_case", "validate_fhir_bundle", "check_handoff_completeness", "create_handoff_draft",
                  "confirm_handoff", "record_ed_acknowledgement", "list_assigned_cases"}


def run(coro):
    return asyncio.run(coro)


async def with_session(crew, fn, keys=None):
    keys = keys or Keys.from_env_or_new()
    async with stdio_client(server_params(keys, crew)) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        return await fn(s, keys)


def test_discovery_and_strict_schemas():
    async def go(s, keys):
        tools = (await s.list_tools()).tools
        assert {t.name for t in tools} == EXPECTED_TOOLS
        assert all(t.inputSchema.get("additionalProperties") is False for t in tools)
        confirm = next(t for t in tools if t.name == "confirm_handoff")
        assert confirm.annotations.destructiveHint is True
        r = await s.call_tool("get_ambulance_case", {"case_id": "AMB-001", "role": "doctor"})
        assert r.isError and "unexpected_arguments" in r.content[0].text
        prompts = {p.name for p in (await s.list_prompts()).prompts}
        assert prompts == {"prepare_mist_handoff", "prepare_sbar_handoff", "explain_validation_failure"}
    run(with_session("CREW-A", go))


def test_agent_sends_complete_case_with_approval():
    async def go(s, keys):
        res = await Agent(s, MockModel(), ApprovalGate(keys, "auto"), verbose=False).run("AMB-001")
        assert res.sent and res.stop_reason == "final_answer"
        assert res.tool_calls == ["get_ambulance_case", "validate_fhir_bundle", "check_handoff_completeness",
                                  "create_handoff_draft", "confirm_handoff"]
    run(with_session("CREW-A", go))


def test_clinician_decline_means_not_sent():
    async def go(s, keys):
        res = await Agent(s, MockModel(), ApprovalGate(keys, "deny"), verbose=False).run("AMB-001")
        assert not res.sent and "NOT sent" in res.final_text
    run(with_session("CREW-A", go))


def test_incomplete_case_escalates_without_confirm():
    async def go(s, keys):
        res = await Agent(s, MockModel(), ApprovalGate(keys, "auto"), verbose=False).run("AMB-021")
        assert not res.sent and "confirm_handoff" not in res.tool_calls
        assert "times.left_scene" in res.final_text
    run(with_session("CREW-A", go))


def test_hallucinated_tool_and_invented_value_are_caught_then_recovered():
    async def go(s, keys):
        res = await Agent(s, FaultyMockModel(), ApprovalGate(keys, "auto"), verbose=False).run("AMB-001")
        assert res.unknown_tool_calls == 1 and res.critic_rejections == 1
        assert res.sent and "estimated" not in res.final_text
    run(with_session("CREW-A", go))


class LoopingModel:
    name = "looping"

    def next_action(self, messages, tools):
        return Action("tool", "validate_fhir_bundle", {"case_id": "AMB-001"}, call_id=f"c{len(messages)}")


def test_runaway_loop_is_stopped():
    async def go(s, keys):
        res = await Agent(s, LoopingModel(), ApprovalGate(keys, "auto"), verbose=False).run("AMB-001")
        assert res.stop_reason == "loop_detected" and res.turns <= 3
    run(with_session("CREW-A", go))


def test_token_budget_is_enforced():
    async def go(s, keys):
        res = await Agent(s, MockModel(), ApprovalGate(keys, "auto"), token_budget=5000, verbose=False).run("AMB-001")
        assert res.stop_reason == "token_budget_exhausted" and not res.sent
    run(with_session("CREW-A", go))


def test_critic():
    assert critic("HR 82 /min", '{"value": 82}') == []
    assert "unsupported number 120" in critic("BP 120/80", '{"value": 82}')
    assert critic("Provisional impression (not a diagnosis)", "") == []
    assert critic("I recommend aspirin", "")


def test_http_transport_auth_and_scope():
    from project.dataset import crews
    from project.http_client import free_port, http_session, probe_http_security, spawn_http_server
    from project.security import issue_session_token

    keys = Keys.from_env_or_new()
    c = crews()["CREW-B"]
    token = issue_session_token(keys.session, "CREW-B", c["tenant"], c["cases"])

    async def go(url):
        async with http_session(url, token) as s:
            await s.initialize()
            ok = await s.call_tool("validate_fhir_bundle", {"case_id": "AMB-002"})
            denied = await s.call_tool("get_ambulance_case", {"case_id": "AMB-001"})
            return ok, denied

    with spawn_http_server(keys, free_port()) as url:
        assert probe_http_security(url, token) == {"no_token": 401, "forged_token": 401, "foreign_origin": 403}
        ok, denied = run(go(url))
    assert not ok.isError and json.loads(ok.content[0].text)["valid"]
    assert denied.isError and "forbidden" in denied.content[0].text
