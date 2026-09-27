import csv
import io
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from fpdf import FPDF, Align, XPos, YPos

import catalog
import gateway
import grading

_NEW_LINE = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}

_GRADE_FILL_COLORS = {
    "A": (30, 142, 62),
    "B": (249, 171, 0),
    "C": (249, 171, 0),
    "D": (217, 48, 37),
    "F": (217, 48, 37),
}

_CATEGORY_COLORS = {
    "accuracy": "#4285F4",
    "rule_checks": "#0668E1",
    "cost_efficiency": "#1e8e3e",
    "response_time": "#f9ab00",
    "throughput": "#e8710a",
}
_CATEGORY_LABELS = {
    "accuracy": "Accuracy",
    "rule_checks": "Rule Checks",
    "cost_efficiency": "Cost Efficiency",
    "response_time": "Response Time",
    "throughput": "Speed (tok/s)",
}

_CSV_FIELDS = [
    "prompt", "model_id", "status", "response_text", "judge_score",
    "judge_rationale", "checks_passed", "checks_total", "cost_usd", "latency_ms", "tokens", "tokens_per_sec",
    "accuracy_score", "rule_checks_score", "cost_efficiency_score", "response_time_score", "throughput_score",
    "best_model_for_prompt", "best_model_reason",
]


def _grade_fill(letter):
    if not letter:
        return (200, 200, 200)
    return _GRADE_FILL_COLORS.get(letter[0], (200, 200, 200))


def _pdf_safe(text):
    return (text or "").replace("—", "-").replace("≈", "~")


def _is_reasoning(target):
    model_id, _ = gateway.parse_target(target)
    _, model = catalog.find_model(catalog.load_catalog(), model_id)
    return bool(model and model.get("reasoning"))


def _build_category_chart(grades):
    models = [m for m, g in grades.items() if g.get("categories")]
    if not models:
        return None

    categories = list(_CATEGORY_COLORS.keys())
    n = len(categories)
    width = 0.8 / n
    positions = list(range(len(models)))

    fig, ax = plt.subplots(figsize=(8, 4))
    for i, cat in enumerate(categories):
        values = [grades[m]["categories"].get(cat) or 0 for m in models]
        bar_positions = [p + i * width for p in positions]
        ax.bar(bar_positions, values, width, label=_CATEGORY_LABELS[cat], color=_CATEGORY_COLORS[cat])

    tick_positions = [p + width * (n - 1) / 2 for p in positions]
    ax.set_ylabel("Score (0-100)")
    ax.set_title("Category Scores by Model")
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(models, rotation=15, ha="right")
    ax.set_ylim(0, 110)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.35), ncol=5, fontsize=8)
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150)
    plt.close(fig)
    buffer.seek(0)
    return buffer.getvalue()


def build_pdf(run_result, priority=None):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Courier", "B", 16)
    pdf.cell(0, 10, "EvalForge Lite Report", **_NEW_LINE)

    created_at = run_result.get("created_at")
    if created_at:
        pdf.set_font("Courier", "", 9)
        pdf.set_text_color(120, 120, 120)
        timestamp = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S")
        pdf.cell(0, 6, f"Generated {timestamp}", **_NEW_LINE)
        pdf.set_text_color(0, 0, 0)

    grades = run_result.get("grades") or {}
    stats = run_result.get("stats") or {}

    judge_info = run_result.get("judge")
    if judge_info:
        pdf.set_font("Courier", "", 9)
        pdf.set_text_color(120, 120, 120)
        backend_label = gateway.BACKEND_LABELS.get(judge_info.get("backend"), judge_info.get("backend"))
        pdf.cell(0, 6, f"Judged by {judge_info.get('model')} via {backend_label}", **_NEW_LINE)
        pdf.set_text_color(0, 0, 0)

    if priority:
        ranking = grading.rank_targets(grades, stats, priority)
        best_pick = ranking[0] if ranking else "n/a"
        pdf.set_font("Courier", "", 9)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 6, f"Priority: {grading.PRIORITY_LABELS[priority]} - best pick: {best_pick}", **_NEW_LINE)
        pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    verdict = run_result.get("verdict") or {}
    pdf.set_font("Courier", "B", 12)
    pdf.cell(0, 8, "Overall Verdict", **_NEW_LINE)
    pdf.set_font("Courier", "", 10)
    winner = verdict.get("winner") or "No verdict available"
    pdf.multi_cell(0, 6, f"Winner: {winner}\n{verdict.get('rationale', '')}", **_NEW_LINE)
    pdf.ln(4)

    pdf.set_font("Courier", "B", 12)
    pdf.cell(0, 8, "Leaderboard", **_NEW_LINE)
    if not grades:
        pdf.set_font("Courier", "", 10)
        pdf.multi_cell(0, 6, "No grading data available.", **_NEW_LINE)
    else:
        col_widths = (55, 20, 20, 30, 30, 25)
        headers = ("Model", "Grade", "Score", "Total Cost", "Avg Latency", "Tok/s")
        pdf.set_font("Courier", "B", 9)
        for width, header in zip(col_widths, headers):
            pdf.cell(width, 7, header, border=1)
        pdf.ln()

        pdf.set_font("Courier", "", 9)
        for model_id, grade in grades.items():
            model_stats = stats.get(model_id) or {}
            letter = grade.get("letter")

            pdf.cell(col_widths[0], 7, model_id, border=1)

            fill = _grade_fill(letter)
            pdf.set_fill_color(*fill)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(col_widths[1], 7, letter or "N/A", border=1, fill=True, align="C")
            pdf.set_text_color(0, 0, 0)

            score = grade.get("score")
            pdf.cell(col_widths[2], 7, f"{score}" if score is not None else "N/A", border=1, align="C")

            total_cost = model_stats.get("total_cost_usd")
            pdf.cell(col_widths[3], 7, f"${total_cost:.4f}" if total_cost is not None else "N/A", border=1, align="C")

            avg_latency = model_stats.get("avg_latency_ms")
            pdf.cell(col_widths[4], 7, f"{avg_latency:.0f}ms" if avg_latency is not None else "N/A", border=1, align="C")

            tokens_per_sec = model_stats.get("avg_tokens_per_sec")
            if tokens_per_sec is not None:
                prefix = "~" if _is_reasoning(model_id) else ""
                tok_s_text = f"{prefix}{tokens_per_sec:.1f}"
            else:
                tok_s_text = "N/A"
            pdf.cell(col_widths[5], 7, tok_s_text, border=1, align="C")
            pdf.ln()
    pdf.ln(4)

    if any(g.get("categories") for g in grades.values()):
        pdf.set_font("Courier", "B", 12)
        pdf.cell(0, 8, "Category Breakdown", **_NEW_LINE)
        cat_col_widths = (55, 25, 25, 25, 25, 25)
        cat_headers = ("Model", "Accuracy", "Checks", "Cost Eff.", "Resp. Time", "Speed")
        pdf.set_font("Courier", "B", 9)
        for width, header in zip(cat_col_widths, cat_headers):
            pdf.cell(width, 7, header, border=1)
        pdf.ln()

        pdf.set_font("Courier", "", 9)
        for model_id, grade in grades.items():
            categories = grade.get("categories") or {}
            pdf.cell(cat_col_widths[0], 7, model_id, border=1)
            for width, key in zip(cat_col_widths[1:], _CATEGORY_COLORS.keys()):
                value = categories.get(key)
                pdf.cell(width, 7, f"{value:.0f}" if value is not None else "N/A", border=1, align="C")
            pdf.ln()
        pdf.ln(4)

        chart_bytes = _build_category_chart(grades)
        if chart_bytes:
            pdf.image(io.BytesIO(chart_bytes), x=Align.C, w=170)
            pdf.ln(4)

    suggestions = run_result.get("suggestions") or {}
    advice = run_result.get("advice") or ""
    bias_note = run_result.get("bias_note") or ""
    if any(suggestions.values()) or advice or bias_note:
        pdf.set_font("Courier", "B", 12)
        pdf.cell(0, 8, "Suggestions", **_NEW_LINE)
        pdf.set_font("Courier", "", 9)
        for target, suggestion in suggestions.items():
            if target not in stats:
                continue
            if suggestion:
                pdf.multi_cell(
                    0, 5, f"{target}: try {suggestion['name']} - {_pdf_safe(suggestion['reason'])}", **_NEW_LINE
                )
            else:
                pdf.multi_cell(0, 5, f"{target}: good fit - no better option in this catalog", **_NEW_LINE)

        if advice:
            pdf.ln(2)
            pdf.multi_cell(0, 5, _pdf_safe(advice), **_NEW_LINE)

        if bias_note:
            pdf.ln(2)
            pdf.set_text_color(120, 120, 120)
            pdf.multi_cell(0, 5, _pdf_safe(bias_note), **_NEW_LINE)
            pdf.set_text_color(0, 0, 0)

        if any(_is_reasoning(target) for target in grades):
            pdf.set_font("Courier", "", 8)
            pdf.set_text_color(120, 120, 120)
            pdf.multi_cell(0, 5, "~ = approximate: includes hidden reasoning tokens on some providers.", **_NEW_LINE)
            pdf.set_text_color(0, 0, 0)
        pdf.ln(2)

    pdf.set_font("Courier", "B", 12)
    pdf.cell(0, 8, "Test Cases", **_NEW_LINE)
    for row in run_result.get("results") or []:
        pdf.set_font("Courier", "B", 10)
        pdf.multi_cell(0, 6, f"Prompt: {row['test_case']['prompt']}", **_NEW_LINE)

        best_model = row.get("best_model")
        if best_model and best_model.get("model_id"):
            pdf.set_font("Courier", "", 9)
            pdf.set_text_color(30, 142, 62)
            pdf.multi_cell(0, 5, f"  Recommended: {best_model['model_id']} - {best_model['reason']}", **_NEW_LINE)
            pdf.set_text_color(0, 0, 0)

        pdf.set_font("Courier", "", 9)
        for model_id, cell in row["cells"].items():
            if cell.get("blocked"):
                pdf.multi_cell(0, 5, f"  [{model_id}] BLOCKED - {cell.get('policy_clause')}: {cell.get('policy_reason')}", **_NEW_LINE)
            elif cell.get("error"):
                pdf.multi_cell(0, 5, f"  [{model_id}] ERROR: {cell.get('error')}", **_NEW_LINE)
            else:
                pdf.multi_cell(0, 5, f"  [{model_id}] {cell.get('response_text')}", **_NEW_LINE)
                if cell.get("judge_score") is not None:
                    pdf.multi_cell(0, 5, f"    judge score: {cell['judge_score']}/5 - {cell.get('judge_rationale')}", **_NEW_LINE)
        pdf.ln(2)

    return bytes(pdf.output())


def build_csv(run_result):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_FIELDS)

    grades = run_result.get("grades") or {}

    for row in run_result.get("results") or []:
        prompt = row["test_case"]["prompt"]
        best_model = row.get("best_model") or {}
        best_model_id = best_model.get("model_id") or ""
        best_model_reason = best_model.get("reason") or ""

        for model_id, cell in row["cells"].items():
            categories = (grades.get(model_id) or {}).get("categories") or {}
            category_values = [
                categories.get("accuracy", ""),
                categories.get("rule_checks", ""),
                categories.get("cost_efficiency", ""),
                categories.get("response_time", ""),
                categories.get("throughput", ""),
            ]
            category_values = [v if v is not None else "" for v in category_values]

            if cell.get("blocked"):
                writer.writerow([
                    prompt, model_id, "blocked", "", "",
                    f"{cell.get('policy_clause')}: {cell.get('policy_reason')}",
                    "", "", "", "", "", "",
                    *category_values, best_model_id, best_model_reason,
                ])
            elif cell.get("error"):
                writer.writerow([
                    prompt, model_id, "error", cell.get("error"), "",
                    "", "", "", "", "", "", "",
                    *category_values, best_model_id, best_model_reason,
                ])
            else:
                checks = cell.get("checks") or []
                checks_passed = sum(1 for c in checks if c["passed"])
                writer.writerow([
                    prompt, model_id, "ok", cell.get("response_text"),
                    cell.get("judge_score") if cell.get("judge_score") is not None else "",
                    cell.get("judge_rationale") or "",
                    checks_passed, len(checks),
                    cell.get("cost_usd"), cell.get("latency_ms"), cell.get("tokens"),
                    cell.get("tokens_per_sec") if cell.get("tokens_per_sec") is not None else "",
                    *category_values, best_model_id, best_model_reason,
                ])

    return buffer.getvalue()
