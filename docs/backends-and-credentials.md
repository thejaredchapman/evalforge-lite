---
title: Backends and credentials
nav_order: 5
---

# Backends and credentials

EvalForge Lite can send your prompts through four providers, called *backends*. This page explains what each one is, what you have to enter, how regions work, and how your credentials are handled.

## Why this helps

- **Test where you will deploy.** If your company runs on AWS, Google Cloud or Azure, you can test the same model through that platform and see its real latency, not just OpenRouter's.
- **One key can be enough.** OpenRouter needs a single API key and reaches many models, so you can start in minutes.
- **Use only what you have.** You fill in only the backends you need. A run asks for credentials only for the backends it actually uses.
- **Credentials are not stored.** They travel with each request, and error messages shown to you are scrubbed of them.

## The four backends

### OpenRouter

A hosted service that gives one API in front of many providers' models. You need a single **OpenRouter API key**, which looks like `sk-or-v1-...`. The credentials panel links to OpenRouter's key page (<https://openrouter.ai/workspaces/default/keys>).

Every model in the catalog can run here, and you can type any other OpenRouter model id under **Custom model ID**.

### Amazon Bedrock

AWS's managed model service. Fill in:

- **AWS region**, chosen from a dropdown (for example `us-east-1`).
- One of two ways to sign in:
  - **Bedrock API key** (a bearer token, for example starting `ABSK...` or `bedrock-api-key-...`), or
  - **Access keys**: **Access key ID**, **Secret access key** and an optional **Session token** (for temporary AWS credentials).

If you give both, the Bedrock API key is used.

**The `{geo}` token.** Some Bedrock models are called through a cross-region inference profile, whose id starts with a geography prefix such as `us.` or `eu.`. The catalog and the default Bedrock judge model store this as a literal `{geo}`, and EvalForge Lite replaces it from your region: a region starting `us-` becomes `us`, `us-gov-` becomes `us-gov`, `eu-` becomes `eu`, and `ap-` becomes `apac`. For any other region prefix (for example `ca-` or `sa-`) there is no mapping, and using a `{geo}` model fails with the message "No cross-region inference profile geography for region ...". You never type `{geo}` yourself.

### Google Vertex AI

Google Cloud's model service, called through its OpenAI-compatible endpoint. Fill in:

- **GCP project ID** (for example `my-project-123`).
- **Region** from the dropdown, for example `us-central1` or `global`.
- One of two ways to sign in:
  - **Access token**: a short-lived OAuth token. The page suggests getting one with `gcloud auth print-access-token`. It starts `ya29...`.
  - **Service-account JSON**: choose the key file you downloaded from Google Cloud. EvalForge Lite exchanges it for a short-lived token with Google's token service and does not use any token address written inside the file.

### Microsoft Foundry

Azure AI Foundry's model service. Fill in:

- **Azure AI Foundry resource name** (for example `my-foundry-resource`). Requests go to `https://<resource>.services.ai.azure.com`.
- **Region** from the dropdown (for example `eastus2`).
- One of two ways to sign in (exactly one, not both):
  - **API key**, or
  - **Entra ID access token**, which the page suggests getting with `az account get-access-token --resource https://cognitiveservices.azure.com`.

## Where to find your credentials

EvalForge Lite does not create keys for you. Use your provider's own console to create the key or token, with the least permission that lets you call models:

- **OpenRouter:** the key page linked above.
- **Bedrock:** create a Bedrock API key or an AWS access key in your AWS account, and make sure the models you want are enabled for you in that region.
- **Vertex AI:** either run the `gcloud` command above or create a service-account key for your project.
- **Foundry:** copy the key from your Foundry resource, or use the `az` command above for a token.

The footer of the app links to each provider's own support page, and **Provider status** in the header links to each provider's live status page.

## Format checks

Before a run, EvalForge Lite checks the shape of what you entered and rejects obviously wrong values with a message, before the run counts against your limit. For example, a region that does not look like a region for that provider, a project or resource name in an invalid format, or a key with leading or trailing whitespace or control characters in it (often a stray space or newline from copy and paste). These checks also protect the server from being pointed at arbitrary addresses.

## Judge backend

The **Judge & policy backend** picker chooses which backend runs the judge, the policy gate and the prompt evaluator. You must have credentials for it. The judge model on each backend defaults to:

| Backend | Default judge model | Environment variable to change it |
|---|---|---|
| OpenRouter | `openai/gpt-4o-mini` | `JUDGE_MODEL` |
| Amazon Bedrock | `{geo}.anthropic.claude-haiku-4-5-20251001-v1:0` | `BEDROCK_JUDGE_MODEL` |
| Google Vertex AI | `google/gemini-2.5-flash` | `VERTEX_JUDGE_MODEL` |
| Microsoft Foundry | `gpt-4o-mini` | `FOUNDRY_JUDGE_MODEL` |

The environment variables are set by whoever starts the server. Make sure the judge model is available to your account on that backend.

## Targets: `X` and `X@backend`

A *target* is a model plus the backend it runs on. In the page you tick a checkbox (**OpenRouter**, **Bedrock**, **Vertex** or **Foundry**) under a model. Behind the scenes:

- `anthropic/claude-sonnet-4.5` is the model through OpenRouter.
- `anthropic/claude-sonnet-4.5@bedrock` is the same model through Bedrock.
- The same pattern works for `@vertex` and `@foundry`.

Each target counts toward the 4-model cap, so `X` and `X@bedrock` use two. Only the combinations in the catalog are offered. A model with no route for a backend has no checkbox for it, and asking for it anyway (through the API or MCP) is not rejected up front: the call for that target fails during the run with the error "... is not available on ...", so the run still counts against your limit.

**Why it helps:** the same model can behave and cost differently on different platforms, and this puts both in one table.

## Regions and the warning

Some routes only exist in certain regions. For example, Vertex's Llama models are only offered in `us-east5`, some preview models need the `global` region, and Foundry's Llama routes are only curated for a handful of regions.

When you select a Bedrock, Vertex or Foundry target and pick a region the catalog does not list for it, the checkbox gets a **⚠** and a line appears beside **Run comparison**, such as "Not listed in us-central1 — available in us-east5. Switch region in the Google Vertex AI tab." This is advice only. It never blocks a run, because the region data is a curated, dated snapshot that can fall behind reality. If a model really is available where you are, the run still works.

Foundry note: the region you pick is checked for format and used for these warnings, while requests themselves go to your resource's address.

The [Where models run page](web-app.md#where-models-run) (`/availability`) lists the curated regions for every model, with the date each list was verified and a link to the provider's source page.

**Why it helps:** you find out about a likely region mismatch before the run, not from a failed call.

## Costs on these backends

OpenRouter reports its own cost for each call. Bedrock, Vertex AI and Foundry do not report cost back, so EvalForge Lite **estimates** it from the tokens used and the per-million-token prices in its bundled catalog. A model with no price in the catalog shows $0 and "unavailable" in the pre-run estimate. These estimates are not your cloud bill. See [Comparing models](comparing-models.md#total-cost).

## How your credentials are handled

- Credentials are sent from your browser to the EvalForge Lite server with each request and used only for that request. The server does not write them to disk or keep them afterwards, and the page does not save them in your browser.
- Secrets are removed from any error text sent back to you or written to the server log: the exact values you supplied, plus patterns that look like keys and tokens (such as `sk-`, AWS key ids, Bedrock keys, `ya29.` tokens, private-key blocks and bearer tokens).
- Do not paste a credential into the Prompt or Rubric fields. Those are sent to the models and to the judge. EvalForge Lite never puts credentials into a prompt itself.
- If the operator holds a backend's key on the server, the tab says **Provided by this server**. In that case the server's key is always used and anything your browser sends for that backend is ignored. See [Hosting and server-side keys](hosting-and-server-keys.md).

For the full data picture see [Privacy and limits](privacy-and-limits.md).
