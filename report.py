import csv
import io
from datetime import datetime

from fpdf import FPDF, XPos, YPos

_NEW_LINE = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}

_GRADE_FILL_COLORS = {
    "A": (30, 142, 62),
    "B": (249, 171, 0),
    "C": (249, 171, 0),
    "D": (217, 48, 37),
    "F": (217, 48, 37),
}

_CSV_FIELDS = [
    "prompt", "model_id", "status", "response_text", "judge_score",
    "judge_rationale", "checks_passed", "checks_total", "cost_usd", "latency_ms", "tokens",
]


def _grade_fill(letter):
    if not letter:
        return (200, 200, 200)
    return _GRADE_FILL_COLORS.get(letter[0], (200, 200, 200))


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

    pdf.set_font("Courier", "B", 12)
    pdf.cell(0, 8, "Test Cases", **_NEW_LINE)
    for row in run_result.get("results") or []:
        pdf.set_font("Courier", "B", 10)
        pdf.multi_cell(0, 6, f"Prompt: {row['test_case']['prompt']}", **_NEW_LINE)
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

    for row in run_result.get("results") or []:
        prompt = row["test_case"]["prompt"]
        for model_id, cell in row["cells"].items():
            if cell.get("blocked"):
                writer.writerow([
                    prompt, model_id, "blocked", "", "",
                    f"{cell.get('policy_clause')}: {cell.get('policy_reason')}",
                    "", "", "", "", "",
                ])
            elif cell.get("error"):
                writer.writerow([
                    prompt, model_id, "error", cell.get("error"), "",
                    "", "", "", "", "", "",
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
                ])

    return buffer.getvalue()
