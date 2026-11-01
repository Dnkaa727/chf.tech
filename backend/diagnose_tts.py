r"""One short GenAPI probe, runnable in an existing container without rebuilding it.

PowerShell: Get-Content -Raw .\backend\diagnose_tts.py | docker exec -i chf-tech python -
Only a fixed public phrase is submitted. Never print request headers or credentials.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from urllib.parse import quote

import httpx

ENDPOINT = "https://api.gen-api.ru/api/v1/networks/silero-tts"
PAYLOAD = {"text": "\u041f\u0440\u0438\u0432\u0435\u0442! \u042d\u0442\u043e \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0433\u043e\u043b\u043e\u0441\u0430.", "callback_url": None}


def redact(value, key: str):
    """Keep useful validation messages, but scrub credentials even inside nested errors."""
    if isinstance(value, dict):
        return {
            redact(str(name), key): "[REDACTED]" if re.search(
                r"(?:key|token|secret|password|authorization|cookie)", str(name), re.I
            ) else redact(item, key)
            for name, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, key) for item in value[:30]]
    if isinstance(value, str):
        if key:
            for variant in {key, json.dumps(key)[1:-1], quote(key, safe="")}:
                value = value.replace(variant, "[REDACTED]")
        value = re.sub(r"(?i)Bearer\s+[^\s\"'<>]+", "Bearer [REDACTED]", value)
        return value
    return value


def probe(key: str, client: httpx.Client) -> dict:
    if not key:
        return {"error": "GENAPI_API_KEY is missing in the running container"}
    try:
        response = client.post(ENDPOINT, json=PAYLOAD, headers={
            "Authorization": f"Bearer {key}", "Accept": "application/json",
        })
    except httpx.HTTPError as error:
        return {"transport_error": type(error).__name__}
    report = {"http_status": response.status_code}
    try:
        body = response.json()
    except ValueError:
        body = response.text
    if response.is_success:
        # Do not expose signed asset URLs or start additional generation/download requests.
        report["result"] = {name: body.get(name) for name in ("request_id", "status")} if isinstance(body, dict) else "accepted"
    else:
        report["provider_error"] = redact(body, key)
    return report


def main() -> int:
    key = os.getenv("GENAPI_API_KEY", "").strip()
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        report = probe(key, client)
    source = Path("backend/tts.py")
    if source.is_file():
        report["container_has_minimal_payload"] = 'payload: dict = {"text": text, "callback_url": None}' in source.read_text()
    # Redact before truncating, so a cut-off token cannot escape replacement.
    print(json.dumps(redact(report, key), ensure_ascii=False, indent=2)[:6000])
    return 0 if report.get("http_status", 500) < 400 else 1


if __name__ == "__main__":
    raise SystemExit(main())
