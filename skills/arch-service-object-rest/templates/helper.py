"""Helper — the evidence an API call leaves in the Allure report.

Every call attaches three things, in this order:

    curl        a runnable reproduction of the exact request
    request     method, URL, headers and body — as they went on the wire
    response    status, timing, headers and body — as they came back

The curl is built from ``httpx.Request``, i.e. AFTER session headers are
merged, query params encoded and the body serialised — so it reproduces
what actually happened rather than what the call site meant. Secret
headers are redacted by default, because a report is something people
paste into tickets; ``ALLURE_SHOW_SECRETS=1`` puts the real values back
for local debugging.
"""
from __future__ import annotations

import json
import os
import shlex
from typing import Any

import allure
import httpx

#: Header values that never reach a report unless explicitly asked for.
SENSITIVE_HEADERS = frozenset({
    "authorization", "proxy-authorization", "cookie", "set-cookie",
    "x-api-key", "api-key", "x-auth-token", "x-csrf-token", "x-access-token",
})

#: Headers curl computes itself. Left out of the COMMAND so it stays
#: readable and pasteable (content-length would break it outright if the
#: body were edited); kept in full in the request attachment, which is
#: the complete record.
TRANSPORT_HEADERS = frozenset({
    "host", "content-length", "connection", "accept-encoding",
})

#: Bodies longer than this are cut; the evidence says by how much.
MAX_BODY_CHARS = 50_000

_REDACTED = "<redacted — rerun with ALLURE_SHOW_SECRETS=1 to include>"


def _show_secrets() -> bool:
    return os.getenv("ALLURE_SHOW_SECRETS", "").strip().lower() in {"1", "true", "yes"}


def _header_value(name: str, value: str) -> str:
    if _show_secrets() or name.lower() not in SENSITIVE_HEADERS:
        return value
    return _REDACTED


def _headers(headers: Any) -> dict[str, str]:
    return {k: _header_value(k, v) for k, v in dict(headers).items()}


def _decode(raw: bytes | None) -> str:
    if not raw:
        return ""
    text = raw.decode("utf-8", errors="replace")
    if len(text) > MAX_BODY_CHARS:
        cut = len(text) - MAX_BODY_CHARS
        return text[:MAX_BODY_CHARS] + f"\n… truncated, {cut} more characters"
    return text


def _maybe_json(text: str) -> Any:
    """The body as parsed JSON when it is JSON — so the report renders it
    as a tree — and as raw text when it is not."""
    if not text:
        return ""
    try:
        return json.loads(text)
    except ValueError:
        return text


def as_curl(request: httpx.Request) -> str:
    """The request as a curl command that can be pasted into a shell."""
    parts = [f"curl -i -X {request.method}", shlex.quote(str(request.url))]
    for name, value in request.headers.items():
        if name.lower() in TRANSPORT_HEADERS:
            continue
        parts.append(f"-H {shlex.quote(f'{name}: {_header_value(name, value)}')}")
    body = _decode(request.content)
    if body:
        parts.append(f"--data-raw {shlex.quote(body)}")
    return " \\\n  ".join(parts)


class Helper:
    """Attach request / response evidence to the Allure report."""

    @staticmethod
    def attach(name: str, data: Any) -> None:
        if isinstance(data, str):
            body, kind = data, allure.attachment_type.TEXT
        else:
            body = json.dumps(data, indent=2, ensure_ascii=False, default=str)
            kind = allure.attachment_type.JSON
        allure.attach(body, name=name, attachment_type=kind)

    @staticmethod
    def attach_request(request: httpx.Request) -> None:
        """The curl first — it is what a person reaches for — then the
        request broken out."""
        allure.attach(
            as_curl(request),
            name=f"curl · {request.method} {request.url.path}",
            attachment_type=allure.attachment_type.TEXT,
        )
        Helper.attach(
            f"request · {request.method} {request.url.path}",
            {
                "method": request.method,
                "url": str(request.url),
                "headers": _headers(request.headers),
                "body": _maybe_json(_decode(request.content)),
            },
        )

    @staticmethod
    def attach_response(response: httpx.Response) -> None:
        try:
            elapsed_ms = round(response.elapsed.total_seconds() * 1000)
        except RuntimeError:            # not read yet / streamed
            elapsed_ms = None
        Helper.attach(
            f"response · {response.status_code} · {elapsed_ms} ms",
            {
                "status": response.status_code,
                "reason": response.reason_phrase,
                "elapsed_ms": elapsed_ms,
                "headers": _headers(response.headers),
                "body": _maybe_json(_decode(response.content)),
            },
        )

    @staticmethod
    def attach_transport_error(request: httpx.Request, exc: BaseException) -> None:
        """A request that never got an answer is still evidence — the
        curl is already attached, this says why nothing came back."""
        Helper.attach(
            f"response · no answer ({type(exc).__name__})",
            {"error": f"{type(exc).__name__}: {exc}", "url": str(request.url)},
        )
