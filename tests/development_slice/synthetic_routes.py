"""Complete, approved synthetic destinations for the development fixture."""

_ROUTES = {
    "http://receiver:8766/v1/chat/completions": "receiver",
    "http://receiver_delay:8766/v1/chat/completions": "receiver_delay",
    "http://receiver_fail:8766/v1/chat/completions": "receiver_fail",
}


def fixture_destination(base: dict, url: str) -> dict:
    try:
        endpoint = _ROUTES[url]
    except (KeyError, TypeError) as cause:
        raise ValueError("unapproved synthetic fixture destination") from cause
    return {**base, "endpoint": endpoint}
