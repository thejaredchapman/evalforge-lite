import base64
import json
import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

_SERVER_PATH = str(Path(__file__).resolve().parent.parent / "mcp_server.py")


def _parse(result):
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_full_workflow_over_real_stdio_transport():
    params = StdioServerParameters(command=sys.executable, args=[_SERVER_PATH])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            catalog_result = _parse(await session.call_tool("list_models", {}))
            assert len(catalog_result["frontier"]) > 0

            suggest_result = _parse(await session.call_tool("suggest_models", {"model_id": "openai/gpt-5"}))
            assert "suggestions" in suggest_result

            policy_result = _parse(await session.call_tool("set_policy", {"policy_text": "No medical advice."}))
            assert policy_result == {"ok": True}

            # Empty test_cases/models short-circuits runner.run()/judge.overall_verdict entirely
            # (no models to iterate, no verdict call needed) — this is a real end-to-end round
            # trip with zero network calls, matching the project-wide "no live calls in tests" rule.
            run_result = _parse(await session.call_tool(
                "run_comparison", {"test_cases": [], "models": [], "api_key": "sk-or-v1-test"},
            ))
            assert "run_id" in run_result
            run_id = run_result["run_id"]

            runs_result = _parse(await session.call_tool("list_runs", {}))
            assert runs_result["runs"][0]["run_id"] == run_id

            report_result = _parse(await session.call_tool("get_report", {"run_id": run_id}))
            pdf_bytes = base64.b64decode(report_result["pdf_base64"])
            assert pdf_bytes.startswith(b"%PDF")

            csv_result = _parse(await session.call_tool("get_report_csv", {"run_id": run_id}))
            assert csv_result["csv"].startswith("prompt,model_id,status")


@pytest.mark.asyncio
async def test_missing_required_argument_is_rejected_over_real_stdio_transport():
    params = StdioServerParameters(command=sys.executable, args=[_SERVER_PATH])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("suggest_models", {})
            assert result.is_error is True


@pytest.mark.asyncio
async def test_get_report_without_a_prior_run_returns_error_over_real_stdio_transport():
    params = StdioServerParameters(command=sys.executable, args=[_SERVER_PATH])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = _parse(await session.call_tool("get_report", {}))
            assert result == {"error": "no_run_available"}
