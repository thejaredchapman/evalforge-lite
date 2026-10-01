---
title: Web app guide
nav_order: 3
---

# Web app guide

This page walks through the web app in the order you meet things on screen, from the credentials panel at the top to the downloads at the bottom. Labels in **bold** are the exact words on the page. For a first run, read [Getting started](getting-started.md) first.

## Why this helps

- **Everything on one screen.** Credentials, model choice, prompts, policy, run and results are on a single page, so one sitting takes you from idea to report.
- **Mix backends freely.** You can fill in several backends at once and run models from different ones in the same comparison.
- **See cost before you spend it.** A cost estimate appears as soon as you select models and add prompts.
- **Nothing is lost by exploring.** Filtering the model list never changes which models you have selected.
- **Light and dark themes.** The page follows your system theme, and the button in the header (moon or sun icon) switches it. Your choice is remembered in your browser.

## The header

At the top you will find the page title and, below it, two links: **Where models run** (the [availability page](#where-models-run)) and a **Provider status** menu with links to the live status pages for OpenRouter, AWS, Google Cloud and Azure. On a narrow screen a menu button lists the sections: Credentials, Models, Policy, Test Cases, Run, Results and **Where models run**.

## 1. Credentials panel

The panel has four tabs, **OpenRouter**, **Amazon Bedrock**, **Google Vertex AI** and **Microsoft Foundry**. Fill in only the backends you want to use. The exact fields for each are on [Backends and credentials](backends-and-credentials.md).

- Secret fields are masked password boxes.
- Credentials are sent with each request and not stored by the server. They are never saved in your browser either, so reloading the page clears them.
- If the operator keeps a backend's key on the server, that tab shows **Provided by this server. Nothing to enter here.** (with the region, if the operator set one) and has no input boxes. The tab is also marked "server".

**Why it helps:** you can test providers you have access to without sharing keys with anyone, and without installing any cloud tooling.

### Judge & policy backend

Under the tabs, **Judge & policy backend** chooses which backend runs the *judge model*, meaning the LLM that scores answers, writes the per-response evaluation, writes the overall verdict and checks your policy. It can be a different backend from the models you are testing, but you must fill in credentials for it (unless the operator holds them). The default is OpenRouter.

**Why it helps:** you can test models on one platform but let a cheap model on another platform do the judging, or use whichever backend you already have a key for.

## 2. Models

### Frontier models

**Frontier models** shows one big colored badge per provider: the flagship model for OpenAI, Anthropic, Google and Meta Llama. Click a badge to select it, click again to deselect it. Badges run the model through OpenRouter. The counter beneath reads **Selected 0 / 4**.

**Why it helps:** the frontier badges are the fastest way to pit the biggest names against each other in a few clicks. For OpenAI, Anthropic and Google these are OpenRouter "latest" aliases, so the badge follows the provider's newest flagship without the catalog having to be edited.

### Browse by provider

Under **Browse by provider**, each provider (openai, anthropic, google, meta-llama) is a dropdown that shows how many models it holds and how many you have selected. Open one to see its blurb and its models.

Each model row shows:

- The model name.
- A **Reasoning** badge (hover text: "Supports extended reasoning") for models the catalog marks as reasoning models.
- Small tag pills such as "Coding" or "Long documents".
- One or more checkboxes, one per place you can run it: **OpenRouter** always, plus **Bedrock**, **Vertex** or **Foundry** when the catalog has a route for that model on that backend. Ticking **Bedrock** selects the target `model@bedrock`, which runs that model on Bedrock.

Under each provider a heading **More from OpenRouter's live catalog** can list up to 10 extra, newest-first models from OpenRouter's public list. These are untagged.

**Why it helps:** the same model on two backends is two checkboxes, so comparing "model on OpenRouter" with "model on Bedrock" takes two clicks. Live extras mean you are not limited to the models bundled with the app.

### Filter by need or industry

Above the provider list are filter buttons in two rows, **What do you need?** and **Industry**.

- Need: Coding, Reasoning & maths, Long documents, Fast & cheap, Creative writing, Multilingual, Agents & tool use.
- Industry: Healthcare, Legal, Finance, Customer support, Education, Research.

Click one or more to filter. Several filters combine with AND: a model must carry every selected tag. When a filter is on, a line explains it (for example "Coding: Strong at writing, explaining and fixing code."), a counter shows **Showing N of M models**, and **Clear filters** appears. Providers with no match are hidden. Rows you have already selected stay visible so you can untick them. The extra live models have no tags, so they are hidden while a filter is on unless selected.

The tags are a curated starting point, and the page says so: "Tags curated as of 2026-10-01. A starting point, not a benchmark — verify on your own." They are an editorial judgement, not test results.

**Why it helps:** it shortens a long list to models worth trying for your use case, and the real comparison then tells you whether the tag was right for your prompts.

### The 4-model cap

You can select at most 4 targets. At the limit, the remaining checkboxes are disabled with the hint **You can compare up to 4 models — deselect one first.** The server enforces the same cap, independent of the page. Selecting `X` and `X@bedrock` uses two of the four.

**Why it helps:** four columns stay readable side by side, and the number of model calls per prompt has a ceiling.

### Custom model ID

If a model is not in the catalog, type its OpenRouter id (format `provider/model-id`) into **Custom model ID** and click **Add**. As you type, the box suggests ids from OpenRouter's full list. Added models appear in a list with a **×** to remove them. Custom ids run through OpenRouter and count toward the 4-model cap.

**Why it helps:** any model OpenRouter offers can be tested, not only the bundled ones. The page also links to OpenRouter's model list and rankings for ideas.

## 3. Company policy (optional)

Under **Company policy (optional)**, choose a `.txt`, `.md` or `.pdf` file. The status reads **Policy loaded.** when it is accepted.

Once a policy is loaded, each model's copy of a prompt is checked separately, before it is sent: one judge call per prompt per model. If the judge flags it, that prompt is **blocked** for that model and never sent to it. Because the judge is a model and can answer differently from call to call, a borderline prompt can be blocked for one model and allowed for another. The blocked cell shows the policy clause and reason. Text is pulled from a PDF with a PDF reader, and any other file type is read as UTF-8 text.

The gate **fails closed**: if the check errors, the judge is unreachable, or the reply cannot be understood, the prompt is treated as a violation and blocked with the reason "Could not verify policy compliance."

The policy is held in server memory for your browser session only. It is not written to disk.

**Why it helps:** prompts that break your organisation's rules never reach a third-party model, and a broken check can never silently let one through. Blocked cells still appear in the results, so you can see what was stopped and why.

## 4. Test cases

Click **+ Add test case** for each prompt. Each test case has:

- A **Prompt** box. This is exactly what gets sent to every model.
- An optional **Rubric (optional)** line. A *rubric* is your description of what a good answer looks like. When present, the judge scores each answer 1 to 5 against it.
- An **Evaluate prompt** button, explained below.

There is no limit stated in the app on how many test cases you add, but each one multiplies the number of model calls, so the estimate and the run time grow with it.

**Rule-based checks** (`contains`, `regex`, `json_valid`, `max_length`) exist in the engine but have no input boxes in the web page. They can be supplied through the API or the MCP server's `run_comparison` tool, where each test case may carry a `checks` list. See [MCP server](mcp-server.md). In the web page, scoring comes from the rubric and the per-response evaluation.

**Why it helps:** a rubric turns "which answer feels better" into a repeatable score. Several prompts show how a model behaves across tasks rather than on one lucky question.

### Evaluate prompt

**Evaluate prompt** asks the judge to rate the prompt itself, before you spend a run on it. The result appears beside the button as a score out of 5 and a line of feedback on clarity and specificity, for example "4/5 — ...". If the judge replies with something unusable, the feedback reads "Could not evaluate prompt." This is explicit; it never runs automatically. It uses the judge backend, so that backend's credentials must be filled in.

It has its own allowance, separate from the run limit: 3 prompt evaluations per 8 hours per browser session.

**Why it helps:** it catches vague wording for the price of one cheap judge call instead of a full run across several models.

## 5. Run options

- **What matters most?** has **Balanced**, **Best quality**, **Fastest** and **Cheapest**. It does not affect what is run. It re-weights the result afterwards, so you can change it after the run too. See [Comparing models](comparing-models.md#what-matters-most).
- **Repeat each prompt** has **1×**, **2×** and **3×**. The hint says "More accurate timing; multiplies model calls and cost." Repeats send each prompt several times so response time and speed are averaged. It counts as one run against the rate limit.

Next to the run button you will see **Selected N / 4** and an estimate such as **Estimated cost: ~$0.0042 (rough; excludes judge calls)**. The estimate assumes roughly one input token per four characters of prompt plus 500 output tokens per call, multiplied by models, test cases and repeats. If a selected model has no price data the line says "unavailable for N model(s)". It updates whenever you change the selection, the prompts or the repeats.

If any selected model needs a region that your chosen region may not offer, a warning line appears listing it, with a link to **See full availability**. See [Backends and credentials](backends-and-credentials.md#regions-and-the-warning).

**Why it helps:** you see a ballpark price before committing, and repeats give steadier timing on a noisy network.

## 6. Run comparison

Click **Run comparison**. Before sending anything, the page checks that you picked at least one model ("Pick at least one model.") and that you filled in credentials for every backend involved, including the judge backend ("Add Amazon Bedrock credentials first."). The server then validates the request again, and checks the shape of each credential (for example a malformed region) before it counts the run against your limit.

While it works the status shows **Running...**. If you have used your 3 runs in the 8-hour window, you see a message with the time you can try again.

Failures of individual model calls do not stop the run. When the run finishes, a pop-up titled "A model call failed" (or "N model calls failed" when several did) lists the errors, with credentials redacted, and has buttons to **Copy details** and **Report an issue on GitHub**. When all the failures are on one backend, it also links to that backend's status page and to reporting a problem to it. A failed cell in the results shows `ERROR` and a **Details** button; clicking it opens the same kind of pop-up titled `[model] failed` (with the model's name) for that one cell.

## 7. Results

After the run, the results section shows, from top to bottom:

1. **Cost banner:** the total estimated cost of the run, split between models and judge calls.
2. **Overall verdict:** the winning model and the judge's rationale.
3. **Side-by-side:** one column per target with a letter grade, four bars, raw numbers, "Overall eval x/5" (the average of the judge's own overall score for each response, not the same thing as the Quality bar), a latency comparison against the fastest target, and a suggested alternative with a **Try it** button. A line **Judged by ... via ...** says which model did the judging. An advice box adds the judge's plain-English trade-off explanation and, where it applies, a bias warning.
4. **How to read this:** a collapsible tip list.
5. **Leaderboard:** a ranked list with each target's grade, score, cost, latency, category chips and a one-sentence summary.
6. **Latency comparison:** a bar per model for each prompt, plus averages.
7. **Category Scores:** a chart of per-category scores.
8. **Results:** each prompt with a **Recommended:** line naming the best model for that prompt, every model's actual response, its latency compared with the fastest, and a collapsible **Evaluation**. Per-cell judge scores and rule-check results are not shown on the page: judge scores are in the CSV and the PDF report, and rule-check pass counts are in the CSV.

All of this is explained in [Comparing models](comparing-models.md).

**Why it helps:** you can read the real answers next to the scores, so a number never has to be taken on trust.

## 8. Recent runs

After your first run a **Recent runs** strip appears. Each entry shows the time and the winner. Click one to bring that run back on screen. The strip lists runs from the current page session. The server also keeps your last 5 runs for your browser session so downloads for them keep working.

**Why it helps:** you can flip between runs to see how a rewritten prompt or a different selection changed the outcome, without re-running anything.

## 9. Downloads

- **Download PDF report** produces `evalforge-report.pdf` for the run on screen, using the priority currently selected under **What matters most?**. It includes the grades, charts and the judge disclosure line.
- **Download CSV** produces `evalforge-report.csv` with one row per prompt and model, including scores, latency, tokens, cost-related category scores and the per-response evaluation scores.

**Why it helps:** the PDF is something you can attach to a decision, and the CSV lets you slice the data in a spreadsheet.

## Where models run

The **Where models run** page (`/availability`) lists every catalog model and shows whether OpenRouter currently lists it (checked live, cached for up to 6 hours) and which regions it is curated for on Bedrock, Vertex AI and Foundry. You can filter by model or provider name, backend and region, and sort by any column. The region data is dated and sourced, and it can lag behind reality, so confirm on the provider's own page before a production decision. If the live check fails, the page keeps the last good data and marks it as stale.

**Why it helps:** it answers "can I run this model in my region?" before you waste a run on it.

## Footer

The footer links to report an issue with EvalForge Lite on GitHub, to the contributing guide, and to each provider's own support page.
