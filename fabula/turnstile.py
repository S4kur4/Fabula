from __future__ import annotations

import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app


SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
LOGGER = logging.getLogger(__name__)


def is_enabled() -> bool:
    return bool(
        current_app.config.get("TURNSTILE_SITE_KEY")
        and current_app.config.get("TURNSTILE_SECRET_KEY")
    )


def verify_token(token: str, remote_ip: str) -> tuple[bool, str]:
    if not is_enabled():
        return True, "disabled"
    if not token or len(token) > 2048:
        return False, "missing-or-oversized-token"

    verifier = current_app.config.get("TURNSTILE_VERIFIER")
    if callable(verifier):
        result = verifier(token, remote_ip)
    else:
        body = urlencode(
            {
                "secret": current_app.config["TURNSTILE_SECRET_KEY"],
                "response": token,
                "remoteip": remote_ip,
            }
        ).encode("utf-8")
        verification_request = Request(
            SITEVERIFY_URL,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urlopen(
                verification_request,
                timeout=current_app.config["TURNSTILE_TIMEOUT_SECONDS"],
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            LOGGER.warning("Turnstile Siteverify request failed: %s", type(error).__name__)
            return False, "siteverify-unavailable"

    if not isinstance(result, dict) or not result.get("success"):
        return False, "verification-failed"
    if result.get("action") != current_app.config["TURNSTILE_ACTION"]:
        return False, "action-mismatch"

    expected_hostnames = current_app.config["TURNSTILE_EXPECTED_HOSTNAMES"]
    response_hostname = str(result.get("hostname", "")).strip().lower()
    if expected_hostnames and response_hostname not in expected_hostnames:
        return False, "hostname-mismatch"
    return True, "verified"
