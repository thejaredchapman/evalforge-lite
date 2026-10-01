---
title: Getting started
nav_order: 2
---

# Getting started

This page takes you from nothing to your first model comparison on your own computer. It assumes you have never run a Python web app before. You do not need to be a programmer, but you do need to be able to open a terminal.

If you only want to use EvalForge Lite from Claude, skip to the [MCP server](mcp-server.md) page. If someone already hosts a copy for you, skip to step 4.

## Why this helps

- **Nothing to configure first.** Apart from Python itself, the app needs no database, no account and no config file to start.
- **Your keys stay yours.** The app reads no credentials from the server's environment unless the operator deliberately sets them. By default each key you paste is used for that request only.
- **One command to run.** The whole app is a single `python app.py`.

## What you need

- **Python 3.10 or newer.** The project is developed and tested on Python 3.12. Check with `python3 --version`.
- **Credentials for at least one backend.** The easiest is an OpenRouter API key. See [Backends and credentials](backends-and-credentials.md) for all four.
- **A judge backend.** The judge (the model that scores answers) runs on one backend and needs credentials there. By default that is OpenRouter, so an OpenRouter key covers the whole first run.

## 1. Install

Get the code and open a terminal in its folder, then create an isolated Python environment and install the requirements.

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

On Windows, activate with `venv\Scripts\activate` instead of the `source` line. If `python3.12` is not found, use any `python3` that is 3.10 or newer.

Expected result: `pip` finishes without errors and your prompt starts with `(venv)`.

## 2. Optional: judge-model overrides and `.env`

You can skip this on your first run. The repo includes `.env.example`, which documents optional settings: which model acts as judge on each backend, and the operator-only server-side keys (see [Hosting and server-side keys](hosting-and-server-keys.md)).

```bash
cp .env.example .env
```

**The app does not read `.env` by itself.** Edit the file, then load it into your shell before starting the app:

```bash
set -a; source .env; set +a
```

The judge model defaults are read from these environment variables:

| Variable | Default |
|---|---|
| `JUDGE_MODEL` (OpenRouter) | `openai/gpt-4o-mini` |
| `BEDROCK_JUDGE_MODEL` | `{geo}.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `VERTEX_JUDGE_MODEL` | `google/gemini-2.5-flash` |
| `FOUNDRY_JUDGE_MODEL` | `gpt-4o-mini` |

**Why it helps:** you can point the judge at a model you already have access to, without changing code. On Bedrock, the literal `{geo}` is replaced by the right region prefix for the region you choose.

## 3. Start the app

```bash
python app.py
```

Expected result: Flask prints that it is running on `http://127.0.0.1:8000`. Leave the terminal open.

Options, all environment variables:

- `PORT=9000` runs it on another port. The default is 8000.
- `HOST=0.0.0.0` makes it reachable from other machines. The default is `127.0.0.1`, which is local only.
- `FLASK_DEBUG=1` turns on Flask's interactive debugger. It is off by default because the app handles live credentials.

## 4. Open it

Go to `http://localhost:8000` in your browser. You will see the title "EvalForge Lite", a credentials panel with four tabs, a model picker, a policy upload, a test-case area and a **Run comparison** button.

## 5. Add a key

1. In the credentials panel, the **OpenRouter** tab is selected. Paste your key into **OpenRouter API key** (it looks like `sk-or-v1-...`). If you do not have one, the panel links to OpenRouter's key page.
2. Leave **Judge & policy backend** on **OpenRouter** for now.

## 6. Run your first comparison

1. Under **Frontier models**, click two or three of the big colored badges (one per provider). Each click selects that model through OpenRouter. The counter shows `Selected 2 / 4`.
2. Under **Test cases**, click **+ Add test case**. Type a prompt, for example: `Explain what an API rate limit is in two sentences.`
3. In the **Rubric (optional)** box, describe a good answer, for example: `Accurate, exactly two sentences, no jargon.`
4. Look at the line next to the run button. It shows `Estimated cost: ~$0.00xx (rough; excludes judge calls)` once models are selected.
5. Click **Run comparison**. The status shows `Running...`.

A run sends your prompt to every selected model and then makes several judge calls, so it takes noticeably longer than a single chat message. Each individual model call times out after 60 seconds.

Expected result: the results area appears with a cost banner, an **Overall verdict**, a **Side-by-side** view, a **Leaderboard**, a **Latency comparison**, **Category Scores** and the individual **Results**.

A run counts against a limit of 3 runs per 8 hours for your browser session, so do not click it repeatedly while experimenting.

## 7. Read the result

- The **Overall verdict** names the winner and gives the judge's reason.
- Each column in **Side-by-side** has a letter grade and four bars: Quality, Response time, Speed and Cost. Higher bars are better on all four.
- Click through to each response under **Results** to read the answer itself and its **Evaluation**.
- Change **What matters most?** to see which model is best for "Best quality", "Fastest" or "Cheapest" without running again.

The full explanation is on [Comparing models](comparing-models.md).

## 8. Download

Use **Download PDF report** or **Download CSV** at the bottom of the results.

## Next steps

- Learn every control in the [Web app guide](web-app.md).
- Add Bedrock, Vertex AI or Foundry credentials: [Backends and credentials](backends-and-credentials.md).
- If something fails: [Troubleshooting and FAQ](troubleshooting-and-faq.md).
