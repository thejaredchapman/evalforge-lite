import csv
import io
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from fpdf import FPDF, Align, XPos, YPos

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
    "speed": "#f9ab00",
}
_CATEGORY_LABELS = {
    "accuracy": "Accuracy",
    "rule_checks": "Rule Checks",
    "cost_efficiency": "Cost Efficiency",
    "speed": "Speed",
}

_CSV_FIELDS = [
    "prompt", "model_id", "status", "response_text", "judge_score",
    "judge_rationale", "checks_passed", "checks_total", "cost_usd", "latency_ms", "tokens",
    "accuracy_score", "rule_checks_score", "cost_efficiency_score", "speed_score",
    "best_model_for_prompt", "best_model_reason",
]


def _grade_fill(letter):
    if not letter:
        return (200, 200, 200)
    return _GRADE_FILL_COLORS.get(letter[0], (200, 200, 200))


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
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.35), ncol=4, fontsize=8)
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150)
    plt.close(fig)
    buffer.seek(0)
    return buffer.getvalue()


def build_pdf(run_result):
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
    grades = run_result.get("grades") or {}
    stats = run_result.get("stats") or {}
    if not grades:
        pdf.set_font("Courier", "", 10)
        pdf.multi_cell(0, 6, "No grading data available.", **_NEW_LINE)
    else:
        col_widths = (60, 25, 25, 35, 35)
        headers = ("Model", "Grade", "Score", "Total Cost", "Avg Latency")
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
            pdf.ln()
    pdf.ln(4)

    if any(g.get("categories") for g in grades.values()):
        pdf.set_font("Courier", "B", 12)
        pdf.cell(0, 8, "Category Breakdown", **_NEW_LINE)
        cat_col_widths = (60, 30, 30, 30, 30)
        cat_headers = ("Model", "Accuracy", "Checks", "Cost Eff.", "Speed")
        pdf.set_font("Courier", "B", 9)
        for width, header in zip(cat_col_widths, cat_headers):
            pdf.cell(width, 7, header, border=1)
        pdf.ln()

        pdf.set_font("Courier", "", 9)
        for model_id, grade in grades.items():
            categories = grade.get("categories") or {}
            pdf.cell(cat_col_widths[0], 7, model_id, border=1)
            for width, key in zip(cat_col_widths[1:], ("accuracy", "rule_checks", "cost_efficiency", "speed")):
                value = categories.get(key)
                pdf.cell(width, 7, f"{value:.0f}" if value is not None else "N/A", border=1, align="C")
            pdf.ln()
        pdf.ln(4)

        chart_bytes = _build_category_chart(grades)
        if chart_bytes:
            pdf.image(io.BytesIO(chart_bytes), x=Align.C, w=170)
            pdf.ln(4)

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
                categories.get("speed", ""),
            ]
            category_values = [v if v is not None else "" for v in category_values]

            if cell.get("blocked"):
                writer.writerow([
                    prompt, model_id, "blocked", "", "",
                    f"{cell.get('policy_clause')}: {cell.get('policy_reason')}",
                    "", "", "", "", "",
                    *category_values, best_model_id, best_model_reason,
                ])
            elif cell.get("error"):
                writer.writerow([
                    prompt, model_id, "error", cell.get("error"), "",
                    "", "", "", "", "", "",
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
                    *category_values, best_model_id, best_model_reason,
                ])

    return buffer.getvalue()
