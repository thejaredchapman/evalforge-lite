---
title: Comparing models
nav_order: 4
---

# Comparing models

This page explains how to read a result: what each number means, how the grade is built, what the judge model does, and where the numbers can mislead you. A comparison is only as good as your prompts, so use it alongside your own judgement.

## Why this helps

- **One score you can sort by, and the parts behind it.** Quality is a single 0 to 100 number with a letter grade, but speed, response time and cost are shown separately so you can weigh them yourself.
- **Relative scores, not guesses.** Response time, speed and cost are scored against the other models in the same run, so "fast" means "faster than the others you chose", not an absolute claim.
- **Re-weight instantly.** The "What matters most?" selector re-scores the result and moves the "Best for ..." badge in your browser with no new run and no extra cost.
- **Reasons, not just numbers.** Every successful response carries written strengths, weaknesses and reasoning.
- **You can see who judged.** The page names the judge model and, when it can recognise the judge's provider from its model id, warns if that provider is one you are testing.

## The four metrics

Each column in **Side-by-side** shows four bars out of 100. A higher bar is always better.

| Metric | What it measures | Scored how |
|---|---|---|
| **Quality** | The model's overall grade for the run, blending the rubric judge, rule checks and the per-response evaluation (see [How the grade is built](#how-the-grade-is-built)). | Absolute, 0 to 100. |
| **Response time** | How long the full answer took to arrive. | Relative to the other models in this run. The fastest scores 100, the slowest 0. |
| **Speed** | Output tokens per second (a token is roughly a word fragment). A model is not penalised for writing a longer answer. | Relative to this run. |
| **Cost** | Total cost across the run's model calls. | Relative to this run. The cheapest scores 100, the most expensive 0. |

If every compared model ties on a metric, they all get 100 for it. If a model has no data for a metric, the bar shows "n/a".

Under the bars, the raw numbers appear: average latency in milliseconds (with a plus-or-minus spread when you used repeats), tokens per second, and the cost in dollars. For a reasoning model the speed is prefixed with "≈": on some providers its tokens-per-second includes hidden reasoning tokens, so it is approximate.

A target with no successful response (every cell failed or was blocked by policy) has no bars. Its column says "No successful responses" with the error and blocked counts.

**Why it helps:** a model that is slightly better but ten times as expensive is visible at a glance.

## How the grade is built

The grade comes from up to three ingredients.

1. **Rubric judge score.** If a test case has a rubric, the judge model scores each answer from 1 to 5 against it. The average is multiplied by 20 to give 0 to 100.
2. **Rule checks.** If a test case has rule checks (supplied through the API or MCP, see [MCP server](mcp-server.md)), the score is the percentage that passed. These checks run locally against the response text, with no extra model call, so they cost nothing and give the same answer every time.
3. **Per-response evaluation.** Every successful answer also gets a six-criterion evaluation (below).

Putting them together:

- Rubric score and rule checks together are blended **70% judge, 30% rule checks**.
- That blended score is then averaged **50/50** with the evaluation score when one exists.
- With only a rubric score, or only rule checks, that one is used in place of the blend.
- With neither but an evaluation, the evaluation score is Quality.
- With nothing at all, Quality shows "N/A" and the sentence says "No scoring data available for this model."

The letter grade follows from the 0 to 100 score:

| Score | Grade | Score | Grade |
|---|---|---|---|
| 97 and up | A+ | 77 to 79.9 | C+ |
| 93 to 96.9 | A | 73 to 76.9 | C |
| 90 to 92.9 | A- | 70 to 72.9 | C- |
| 87 to 89.9 | B+ | 60 to 69.9 | D |
| 83 to 86.9 | B | below 60 | F |
| 80 to 82.9 | B- | | |

**Why it helps:** the rubric measures what you care about for this task, the rule checks catch hard requirements such as valid JSON or a length limit, and the evaluation catches problems you did not think to write a rubric for.

## What matters most?

The **What matters most?** selector sets how the four metrics are weighted:

| Priority | Quality | Response time | Speed | Cost |
|---|---|---|---|---|
| **Balanced** (default) | 40% | 20% | 20% | 20% |
| **Best quality** | 70% | 10% | 10% | 10% |
| **Fastest** | 20% | 40% | 40% | 0% |
| **Cheapest** | 30% | 10% | 10% | 50% |

Changing it re-scores instantly in the browser with no new run. It does not reorder the columns. Instead, the column that scores best for your priority gets a **Best for ...** badge, and only once at least two models have results (one result has nothing to be compared with). If a metric is missing for a model, it is left out and the remaining weights are rescaled, so a single missing value does not unfairly drag the score down. Ties are broken by Quality, then by lower latency. The PDF uses the priority selected when you download it.

The **How to read this** box on the page offers rules of thumb: for chat, favour response time; for long outputs such as reports or code, favour speed; for accuracy-critical work, favour quality; if two models are within about 5 quality points, prefer the faster or cheaper one; and run three or more representative prompts before deciding.

**Why it helps:** the same run answers "best overall", "best if I must be quick" and "best if budget is tight" without paying for three runs.

## Overall verdict

At the top of the results, **Overall verdict** gives the judge's pick of winner with a short rationale. The judge sees only each target's score and letter grade, so it ignores speed, cost and your priority selection. It is a summary of those aggregate grades, not a separate test, so treat the leaderboard and your priority as the main guide. If the verdict reply cannot be understood the page shows "No verdict available."

## Per-response evaluation

Every successful response gets one combined judge call that scores it from 1 to 5 on six criteria:

- **Answered the question?** (shown as a tick, tilde or cross: 4 or 5 is a tick, 3 is a tilde, below 3 is a cross)
- **Quality**
- **Instruction following**
- **Completeness**
- **Helpfulness**
- **Safety**

Alongside the scores it writes **Strengths**, **Weaknesses**, a short reasoning paragraph and an **Overall** score out of 5. The evaluation is collapsible under each response (**Evaluation**). The column shows each model's average of the judge's **Overall** score as **Overall eval x/5**. That is a different number from the Quality blend, which uses the mean of the six criteria scores rather than the Overall field.

Evaluation runs once per cell (a prompt and model pair), not once per repeat. If a response's evaluation fails or cannot be read, that card says "Evaluation unavailable." and that response is simply left out of the evaluation half of Quality. It never fails the run. Blocked and errored cells have no evaluation.

The judge is told to treat the response as data and to ignore any instructions written inside it, and the delimiters it uses are neutralised if they appear in the text, which reduces the chance that a response talks the judge into a high score.

**Why it helps:** it explains a grade in words, and it works even when you wrote no rubric.

## Latency comparison

Each column shows how its average response time compares with the fastest target, for example "1.8x slower than fastest (2340 ms)", or "Fastest". The **Latency comparison** panel under the leaderboard shows, for each prompt, a bar per model with the fastest highlighted, and finally "Averages across all prompts".

**Why it helps:** a plain multiple ("1.8x slower") is easier to reason about than a score.

## Total cost

The banner above the verdict totals the whole run, for example "This run cost ≈ $0.0123 — models $0.0101 + judge $0.0022 (6 judge calls)." Judge calls counted are the rubric judge, the per-response evaluation, the policy gate, the overall verdict and the suggestion explainer.

OpenRouter reports the real cost of its calls. For Bedrock, Vertex AI and Foundry, EvalForge Lite does not get a bill back: it **estimates** cost from the token counts the provider returns and the per-million-token prices stored in the app's catalog. The banner says so whenever one of those backends is involved. Treat those figures as estimates, not what your cloud bill will say.

The **Estimated cost** shown before you run is rougher still: it assumes about one input token per four characters plus 500 output tokens per call, and excludes judge calls.

**Why it helps:** you learn what a comparison really cost, including the judge's share, and can budget repeat runs.

## Suggestions and Try it

A column may suggest another model, for example a faster or cheaper tier from the same provider. The rules behind this:

- Suggestions come only from the **same provider** and the **same backend** as the model they replace.
- They never name a model from another provider, an OpenRouter "latest" alias, or a model already in your comparison.
- Rules decide which sibling to suggest, based on quality, speed or cost gaps and the model's tier (fast, balanced or flagship). The judge then writes a short plain-English explanation, and the page falls back to the rule's own one-line reason if that explanation fails or mentions a model outside the comparison.
- This costs one extra judge call per run.

If nothing better is found, the column says "Good fit — no better option in this catalog."

Click **Try it** to swap the suggestion into your selection. If the model it replaces is still selected, the suggestion takes its place. If you already unticked it, the suggestion is added instead, subject to the cap of 4. It does not start a run; click **Run comparison** to test it.

**Why it helps:** it points you at the next model worth testing instead of leaving you to browse the catalog.

## Judge disclosure and bias note

The line **Judged by `[model]` via `[backend]`** tells you which model scored the run. If the app can tell from the judge's model id that it belongs to the same provider as a model you compared, a note appears, in this form: "The judge (...) is from the same family as ... — scores may lean in its favor." A judge can favour its own family's writing style, so for an important decision, run again with a judge from a different provider (use **Judge & policy backend**).

The note is a best-effort warning, not a guarantee. The app finds the judge's provider by looking for a provider name in the judge's model id. The default Foundry judge, `gpt-4o-mini`, has no such name in it, so judging OpenAI models with it shows no warning even though it is an OpenAI model. A custom judge model set through a `*_JUDGE_MODEL` variable behaves the same way if its id has no provider name in it. Check which judge ran and where its model comes from rather than relying on the absence of a note.

**Why it helps:** you know when a score deserves a second look.

## Repeats

**Repeat each prompt** at 2× or 3× sends every prompt several times and averages response time and speed, showing the spread. Judge scoring and rule checks run once, on the first response. A repeat run still counts as one run against your limit, but it multiplies the number of model calls and therefore the cost.

**Why it helps:** one request can be slow by luck; averages are steadier.

## Best model per prompt

Each prompt also records which model handled that specific prompt best, with a reason. It uses the judge score if a rubric was used, then rule-check pass rate, and as a last resort just the fastest response (the reason then says so and suggests adding a rubric or checks). It reuses data already collected, with no extra model call. It is shown on the page as **Recommended: ...** above that prompt's responses, and in the CSV as `best_model_for_prompt`.

## Limits of these numbers

- **Judge scores are opinions.** A judge model is itself an LLM and can be inconsistent or biased. Two runs of the same prompt can score differently.
- **Relative scores shift with the field.** Add or remove a model and the other models' response time, speed and cost scores change.
- **A few prompts are noisy.** Use three or more representative prompts before deciding.
- **Costs on Bedrock, Vertex and Foundry are estimates**, as above.
- **Tags are not benchmarks.** The "Coding", "Long documents" and other filters in the model picker are curated, dated suggestions, not test results.
- **Catalog data can age.** Model ids, prices and regions are curated snapshots and can go stale as providers change things.
