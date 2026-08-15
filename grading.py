GRADE_BOUNDARIES = [
    (97, "A+"), (93, "A"), (90, "A-"),
    (87, "B+"), (83, "B"), (80, "B-"),
    (77, "C+"), (73, "C"), (70, "C-"),
    (60, "D"), (0, "F"),
]


def letter_grade(score):
    for threshold, letter in GRADE_BOUNDARIES:
        if score >= threshold:
            return letter
    return "F"


def compute_score(judge_scores, rule_check_results):
    judge_component = None
    if judge_scores:
        judge_component = (sum(judge_scores) / len(judge_scores)) * 20

    rule_component = None
    if rule_check_results:
        rule_component = 100 * (sum(1 for r in rule_check_results if r) / len(rule_check_results))

    if judge_component is not None and rule_component is not None:
        return round(judge_component * 0.7 + rule_component * 0.3, 1)
    if judge_component is not None:
        return round(judge_component, 1)
    if rule_component is not None:
        return round(rule_component, 1)
    return None


def summary_sentence(score, letter, rule_check_results, judge_rationales):
    if score is None:
        return "No scoring data available for this model."

    if letter in ("A+", "A", "A-"):
        tier_phrase = "Strong performer"
    elif letter in ("B+", "B", "B-"):
        tier_phrase = "Solid performer"
    elif letter in ("C+", "C", "C-"):
        tier_phrase = "Middling performer"
    elif letter == "D":
        tier_phrase = "Weak performer"
    else:
        tier_phrase = "Poor performer"

    detail = ""
    if rule_check_results:
        fail_count = sum(1 for r in rule_check_results if not r)
        if fail_count > 0:
            detail = f" Failed {fail_count} of {len(rule_check_results)} rule checks."
        else:
            detail = " Passed all rule checks."
    elif judge_rationales:
        detail = f" {judge_rationales[0]}"

    return f"{tier_phrase} ({letter}, {score}/100).{detail}"


def grade_model(judge_scores, rule_check_results, judge_rationales):
    score = compute_score(judge_scores, rule_check_results)
    if score is None:
        return {"score": None, "letter": None, "sentence": "No scoring data available for this model."}
    letter = letter_grade(score)
    sentence = summary_sentence(score, letter, rule_check_results, judge_rationales)
    return {"score": score, "letter": letter, "sentence": sentence}
