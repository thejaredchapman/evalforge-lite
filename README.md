# EvalForge Lite

<!-- mcp-name: io.github.thejaredchapman/evalforge-lite -->

Compare text LLMs side by side. Write a few test prompts, pick up to four models
across OpenRouter, Amazon Bedrock, Google Vertex AI and Microsoft Foundry, and
EvalForge Lite sends the same prompts to all of them, scores the answers
automatically, and shows a leaderboard with letter grades, response time, speed
and estimated cost. Use it as a web app or as an MCP server for Claude and other
assistants. You bring your own credentials, or the person hosting it keeps them
on the server for you.

**Documentation site:** https://thejaredchapman.github.io/evalforge-lite/

## Why use it

- **Test on your own prompts.** Choose models from evidence about your tasks, not a generic benchmark.
- **Up to 4 models per run, across 4 backends.** `X` (OpenRouter) and `X@bedrock` are separate targets, so you can check one model on two platforms in a single run.
- **Automatic grading.** A judge model scores each answer against your rubric, and rule checks (`contains`, `regex`, `json_valid`, `max_length`, available through the API and MCP) add a pass or fail. You get a 0-100 score and a letter grade.
- **A second opinion on every response.** Each answer is also evaluated on six criteria (answered, quality, instruction following, completeness, helpfulness, safety) with strengths and weaknesses written out.
- **Speed and cost beside quality.** Latency, tokens per second and estimated cost for every model, and a "What matters most?" selector that re-ranks without a new run.
- **Policy gate.** Upload a company policy and prompts that violate it are blocked before any model is called. If the check itself fails, the prompt is blocked.
- **Reports.** Download a PDF or a CSV for any of your last five runs.
- **No accounts, no database.** Credentials are used for one request and not stored. Nothing is written to disk.

## Quick start

### 1. Run the web app on your computer

Requires Python 3.10 or newer (tested on 3.12).

    python3.12 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    python app.py

Open http://localhost:8000, paste a key for at least one backend (an OpenRouter
API key is the quickest: https://openrouter.ai/workspaces/default/keys), add a
test case, pick two to four models, and click **Run comparison**. Runs are
limited to 3 per 8 hours per browser session.
Full walkthrough: [Getting started](docs/getting-started.md).

### 2. Use it from Claude (MCP server)

With [`uv`](https://docs.astral.sh/uv/) installed:

    uvx evalforge-lite

Add it to Claude Code in one line:

    claude mcp add evalforge-lite -- uvx evalforge-lite

Or install the Claude Code plugin, which bundles the same server:

    claude plugin marketplace add thejaredchapman/evalforge-lite
    claude plugin install evalforge-lite@evalforge

Then ask your assistant to compare models. It gets 9 tools: `list_models`,
`suggest_models`, `list_availability`, `set_policy`, `evaluate_prompt`,
`run_comparison`, `list_runs`, `get_report`, `get_report_csv`.
Details, Claude Desktop config and credential shapes: [MCP server](docs/mcp-server.md).

### 3. Host it for other people

Deploy with the included `render.yaml` (gunicorn, one worker) or any host that
can run `gunicorn --workers 1 --threads 4 --bind 0.0.0.0:$PORT app:app`. By
default every visitor supplies their own key. Optionally keep provider keys on
the server with environment variables and a shared daily cap (50 per 24 hours by
default). Keep it at one worker: all state is in memory per process.
Full guide: [Hosting and server-side keys](docs/hosting-and-server-keys.md).

## Good to know

- The app does not read `.env` by itself. To use values from it, run `set -a; source .env; set +a` before `python app.py`.
- Each run is limited to 4 models, and each browser session gets 3 runs per 8 hours.
- All state lives in memory and is cleared when the server restarts. See [Privacy and limits](docs/privacy-and-limits.md).
- Upgrading from an older version and reading the CSV or API fields? See the notes in [Troubleshooting and FAQ](docs/troubleshooting-and-faq.md#changes-to-exports-and-api-fields).

## Backends and credentials

| Backend | What you provide |
|---|---|
| OpenRouter | One API key |
| Amazon Bedrock | A region, plus a Bedrock API key or AWS access keys (optional session token) |
| Google Vertex AI | A project id and region, plus an access token or service-account JSON |
| Microsoft Foundry | A resource name and region, plus an API key or Entra ID access token |

A separate **judge backend** setting chooses where the judge and policy gate
run. Bedrock, Vertex and Foundry costs are estimates from catalog prices, not
your cloud bill. See [Backends and credentials](docs/backends-and-credentials.md).

## Documentation

| Page | What is in it |
|---|---|
| [Overview](docs/index.md) | What it is, who it is for, the three ways to use it |
| [Getting started](docs/getting-started.md) | Install, run, and your first comparison |
| [Web app guide](docs/web-app.md) | Every part of the screen, in order |
| [Comparing models](docs/comparing-models.md) | Reading metrics, grades, evaluation, cost and their limits |
| [Backends and credentials](docs/backends-and-credentials.md) | Keys, regions, `X@backend` targets |
| [MCP server](docs/mcp-server.md) | Install paths, all 9 tools, example prompts |
| [Hosting and server-side keys](docs/hosting-and-server-keys.md) | Deploying for others, operator-held keys, daily cap |
| [Troubleshooting and FAQ](docs/troubleshooting-and-faq.md) | Common messages, fixes, and notes on CSV/API field changes |
| [Privacy and limits](docs/privacy-and-limits.md) | What data goes where, what is stored, every limit |

## Test

    pytest tests/ -v

Every model and HTTP call is mocked, so the suite needs no API key and makes no
network calls.

## Contributing

Contributions are welcome: bug reports, model-catalog updates, new checks, docs,
and new backends. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests and the
pull request process. When the app shows an error, the popup's **Report an issue
on GitHub** button opens a pre-filled bug report.

## License

[MIT](LICENSE)
