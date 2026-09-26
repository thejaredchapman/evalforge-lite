import json

import pytest

import scrub


@pytest.mark.parametrize("secret", [
    "sk-or-v1-abcdefgh12345678",
    "AKIAABCDEFGHIJKLMNOP",
    "ASIAABCDEFGHIJKLMNOP",
    "ABSKQmVkcm9ja0FQSUtleS1leGFtcGxlZXhhbXBsZQ==",
    "bedrock-api-key-YmVkcm9jay5hbWF6b25hd3MuY29tLz9BY3Rpb24",
    "ya29.a0AfH6SMBexample_token-value",
])
def test_scrub_redacts_known_secret_formats(secret):
    out = scrub.scrub(f"request failed using {secret} today")
    assert secret not in out
    assert "[REDACTED]" in out


def test_scrub_redacts_pem_private_key_blocks():
    pem = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg\nkqhkiG9w0BAQEF\n-----END PRIVATE KEY-----"
    out = scrub.scrub(f"bad key: {pem} end")
    assert "MIIEvQIBADANBg" not in out
    assert out == "bad key: [REDACTED] end"


def test_scrub_redacts_exact_creds_values_without_a_pattern():
    creds = {"bedrock": {"region": "us-east-1", "access_key_id": "AKIAABCDEFGHIJKLMNOP",
                         "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"}}
    out = scrub.scrub("sig mismatch for wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", creds)
    assert "wJalrXUtnFEMI" not in out


def test_scrub_redacts_service_account_private_key_in_either_encoding():
    key = "-----BEGIN PRIVATE KEY-----\nABCDEFGH12345678\n-----END PRIVATE KEY-----\n"
    sa_json = json.dumps({"type": "service_account", "private_key": key})
    creds = {"vertex": {"project": "p", "region": "us-central1", "service_account_json": sa_json}}
    escaped = json.dumps(key)[1:-1]
    out = scrub.scrub(f"echo: {escaped}", creds)
    assert "ABCDEFGH12345678" not in out


def test_scrub_leaves_short_or_non_secret_values_alone():
    creds = {"bedrock": {"region": "us-east-1", "api_key": "short"}}
    assert scrub.scrub("region us-east-1 key short", creds) == "region us-east-1 key short"


def test_scrub_without_creds_still_applies_patterns():
    assert scrub.scrub("nothing secret here") == "nothing secret here"
