"""Fine-tune the German spaCy NER for support mails and chats.

    python packages/core/scripts/ner_train.py [--dir local/ner] [--epochs 12] [--out local/ner/models/de_c24_ner]

Training data, all built here and never from the dev/test splits of gold.jsonl:
  1. GermEval 2014 (public, CC BY 4.0; local/ner/public/germeval14/train.tsv) as rehearsal, so the model keeps
     its general German NER. OTH -> MISC, *deriv/*part -> O.
  2. The ``train`` split of gold.jsonl (real sbx/int mails and chats). Address spans and tokens that do not
     line up with an entity boundary are left out of the loss ("missing"), not taught as O.
  4. Optional (--ler datasets/ler): German LER court decisions with synthetic names (see ler_data.py). Courts,
     laws, case law and literature are taught as O, so the model stops tagging them as PER/ORG/LOC. Without
     local/ner/gold.jsonl the LER dev split selects the model, so training runs from the repository alone.
  3. Synthetic support texts from templates: signatures, greetings, mail headers, payees, authorities, lower-
     case chat. Names come from GermEval and the INT test-customer list; organisations and places from a
     public-knowledge list. Every entity string that occurs in the dev or test split is removed from these
     lists first, so the scores on dev/test measure generalisation, not memory.

The model is selected on the dev split (pipeline mode, strict micro F1). Test is only reported.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

import spacy
from spacy.training import Example, offsets_to_biluo_tags
from spacy.util import compounding, minibatch

from anonymizer.detect.engine import NER_STOPWORDS
from anonymizer.detect.ner import SpacyRecognizer
from anonymizer.detect.recognizers import NAME_STOPWORDS
from anonymizer.ner_dataset import (
    DEFAULT_KEEP, Span, _occurrences, keep_pattern, read_gold, relevant, resolve, score_doc, summarize,
)

sys.path.insert(0, str(Path(__file__).parent))
from ner_gold import predict_pipeline  # noqa: E402

SEED = 24

# Public knowledge: banks, insurers, payment providers, merchants, authorities, media.
ORGS = [
    "Deutsche Bank", "Commerzbank", "Postbank", "Sparkasse Krefeld", "Sparkasse KölnBonn", "Hamburger Sparkasse",
    "Stadtsparkasse München", "Berliner Sparkasse", "Volksbank Mittelhessen", "Berliner Volksbank", "ING",
    "DKB", "comdirect", "Consorsbank", "N26", "Revolut", "Targobank", "Santander", "HypoVereinsbank",
    "Sparda-Bank West", "PSD Bank Nord", "Norisbank", "1822direkt", "Openbank", "TF Bank", "Creditplus",
    "Bank of Scotland", "VW Bank", "Audi Bank", "Barclays", "Advanzia Bank", "Trade Republic", "Scalable Capital",
    "Allianz", "AXA", "ARAG", "HUK-Coburg", "Ergo", "Generali", "DEVK", "R+V Versicherung", "Debeka",
    "PayPal", "Klarna", "Amazon", "Zalando", "Otto", "eBay", "Temu", "Shein", "Netflix", "Spotify",
    "Apple", "Google", "Microsoft", "Telekom", "Vodafone", "O2", "1&1", "Lidl", "Aldi Süd", "Rewe", "Edeka",
    "dm", "Rossmann", "IKEA", "MediaMarkt", "Saturn", "Deutsche Bahn", "Lufthansa", "Ryanair", "Booking.com",
    "Airbnb", "Uber", "Lieferando", "McFit", "Fitness First", "Sky", "DAZN", "Stadtwerke München", "E.ON",
    "Vattenfall", "Schufa", "BaFin", "Bundesanstalt für Finanzdienstleistungsaufsicht", "Finanzamt Frankfurt",
    "Finanzamt Köln-Mitte", "Bundeszentralamt für Steuern", "Deutsche Rentenversicherung", "Agentur für Arbeit",
    "Jobcenter Berlin Mitte", "Amtsgericht Hamburg", "Amtsgericht München", "Landgericht Berlin",
    "Staatsanwaltschaft Hamburg", "Polizeipräsidium Frankfurt", "Bundeskriminalamt", "Deutsche Post", "DHL",
    "Hermes", "ZDF", "ARD", "WDR", "Spiegel", "Bild", "Süddeutsche Zeitung", "Stiftung Warentest",
    "Verbraucherzentrale NRW", "Kanzlei Müller & Partner", "Kanzlei Schmidt Rechtsanwälte", "Notariat Weber",
    "Hausverwaltung Krause GmbH", "Autohaus Becker GmbH", "Meyer Immobilien GmbH", "Lokalanzeiger",
]
LOCS = [
    "Deutschland", "Österreich", "Schweiz", "Frankreich", "Italien", "Spanien", "Portugal", "Polen", "Türkei",
    "Griechenland", "Kroatien", "Niederlande", "Belgien", "Dänemark", "Schweden", "Norwegen", "England",
    "Großbritannien", "Irland", "USA", "Kanada", "Mexiko", "Brasilien", "Thailand", "Vietnam", "Japan", "China",
    "Indien", "Ägypten", "Marokko", "Tunesien", "Dubai", "Australien", "Neuseeland", "Rumänien", "Bulgarien",
    "Ukraine", "Russland", "Berlin", "Hamburg", "München", "Köln", "Frankfurt", "Frankfurt am Main", "Stuttgart",
    "Düsseldorf", "Leipzig", "Dresden", "Hannover", "Nürnberg", "Bremen", "Essen", "Dortmund", "Bonn", "Mainz",
    "Wiesbaden", "Darmstadt", "Offenbach", "Heidelberg", "Mannheim", "Karlsruhe", "Freiburg", "Augsburg",
    "Regensburg", "Würzburg", "Kassel", "Erfurt", "Rostock", "Kiel", "Lübeck", "Münster", "Bielefeld", "Aachen",
    "Krefeld", "Wien", "Graz", "Zürich", "Basel", "Paris", "London", "Madrid", "Barcelona", "Rom", "Mailand",
    "Amsterdam", "Prag", "Warschau", "Istanbul", "Antalya", "Mallorca", "Malta", "New York", "Bangkok", "Bali",
]
FIRST_EXTRA = ["Lena", "Jonas", "Mia", "Leon", "Emma", "Paul", "Hannah", "Finn", "Sophia", "Elias", "Lea", "Noah",
               "Ayşe", "Mehmet", "Fatima", "Ali", "Olena", "Dmytro", "Katarzyna", "Piotr", "Giulia", "Luca",
               "Sven", "Birgit", "Uwe", "Petra", "Jürgen", "Sabine", "Dieter", "Monika", "Kevin", "Jacqueline"]
LAST_EXTRA = ["Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker", "Schulz",
              "Hoffmann", "Koch", "Richter", "Klein", "Wolf", "Schröder", "Neumann", "Schwarz", "Zimmermann",
              "Braun", "Krüger", "Hofmann", "Hartmann", "Lange", "Schmitt", "Werner", "Yılmaz", "Kaya", "Nowak",
              "Kowalski", "Rossi", "Popescu", "Ivanova", "Nguyen", "Öztürk", "Demir", "Al-Hassan"]

# {P} full name, {F} first name, {L} last name, {I} initial plus last name, {O} organisation, {C} place.
TEMPLATES = [
    "Subject: Anfrage vom {D} um {T} Uhr\n\nBody: {Q}\n\nMit freundlichen Grüßen\n{P}",
    "Subject: {S}\n\nBody: Hallo,\n\n{Q}\n\nViele Grüße\n{P}",
    "Subject: {S}\n\nBody: Guten Tag,\n\n{Q}\n\nGruß\n{I}",
    "Betreff: {S}\n\n{Q}\n\nLG {F}",
    "Subject: {S}\n\nBody: {Q} Danke! {F}",
    "Subject: {S}\n\nBody: Sehr geehrte Damen und Herren,\n\nich bin Rechtsanwalt und vertrete Herrn {P}. {Q}\n\nMit freundlichen Grüßen\nRA Dr. {L}\n{O}",
    "Subject: {S}\n\nBody: Sehr geehrte Damen und Herren, ich vertrete meine Mandantin, Frau {L}. {Q} Mit freundlichen Grüßen, Rechtsanwalt {P}, {O}",
    "Subject: {S}\n\nBody: Sehr geehrte Damen und Herren, der {O} liegt eine Beschwerde von Herrn {P} vor. Wir bitten um Stellungnahme. Mit freundlichen Grüßen {O2}",
    "{\"answer\":\"Guten Tag {P} R{N},\\n wie kann ich Ihnen heute helfen?\"}",
    "{\"answer\":\"Guten Abend {P} R{N},\\n wie kann ich Ihnen heute helfen?\"}",
    "Hallo {P}, vielen Dank für Ihre Nachricht. {A}",
    "ich habe gestern {M} € an {P} überwiesen, das ist aber nicht angekommen",
    "Ich habe eine Überweisung an {P} gemacht, die IBAN war falsch. Können Sie die zurückholen?",
    "Empfänger: {P}\nIBAN: DE{N}{N}\nBetrag: {M} €\nVerwendungszweck: Miete",
    "Name: {P}\nGeburtsdatum: 01.03.1990\nAnschrift: Hauptstraße 5, 12345 {C}",
    "Kontoinhaber: {P} Empfänger: {O} Betrag: {M} € Zeitpunkt: {D} um {T} Uhr",
    "{O} hat bei mir {M} € abgebucht, das habe ich nicht autorisiert. Bitte zurückbuchen.",
    "Warum wurde meine Kartenzahlung bei {O} abgelehnt?",
    "Ich bin gerade in {C} und meine Karte funktioniert nicht.",
    "ich bin in {c} und kann nicht mit karte zahlen",
    "Kann ich in {C} kostenlos Geld abheben?",
    "Ich möchte mein Konto bei der {O} kündigen und zu euch wechseln.",
    "Mein Gehalt kommt von der {O}, wann ist es auf dem Konto?",
    "Der Beschluss des {G} vom {D} betrifft den Beschuldigten {P}. Ich bitte um Übersendung. {O2}, Dr. {P2}",
    "Betreff: Nachlass {P} – Sehr geehrte Damen und Herren, wir vertreten die Erben nach Frau {P}. Mit freundlichen Grüßen Notar {P2}",
    "Mein Name ist {P} und ich wohne in {C}. {Q}",
    "ich heiße {f} {l} und {q}",
    "Ich heiße jetzt {L}, mein Nachname hat sich geändert.",
    "Immer wenn ich die App starte steht da Herr {L}. Richtig ist Frau {L}.",
    "hallo ich bin {f}, {q}",
    "Meine Frau {F} möchte auch ein Konto eröffnen.",
    "Wer ist {P}?",
    "{Q}\n\nViele Grüße\n\n{P}\n\nProduktmanager – Kundenservice\n\nC24 Bank GmbH\n\nGeschäftsführer: {P2}, {P3}\n\n{G2} HRB: 114 517 | UST Ident Nr.: DE 322 469 451",
    "**From:** C24 GmbH INT <support@example.zendesk.com>\n**To:** {P} <{e}@example.com>\n**Subject:** Unsere Antwort auf Ihre Anfrage\n\nHallo {P}, unser Kundenservice hat sich Ihr Anliegen angesehen.",
    "Presseanfrage: Die Redaktion von {O} bittet um Stellungnahme. Viele Grüße {P}",
    "Hey liebes C24 Team! Ich bin {F} von {O} und würde eure Bank gerne vorstellen. LG {F}",
    # Bot answers listing transactions: payees mixed with own pockets and generic entries that are not entities.
    "{\"answer\":\"Das sind Ihre <strong>letzten Buchungen</strong> seit <strong>{D}</strong>:\\n\\n⦁ {d} — {B}: -{M} EUR - SEPA-Überweisung\\n\\n⦁ {d} — Notgroschen: -{M} EUR - SEPA-Überweisung\\n\\n⦁ {d} — {O}: -{M} EUR - Kartenzahlung\\n\\n⦁ {d} — Geldautomat: -{M} EUR - Bargeldabhebung\\n\\n⦁ {d} — {P}: {M} EUR - SEPA-Gutschrift\"}",
    "{\"answer\":\"Im <strong>Oktober 2026</strong> haben Sie an diese Empfänger überwiesen:\\n\\n⦁ <strong>{B}</strong>: {M} EUR\\n\\n⦁ <strong>{O}</strong>: {M} EUR\\n\\n⦁ <strong>Sparkonto</strong>: {M} EUR\\n\\n⦁ <strong>{P}</strong>: {M} EUR\"}",
    "{\"answer\":\"Ihr größter Geldeingang im Oktober 2026 war <strong>{M} EUR</strong> von <strong>{O}</strong> (Gehalt).\"}",
    "{\"answer\":\"Die größte Abbuchung ging an <strong>{B}</strong> über {M} EUR am {d}.\"}",
    "{\"answer\":\"Sie haben am häufigsten bei {O}, {B} und {O2} eingekauft.\"}",
    "⦁ <strong>{O}</strong>, {B}, Sparkonto, {O2}, Tagesgeld und {P}",
    "Zuletzt hat Ihnen {P} am {d} {M} EUR überwiesen.",
    "{\"type\":\"TRANSACTION_LIST\",\"data\":{\"transactions\":[{\"counterpartyName\":\"{B}\",\"amount\":-{M}},{\"counterpartyName\":\"{P}\",\"amount\":{M}}]}}",
]
# Business names as they appear as payees: trade plus surname or a made-up name.
TRADES = ["Bäckerei", "Möbelhaus", "Hausverwaltung", "Autohaus", "Zahnarztpraxis", "Physiotherapie", "Elektro",
          "Friseursalon", "Blumenhaus", "Getränkemarkt", "Fahrschule", "Malerbetrieb", "Sanitär", "Optik", "Reisebüro",
          "Metzgerei", "Steuerberatung", "Immobilien", "Schreinerei", "Fitnessstudio", "Tierarztpraxis"]
DINING = ["Pizzeria", "Ristorante", "Osteria", "Taverna", "Restaurant", "Café", "Bistro", "Imbiss", "Gasthaus"]
DINING_NAMES = ["Da Mario", "Roma", "Venezia", "La Piazza", "Akropolis", "Sonnenhof", "Zum Goldenen Hirsch",
                "Mamma Mia", "Il Gabbiano", "Zur Linde", "Olympia", "Sakura", "Anatolia"]
SUFFIXES = ["GmbH", "GmbH & Co. KG", "AG", "e.K.", "& Söhne", "KG", "UG"]
# Texts without entities: domain words and mail headers that NER must leave alone.
NEGATIVES = [
    "Subject: {S}\n\nBody: {Q}", "Betreff: {S}\n\n{Q}", "{Q}", "{q}", "Subject: Chatbot Bewertung vom {D} um {T} Uhr\n\nBody: {A}",
    "{\"answer\":\"{A}\",\"links\":[],\"subtopic\":\"{S}\"}", "Gesendet von Outlook für Mac\n\n{Q}",
    "Chargeback Antrag: Kunde hat für folgende Kartenzahlung einen Chargeback Antrag eingereicht. Betrag: -{M} €",
]
SUBJECTS = ["Kontoeröffnung abgelehnt", "Dispolimit erhöhen", "Karte gesperrt", "Überweisungslimit", "Rückbuchung",
            "Kündigung", "Pfändung", "Kontoumzug", "Frage zu Karte", "Lastschrift zurückgeben", "Prämie",
            "Freistellungsauftrag", "Nachweise", "Legitimation", "Smartkonto", "Maxkonto", "Wero", "Cashback"]
QUESTIONS = ["Wie kann ich meinen Dispokredit erhöhen?", "Warum ist meine Karte gesperrt?",
             "Bitte prüfen Sie die Abbuchung und buchen Sie den Betrag zurück.",
             "Wann bekomme ich die Prämie für den Kontoumzug?", "Wie richte ich einen Freistellungsauftrag ein?",
             "Ich möchte mein Girokonto kündigen.", "Mein Überweisungslimit reicht nicht, bitte erhöhen.",
             "Wie lange dauert die Legitimation per VideoIdent?", "Kann ich mein Smartkonto in ein Maxkonto wechseln?",
             "Die Lastschrift habe ich nie autorisiert.", "Bitte wandeln Sie mein Konto in ein P-Konto um.",
             "Anbei die Meldebescheinigung und der Mietvertrag.", "Wo finde ich meine Kontoauszüge im Dokumentencenter?"]
Q_LOWER = ["wie kann ich meine karte sperren", "wo finde ich meine iban", "wann kommt wero",
           "warum geht meine überweisung nicht", "ich will mein konto kündigen", "dispo erhöhen bitte",
           "wie viel habe ich für lebensmittel ausgegeben"]
ANSWERS = ["Sie können Ihr Überweisungslimit in der App unter Profil anpassen.",
           "Die Kontoinhaberbestätigung finden Sie im Dokumentencenter.",
           "Für Bargeldabhebungen gelten je nach Kontomodell unterschiedliche Freiverfügungen.",
           "Ihr Dispokredit wird nach der Prüfung freigeschaltet.", "Das Tagesgeldpocket wird monatlich verzinst."]
COURTS = ["Amtsgerichts München", "Amtsgerichts Hamburg", "Landgerichts Berlin", "Amtsgerichts Düsseldorf"]
COURTS_NOM = ["Amtsgericht München", "Amtsgericht Hamburg", "Amtsgericht Charlottenburg", "Amtsgericht Düsseldorf",
              "Amtsgericht Stuttgart"]


def load_germeval(path: Path, limit: int, rng: random.Random) -> list[tuple[str, list[tuple[int, int, str]]]]:
    sents, toks = [], []
    for line in path.read_text(encoding="utf-8").splitlines() + [""]:
        if not line.strip():
            if toks:
                sents.append(toks)
            toks = []
            continue
        if line.startswith("#"):
            continue
        cols = line.split("\t")
        toks.append((cols[1], cols[2]))
    rng.shuffle(sents)
    out = []
    for toks in sents[:limit]:
        text, spans, pos, cur = "", [], 0, None
        for i, (tok, tag) in enumerate(toks):
            if i:
                text += " "
                pos += 1
            start, end = pos, pos + len(tok)
            text += tok
            pos = end
            kind = tag[2:] if tag != "O" else ""
            label = {"PER": "PER", "ORG": "ORG", "LOC": "LOC", "OTH": "MISC"}.get(kind)
            if tag.startswith("B-") and label:
                cur = [start, end, label]
                spans.append(cur)
            elif tag.startswith("I-") and label and cur and cur[2] == label:
                cur[1] = end
            else:
                cur = None
        out.append((text, [tuple(s) for s in spans]))
    return out


def germeval_names(path: Path) -> list[str]:
    names, cur = set(), []
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        tag = cols[2] if len(cols) > 2 else "O"
        if tag == "B-PER":
            if len(cur) >= 2:
                names.add(" ".join(cur))
            cur = [cols[1]]
        elif tag == "I-PER" and cur:
            cur.append(cols[1])
        else:
            if len(cur) >= 2:
                names.add(" ".join(cur))
            cur = []
    return sorted(n for n in names if all(w[:1].isupper() and w.replace("-", "").isalpha() for w in n.split()))


class Filler:
    """Fills one template; returns text and entity offsets."""

    def __init__(self, rng: random.Random, names: list[str], orgs: list[str], locs: list[str]) -> None:
        self.rng, self.names, self.orgs, self.locs = rng, names, orgs, locs

    held_out: set[str] = set()

    def business(self) -> str:
        """A payee business name that does not occur in the dev or test split."""
        r = self.rng
        while True:
            last = r.choice(self.names).split()[-1]
            kind = r.random()
            if kind < 0.4:
                name = f"{r.choice(TRADES)} {last}"
            elif kind < 0.7:
                name = f"{r.choice(DINING)} {r.choice(DINING_NAMES)}"
            else:
                name = f"{last} {r.choice(['Software', 'Bau', 'Logistik', 'Handel', 'Consulting', 'Energie'])} " \
                       f"{r.choice(SUFFIXES)}"
            if name.lower() not in self.held_out:
                return name

    def fill(self, template: str) -> tuple[str, list[tuple[int, int, str]]]:
        r = self.rng
        full = r.choice(self.names)
        first, last = full.split()[0], full.split()[-1]
        values = {
            "P": (full, "PER"), "P2": (r.choice(self.names), "PER"), "P3": (r.choice(self.names), "PER"),
            "F": (first, "PER"), "L": (last, "PER"), "I": (f"{first[0]}. {last}", "PER"),
            "f": (first.lower(), "PER"), "l": (last.lower(), "PER"),
            "O": (r.choice(self.orgs), "ORG"), "O2": (r.choice(self.orgs), "ORG"),
            "C": (r.choice(self.locs), "LOC"), "c": (r.choice(self.locs).lower(), "LOC"),
            "G": (r.choice(COURTS), "ORG"), "G2": (r.choice(COURTS_NOM), "ORG"),
            "S": (r.choice(SUBJECTS), None), "Q": (r.choice(QUESTIONS), None), "q": (r.choice(Q_LOWER), None),
            "A": (r.choice(ANSWERS), None), "M": (f"{r.randint(5, 2000)},{r.randint(0, 99):02d}", None),
            "D": (f"{r.randint(1, 28):02d}.{r.randint(1, 12):02d}.2026", None),
            "d": (f"{r.randint(1, 28):02d}.{r.randint(1, 12):02d}.", None), "B": (self.business(), "ORG"),
            "T": (f"{r.randint(8, 20):02d}:{r.randint(0, 59):02d}", None), "N": (str(r.randint(1000000, 9999999)), None),
            "e": (f"{first.lower()}.{last.lower()}", None),
        }
        text, spans, i = "", [], 0
        while i < len(template):
            if template[i] == "{" and "}" in template[i:]:
                key = template[i + 1:template.index("}", i)]
                if key in values:
                    value, label = values[key]
                    if label:
                        spans.append((len(text), len(text) + len(value), label))
                    text += value
                    i += len(key) + 2
                    continue
            text += template[i]
            i += 1
        return text, spans


def to_example(nlp, text: str, spans: list[tuple[int, int, str]], missing: list[tuple[int, int]] = ()) -> Example | None:
    doc = nlp.make_doc(text)
    tags = offsets_to_biluo_tags(doc, [s for s in spans])
    for start, end in missing:
        for t in doc:
            if t.idx < end and start < t.idx + len(t.text):
                tags[t.i] = "-"
    if all(t == "-" for t in tags):
        return None
    return Example.from_dict(doc, {"entities": tags})


PARTIAL_RAW = {"ocr": "ocr_sbx.jsonl", "ocrint": "ocr_int.jsonl"}


def partial_examples(nlp, base: Path, files: list[Path]) -> list[Example]:
    """Partially annotated letters: accepted entities, rejected strings taught as O, every other token missing."""
    texts = {}
    for prefix, name in PARTIAL_RAW.items():
        path = base / "raw" / name
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                texts[f"{prefix}:{row['db_id']}"] = row["text"]
    out = []
    for f in files:
        for key, ann in json.loads(f.read_text(encoding="utf-8"))["docs"].items():
            text = texts[key]
            spans = resolve(text, ann.get("accept", []), required=True, key=key)
            doc = nlp.make_doc(text)
            tags = ["-"] * len(doc)
            for s in spans:
                span = doc.char_span(s.start, s.end)
                if span is None:
                    continue
                if len(span) == 1:
                    tags[span.start] = f"U-{s.label}"
                else:
                    tags[span.start] = f"B-{s.label}"
                    for i in range(span.start + 1, span.end - 1):
                        tags[i] = f"I-{s.label}"
                    tags[span.end - 1] = f"L-{s.label}"
            for surface in ann.get("reject", []):
                for start in _occurrences(text, surface):
                    neg = Span(start, start + len(surface), "O")
                    if any(neg.overlaps(s) for s in spans):
                        continue
                    for t in doc:
                        if t.idx < neg.end and neg.start < t.idx + len(t.text) and tags[t.i] == "-":
                            tags[t.i] = "O"
            if any(t != "-" for t in tags):
                out.append(Example.from_dict(doc, {"entities": tags}))
    return out


def feedback_examples(nlp, files: list[Path]) -> list[Example]:
    """Corrections exported from the Chat tab (GET /v1/feedback/export): marked persons, organisations and places
    are entities, wrongly detected strings are O, every other token is left out of the loss."""
    out = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            text = row["text"]
            doc = nlp.make_doc(text)
            tags = ["-"] * len(doc)
            for s in row["spans"]:
                span = doc.char_span(s["start"], s["end"], alignment_mode="expand")
                if span is None or s["label"] not in ("PER", "ORG", "LOC"):
                    continue  # rule types (case numbers, courts, …) are not NER labels
                for k, i in enumerate(range(span.start, span.end)):
                    tags[i] = ("U-" if len(span) == 1 else "B-" if k == 0 else "L-" if i == span.end - 1 else "I-") \
                        + s["label"]
            for r in row.get("reject", []):
                for t in doc:
                    if t.idx < r["end"] and r["start"] < t.idx + len(t.text) and tags[t.i] == "-":
                        tags[t.i] = "O"
            if any(t != "-" for t in tags):
                out.append(Example.from_dict(doc, {"entities": tags}))
    return out


_PUBLIC_TYPES = {"court", "legal_citation", "case_number", "date", "money", "iban", "email", "phone"}


def court_examples(nlp, docs, max_chars: int = 2500) -> list[Example]:
    """Whole decisions with filled placeholders (court_data.py): per paragraph block, inserted persons,
    organisations and places are entities; lower-case words, numbers, punctuation and what the rules find
    (courts, citations, case numbers, dates) are O; other capitalised words stay missing, because the court
    may have left a real name there (judges, often lawyers)."""
    from anonymizer.detect import Detector, DetectorConfig  # noqa: PLC0415

    rules = Detector(DetectorConfig(enable_ner=False))
    out = []
    for d in docs:
        public = [(x.start, x.end) for x in rules.scan(d.text, "de").detections if x.entity_type in _PUBLIC_TYPES]
        start = 0
        for block in re.split(r"(\n\n)", d.text):
            end = start + len(block)
            spans = [s for s in d.spans if start <= s.start and s.end <= end]
            if spans and block.strip() and len(block) <= max_chars:
                doc = nlp.make_doc(block)
                tags = []
                for t in doc:
                    a, b = start + t.idx, start + t.idx + len(t.text)
                    known_o = not t.text[:1].isupper() or any(ps <= a and b <= pe for ps, pe in public)
                    tags.append("O" if known_o else "-")
                for s in spans:
                    span = doc.char_span(s.start - start, s.end - start, alignment_mode="expand")
                    if span is None:
                        continue
                    if s.label not in ("PER", "ORG", "LOC"):
                        for i in range(span.start, span.end):
                            tags[i] = "-" if s.label == "ADDR" else "O"
                        continue
                    for k, i in enumerate(range(span.start, span.end)):
                        tags[i] = ("U-" if len(span) == 1 else "B-" if k == 0 else "L-" if i == span.end - 1 else "I-") \
                            + s.label
                out.append(Example.from_dict(doc, {"entities": tags}))
            start = end
    return out


def evaluate(nlp_path_or_obj, docs) -> dict:
    rec = SpacyRecognizer({"de": "de_core_news_lg", "en": "en_core_web_lg"}, NAME_STOPWORDS | NER_STOPWORDS,
                          keep=list(DEFAULT_KEEP))
    if not isinstance(nlp_path_or_obj, str):
        from anonymizer.detect import ner as ner_mod  # noqa: PLC0415
        # A "+" name, like a shipped fine-tuned model, so the pipeline applies the same rules (lower-case chat).
        ner_mod._MODEL_CACHE["de_core_news_lg+__candidate__"] = nlp_path_or_obj
        rec = SpacyRecognizer({"de": "de_core_news_lg+__candidate__", "en": "en_core_web_lg"},
                              NAME_STOPWORDS | NER_STOPWORDS, keep=list(DEFAULT_KEEP))
    keep = keep_pattern(DEFAULT_KEEP)
    per_doc = []
    for d in docs:
        pred = [p for p in predict_pipeline(rec, d.text) if relevant(p, d.text, d.spans, keep)]
        per_doc.append((d.key, score_doc(d.spans, pred, partial=False)[0]))
    return summarize(per_doc)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="local/ner", type=Path)
    ap.add_argument("--out", default="local/ner/models/de_c24_ner", type=Path)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--germeval", type=int, default=6000, help="GermEval sentences for rehearsal")
    ap.add_argument("--synthetic", type=int, default=4000)
    ap.add_argument("--gold-repeat", type=int, default=3, help="how often the gold train split is repeated")
    ap.add_argument("--partial", type=Path, nargs="*", default=[],
                    help="partial annotation files for OCR letters (accept/reject lists), training only")
    ap.add_argument("--partial-repeat", type=int, default=2)
    ap.add_argument("--ler", type=Path, help="datasets/ler: add LER train docs (and use LER dev without gold.jsonl)")
    ap.add_argument("--ler-docs", type=int, default=0, help="LER train docs to use (0 = all)")
    ap.add_argument("--ler-repeat", type=int, default=1)
    ap.add_argument("--courts", type=Path, help="datasets/courts: whole decisions with filled placeholders")
    ap.add_argument("--courts-repeat", type=int, default=1)
    ap.add_argument("--feedback", type=Path, nargs="*", default=[], help="feedback.jsonl from GET /v1/feedback/export")
    ap.add_argument("--feedback-repeat", type=int, default=3)
    ap.add_argument("--init", type=Path, help="continue from a saved model instead of de_core_news_lg; only "
                    "epochs that beat its dev score are saved")
    args = ap.parse_args()
    rng = random.Random(SEED)

    gold_path = args.dir / "gold.jsonl"
    gold = read_gold(gold_path) if gold_path.exists() else []
    ler_train, ler_dev, ler_test = [], [], []
    if args.ler:
        from ler_data import load as load_ler  # noqa: PLC0415 - same scripts folder

        ler_train, ler_dev, ler_test = (load_ler(args.ler, s) for s in ("train", "dev", "test"))
        if args.ler_docs:
            ler_train = rng.sample(ler_train, min(args.ler_docs, len(ler_train)))
    if not gold and not ler_dev:
        sys.exit(f"no data: {gold_path} is missing and --ler is not set")
    train_docs = [d for d in gold if d.split == "train"]
    # Model selection: the company dev split if there is one, otherwise LER dev.
    dev_docs = [d for d in gold if d.split == "dev"] or ler_dev
    held_out = {d.text[s.start:s.end].lower() for d in [*gold, *ler_dev, *ler_test]
                if d.split in ("dev", "test") for s in d.spans if s.label in ("PER", "ORG", "LOC")}

    def unseen(xs: list[str]) -> list[str]:
        return [x for x in xs if x.lower() not in held_out and not any(w.lower() in held_out for w in x.split())]

    ge_path = args.dir / "public" / "germeval14" / "train.tsv"
    names_path = args.dir / "public" / "int_names.txt"
    int_names = [n.strip() for n in names_path.read_text(encoding="utf-8").splitlines() if n.strip()] \
        if names_path.exists() else []
    if not ge_path.exists():
        print(f"{ge_path} missing: no GermEval rehearsal (LER and synthetic texts only)")
    names = unseen((germeval_names(ge_path) if ge_path.exists() else []) + int_names
                   + [f"{f} {l}" for f in FIRST_EXTRA for l in LAST_EXTRA])
    orgs, locs = unseen(ORGS), unseen(LOCS)
    print(f"gazetteers after removing dev/test strings: {len(names)} names, {len(orgs)} orgs, {len(locs)} places")

    nlp = spacy.load(args.init or "de_core_news_lg")
    examples: list[Example] = []
    for text, spans in (load_germeval(ge_path, args.germeval, rng) if ge_path.exists() else []):
        if (ex := to_example(nlp, text, spans)) is not None:
            examples.append(ex)
    n_ge = len(examples)
    filler = Filler(rng, names, orgs, locs)
    filler.held_out = held_out
    for i in range(args.synthetic):
        template = rng.choice(NEGATIVES) if i % 5 == 0 else rng.choice(TEMPLATES)
        text, spans = filler.fill(template)
        if (ex := to_example(nlp, text, spans)) is not None:
            examples.append(ex)
    n_syn = len(examples) - n_ge
    gold_examples = []
    for d in train_docs:
        spans = [(s.start, s.end, s.label) for s in d.spans if s.label != "ADDR"]
        missing = [(s.start, s.end) for s in d.spans if s.label == "ADDR"]
        doc = nlp.make_doc(d.text)
        # Gold spans inside a token ("Commerzbank" in "Commerzbank-Konto") cannot be taught; mark those tokens missing.
        for s in list(spans):
            if doc.char_span(s[0], s[1]) is None:
                spans.remove(s)
                missing.append((s[0], s[1]))
        if (ex := to_example(nlp, d.text, spans, missing)) is not None:
            gold_examples.append(ex)
    examples += gold_examples * args.gold_repeat
    ler_examples = []
    for d in ler_train:
        # Only private parties are entities; courts, laws, case law, literature are O (taught, not missing).
        spans = [(s.start, s.end, s.label) for s in d.spans if s.label in ("PER", "ORG", "LOC")]
        missing = [(s.start, s.end) for s in d.spans if s.label == "ADDR"]
        doc = nlp.make_doc(d.text)
        for s in list(spans):
            if doc.char_span(s[0], s[1]) is None:
                spans.remove(s)
                missing.append((s[0], s[1]))
        if (ex := to_example(nlp, d.text, spans, missing)) is not None:
            ler_examples.append(ex)
    examples += ler_examples * args.ler_repeat
    partial = partial_examples(nlp, args.dir, args.partial)
    examples += partial * args.partial_repeat
    fb = feedback_examples(nlp, args.feedback)
    examples += fb * args.feedback_repeat
    court_ex = []
    if args.courts:
        from court_data import load as load_courts  # noqa: PLC0415 - same scripts folder

        court_ex = court_examples(nlp, load_courts(args.courts, "train"))
    examples += court_ex * args.courts_repeat
    print(f"examples: germeval {n_ge}, synthetic {n_syn}, gold train {len(gold_examples)} x{args.gold_repeat}, "
          f"partial {len(partial)} x{args.partial_repeat}, ler {len(ler_examples)} x{args.ler_repeat}, "
          f"feedback {len(fb)} x{args.feedback_repeat}, courts {len(court_ex)} x{args.courts_repeat}")

    # The starting point is scored with the model already in memory (no second copy of the 600 MB vectors).
    base = evaluate(nlp, dev_docs) if args.init else evaluate("de_core_news_lg", dev_docs)
    print(f"dev start micro F1={base['micro']['f1']} P={base['micro']['precision']} R={base['micro']['recall']}",
          flush=True)
    best, best_f1, history = 0, (base["micro"]["f1"] or 0.0) if args.init else -1.0, []
    # Only the NER is trained (it has its own tok2vec); tagger etc. stay as shipped because the pipeline uses
    # their POS tags. Evaluation runs the full pipeline, so no select_pipes() around it.
    others = [n for n in nlp.pipe_names if n != "ner"]
    optimizer = nlp.resume_training()
    for epoch in range(args.epochs):
        rng.shuffle(examples)
        losses: dict = {}
        for batch in minibatch(examples, size=compounding(8.0, 32.0, 1.001)):
            nlp.update(batch, sgd=optimizer, drop=0.25, losses=losses, exclude=others)
        with nlp.use_params(optimizer.averages):
            score = evaluate(nlp, dev_docs)
            f1 = score["micro"]["f1"] or 0.0
            history.append({"epoch": epoch + 1, "loss": round(float(losses.get("ner", 0.0)), 1), "dev": score["micro"]})
            print(f"epoch {epoch + 1}: loss {losses.get('ner', 0.0):.1f} dev F1={f1} "
                  f"P={score['micro']['precision']} R={score['micro']['recall']}", flush=True)
            if f1 > best_f1:
                best_f1 = f1
                args.out.mkdir(parents=True, exist_ok=True)
                nlp.to_disk(args.out)
                best = epoch + 1
    (args.out / "training.json").write_text(json.dumps({
        "seed": SEED, "best_epoch": best, "dev_baseline": base["micro"], "history": history,
        "data": {"germeval": n_ge, "synthetic": n_syn, "gold_train": len(gold_examples),
                 "gold_repeat": args.gold_repeat, "partial": len(partial), "partial_repeat": args.partial_repeat,
                 "ler": len(ler_examples), "ler_repeat": args.ler_repeat,
                 "feedback": len(fb), "feedback_repeat": args.feedback_repeat,
                 "courts": len(court_ex), "courts_repeat": args.courts_repeat,
                 "dev": "gold.jsonl" if gold else "ler_dev"},
    }, indent=2), encoding="utf-8")
    print(f"best epoch {best}, dev F1 {best_f1}; model saved to {args.out}")


if __name__ == "__main__":
    main()
