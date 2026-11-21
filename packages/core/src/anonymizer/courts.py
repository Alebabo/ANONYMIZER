"""Whole court decisions as gold data: the court's anonymization placeholders become synthetic values.

German courts publish decisions with personal data replaced by "…" (also "...", "X", "A."): "Herr …",
"…straße 5", "in …", "die … GmbH". Each placeholder whose context says what it stood for is filled with a
synthetic value of that kind, and its span is recorded. That gives exact labels for exactly the places where
personal data sits in real legal documents (rubrum, parties, witnesses, addresses).

Placeholders without a telling context (a bare "…") are left as they are; the value they stood for is unknown.
Real names the court left in the text (judges, often lawyers) are not labelled, so this data scores recall on
the inserted values and teaches entities; precision is measured on German LER (anonymizer.ler).
"""

from __future__ import annotations

import hashlib
import html
import random
import re
from dataclasses import dataclass

from anonymizer.ler import Names
from anonymizer.ner_dataset import GoldDoc, Span

# How courts mark a removed value: "…", "...", "[...]", also an initial with dots ("H...", "M…", "Ts….").
# Extra dots after the ellipsis belong to it, except the last one: that is the sentence's full stop.
PH = r"(?:(?:(?<![\w.])[A-ZÄÖÜ][a-zäöü]?\s?)?(?:…|\.{3})(?:\.{1,3}(?=\.))?|\[\.{3}\])"
# Initials instead of a name: "Herr K.", "das Kind A. L. D.", "Zeugin M" (only after a role word, see RULES).
INITIALS = r"(?<![\w.])[A-ZÄÖÜ]\.?(?:\s?[A-ZÄÖÜ]\.){0,3}(?![\wÄÖÜäöü])"
# A run of them for multi-word names: "M... H... & Co.", "C…. J.... S...".
PH_RUN = rf"(?:{PH})(?:\s(?:&\s)?(?:{PH})){{0,4}}"
_BLOCK = re.compile(r"</?(?:p|br|div|dd|dt|dl|li|h\d|tr|table|blockquote)\b[^>]*>", re.I)


def clean_html(content: str) -> str:
    """Decision HTML to plain text with paragraph breaks."""
    t = _BLOCK.sub("\n", content)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def split_of(case_id: int) -> str:
    """Stable split by decision: 80 % train, 10 % dev, 10 % test."""
    h = int(hashlib.sha1(str(case_id).encode()).hexdigest(), 16) % 10
    return "test" if h == 0 else "dev" if h == 1 else "train"


def placeholder_contexts(text: str) -> list[str]:
    """'<two words before> … <word after>' per placeholder, to see which kinds exist."""
    out = []
    for m in re.finditer(PH, text):
        before = re.findall(r"[\wÄÖÜäöüß.-]+", text[max(0, m.start() - 40):m.start()])[-2:]
        after = re.findall(r"[\wÄÖÜäöüß.-]+", text[m.end():m.end() + 25])[:1]
        glued_before = m.start() > 0 and text[m.start() - 1].isalnum()
        glued_after = m.end() < len(text) and text[m.end()].isalnum()
        out.append(f"{' '.join(before)}{'' if glued_before else ' '}…{'' if glued_after else ' '}{' '.join(after)}")
    return out


@dataclass
class Rule:
    """A placeholder in this context stands for a value of ``label``; ``make`` builds the value."""
    pattern: re.Pattern
    label: str
    kind: str


def _r(p: str, label: str, kind: str) -> Rule:
    return Rule(re.compile(p), label, kind)


# Context rules, most specific first. Group "ph" is the placeholder to replace (whole match may include
# context words that stay as they are).
_TITLE = r"(?:Herrn?|Frau|Dr\.|Prof\.|Rechtsanwalt|Rechtsanwältin|Rechtsanwälte|Rechtsanwälten|RAin?|"
_TITLE += r"Zeugen?|Zeugin|Sachverständigen?|Sachverständige|Notar|Notarin|Steuerberater(?:in)?|Betreuer(?:in)?|"
_TITLE += r"Verfahrensbevollmächtigte[rn]?|Kläger(?:in)?|Beklagte[rn]?|Antragsteller(?:in)?|Antragsgegner(?:in)?|"
_TITLE += r"Eheleute|Kinde?s?|Geschädigte[rn]?|Angeklagte[rn]?|Angeschuldigte[rn]?|Beschuldigte[rn]?|"
_TITLE += r"(?:Privat)?[Ss]achverständige[nr]?|Gutachter(?:s|in)?|Arzt|Arztes|Ärztin|Stationsarzt(?:es)?|Oberarzt(?:es)?|"
_TITLE += r"Chefarzt(?:es)?|Dr\.\smed\.|Dipl\.-[A-Z][a-z]+\.?|KHK|KOK|POK|PHK|PK|KK|POM|Polizeibeamte[nr]?|"
_TITLE += r"Tochter|Sohn|Sohnes|Ehemann|Ehemannes|Ehefrau|Mutter|Vater|Vaters|Bruder|Bruders|Schwester|Erblasser(?:in|s)?|"
_TITLE += r"Herren|vertreten\sdurch|Geschäftsführer(?:in|s)?|Inhaber(?:in|s)?|Vermieter(?:in|s)?|Mieter(?:in|s)?)"
_DATE_PH = r"(?:geboren\sam|geb\.\s?(?:am)?|am|vom|seit\sdem)"
RULES = [
    # dates of birth and death: "geboren am …", "der am … verstorbene", "die am … geborene"
    _r(rf"\b{_DATE_PH}\s(?P<ph>{PH})(?=\s(?:verstorben|geboren|in\s|\.|,))", "DATE", "date"),
    _r(rf"\b(?:geboren\sam|geb\.(?:\sam)?)\s(?P<ph>{PH})", "DATE", "date"),
    # the own file numbers: "Az. …", "Aktenzeichen …"
    _r(rf"\b(?:Az\.|Aktenzeichen|Geschäftszeichen)\s?:?\s(?P<ph>{PH})", "AZ", "case_number"),
    # bank data
    _r(rf"\b(?:IBAN|Kontonummer|Konto-Nr\.)\s?:?\s(?P<ph>{PH})", "IBAN", "iban"),
    # banks and similar named organisations: "Sparkasse …", "… Bank", "bei der … Bank"
    _r(rf"\b(?:Sparkasse|Volksbank|Raiffeisenbank|Kreissparkasse|Stadtsparkasse)\s(?P<ph>{PH})", "ORG", "city"),
    _r(rf"(?P<ph>{PH})\s(?:Bank|Versicherung|Klinik|Kliniken|Krankenhaus|Werke|Holding)\b", "ORG", "company_stem"),
    # land register and travel: "Grundbuch von …", "Flug von … nach …"
    _r(rf"\b(?:Grundbuch\svon|Gemarkung|Flug\svon|Flughafen)\s(?P<ph>{PH})", "LOC", "city"),
    _r(rf"\bvon\s{PH}\snach\s(?P<ph>{PH})", "LOC", "city"),
    # "…straße 5", "…-Straße 12a", "Am … 3"
    _r(rf"(?P<ph>{PH})-?(?:[Ss]traße|[Ww]eg|[Aa]llee|[Pp]latz|[Rr]ing|[Gg]asse|[Dd]amm|[Uu]fer)\s?\d*\s?[a-z]?\b", "ADDR", "street"),
    _r(rf"\b(?:[A-ZÄÖÜ][a-zäöüß]+(?:straße|weg|allee|platz|ring|gasse))\s(?P<ph>{PH})", "ADDR", "number"),
    # postcode + city: "12345 …", "… (Ort)"
    _r(rf"\b\d{{5}}\s(?P<ph>{PH})", "LOC", "city"),
    # companies: "… GmbH", "Firma …", "die … AG"
    _r(rf"(?P<ph>{PH_RUN})\s?(?:&\s?Co\.\s?KG|GmbH|AG|KG|UG|OHG|GbR|e\.\s?V\.|mbH|SE|Ltd\.?|Inc\.?)\b", "ORG", "company_stem"),
    _r(rf"\b(?:Firma|Fa\.|Unternehmen|Arbeitgeberin|Bank|Versicherung|Sparkasse|Kanzlei)\s(?P<ph>{PH})", "ORG", "company"),
    # persons after a title or role
    _r(rf"\b{_TITLE}\s(?:(?:Dr\.|Prof\.)\s)?(?P<ph>{PH_RUN})", "PER", "person"),
    _r(rf"\b{_TITLE}\s(?:(?:Dr\.|Prof\.)\s)?(?P<ph>{INITIALS})", "PER", "person"),
    # "geboren am … in …", "wohnhaft in …"
    _r(rf"\b(?:wohnhaft|wohnend|geboren|aus|in|nach)\s(?:in\s)?(?P<ph>{PH})(?=[\s,.;)])", "LOC", "city"),
]


class Filler:
    def __init__(self, names: Names) -> None:
        self.names = names
        self.rng = names.rng

    def value(self, kind: str, before: str) -> str:
        n = self.names
        if kind == "person":
            return n.person(before)
        if kind == "company_stem":
            return n.company_stem()
        if kind == "company":
            return f"{n.company_stem()} {self.rng.choice(['GmbH', 'AG', 'KG', 'GmbH & Co. KG', 'e.K.'])}"
        if kind == "city":
            return n.city()
        if kind == "street":
            return n.company_stem()  # "…straße" -> "Müllerstraße": a surname is the common street stem
        if kind == "number":
            return str(self.rng.randint(1, 140)) + self.rng.choice(["", "", "", "a", "b"])
        if kind == "date":
            return f"{self.rng.randint(1, 28):02d}.{self.rng.randint(1, 12):02d}.{self.rng.randint(1932, 2015)}"
        if kind == "case_number":
            reg = self.rng.choice(["O", "C", "S", "U", "Ca", "Sa", "Js", "K", "L", "F", "T"])
            return f"{self.rng.randint(1, 40)} {reg} {self.rng.randint(1, 999)}/{self.rng.randint(10, 26)}"
        if kind == "iban":
            bban = "".join(str(self.rng.randint(0, 9)) for _ in range(18))
            check = 98 - int(bban + "131400") % 97  # ISO 13616 check digits for "DE"
            iban = f"DE{check:02d}{bban}"
            return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))
        raise ValueError(kind)


def fill(text: str, filler: Filler) -> tuple[str, list[Span]]:
    """Replace every placeholder whose context matches a rule; return the new text and the inserted spans.
    For streets the whole street name is the span ("Müllerstraße 12"), for the rest the inserted value."""
    jobs: list[tuple[int, int, str, str]] = []  # placeholder start, end, label, kind
    for rule in RULES:  # earlier rules win; a placeholder overlapping one already taken is skipped
        for m in rule.pattern.finditer(text):
            s, e = m.span("ph")
            if s < 0 or e <= s:
                continue
            if rule.kind in ("iban", "case_number") and e < len(text) and text[e].isalnum():
                continue  # only partly removed ("Kontonummer …14"): the full value is unknown
            if re.fullmatch(INITIALS, text[s:e]) and text[s:e].endswith(".") \
                    and re.match(r"\s+[A-ZÄÖÜ„(]|\s*$|\s*\n", text[e:]):
                e -= 1  # "Herr K. Er sagte": the dot also ends the sentence, keep it
            if any(s < te and ts < e for ts, te, _, _ in jobs):
                continue
            jobs.append((s, e, rule.label, rule.kind))
    jobs.sort()
    out, spans, pos, shift = [], [], 0, 0
    for s, e, label, kind in jobs:
        value = filler.value(kind, text[max(0, s - 30):s])
        glued = e < len(text) and text[e].isalnum()
        if glued and kind == "date" and text[e].isdigit():
            # partly removed: "geboren am …2017" (day and month gone), "am …11.2007" (day gone)
            value = value[:3] if re.match(r"\d{1,2}\.\d{4}", text[e:]) else value[:6]
        elif glued and kind in ("person", "company_stem", "company", "city"):
            value += " "  # "Zeugin …als" -> "Zeugin Meier als", "…GmbH" -> "Weber GmbH"
        out.append(text[pos:s])
        new_start = s + shift
        out.append(value)
        shift += len(value) - (e - s)
        pos = e
        spans.append((new_start, new_start + len(value.rstrip()), label, kind))
    out.append(text[pos:])
    new = "".join(out)
    result = []
    for a, b, label, kind in spans:
        if kind == "street":  # extend over the street word and house number: "Müller" + "straße 12a"
            m = re.match(r"-?(?:[Ss]traße|[Ww]eg|[Aa]llee|[Pp]latz|[Rr]ing|[Gg]asse|[Dd]amm|[Uu]fer)(?:\s?\d+(?:\s?[a-z]\b)?)?", new[b:])
            b += m.end() if m else 0
        if kind in ("company_stem", "city") and label == "ORG":  # "Maier GmbH & Co. KG", "Neumann Bank"
            m = re.match(r"\s?(?:&\s?Co\.\s?KG|GmbH\s&\sCo\.\sKG|GmbH|AG|KG|UG|OHG|GbR|e\.\s?V\.|mbH|SE|Ltd\.|Inc\.|Bank|"
                         r"Versicherung|Klinik|Kliniken|Krankenhaus|Werke|Holding)(?:\s&\s?Co\.\s?KG)?(?![\w&])", new[b:])
            b += m.end() if m else 0
            m = re.search(r"(?:Sparkasse|Volksbank|Raiffeisenbank|Kreissparkasse|Stadtsparkasse)\s$", new[max(0, a - 25):a])
            a -= len(m.group()) if m else 0
        if kind == "number":  # "Lindenstraße 12": the whole address
            m = re.search(r"[A-ZÄÖÜ][a-zäöüß]+(?:straße|weg|allee|platz|ring|gasse)\s$", new[max(0, a - 40):a])
            a -= len(m.group()) if m else 0
        result.append(Span(a, b, label))
    return new, result


def build_doc(case: dict, text: str, split: str, seed: int = 24) -> GoldDoc | None:
    names = Names(seed + int(case["id"]), held_out=split != "train")
    names.rng = random.Random(seed + int(case["id"]))
    new, spans = fill(text, Filler(names))
    # A span that does not sit on word boundaries means the source text was garbled around the placeholder
    # ("geboren am …2020"); such a decision is left out rather than taught wrong.
    if not spans or any((sp.start > 0 and new[sp.start - 1].isalnum())
                        or (sp.end < len(new) and new[sp.end].isalnum() and sp.label != "ADDR") for sp in spans):
        return None
    court = case["court"]["name"] if isinstance(case.get("court"), dict) else ""
    return GoldDoc(f"courts:{case['id']}", new, spans, ["courts", court], None, split)
