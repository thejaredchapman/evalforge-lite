# Contributing to EvalForge Lite

Thanks for helping. Bug reports, model-catalog updates, new checks, docs fixes,
and new backends are all welcome.

## Ways to contribute

- **Report a bug.** Open an issue with the
  [bug report template](https://github.com/thejaredchapman/evalforge-lite/issues/new?template=bug_report.md).
  When the app shows an error popup, **Report an issue on GitHub** pre-fills
  the error details for you.
- **Suggest a feature.** Use the
  [feature request template](https://github.com/thejaredchapman/evalforge-lite/issues/new?template=feature_request.md).
- **Send a pull request.** For anything larger than a small fix, open an issue
  first so we can agree on the approach before you write code.

## Never share credentials

This app runs on other people's API keys, AWS credentials, and Google service
accounts. Before posting an issue, log, or screenshot:

- Remove API keys, AWS access keys, session tokens, and service-account JSON.
  Error popups redact known credential formats automatically, but check anyway.
- Never commit a `.env` file or a key file. `.env` is gitignored; keep it that way.
- Found a security problem? Don't open a public issue. Report it privately
  through GitHub's **Security → Report a vulnerability** on this repository.

## Development setup

Requires Python 3.10+ (3.12 recommended; see `.python-version`).

```bash
git clone https://github.com/thejaredchapman/evalforge-lite.git
cd evalforge-lite
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # optional: override judge models
python app.py               # http://localhost:8000
```

## Tests

```bash
pytest tests/ -v
```

The suite mocks every provider call, so it needs no API keys and makes no
network calls. CI runs it on every pull request, and it must pass before merge.

To check a real backend end to end (tiny, billable calls), use the live smoke
test. Credentials are read from environment variables and never printed:

```bash
python scripts/live_smoke.py            # every backend with credentials set
python scripts/live_smoke.py bedrock    # just one
```

See the docstring at the top of `scripts/live_smoke.py` for the variables.

## Common contributions

**Add or update a model.** Edit `data/providers.json`. Each entry needs an `id`,
`name`, `family`, `tier`, and one or more `routes` (`bedrock`, `vertex`, or
OpenRouter), each with the provider's model ID and per-million-token prices.
Bedrock IDs can use the `{geo}` placeholder for cross-region inference
profiles. Run `pytest tests/test_catalog.py -v` afterwards.

**Add a rule-based check.** Checks live in `checks.py`; add tests in
`tests/test_checks.py`.

**Add a backend.** Follow `bedrock.py` and `vertex.py`: a `call_model()` that
returns the same result shape, errors raised as a `GatewayError` subclass
(use `errors.describe_request_error()` so users see the provider's response
body), credential preparation in `gateway.py`, and redaction rules for any new
secret fields in `scrub.py`. Add mocked tests, and extend
`scripts/live_smoke.py`.

## Pull requests

1. Fork the repo and create a branch from `main` (`fix/...`, `feat/...`, `docs/...`).
2. Keep each PR focused on one change, and add or update tests with it.
3. Run `pytest tests/ -v` locally.
4. Update the README if you change behavior users will see.
5. Fill in the pull request template.

## License

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
