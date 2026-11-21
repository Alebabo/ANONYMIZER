"""Python client for the OpenAnonymizer privacy API.

    from anonymizer_sdk import OpenAnonymizer

    anonymizer = OpenAnonymizer(api_key="anonymizer_...")            # or ANONYMIZER_API_KEY / ANONYMIZER_BASE_URL
    result = anonymizer.protect("Max Mustermann is our client ...")
    if result.allowed:
        print(result.text)

The client is thin on purpose: all privacy logic runs in the OpenAnonymizer service,
so the same policies apply to every application.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

__all__ = ["OpenAnonymizer", "AnonymizerError", "PolicyViolation", "Result"]
__version__ = "0.1.0"

DEFAULT_BASE_URL = "http://localhost:8080"


class AnonymizerError(Exception):
    def __init__(self, status: int, message: str, body: Any = None) -> None:
        super().__init__(f"{status}: {message}")
        self.status, self.message, self.body = status, message, body


class PolicyViolation(AnonymizerError):
    """Raised by ``require_allowed=True`` calls when the policy forbids sending."""


class Result(dict):
    """dict with attribute access (``result.text``) for convenience."""

    def __getattr__(self, name: str) -> Any:
        try:
            value = self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc
        return Result(value) if isinstance(value, dict) else value


def _wrap(data: Any) -> Any:
    if isinstance(data, dict):
        return Result(data)
    if isinstance(data, list):
        return [_wrap(x) for x in data]
    return data


class OpenAnonymizer:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("ANONYMIZER_API_KEY")
        if not self.api_key:
            raise ValueError("api_key missing (pass it or set ANONYMIZER_API_KEY)")
        self.base_url = (base_url or os.environ.get("ANONYMIZER_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)

    # -- plumbing --------------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {"Authorization": f"Bearer {self.api_key}", "User-Agent": f"anonymizer-sdk-python/{__version__}"}
        resp = self._http.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = None
            detail = body.get("detail") if isinstance(body, dict) else None
            if isinstance(body, dict) and isinstance(body.get("error"), dict):
                detail = body["error"].get("message")
            raise AnonymizerError(resp.status_code, str(detail or resp.reason_phrase), body)
        return _wrap(resp.json())

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> "OpenAnonymizer":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @staticmethod
    def _clean(**kwargs: Any) -> dict[str, Any]:
        return {k: v for k, v in kwargs.items() if v is not None}

    # -- privacy ---------------------------------------------------------------
    def scan(self, text: str, language: str | None = None) -> Result:
        """Detected entities with types and offsets (no raw values)."""
        return self._request("POST", "/v1/scan", json=self._clean(text=text, language=language))

    def classify(self, text: str, language: str | None = None, corrections: dict[str, str] | None = None) -> Result:
        return self._request("POST", "/v1/classify", json=self._clean(text=text, language=language,
                                                                         corrections=corrections))

    def anonymize(self, text: str, language: str | None = None, methods: dict[str, str] | None = None,
                  namespace: str | None = None, include_role: bool = False) -> Result:
        """Anonymize with per-type methods (no policy gate). ``result.text`` is the transformed text."""
        return self._request("POST", "/v1/anonymize", json=self._clean(
            text=text, language=language, methods=methods, namespace=namespace, include_role=include_role or None))

    def protect(self, text: str, destination: str = "external", namespace: str | None = None,
                policy: str | None = None, tenant: str | None = None, team: str | None = None,
                language: str | None = None, require_allowed: bool = False) -> Result:
        """Full pipeline with policy. ``result.text`` is None unless ``result.allowed``."""
        result = self._request("POST", "/v1/protect", json=self._clean(
            text=text, destination=destination, namespace=namespace, policy=policy, tenant=tenant, team=team,
            language=language))
        if require_allowed and not result["allowed"]:
            raise PolicyViolation(403, f"policy outcome: {result['outcome']}", result)
        return result

    def protect_document(self, file: str | Path | bytes, filename: str | None = None,
                         destination: str = "external", namespace: str | None = None,
                         policy: str | None = None, language: str | None = None) -> Result:
        """Protect a PDF/DOCX/TXT. For DOCX, ``result.content`` holds the anonymized file bytes."""
        if isinstance(file, (str, Path)):
            path = Path(file)
            data, filename = path.read_bytes(), filename or path.name
        else:
            data = file
        form = self._clean(destination=destination, namespace=namespace, policy=policy, language=language)
        result = self._request("POST", "/v1/documents/protect", data=form,
                               files={"file": (filename or "document", data, "application/octet-stream")})
        if result.get("content_base64"):
            import base64

            result["content"] = base64.b64decode(result["content_base64"])
        return result

    def restore(self, text: str, namespace: str) -> Result:
        """Resolve placeholders (requires an admin key)."""
        return self._request("POST", "/v1/restore", json={"text": text, "namespace": namespace})

    # -- policies & observability ---------------------------------------------------
    def policies(self) -> list[Result]:
        return self._request("GET", "/v1/policies")

    def policy(self, name: str, version: int | None = None, effective: bool = False) -> Result:
        return self._request("GET", f"/v1/policies/{name}",
                             params=self._clean(version=version, effective=str(effective).lower()))

    def create_policy(self, yaml: str) -> Result:
        """Save a new policy version (requires an admin key)."""
        return self._request("POST", "/v1/policies", json={"yaml": yaml})

    def dry_run_policy(self, text: str, candidate_yaml: str, destination: str = "external",
                       against: str | None = None) -> Result:
        return self._request("POST", "/v1/policies/dry-run", json=self._clean(
            text=text, candidate_yaml=candidate_yaml, destination=destination, against=against))

    def traces(self, limit: int = 50, outcome: str | None = None, route: str | None = None) -> list[Result]:
        return self._request("GET", "/v1/traces", params=self._clean(limit=limit, outcome=outcome, route=route))

    def trace(self, trace_id: str) -> Result:
        return self._request("GET", f"/v1/traces/{trace_id}")

    def metrics(self, hours: int = 24) -> Result:
        return self._request("GET", "/v1/metrics", params={"hours": hours})

    def info(self) -> Result:
        return self._request("GET", "/v1/info")

    def sources(self) -> Result:
        """Policy used by the playground (CSV) and whether MCP over HTTP is enabled."""
        return self._request("GET", "/v1/sources")
