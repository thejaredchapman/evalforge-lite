---
created: 2026-10-04T05:30:30Z
title: Add selectable judge engine (llm or JEV)
area: general
files:
  - judge.py
  - policy.py
  - gateway.py
  - scrub.py
  - server_creds.py
  - runner.py
  - analysis.py
  - app.py
  - mcp_server.py
  - templates/index.html
  - static/app.js
---

## Problem

EvalForge Lite scores responses only with LLM-as-judge (`judge.py`), which is non-deterministic and the largest judge-cost line. The goal is a more deterministic option. TypeSafe AI's JEV (a hosted "System One" model that returns typed answers with calibrated probabilities: `Noul` yes/no, `Choice`, `Score`; LangChain wrapper `langchain-typesafe`, `TYPESAFE_API_KEY`) could serve as an alternative judge engine. LangChain reported 500/500 repeat-decision agreement, 92-913x lower score variance, about $0.00035/call and 0.44s latency. The evidence is thin (five unique runs, one human labeler) and JEV returns no rationale text.

Decision: users choose the engine per run via a new `judge_engine` param (`llm` | `jev`, default `llm`). In JEV mode, `overall_verdict()` and `explain_recommendations()` still call the LLM judge (JEV cannot write prose), so a `judge_backend` credential is still required.

## Solution

Everything depends on step 1.

1. SPIKE (go/no-go): confirm JEV raw API access, request shape, pricing and rate limits (only known so far via `langchain-typesafe`). Score ~20 saved responses with both engines and compare variance, agreement and cost.
2. Credentials: `creds.jev` in `gateway.normalize_creds`/`prepare_creds`; JEV key regex + exact-value redaction in `scrub.py`; optional `server_creds.py` support.
3. `jev.py` client following the `foundry.py` pattern (`JevError(GatewayError)`, pure request builder, mocked network in tests).
4. `judge.py` engine dispatch for `llm_judge()` / `evaluate_response()` mapped to `Score`/`Noul` questions; same output shapes and safe-default failure behavior.
5. `policy.check_policy()` -> `Noul` with a confidence threshold; errors and low confidence still fail closed.
6. Prose functions always use `JUDGE_MODELS[backend]`; make a missing LLM credential explicit in the UI and validation.
7. Accept/validate `judge_engine` in `/api/run`, `/api/evaluate-prompt` and the MCP tools; thread through `runner.run()` and `analysis.build_run_result()`.
8. `CostMeter` records JEV spend; judge-disclosure/bias-note and the PDF report name the engine.
9. Frontend engine picker + JEV key field (`index.html`, `app.js`) with a note that prose still uses the LLM judge.
10. Tests (engine selection, fail-closed, scrub; no live network) and docs (CLAUDE.md architecture bullets, user guide).
11. Recommended: build a small human-labeled set to measure each engine's agreement (repeatable != correct).

Sources:
- https://www.langchain.com/blog/building-a-harness-with-jev
- https://www.langchain.com/blog/jev-agent-evals-langsmith
- https://befailproof.ai/jev/research/jev-evals-langchain/
