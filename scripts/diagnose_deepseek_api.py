"""Probe the DeepSeek endpoint without sending any report content or API key to logs."""

from __future__ import annotations

import json
import os
import sys

import httpx


def compact_body(response: httpx.Response) -> str:
    try:
        text = response.text.strip()
    except Exception:  # pragma: no cover - defensive diagnostic path
        return "<unable to read response body>"
    return text[:2000] if text else "<empty response body>"


def diagnostic_headers(response: httpx.Response) -> dict[str, str]:
    safe_headers = (
        "server",
        "content-type",
        "content-length",
        "x-ds-trace-id",
        "eo-log-uuid",
        "via",
        "cf-ray",
        "date",
    )
    return {
        name: response.headers[name]
        for name in safe_headers
        if name in response.headers
    }


def probe(client: httpx.Client, *, name: str, payload: dict) -> dict:
    response = client.post("/chat/completions", json=payload)
    return {
        "probe": name,
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "diagnostic_headers": diagnostic_headers(response),
        "body": compact_body(response),
    }


def probe_models(client: httpx.Client) -> dict:
    response = client.get("/models")
    return {
        "probe": "models_endpoint",
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "diagnostic_headers": diagnostic_headers(response),
        "body": compact_body(response),
    }


def main() -> None:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    trust_environment_proxy = os.environ.get("DEEPSEEK_TRUST_ENV", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    base_payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(
        base_url=base_url,
        headers=headers,
        timeout=45.0,
        trust_env=trust_environment_proxy,
    ) as client:
        results = [
            probe_models(client),
            probe(client, name="minimal_64_tokens", payload={**base_payload, "max_tokens": 64}),
            probe(client, name="plain_8000_tokens", payload={**base_payload, "max_tokens": 8000}),
            probe(
                client,
                name="json_object_8000_tokens",
                payload={
                    **base_payload,
                    "max_tokens": 8000,
                    "response_format": {"type": "json_object"},
                },
            ),
        ]

    print(
        json.dumps(
            {
                "base_url": base_url,
                "model": model,
                "trust_environment_proxy": trust_environment_proxy,
                "key_sanity": {
                    "length": len(api_key),
                    "has_leading_or_trailing_whitespace": api_key != api_key.strip(),
                },
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not any(
        item["probe"] == "minimal_64_tokens" and item["status_code"] == 200
        for item in results
    ):
        sys.exit(1)


if __name__ == "__main__":
    main()
