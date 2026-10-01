---
title: Hosting and server-side keys
nav_order: 7
---

# Hosting and server-side keys

This page is for people who run EvalForge Lite for other people, such as a team or a demo. It covers how to deploy the web app, and the optional feature that lets you keep provider keys on the server so users never have to paste their own.

**If you only use EvalForge Lite yourself, or every user brings their own key, you can skip the server-side keys part.** That is the default and needs no setup.

## Why this helps

- **Users never see your key.** A server-held key lives in an environment variable, is never sent to the browser, and is removed from error messages. Users just see **Provided by this server** where the key box would be.
- **One shared budget with a cap.** Every run that uses a server-held key counts against a shared limit, 50 per rolling 24 hours by default, so a busy day cannot run up an unlimited bill.
- **Mix and match.** You can hold a key for one backend and leave the others for users to fill in.
- **Reversible in one step.** Remove the variables and restart, and users go back to entering their own keys.
- **Nothing to run besides the app.** No database, no queue and no other service.

## Deploying the web app

### On Render

The repo includes a `render.yaml` for [Render](https://render.com). Connect the GitHub repository, Render detects it as a Blueprint, and it deploys with [gunicorn](https://gunicorn.org/) instead of Flask's development server. The start command in `render.yaml` is:

```bash
gunicorn --workers 1 --threads 4 --bind 0.0.0.0:$PORT app:app
```

The build command is `pip install -r requirements.txt`, and the blueprint uses Render's `free` plan.

### Keep it at one worker

Leave `--workers 1` as it is. All the app's state is a plain in-memory structure inside one Python process: the uploaded policy text, each session's run history, and the rate-limit counters (including the server-key daily count). It is protected by locks for thread safety but is **not** shared between processes. `--threads 4` gives real concurrency inside that one process safely. Adding more workers would let requests from the same browser land on different processes with different state, which silently breaks policy gating, run history and the rate limits.

State also resets on every restart or redeploy. That is expected: the app stores nothing on disk by design.

### On any other host

Bind to `0.0.0.0`, not `127.0.0.1`. `127.0.0.1` is the default for local-only use. Either run gunicorn the same way as above, or, if you start the app with `python app.py`, set `HOST=0.0.0.0`. The other settings `python app.py` reads are `PORT` (default `8000`) and `FLASK_DEBUG=1` (off by default; do not turn it on for a deployment, because the app handles live credentials).

Once deployed, the URL works for anyone who has it. Your hosting's bandwidth and CPU are shared across everyone who uses it. Each visitor supplies their own credentials for the backends they use, so you are not billed for their model usage, unless you set server-side keys (below).

### Optional: judge-model settings

These environment variables choose which model acts as the judge on each backend. They are read once at startup, so restart after changing them:

| Variable | Default |
|---|---|
| `JUDGE_MODEL` (OpenRouter) | `openai/gpt-4o-mini` |
| `BEDROCK_JUDGE_MODEL` | `{geo}.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `VERTEX_JUDGE_MODEL` | `google/gemini-2.5-flash` |
| `FOUNDRY_JUDGE_MODEL` | `gpt-4o-mini` |

The `{geo}` in the Bedrock default is replaced with the cross-region inference prefix for the credentials' region. See [Backends and credentials](backends-and-credentials.md).

## Server-side keys

### How it works

- Set the environment variables for a backend (table below) and restart the app.
- That backend's tab in the credentials panel now says **Provided by this server** and has no input fields.
- The server's key always wins: anything a browser sends for that backend is ignored.
- Backends you do not set up work as before: users paste their own key.
- Your users spend your key, so there is a shared daily limit (below).

### Step 1: choose what to set

Set **all** the variables listed for a backend, or that backend stays user-supplied. A partly configured backend is ignored on purpose.

| Backend | Variables | Notes |
|---|---|---|
| OpenRouter | `OPENROUTER_API_KEY` | One variable. |
| Amazon Bedrock | `BEDROCK_REGION` **and** `BEDROCK_API_KEY` | Simplest option. |
| Amazon Bedrock (access keys) | `BEDROCK_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, optional `AWS_SESSION_TOKEN` | Used only if `BEDROCK_API_KEY` is not set. |
| Google Vertex AI | `VERTEX_PROJECT` **and** `VERTEX_SERVICE_ACCOUNT_JSON`, optional `VERTEX_REGION` (default `us-central1`) | The JSON text of a service-account key. The JSON must be valid. Short-lived access tokens are not supported on the server. |
| Microsoft Foundry | `FOUNDRY_RESOURCE`, `FOUNDRY_REGION` and `FOUNDRY_API_KEY` | Entra ID access tokens are not supported on the server because they expire. |
| Daily limit | `SERVER_KEY_DAILY_CAP` (optional, default `50`) | See [The daily limit](#the-daily-limit). |

Values are trimmed of leading and trailing spaces, and an empty value counts as not set.

### Step 2: set them and start the app

**On your own computer (macOS or Linux):**

```bash
export OPENROUTER_API_KEY="sk-or-v1-your-key-here"
python app.py
```

Using the `.env` file instead: copy `.env.example` to `.env`, remove the `#` from the lines you want, fill in your values, then load it and start:

```bash
set -a; source .env; set +a
python app.py
```

The app does not read `.env` by itself. `.env` is already git-ignored; never commit it. In `.env`, keep the Vertex JSON on one line inside single quotes, as `.env.example` shows.

**Bedrock example:**

```bash
export BEDROCK_REGION="us-east-1"
export BEDROCK_API_KEY="your-bedrock-api-key"
```

**Vertex AI example** (puts the whole JSON file into one variable):

```bash
export VERTEX_PROJECT="my-gcp-project"
export VERTEX_REGION="us-central1"
export VERTEX_SERVICE_ACCOUNT_JSON="$(cat service-account.json)"
```

**Foundry example:**

```bash
export FOUNDRY_RESOURCE="my-foundry-resource"
export FOUNDRY_REGION="eastus2"
export FOUNDRY_API_KEY="your-foundry-key"
```

**On a host such as Render:** open your service, go to **Environment**, choose **Add Environment Variable**, add the names and values from the table (for Vertex, paste the whole JSON as the value), then **redeploy**. **Docker:** use `-e NAME=value` or `--env-file`. Never put keys in `render.yaml`, in a Dockerfile you write, or in git.

### Step 3: check that it worked

Open the app. The credentials tab for that backend should say **Provided by this server** and show no input boxes. For Bedrock, Vertex and Foundry the note also shows the region.

Or check from a terminal. This lists backend names and regions only, never keys:

```bash
curl -s http://localhost:8000/api/catalog | python3 -m json.tool | grep -A8 server_backends
```

Expected output is a `server_backends` object listing the backends you set, for example `"openrouter": {}` and `"bedrock": {"region": "us-east-1"}`.

### The daily limit

Because users spend your key, the server counts every run and every prompt evaluation that uses a server-held backend. A call uses a server-held backend if the judge backend or any selected model's backend is one you hold. The default is **50 per rolling 24 hours, shared by everyone**. When it is reached, people see "The server's shared usage limit has been reached. Please try again later."

- Change it with `SERVER_KEY_DAILY_CAP`. `0` blocks every call that needs a server-held backend. A value that is not a whole number, or is negative, falls back to 50. To let users enter their own keys again, unset that backend's variables instead.
- The usual per-browser limit (3 runs per 8 hours) still applies on top, and a run refused by the daily limit still counts against it.
- The count lives in memory. Restarting the app resets it, and if you run several worker processes each keeps its own count (the included `render.yaml` uses one worker).

### MCP server

The MCP server reads the same variables from the environment it is started in. With them set, `run_comparison` and `evaluate_prompt` work without `creds` for those backends. See [MCP server](mcp-server.md#server-side-keys).

### Safety notes

- Keep keys only in environment variables or your host's secret store, not in code, README files, screenshots or git.
- The key is never sent to the browser. It is removed from error messages, and so are the Vertex project id, the service account's email and the Foundry resource name.
- Anyone who can open your site can spend your key, up to the daily limit. For a private tool, put the site behind your own login or VPN, and use a provider key with its own spending limit.
- To rotate a key: change the variable and restart.
- To turn the feature off: remove the variables and restart.
- For a public site, the safe default is not to set any server-side key variables, so every visitor pays for their own calls.

### Troubleshooting

- **The tab still shows input boxes.** A required variable is missing or empty (check the table), the app was not restarted, or, for Vertex, the JSON is not valid. Partly configured backends are ignored on purpose.
- **"Shared usage limit has been reached".** Wait for the rolling 24 hours to pass, or raise `SERVER_KEY_DAILY_CAP`.
- **The app uses a key you did not set up.** If you already export `OPENROUTER_API_KEY` (or the AWS or other variables above) in your shell for other tools, this app picks it up and uses it as a server key. Unset it first if you did not mean that.
- **Bedrock still asks for a region.** `BEDROCK_REGION` must be set along with a key.

More messages are covered in [Troubleshooting and FAQ](troubleshooting-and-faq.md).
