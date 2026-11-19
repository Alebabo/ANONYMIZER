"""Leak check against a running OpenAnonymizer API: read conversations through the protected endpoint and look
for anything that should never come out.

Meant for the evaluation phase inside the protected environment (docs/conversations.md):

* **Generic patterns** that must never appear in protected output: e-mail addresses, IBANs, long digit
  runs (order/customer numbers without a custom pattern), phone numbers, URLs with parameters.
* **Known values** (optional ``--secrets`` file, one value per line): real names, e-mails or numbers
  from the sample, exported by an authorized person. Matching is case-insensitive.

The report never prints a found value: generic hits are masked, known values are reported by their
line number in the secrets file. Reads count against the key's daily quota.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import httpx

GENERIC: dict[str, re.Pattern] = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b"),
    "phone": re.compile(r"(?:\+\d{2}|\b0)\d{2,4}[\s/-]?\d{3,}[\s-]?\d{0,6}\b"),
    "long_number": re.compile(r"\b\d(?:[\s.-]?\d){5,}\b"),
    "url_with_params": re.compile(r"https?://\S+\?\S+"),
}


@dataclass
class Finding:
    conversation: str
    message: int
    kind: str
    sample: str  # masked, never the value


@dataclass
class Report:
    conversations: int = 0
    messages: int = 0
    withheld: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    def summary(self) -> dict:
        return {"conversations": self.conversations, "messages": self.messages, "withheld": self.withheld,
                "findings": len(self.findings), "by_kind": dict(Counter(f.kind for f in self.findings)),
                "conversations_with_findings": len({f.conversation for f in self.findings})}


def mask(value: str) -> str:
    value = value.strip()
    return f"{value[:2]}{'*' * max(0, len(value) - 2)} ({len(value)} chars)"


def load_secrets(path: str | Path) -> list[str]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def check_text(text: str, secrets: list[str]) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for kind, rx in GENERIC.items():
        for m in rx.finditer(text):
            hits.append((kind, mask(m.group(0))))
    low = text.lower()
    for i, s in enumerate(secrets, 1):
        if len(s) >= 3 and s.lower() in low:
            hits.append(("known_value", f"secrets line {i}"))
    return hits


def run(client: httpx.Client, base_url: str, key: str, limit: int = 50, secrets: list[str] | None = None,
        since: float | None = None) -> Report:
    headers = {"Authorization": f"Bearer {key}"}
    base = base_url.rstrip("/")
    report = Report()
    ids: list[str] = []
    cursor = None
    while len(ids) < limit:
        params = {"limit": min(100, limit - len(ids))}
        if cursor:
            params["cursor"] = cursor
        if since is not None:
            params["since"] = since
        r = client.get(f"{base}/v1/conversations", params=params, headers=headers)
        r.raise_for_status()
        page = r.json()
        ids += [h["id"] for h in page["data"]]
        cursor = page.get("next_cursor")
        if not cursor or not page["data"]:
            break
    for cid in ids[:limit]:
        r = client.get(f"{base}/v1/conversations/{cid}", headers=headers)
        if r.status_code == 429:
            break
        r.raise_for_status()
        conv = r.json()
        report.conversations += 1
        report.withheld += conv.get("withheld", 0)
        for i, m in enumerate(conv["messages"]):
            report.messages += 1
            if m.get("content"):
                for kind, sample in check_text(m["content"], secrets or []):
                    report.findings.append(Finding(cid, i, kind, sample))
    return report
