"""Synthetic demo traces (metadata only) so a fresh account has something to look at.

Nothing here comes from real requests: entity counts, outcomes and latencies are
drawn from a fixed-seed distribution that resembles legal-AI traffic.
"""

from __future__ import annotations

import random
import time

from anonymizer.tracing import Trace, TraceStep, TraceStore

_ROUTES = [("/v1/chat/completions", 0.72), ("/v1/protect", 0.2), ("/v1/documents/protect", 0.08)]
_ENTITIES = [("person", 0.9), ("organization", 0.5), ("case_number", 0.35), ("email", 0.25), ("address", 0.2),
             ("iban", 0.12), ("date_of_birth", 0.05), ("health_data", 0.03)]
_ACTION = {"person": "pseudonymize", "organization": "pseudonymize", "case_number": "pseudonymize",
           "email": "pseudonymize", "address": "pseudonymize", "iban": "redact", "date_of_birth": "generalize",
           "health_data": "local_only"}
_CRITICAL = {"iban", "health_data", "date_of_birth"}
_PROVIDERS = [("openai", "gpt-4o", 0.75), ("azure", "gpt-4o-mini", 0.25)]


def _pick(rng: random.Random, items: list[tuple]) -> tuple:
    r, acc = rng.random() * sum(i[-1] for i in items), 0.0
    for item in items:
        acc += item[-1]
        if r <= acc:
            return item
    return items[-1]


def make_trace(rng: random.Random, created_at: float) -> Trace:
    route = _pick(rng, _ROUTES)[0]
    counts = {e: rng.randint(1, 3) for e, p in _ENTITIES if rng.random() < p * 0.6} if rng.random() < 0.55 else {}
    crit = sum(n for e, n in counts.items() if e in _CRITICAL)
    sens = sum(counts.values()) - crit
    risk = "critical" if crit else ("sensitive" if sens else "low")
    outcome = "allow"
    if "health_data" in counts:
        outcome = "local_only"
    elif risk == "critical" and rng.random() < 0.08:
        outcome = "review"
    elif rng.random() < 0.004:
        outcome = "block"
    actions = {f"{e}:{_ACTION[e]}": n for e, n in counts.items()}
    transformations = sum(n for e, n in counts.items() if _ACTION[e] not in ("local_only",)) if outcome == "allow" else 0
    provider, model = (None, None)
    steps = [TraceStep(name="Request received", detail=route),
             TraceStep(name="Privacy detection", detail=f"{sum(counts.values())} entities detected"),
             TraceStep(name="Classification", detail=f"{crit} critical · {sens} sensitive · risk {risk}"),
             TraceStep(name="Policy evaluation", detail=f"banking-default@v1 → {outcome}",
                       status="ok" if outcome == "allow" else "blocked")]
    status, latency = 200, round(rng.lognormvariate(4.3, 0.5), 1)
    if outcome == "allow":
        if transformations:
            steps.append(TraceStep(name="Anonymization", detail=f"{transformations} transformations applied"))
        if route == "/v1/chat/completions":
            provider, model, _ = _pick(rng, _PROVIDERS)
            latency = round(latency + rng.lognormvariate(6.2, 0.4), 1)
            if rng.random() < 0.01:
                status = 502
                steps.append(TraceStep(name="Provider request", detail=f"{provider} · {model} · HTTP 502", status="error"))
            else:
                steps.append(TraceStep(name="Provider request", detail=f"{provider} · {model} · HTTP 200"))
                steps.append(TraceStep(name="Response restore", detail=f"{min(transformations, 2)} placeholder(s) restored"))
    elif route == "/v1/chat/completions":
        status = 403
    return Trace(created_at=created_at, route=route, outcome=outcome, allowed=outcome == "allow", risk=risk,
                 needs_review=outcome == "review", policy="banking-default@v1", policy_hash="sha256:demo",
                 destination="external", provider=provider, model=model, language="de" if rng.random() < 0.8 else "en",
                 latency_ms=latency, status=status, error="upstream error" if status == 502 else None,
                 entity_counts=counts, risk_counts={k: v for k, v in (("critical", crit), ("sensitive", sens)) if v},
                 actions=actions, transformations=transformations,
                 signals=["client_relationship"] if counts and rng.random() < 0.3 else [], steps=steps)


def seed_traces(store: TraceStore, org_id: str, count: int = 400, days: int = 7, seed: int = 7) -> int:
    rng = random.Random(seed)
    now = time.time()
    for _ in range(count):
        # more traffic in recent hours so the 24 h views are populated
        age = rng.random() ** 2 * days * 86400
        store.add(make_trace(rng, now - age), org_id)
    return count


__all__ = ["make_trace", "seed_traces"]
