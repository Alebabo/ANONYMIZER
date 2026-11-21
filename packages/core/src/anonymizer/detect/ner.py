"""spaCy NER recognizer (enabled by default).

Models are loaded lazily and must be installed separately
(``python -m spacy download de_core_news_lg en_core_web_lg``; the Docker
image ships them). If spaCy or a model is missing, the engine records a
warning and continues with rule-based detection only.

NER results never override rule-based detections (see ``engine._rank``).
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from typing import Any

from anonymizer.models import Category, Detection, EntityType as E, make_detection

# ANONYMIZER_NER_MODEL_DE selects another German model, e.g. the fine-tuned support NER:
# "de_core_news_lg+models/de_custom_ner/ner" (base model plus NER weights, see models/de_custom_ner/README.md).
DEFAULT_MODELS = {"de": os.environ.get("ANONYMIZER_NER_MODEL_DE") or "de_core_news_lg", "en": "en_core_web_lg"}

_LABELS = {
    "PER": (E.PERSON, Category.PERSONAL_DATA, 0.8),
    "PERSON": (E.PERSON, Category.PERSONAL_DATA, 0.8),
    "ORG": (E.ORGANIZATION, Category.PERSONAL_DATA, 0.6),
    "LOC": (E.LOCATION, Category.PERSONAL_DATA, 0.45),
    "GPE": (E.LOCATION, Category.PERSONAL_DATA, 0.45),
}

_LEADING_HONORIFIC = re.compile(r"^(?:(?:Herrn?|Frau|Hr\.|Fr\.|Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.)\s+)+")
# JSON, markup or escapes inside a span: serialised data, never a name ("angezeigt.\",\"links\":[").
# Bullets join list items ("Kongo⦁ Laos⦁") into one span that is never a single name.
_CODE_CHARS = re.compile(r'["{}\[\]\\<>=|_•⦁·▪●◦]')
_CODE_LIKE = re.compile(r"^[A-Z]{1,4}\d*$|\d")
# Reference numbers such as "K-1001", "AB12345", "INC-42/7": letters, optional separator, digits.
ID_LIKE = re.compile(r"[A-Za-z]{1,4}[-_./ ]?\d[\d\-_./]*")
_HONORIFICS = {"Herr", "Herrn", "Frau", "Hr.", "Fr.", "Hr", "Fr", "Mr.", "Mrs.", "Ms.", "Mr", "Mrs", "Ms", "Dr.",
               "Prof.", "Dr", "Prof"}
# Statistical NER readily labels capitalised common nouns ("Dispolimit", "Karte") as names or organisations.
# A person/organisation span from NER alone is kept only if the model's own tagger sees a proper noun in it
# or a title stands right before it. Real names in hinted columns or with rule cues do not depend on this.
_PROPER = {"PROPN", "X"}
# Types whose NER spans must look like a name. Locations too: German compounds ("Karteneinstellungen",
# "Dispozinsen") are tagged NOUN, real places ("Deutschland", "London") PROPN.
_TAGGED = (E.PERSON, E.ORGANIZATION, E.LOCATION)
_NAME_PARTICLES = {"von", "van", "vom", "zu", "zum", "zur", "de", "da", "di", "du", "del", "della", "der", "den",
                   "ten", "ter", "le", "la", "al", "el", "bin", "ibn", "y", "und", "and", "of", "&"}


# Courts and authorities are organisations even when NER calls "Amtsgericht Frankfurt" a place. A register
# abbreviation glued to the end ("Amtsgericht Frankfurt HRB: 123 456") is not part of the name.
_AUTHORITY = re.compile(r"^(?:Amts|Land|Oberlandes|Arbeits|Sozial|Finanz|Verwaltungs)gerichts?\b|^Staatsanwaltschaft\b"
                        r"|^Finanzamt(?:es|s)?\b|^Jobcenter\b|^Polizeipräsidium\b|^Bundesanstalt\b|^Bundesamt\b")
_REGISTER_TAIL = re.compile(r"(?:\s+(?:HRB|HRA|GnR|PR|VR|UST))+$")


def authority_type(text: str, entity_type: str) -> tuple[str, str]:
    """(entity_type, text) with courts and authorities typed as organisations, register suffix removed."""
    if entity_type in (E.LOCATION, E.ORGANIZATION, E.PERSON) and _AUTHORITY.match(text):
        return E.ORGANIZATION, _REGISTER_TAIL.sub("", text)
    return entity_type, text


def is_casual(text: str) -> bool:
    """A span of plain lower-case words, as typed in chat."""
    return text.islower() and all(t.isalpha() for t in text.split(" "))


def clean_entity(text: str, start: int, entity_type: str, stopwords: set[str],
                 allow_casual: bool = False) -> tuple[int, str] | None:
    """Normalise or reject a raw NER span. Returns (start, text) or None.

    Statistical NER is noisy on legal text: it marks role words
    ("Beklagte"), headings spanning line breaks, abbreviations ("Az", "NDA")
    and code fragments ("DE00") as entities.
    """
    if "\n" in text or "@" in text or "/" in text or _CODE_CHARS.search(text):
        return None
    m = _LEADING_HONORIFIC.match(text)
    if m:
        start += m.end()
        text = text[m.end():]
    stripped = text.lstrip(" ,.;:()")
    start += len(text) - len(stripped)
    text = stripped.rstrip(" ,.;:()")
    tokens = text.split(" ")
    while len(tokens) > 1 and tokens[0] in stopwords:  # "Akte Mustermann" -> "Mustermann"
        start += len(tokens[0]) + 1
        tokens = tokens[1:]
    text = " ".join(tokens)
    if len(text) < 3 or not tokens or all(t in stopwords for t in tokens):
        return None
    # Chat is often written in lower case ("überweisung an schepers", "bei der volksbank"). With a model trained
    # on such chat (allow_casual), plain lower-case words are kept; the stock model is too noisy on them.
    # Lower-case spans with digits, hyphens or dots are code ("drawable-xxxhdpi"), never names.
    if allow_casual and is_casual(text):
        lowered = {w.lower() for w in stopwords}
        return None if all(t in lowered for t in tokens) else (start, text)
    if not any(ch.isupper() for ch in text):
        return None
    # camelCase identifiers ("cardSettings", "creditComparison") start lower-case; name particles may.
    if text[0].islower() and tokens[0] not in _NAME_PARTICLES:
        return None
    # A single all-caps word of 5+ letters is an enum or status value (GREETING, TRANSACTION), not a name.
    if len(tokens) == 1 and len(text) >= 5 and text.isupper():
        return None
    if entity_type == E.PERSON and any(ch.isdigit() for ch in text):
        return None
    # "sein Dispolimit", "nach Urlaub": a plain lower-case word is not part of a name (particles are).
    lower = [t for t in tokens if t.isalpha() and t.islower() and t not in _NAME_PARTICLES]
    if lower and (entity_type == E.PERSON or (entity_type == E.ORGANIZATION and tokens[0] in lower)):
        return None
    if entity_type != E.LOCATION and (_CODE_LIKE.fullmatch(text) or ID_LIKE.fullmatch(text)):
        return None
    if entity_type == E.LOCATION and re.fullmatch(r"[A-Z]{2}\d+|[A-Z][a-z]?", text):
        return None
    return start, text


def _name_like(doc: Any, start: int, end: int, pos: dict[int, str] | None = None) -> bool:
    """A proper noun inside the span, or a title right before it. Without a tagger: keep the span.

    ``pos`` maps token index to POS when the tagger ran on windows only (see ``_window_pos``);
    otherwise the POS is read from ``doc``."""
    span = doc.char_span(start, end, alignment_mode="expand")
    if span is None or not len(span):
        return True
    tags = [pos.get(t.i, "") if pos is not None else t.pos_ for t in span]
    if not any(tags):
        return True
    if any(p in _PROPER for p in tags):
        return True
    return span.start > 0 and doc[span.start - 1].text in _HONORIFICS


# The tagger only matters for PERSON/ORGANIZATION candidates (``_name_like``), yet its shared tok2vec costs about
# as much as NER itself. So NER runs alone and the tagging pipes run only on small windows around candidates.
# The CNN tok2vec sees 4 tokens to each side (window 1, depth 4); a margin of 8 keeps the POS identical.
_TAG_MARGIN = 8


def _ner_only(nlp: Any) -> list[str]:
    """Pipes to skip for the NER pass; empty if NER listens to the shared tok2vec and cannot run alone."""
    if "ner" not in nlp.pipe_names:
        return []
    arch = nlp.get_pipe_config("ner").get("model", {}).get("tok2vec", {}).get("@architectures", "")
    if "Listener" in arch:
        return []
    return [n for n in nlp.pipe_names if n != "ner"]


def _window_pos(nlp: Any, doc: Any, spans: list[tuple[int, int]]) -> dict[int, str]:
    """POS for the tokens of ``spans`` (token ranges), tagging only merged windows around them."""
    pipes = [(n, p) for n, p in nlp.pipeline if n != "ner"]
    windows: list[list[int]] = []
    for s, e in sorted(spans):
        lo, hi = max(0, s - _TAG_MARGIN), min(len(doc), e + _TAG_MARGIN)
        if windows and lo <= windows[-1][1]:
            windows[-1][1] = max(windows[-1][1], hi)
        else:
            windows.append([lo, hi])
    pos: dict[int, str] = {}
    for lo, hi in windows:
        part = doc[lo:hi].as_doc()
        for _, proc in pipes:
            part = proc(part)
        for t in part:
            pos[lo + t.i] = t.pos_
    return pos


# A name standing alone as a sentence or line: the signature block of a decision ("Raum", "Fieback", "Hayen"),
# one judge per line or, in LER, one judge per sentence. In running text the model reads it as the start of the
# next sentence and often misses it ("… entschieden. Fieback bb) Aus den …"). Such a word is checked once more
# on its own, the way it stands in the signature block; only if NER then calls it a person is it kept. Headings
# ("Tatbestand", "Geltungsbereich", "Urlaub") are not persons to the model even on their own.
_ISOLATED_WORD = r"[A-ZÄÖÜ][a-zäöüßàáâãçćčéèêëğíìîıïłńñóòôõøšśşúùûžźż]+(?:-[A-ZÄÖÜ][a-zäöüßéèóçćčšž]+)?"
# Before it: line or text start, or the end of a sentence; not an abbreviation or enumeration ("u. a.", "2.").
# After it: line or text end, an enumeration ("bb)", "(1)", "2.", "III.", "A."), or the capitalised first word of
# the next sentence.
_ISOLATED = re.compile(
    rf"(?:^|(?<=[\w)]{{2}}[.;!?]\s))(?P<name>{_ISOLATED_WORD})"
    rf"(?=[ \t]*$|\s(?:\(?[a-z]{{1,3}}\)|\(\d+\)|\d+(?:\.\d+)*\.?|[IVX]+\.|[A-H]\.)\s|\s[A-ZÄÖÜ])",
    re.MULTILINE,
)
# Adjectives opening a sentence ("Statthafte Klageart", "Gleichheitsrechtliche Anforderungen").
_ADJECTIVE_END = re.compile(r"(?:lich|haft|isch|ig|bar|sam|los|end)(?:e[nmrs]?)?$")
# Only models trained on such lines check isolated words: de_legal_ner learnt from LER, where a judge's signature is a
# sentence of its own. The stock and the support model call almost any single word a person ("Kreditkartenauszug",
# "Loan"); with them the check would only add false positives.
_ISOLATED_MODELS = ("de_legal_ner",)
# Words that appear alone in signature blocks and court copies and that the model takes for names on their own.
_ISOLATED_STOP = {"Beglaubigt", "Ausgefertigt", "Siegel", "Urkundsbeamter", "Urkundsbeamtin", "Justizangestellte",
                  "Justizbeschäftigte", "Justizsekretärin", "Justizsekretär"}


class NERUnavailable(RuntimeError):
    pass


# Process-wide model cache: loading a large model takes seconds.
_MODEL_CACHE: dict[str, Any] = {}
# Documents prepared by prefetch() and not yet analysed; bounded so a huge result cannot pile them up.
_DOC_CACHE_MAX = 5000


class SpacyRecognizer:
    name = "spacy_ner"

    def __init__(self, models: dict[str, str] | None = None, stopwords: set[str] | None = None,
                 keep: list[str] | None = None) -> None:
        self.models = models or DEFAULT_MODELS
        self.stopwords = stopwords or set()
        # "ACME" matches "ACME Bank" and "ACME-Konto", not "ACME5".
        terms = [re.escape(t.strip()) for t in keep or [] if t.strip()]
        self._keep = re.compile(rf"^(?:{'|'.join(terms)})(?![^\W_])", re.IGNORECASE) if terms else None
        self.languages = frozenset(self.models)
        # Fine-tuned support models ("base+ner_dir") were trained on lower-case chat; their lower-case spans are kept.
        self._casual = {lang for lang, model in self.models.items() if "+" in model}
        self._docs: dict[tuple[str, str], Any] = {}
        self._isolated = {lang for lang, model in self.models.items() if any(k in model for k in _ISOLATED_MODELS)}

    def _nlp(self, language: str) -> Any:
        model = self.models[language]
        if model not in _MODEL_CACHE:
            try:
                import spacy  # noqa: PLC0415
            except ImportError as exc:  # pragma: no cover - depends on environment
                raise NERUnavailable("spaCy is not installed") from exc
            # "de_core_news_lg+models/de_custom_ner/ner": base model with fine-tuned NER weights. Only the NER
            # component is shipped; vectors, tagger etc. come from the base model.
            base, _, ner_dir = model.partition("+")
            try:
                nlp = spacy.load(base, disable=["parser", "lemmatizer"])
            except OSError as exc:
                raise NERUnavailable(f"spaCy model '{base}' is not installed") from exc
            if ner_dir:
                try:
                    nlp.get_pipe("ner").from_disk(ner_dir, exclude=["vocab"])
                except (OSError, ValueError) as exc:
                    raise NERUnavailable(f"NER weights '{ner_dir}' could not be loaded: {exc}") from exc
            _MODEL_CACHE[model] = nlp
        return _MODEL_CACHE[model]

    def prefetch(self, texts: Iterable[str], language: str) -> None:
        """Run the model over many texts in one batch (much faster than one call per text); analyze()
        then takes the prepared document instead of running the model again. Results are identical."""
        texts = list(dict.fromkeys(texts))
        for lang in [language] if language in self.models else list(self.models):
            model = self.models[lang]
            todo = [t for t in texts if (model, t) not in self._docs]
            if not todo:
                continue
            if len(self._docs) + len(todo) > _DOC_CACHE_MAX:
                self._docs.clear()
            nlp = self._nlp(lang)
            docs = nlp.pipe(todo[:_DOC_CACHE_MAX], batch_size=64, disable=_ner_only(nlp))
            for t, doc in zip(todo[:_DOC_CACHE_MAX], docs):
                self._docs[(model, t)] = doc

    def analyze(self, text: str, language: str) -> Iterable[Detection]:
        languages = [language] if language in self.models else list(self.models)
        for lang in languages:
            nlp = self._nlp(lang)
            skipped = _ner_only(nlp)
            doc = self._docs.pop((self.models[lang], text), None)
            if doc is None:
                doc = nlp(text, disable=skipped)
            found = []
            for ent in doc.ents:
                mapped = _LABELS.get(ent.label_)
                if mapped is None:
                    continue
                entity_type, category, confidence = mapped
                entity_type, ent_text = authority_type(ent.text, entity_type)
                if entity_type == E.ORGANIZATION and mapped[0] != E.ORGANIZATION:
                    category, confidence = _LABELS["ORG"][1], _LABELS["ORG"][2]
                cleaned = clean_entity(ent_text, ent.start_char, entity_type, self.stopwords, lang in self._casual)
                if cleaned is not None and not (self._keep and self._keep.match(cleaned[1])):
                    found.append((entity_type, category, confidence, *cleaned))
            pos = None
            if skipped:
                spans = []
                for entity_type, _, _, start, value in found:
                    span = doc.char_span(start, start + len(value), alignment_mode="expand")
                    if entity_type in _TAGGED and span is not None and len(span):
                        spans.append((max(0, span.start - 1), span.end))  # the title before it counts too
                pos = _window_pos(nlp, doc, spans) if spans else {}
            kept: list[tuple[int, int]] = []
            for entity_type, category, confidence, start, value in found:
                # The tagger reads lower-case chat words as common nouns, so the proper-noun check does not apply.
                casual = lang in self._casual and is_casual(value)
                if entity_type in _TAGGED and not casual and not _name_like(doc, start, start + len(value), pos):
                    continue
                kept.append((start, start + len(value)))
                yield make_detection(entity_type, category, start, start + len(value), value,
                                     confidence, self.name)
            if lang in self._isolated:
                yield from self._isolated_names(nlp, text, kept, skipped)

    def _isolated_names(self, nlp: Any, text: str, taken: list[tuple[int, int]],
                        skipped: list[str]) -> Iterable[Detection]:
        """Names standing alone as a sentence or line that NER missed in context (see ``_ISOLATED``). The
        tagger reads unknown surnames there as common nouns ("Fieback", "Hayen"), so ``_name_like`` drops them
        even where NER found them; the check on the word alone replaces the proper-noun check."""
        cands = [m for m in _ISOLATED.finditer(text)
                 if m.group("name") not in self.stopwords and m.group("name") not in _ISOLATED_STOP
                 and not _ADJECTIVE_END.search(m.group("name"))
                 and not any(s < m.end() and m.start() < e for s, e in taken)]
        if not cands:
            return
        for m, alone in zip(cands, nlp.pipe([m.group("name") for m in cands], disable=skipped)):
            if any(e.label_ in ("PER", "PERSON") and e.start_char == 0 and e.end_char == len(alone.text)
                   for e in alone.ents):
                yield make_detection(E.PERSON, Category.PERSONAL_DATA, m.start(), m.end(), m.group("name"), 0.7,
                                     self.name)
