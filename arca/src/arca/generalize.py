"""Vergröbern und Prüfhinweise für die Vorschau.

Namen und Firmen ersetzt die Engine durch Tokens. Für den Rückschluss aus dem Zusammenhang reichen aber oft
genaue Daten und Beträge ("Abnahme 19.09.2025, Schaden 1.250.000 €"). Deshalb werden sie vor der Freigabe
vergröbert:

* Daten: ``month`` (19.09.2025 -> 09/2025, Standard), ``year`` (-> 2025) oder ``keep``.
* Beträge: ``range`` (1.250.000 € -> 1–5 Mio. €, Standard) oder ``keep``.

Prüfhinweise: Eigennamen, die nach der Anonymisierung noch im Text stehen (Cato-Tagger: PROPN, z. B.
"aus Lüneburg"), werden markiert, aber nicht ersetzt. Sie sind der Hinweis für die Pflichtprüfung, kein Schutz:
Ortsteile wie "Überseestadt" erkennt auch der Tagger nicht sicher.
"""

from __future__ import annotations

import re
from functools import lru_cache

from arca.tokens import TOKEN_RE

DATE_MODES = ("month", "year", "keep")
MONEY_MODES = ("range", "keep")
DEFAULTS = {"dates": "month", "money": "range"}

_MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
           "November", "Dezember"]
_DATE_NUM = re.compile(r"(?<![\d.])(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4}|\d{2})(?![\d])")
_DATE_LONG = re.compile(r"(?<![\w.])(\d{1,2})\.\s(" + "|".join(_MONTHS) + r")\s(\d{4})(?!\d)")
_MONEY = re.compile(
    r"(?<![\w.,])(?:(?:EUR|€)\s?(?P<a>\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2}|,-)?"
    r"|(?P<b>\d{1,3}(?:\.\d{3})+|\d+)(?:,(?P<frac>\d{1,2})|,-)?\s?(?P<unit>Mio\.?|Millionen|Tsd\.?)?\s?(?:€|Euro|EUR))"
    r"(?![\w])")
_BUCKETS = [
    (1_000, "unter 1.000 €"), (10_000, "1.000–10.000 €"), (50_000, "10.000–50.000 €"),
    (100_000, "50.000–100.000 €"), (500_000, "100.000–500.000 €"), (1_000_000, "500.000 € – 1 Mio. €"),
    (5_000_000, "1–5 Mio. €"), (float("inf"), "über 5 Mio. €"),
]


class OptionError(ValueError):
    pass


def options(raw: dict | None) -> dict:
    opts = {**DEFAULTS, **(raw or {})}
    if opts["dates"] not in DATE_MODES or opts["money"] not in MONEY_MODES or set(opts) - set(DEFAULTS):
        raise OptionError(f"Ungültige Optionen: {raw}")
    return opts


def bucket(amount: float) -> str:
    return next(label for limit, label in _BUCKETS if amount < limit)


def _amount(m: re.Match) -> float:
    whole = (m.group("a") or m.group("b")).replace(".", "")
    value = float(whole + ("." + m.group("frac") if m.group("frac") else ""))
    unit = (m.group("unit") or "").lower()
    if unit.startswith("mio") or unit.startswith("million"):
        value *= 1_000_000
    elif unit.startswith("tsd"):
        value *= 1_000
    return value


def generalize(text: str, spans: list[dict], opts: dict) -> tuple[str, list[dict]]:
    if opts["money"] == "range":
        text, spans = _apply(text, spans, _MONEY, lambda m: bucket(_amount(m)), "money")
    if opts["dates"] != "keep":
        def date(m: re.Match, long: bool = False) -> str:
            month = _MONTHS.index(m.group(2)) + 1 if long else int(m.group(2))
            year = m.group(3)
            if len(year) == 2:
                year = ("20" if int(year) < 50 else "19") + year
            return year if opts["dates"] == "year" else f"{month:02d}/{year}"
        text, spans = _apply(text, spans, _DATE_LONG, lambda m: date(m, True), "date")
        text, spans = _apply(text, spans, _DATE_NUM, date, "date")
    return text, spans


def _apply(text: str, spans: list[dict], pattern: re.Pattern, repl, kind: str) -> tuple[str, list[dict]]:
    """Treffer ersetzen, die keine vorhandene Ersetzung berühren; vorhandene Spans verschieben."""
    pieces: list[str] = []
    edits: list[tuple[int, int, str]] = []  # (start, end) im alten Text, Ersatz
    for m in pattern.finditer(text):
        if any(m.start() < s["end"] and s["start"] < m.end() for s in spans):
            continue
        edits.append((m.start(), m.end(), repl(m)))
    if not edits:
        return text, spans
    cursor = 0
    new_spans: list[dict] = []
    offset = 0
    for start, end, rep in edits:
        pieces.append(text[cursor:start])
        new_spans.append({"start": start + offset, "end": start + offset + len(rep), "type": kind})
        pieces.append(rep)
        offset += len(rep) - (end - start)
        cursor = end
    pieces.append(text[cursor:])

    def moved(pos: int) -> int:
        return pos + sum(len(rep) - (end - start) for start, end, rep in edits if end <= pos)

    old = [{**s, "start": moved(s["start"]), "end": moved(s["end"])} for s in spans]
    return "".join(pieces), sorted(old + new_spans, key=lambda s: s["start"])


@lru_cache(maxsize=1)
def _tagger():
    import spacy

    from anonymizer.detect.ner import CATO
    return spacy.load(str(CATO), exclude=["ner"])


_SKIP = re.compile(r"^(?:REDACTED|ZURÜCKGEHALTEN|Mio|Euro|EUR)$")


def hints(text: str, spans: list[dict]) -> list[dict]:
    """Eigennamen außerhalb der Ersetzungen: Hinweise für die Prüfung (nicht ersetzt)."""
    if not text.strip():
        return []
    try:
        doc = _tagger()(text)
    except OSError:
        return []
    out = []
    for tok in doc:
        if tok.pos_ != "PROPN" or len(tok.text) < 3 or not tok.text[0].isupper():
            continue
        start, end = tok.idx, tok.idx + len(tok.text)
        if TOKEN_RE.fullmatch(tok.text) or _SKIP.match(tok.text):
            continue
        if any(start < s["end"] and s["start"] < end for s in spans):
            continue
        out.append({"start": start, "end": end, "type": "check"})
    return out
