---
title: EvalForge Lite
nav_order: 1
---

# EvalForge Lite

EvalForge Lite is a small web app and MCP server that lets you compare text-generation models (LLMs) side by side. You write one or more test prompts, pick up to four models, and it sends the same prompts to all of them, scores the answers automatically, and shows you a leaderboard with letter grades, response time, speed and estimated cost. You can then download the result as a PDF or CSV.

It works with four providers ("backends"): OpenRouter, Amazon Bedrock, Google Vertex AI and Microsoft Foundry. There are no accounts and no database. You bring your own API credentials, or the person running the server keeps them on the server for you.

## Who it is for

- **People choosing a model** for a product, a team or a workflow, who want evidence from their own prompts rather than a generic benchmark.
- **Teams on a cloud platform** (AWS, Google Cloud or Azure) who want to test the same model through the platform they already pay for.
- **Operators** who host EvalForge Lite for colleagues and want to decide whether people use their own keys or a shared one.
- **Claude users** who would rather run comparisons from inside an AI assistant through the MCP server.

## Why this helps

- **Compare up to 4 models in one run, across 4 backends.** Each choice of model plus backend is called a *target*. `X` (via OpenRouter) and `X@bedrock` are two separate targets, so you can check the same model on two platforms in a single run.
- **Automatic grading.** A *judge model* (a separate LLM that reads each answer) scores it against a *rubric* you write (the standard a good answer must meet), and local rule checks add a pass or fail on top. You get a score out of 100 and a letter grade without reading every answer yourself.
- **A second opinion on every response.** Each successful answer also gets a per-response evaluation on six criteria, with strengths and weaknesses written out, so you can see why a model scored the way it did.
- **Speed and cost next to quality.** The result shows response time, tokens per second and estimated cost for each target, and a "What matters most?" selector re-ranks the models without a new run.
- **A policy gate.** Upload a company policy and any prompt that breaks it is blocked before a model is ever called. If the check itself fails, the prompt is blocked rather than let through.
- **Shareable output.** Download a PDF report or a CSV for a spreadsheet.
- **No account and no stored keys.** Your credentials travel with each request and are not kept after it. Nothing is written to disk.
- **Works inside Claude.** The MCP server exposes 9 tools so an assistant can run the same comparisons and read the results back.

## Three ways to use it

1. **Web app (local or hosted).** Install Python, run `python app.py`, and open `http://localhost:8000`. Or open a copy someone else hosts. Start with [Getting started](getting-started.md), then read the [Web app guide](web-app.md).
2. **MCP server with `uvx`.** With the `uv` tool installed, run `uvx evalforge-lite`, or register it in Claude Code with `claude mcp add evalforge-lite -- uvx evalforge-lite`. See [MCP server](mcp-server.md).
3. **Claude Code plugin.** Run `claude plugin marketplace add thejaredchapman/evalforge-lite` and then `claude plugin install evalforge-lite@evalforge`. This bundles the same MCP server. See [MCP server](mcp-server.md).

## Contents

| Page | What you will find |
|---|---|
| [Getting started](getting-started.md) | Install and run the web app, and your first comparison from start to finish. |
| [Web app guide](web-app.md) | Every part of the screen, in the order you meet it. |
| [Comparing models](comparing-models.md) | How to read the results: metrics, grades, evaluation, cost, and their limits. |
| [Backends and credentials](backends-and-credentials.md) | OpenRouter, Bedrock, Vertex AI and Foundry: what to enter and where regions matter. |
| [MCP server](mcp-server.md) | Install paths, all 9 tools and example prompts. |
| [Hosting and server-side keys](hosting-and-server-keys.md) | For people who host the app for others. |
| [Troubleshooting and FAQ](troubleshooting-and-faq.md) | Common messages and what to do about them. |
| [Privacy and limits](privacy-and-limits.md) | What data goes where, and every limit in one table. |
