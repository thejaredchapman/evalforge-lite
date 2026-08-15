import json
import re


def run_check(check, response_text):
    check_type = check.get("type")

    if check_type == "contains":
        return check["value"] in response_text

    if check_type == "regex":
        return re.search(check["value"], response_text) is not None

    if check_type == "json_valid":
        try:
            json.loads(response_text)
            return True
        except (json.JSONDecodeError, TypeError):
            return False

    if check_type == "max_length":
        return len(response_text) <= check["value"]

    raise ValueError(f"Unknown check type: {check_type!r}")


def run_checks(checks_list, response_text):
    return [
        {"check": check, "passed": run_check(check, response_text)}
        for check in checks_list
    ]
