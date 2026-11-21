"""German LER (Legal Entity Recognition) as gold data for legal texts.

Source: Leitner, Rehm, Moreno-Schneider (2019), "Fine-grained Named Entity Recognition in Legal Documents",
https://github.com/elenanereiss/Legal-Entity-Recognition, CC BY 4.0. 66,723 sentences from federal court
decisions (2017/2018), CoNLL with 19 fine-grained labels.

What this module does with it:

* **Detokenize** the CoNLL tokens into running text and keep every span's character offsets.
* **Map labels** to what OpenAnonymizer protects. Only private parties are NER entities (PER, ORG, LOC). Courts,
  public bodies, laws and case law keep their LER label: they are public references, the rule recognizers
  handle them, and a PER/ORG prediction on them counts as a false positive.
* **Re-insert names.** The published decisions are already anonymized ("Rechtsanwalt F", "die P GmbH",
  "in B."). Those placeholders are replaced by synthetic names, so the model sees realistic text and the labels
  stay exact because we place the values ourselves. Train and dev/test draw from disjoint name lists, so the
  scores measure generalisation, not memory.
"""

from __future__ import annotations

import random
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from anonymizer.ner_dataset import GoldDoc, Span

# LER fine label -> gold label. NER labels are scored; the rest are kept for rule checks and false positives.
LABEL_MAP = {
    "PER": "PER", "RR": "PER", "AN": "PER",          # persons, judges, lawyers
    "UN": "ORG", "ORG": "ORG", "MRK": "ORG",          # companies, other organisations, brands
    "ST": "LOC", "LD": "LOC", "LDS": "LOC",           # cities, countries, landscapes
    "STR": "ADDR",                                    # streets belong to the address recognizer
    "GRT": "GRT", "INN": "INN",                       # courts, public institutions: public, not personal
    "RS": "RS", "GS": "GS", "VO": "VO", "EUN": "EUN", "VS": "VS", "VT": "VT", "LIT": "LIT",
}
# Gold labels on which a person/organisation/location detection is wrong (public legal references).
PUBLIC_LABELS = ("GRT", "INN", "RS", "GS", "VO", "EUN", "VS", "VT", "LIT")

# Synthetic values. Common names in Germany, several origins; companies are made from surnames.
_FIRST = """Anna Maria Laura Julia Sarah Lena Lisa Katharina Sophie Hannah Emma Mia Lea Johanna Clara Paula Marie
Elif Zeynep Aylin Fatma Ayşe Natalia Agnieszka Olga Irina Svetlana Fatima Amira Leila Sofia Giulia Chiara Ana Elena
Petra Sabine Monika Ursula Renate Brigitte Claudia Andrea Susanne Birgit Martina Heike Karin Gabriele Kerstin
Max Paul Lukas Leon Felix Jonas Elias Noah Ben Finn Luca Tim Jan David Moritz Simon Jakob Niklas Philipp Tobias
Mehmet Mustafa Ahmet Emre Can Murat Ali Hasan Piotr Tomasz Krzysztof Andrzej Dmitri Sergej Alexander Ivan Omar
Yusuf Karim Marco Luca Giuseppe Antonio Thomas Michael Andreas Stefan Christian Markus Peter Klaus Jürgen Wolfgang
Frank Uwe Ralf Dirk Bernd Holger Matthias Martin Daniel Florian Sebastian""".split()
_LAST = """Müller Schmidt Schneider Fischer Weber Meyer Wagner Becker Schulz Hoffmann Schäfer Koch Bauer Richter Klein
Wolf Schröder Neumann Schwarz Zimmermann Braun Krüger Hofmann Hartmann Lange Schmitt Werner Schmitz Krause Meier
Lehmann Schmid Schulze Maier Köhler Herrmann König Walter Mayer Huber Kaiser Fuchs Peters Lang Scholz Möller Weiß
Jung Hahn Schubert Vogel Friedrich Keller Günther Frank Berger Winkler Roth Beck Lorenz Baumann Franke Albrecht
Schuster Simon Ludwig Böhm Winter Kraus Martin Schumacher Krämer Vogt Stein Jäger Otto Sommer Groß Seidel Heinrich
Brandt Haas Schreiber Graf Schulte Dietrich Ziegler Kuhn Kühn Pohl Engel Horn Busch Bergmann Thomas Voigt Sauer
Arnold Wolff Pfeiffer Yılmaz Kaya Demir Şahin Çelik Yıldız Öztürk Aydın Özdemir Arslan Doğan Kılıç Kowalski Nowak
Wiśniewski Wójcik Kamiński Lewandowski Zieliński Iwanow Petrow Smirnow Popow Rossi Russo Ferrari Esposito Bianchi
Romano Colombo Haddad Khalil Hassan Ibrahim Nguyen Tran Pham García Fernández López Martínez Novak Horváth Kovač
Jansen Visser Dijkstra Bakker Petersen Nielsen Andersen Hansen Larsen Lindqvist Berg Eriksson""".split()
_CITIES = """Aachen Augsburg Bamberg Bielefeld Bochum Bonn Braunschweig Bremen Chemnitz Cottbus Darmstadt Dessau
Dortmund Dresden Duisburg Düsseldorf Erfurt Erlangen Essen Flensburg Frankfurt Freiburg Fulda Gera Gießen Göttingen
Greifswald Hagen Halle Hamburg Hamm Hannover Heidelberg Heilbronn Hildesheim Ingolstadt Jena Kaiserslautern
Karlsruhe Kassel Kiel Koblenz Köln Konstanz Krefeld Leipzig Lübeck Ludwigshafen Lüneburg Magdeburg Mainz Mannheim
Marburg Moers Münster Neuss Nürnberg Oldenburg Osnabrück Paderborn Passau Potsdam Regensburg Rostock Saarbrücken
Schwerin Siegen Solingen Stralsund Trier Tübingen Ulm Weimar Wiesbaden Wolfsburg Wuppertal Würzburg Zwickau""".split()
_FORMS = ("GmbH", "AG", "KG", "GbR", "UG", "OHG", "SE", "e.V.", "GmbH & Co. KG", "mbH")

# What an anonymized value looks like in the published decisions: initials, "K …", "B1", "...", "X".
_PLACEHOLDER = re.compile(r"^(?:[A-ZÄÖÜ][a-zäöü]?\d?\.?|[A-ZÄÖÜ]\d?\s?…|\.{3}|…)$")
_PLACEHOLDER_TOKEN = re.compile(r"^(?:[A-ZÄÖÜ]{1,3}\d?\.?|[A-ZÄÖÜ]\d?-|\.{3}|…)$")


@dataclass
class Sentence:
    tokens: list[str]
    tags: list[str]  # IOB2 with LER fine labels


def read_conll(lines: Iterable[str]) -> Iterator[Sentence]:
    toks: list[str] = []
    tags: list[str] = []
    for line in lines:
        line = line.rstrip("\n")
        if not line.strip():
            if toks:
                yield Sentence(toks, tags)
            toks, tags = [], []
            continue
        tok, tag = line.rsplit(" ", 1)
        toks.append(tok)
        tags.append(tag)
    if toks:
        yield Sentence(toks, tags)


def entities(s: Sentence) -> list[tuple[int, int, str]]:
    """(first token, end token exclusive, LER label) per entity."""
    out: list[tuple[int, int, str]] = []
    for i, tag in enumerate(s.tags):
        if tag.startswith("B-") or (tag.startswith("I-") and (not out or out[-1][1] != i or out[-1][2] != tag[2:])):
            out.append((i, i + 1, tag[2:]))
        elif tag.startswith("I-"):
            out[-1] = (out[-1][0], i + 1, out[-1][2])
    return out


class Names:
    """Synthetic values; ``held_out`` picks the half of every list that train never sees."""

    def __init__(self, seed: int, held_out: bool) -> None:
        pick = lambda xs: [x for i, x in enumerate(sorted(set(xs))) if (i % 2 == 1) == held_out]  # noqa: E731
        self.first, self.last, self.cities = pick(_FIRST), pick(_LAST), pick(_CITIES)
        self.rng = random.Random(seed)

    def person(self, after: str) -> str:
        # After a title or role ("Herrn", "Rechtsanwalt", "Dr.") a surname reads naturally; else 50:50.
        if re.search(r"(?:Herrn?|Frau|Dr\.|Prof\.|anwalt|anwältin|Richter(?:in)?|Zeugin|Zeuge)\s*$", after):
            return self.rng.choice(self.last)
        return self.rng.choice(self.last) if self.rng.random() < 0.4 else \
            f"{self.rng.choice(self.first)} {self.rng.choice(self.last)}"

    def company_stem(self) -> str:
        return self.rng.choice(self.last)

    def city(self) -> str:
        return self.rng.choice(self.cities)


def _fill(tokens: list[str], label: str, before: str, names: Names) -> list[str] | None:
    """Replacement tokens for an anonymized entity, or None to keep it as it is."""
    text = " ".join(tokens)
    if label in ("PER", "AN", "RR") and _PLACEHOLDER.match(text.replace('" ', "").replace(' "', "")):
        return names.person(before).split()
    if label in ("ST", "LDS") and _PLACEHOLDER.match(text):
        return [names.city()]
    if label == "UN":
        out: list[str] = []
        changed = in_run = False
        for t in tokens:
            if _PLACEHOLDER_TOKEN.match(t) and t not in _FORMS:
                # A run of letters ("D P T S GmbH") becomes one name, not four.
                if not in_run:
                    stem = names.company_stem()
                    out.append(stem + "-" if t.endswith("-") else stem)
                in_run = changed = True
                continue
            m = re.fullmatch(r"[A-ZÄÖÜ]-(GmbH|AG|KG|GbR|UG|Gruppe|Fonds|Werke)", t)  # "A-AG", "M-GmbH"
            out.append(f"{names.company_stem()}-{m.group(1)}" if m else t)
            changed = changed or bool(m)
            in_run = False
        return out if changed else None
    return None


_NO_SPACE_BEFORE = {".", ",", ";", ":", "!", "?", ")", "]", "“", "'", "%", "…"}
_NO_SPACE_AFTER = {"(", "[", "„", "‚"}


def detokenize(tokens: list[str]) -> tuple[str, list[tuple[int, int]]]:
    """Running text and the character span of every token."""
    parts: list[str] = []
    offsets: list[tuple[int, int]] = []
    pos = 0
    prev = None
    for t in tokens:
        space = bool(parts) and t not in _NO_SPACE_BEFORE and prev not in _NO_SPACE_AFTER
        if space:
            parts.append(" ")
            pos += 1
        offsets.append((pos, pos + len(t)))
        parts.append(t)
        pos += len(t)
        prev = t
    return "".join(parts), offsets


def sentence_doc(s: Sentence, names: Names | None) -> tuple[str, list[Span]]:
    """One sentence as text with gold spans; with ``names`` anonymized values get synthetic ones."""
    tokens: list[str] = []
    spans: list[tuple[int, int, str]] = []  # token index range in the new token list
    ents = {start: (end, label) for start, end, label in entities(s)}
    i = 0
    while i < len(s.tokens):
        if i in ents:
            end, label = ents[i]
            original = s.tokens[i:end]
            new = _fill(original, label, " ".join(tokens[-3:]), names) if names else None
            new = new or original
            spans.append((len(tokens), len(tokens) + len(new), LABEL_MAP.get(label, label)))
            tokens.extend(new)
            i = end
        else:
            tokens.append(s.tokens[i])
            i += 1
    text, offs = detokenize(tokens)
    return text, [Span(offs[a][0], offs[b - 1][1], label) for a, b, label in spans]


def build_docs(sentences: Iterable[Sentence], split: str, per_doc: int = 6, seed: int = 24,
               reinsert: bool = True) -> list[GoldDoc]:
    """Consecutive sentences (same decision, mostly) grouped into documents of ``per_doc`` sentences."""
    names = Names(seed, held_out=split != "train") if reinsert else None
    docs: list[GoldDoc] = []
    buf_text: list[str] = []
    buf_spans: list[Span] = []
    pos = 0

    def flush() -> None:
        nonlocal buf_text, buf_spans, pos
        if buf_text:
            docs.append(GoldDoc(f"ler:{split}:{len(docs)}", " ".join(buf_text), buf_spans, ["ler"], None, split))
        buf_text, buf_spans, pos = [], [], 0

    for n, s in enumerate(sentences):
        text, spans = sentence_doc(s, names)
        if buf_text:
            pos += 1  # the joining space
        buf_spans += [Span(sp.start + pos, sp.end + pos, sp.label) for sp in spans]
        buf_text.append(text)
        pos += len(text)
        if (n + 1) % per_doc == 0:
            flush()
    flush()
    return docs
