"""Document context signals.

Signals are cues such as "this text concerns a criminal proceeding" or "this
is a fictitious example". They do not decide anything themselves; the
classification engine combines them with detections. Each detection carries
the signals found within ``window`` characters (bounded by paragraph breaks).
"""

from __future__ import annotations

import re
from bisect import bisect_left

from cato.detect.base import lexicon
from cato.models import Signal

I = re.IGNORECASE

SIGNALS: dict[str, re.Pattern[str]] = {
    "client_relationship": re.compile(lexicon([
        r"Mandant(?:in|en|schaft)?", r"Mandat(?:s\w*)?", r"Mandatsverhältnis", r"mandatiert",
        r"(?:our|my) client", r"client[- ]matter", r"engagement letter", r"retainer",
    ]), I),
    "criminal_proceeding": re.compile(lexicon([
        r"Strafverfahren", r"Ermittlungsverfahren", r"Strafanzeige", r"Anklage(?:schrift)?", r"Strafbefehl",
        r"Staatsanwaltschaft", r"Beschuldigte[rn]?", r"Angeklagte[rn]?", r"Haftbefehl", r"Untersuchungshaft",
        r"Strafverteidig\w*", r"criminal (?:proceedings?|case|investigation|charges?)", r"indictment", r"prosecution",
        r"(?:the )?accused", r"arrest warrant",
    ]), I),
    "litigation": re.compile(lexicon([
        r"Klage(?:schrift|erwiderung)?", r"Kläger(?:in)?", r"Beklagte[rn]?", r"Rechtsstreit", r"Berufung",
        r"Revision", r"mündliche Verhandlung", r"lawsuit", r"litigation", r"plaintiff", r"claimant",
        r"defendant", r"hearing", r"appeal",
    ]), I),
    "employment": re.compile(lexicon([
        r"Arbeitsvertrag", r"Arbeitsverhältnis", r"Kündigung(?:sschutz\w*)?", r"Gehalt", r"Bruttogehalt",
        r"Vergütung", r"Abfindung", r"Arbeitnehmer(?:in)?", r"employment", r"employer", r"salary",
        r"severance", r"termination", r"employee",
    ]), I),
    "financial_distress": re.compile(lexicon([
        r"Insolvenz\w*", r"Zahlungsunfähigkeit", r"Schulden", r"Pfändung\w*", r"Zwangsvollstreckung",
        r"Privatinsolvenz", r"insolvency", r"bankruptcy", r"debt collection", r"garnishment",
    ]), I),
    "confidential": re.compile(lexicon([
        r"vertraulich", r"Mandatsgeheimnis", r"Verschwiegenheit\w*", r"confidential", r"privileged",
        r"nicht zur Weitergabe", r"do not forward",
    ]), I),
    "example_context": re.compile(lexicon([
        r"Beispiel\w*", r"Muster", r"Musterformular", r"Mustervorlage", r"Vorlage", r"fiktiv\w*",
        r"exemplarisch", r"z\.\s?B\.", r"example", r"sample", r"fictitious", r"dummy", r"placeholder",
        r"template", r"for illustration",
    ]), I),
}


def find_signals(text: str) -> list[Signal]:
    found: list[Signal] = []
    for name, regex in SIGNALS.items():
        for m in regex.finditer(text):
            found.append(Signal(name=name, start=m.start(), end=m.end()))
    found.sort(key=lambda s: s.start)
    return found


def _paragraph_window(text: str, start: int, end: int, window: int) -> tuple[int, int]:
    lo = max(0, start - window)
    hi = min(len(text), end + window)
    para_start = text.rfind("\n\n", lo, start)
    if para_start != -1:
        lo = para_start
    para_end = text.find("\n\n", end, hi)
    if para_end != -1:
        hi = para_end
    return lo, hi


class SignalIndex:
    """Signals sorted by start, for repeated ``near`` queries on one document."""

    def __init__(self, signals: list[Signal]) -> None:
        self._signals = sorted(signals, key=lambda s: s.start)
        self._starts = [s.start for s in self._signals]
        self._longest = max((s.end - s.start for s in self._signals), default=0)

    def near(self, text: str, start: int, end: int, window: int) -> tuple[str, ...]:
        """Signal names within ``window`` chars of a span, not crossing a blank line."""
        lo, hi = _paragraph_window(text, start, end, window)
        # A signal reaching into the window starts at most ``_longest`` before it.
        first = bisect_left(self._starts, lo - self._longest)
        last = bisect_left(self._starts, hi)
        names = {s.name for s in self._signals[first:last]
                 if s.end > lo and not (s.start >= start and s.end <= end)}
        return tuple(sorted(names))


def signals_near(text: str, signals: list[Signal], start: int, end: int, window: int) -> tuple[str, ...]:
    """Signal names within ``window`` chars of a span, not crossing a blank line."""
    return SignalIndex(signals).near(text, start, end, window)
