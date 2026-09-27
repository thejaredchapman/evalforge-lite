class GatewayError(Exception):
    pass


MAX_BODY_CHARS = 2000


def describe_request_error(e):
    """Return str(e) plus the provider's response body, so users can see *why*
    a call failed (e.g. Bedrock's "You don't have access to the model"), not
    just the HTTP status. The body is truncated to MAX_BODY_CHARS; callers
    already pass error text through scrub.scrub() before it reaches a user.
    """
    message = str(e)
    response = getattr(e, "response", None)
    if response is None:
        return message
    try:
        body = (response.text or "").strip()
    except Exception:
        body = ""
    if not body:
        return message
    if len(body) > MAX_BODY_CHARS:
        body = f"{body[:MAX_BODY_CHARS]}… [truncated, {len(body)} characters total]"
    return f"{message}\nResponse body: {body}"
