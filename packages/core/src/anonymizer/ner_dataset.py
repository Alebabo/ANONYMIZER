"""Gold data for the spaCy NER model: build a span-annotated set and measure NER against it.

Raw texts (JSONL, one ``{"source", "db_id", "md5", "text"}`` per line) and annotations live outside the
repository (``local/ner``); see ``local/ner/README.md`` there. Annotations name entities by their surface
text, offsets are computed here, so a hand-written offset can never be off by one.

Labels: PER, ORG, LOC are scored. ADDR marks postal addresses; they belong to the rule-based address
recognizer, so NER predictions overlapping an ADDR span are neither right nor wrong. Own brands
(``keep`` terms, e.g. ACME) are never labelled and predictions starting with them are ignored, like the
pipeline does.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCORED = ("PER", "ORG", "LOC")
IGNORED = ("ADDR",)
LABELS = SCORED + IGNORED
DEFAULT_KEEP = ("ACME", "ACMECOMPARE")
# Raw files and the document source they hold. Chat samples share one table, so the same message can be in
# both chat subsets; it is kept once.
RAW_FILES = {"mail": "mail", "chat_cand": "chat", "chat_random": "chat", "assistant": "assistant",
             "int_mail": "intmail", "int_chat": "intchat", "testrun": "run",
             "mail_more": "mail", "chat_more": "chat", "int_chat_more": "intchat", "handmade": "hand"}
# Sources written as a clean holdout: always in the test split, never used for training or tuning.
TEST_ONLY = {"hand"}


class AnnotationError(ValueError):
    pass


@dataclass
class Span:
    start: int
    end: int
    label: str

    def overlaps(self, other: Span) -> bool:
        return self.start < other.end and other.start < self.end


@dataclass
class GoldDoc:
    key: str
    text: str
    spans: list[Span]
    subsets: list[str] = field(default_factory=list)
    review: str | None = None
    split: str = ""

    @property
    def source(self) -> str:
        return self.key.split(":", 1)[0]


_HEADER = re.compile(r"^(?:Subject|Betreff|Body):.*$", re.MULTILINE)


def group_key(text: str) -> str:
    """Near-duplicates share a key: the same mail with another subject line, other whitespace or case, or sent
    again on another stage. They must land in the same split, or the test set leaks into training."""
    body = _HEADER.sub("", text).lower()
    return re.sub(r"[^a-zäöüß]", "", body)[:400]


def split_of(text: str) -> str:
    """Deterministic split by group: 50 % test, 25 % dev, 25 % train."""
    bucket = int(hashlib.md5(group_key(text).encode("utf-8")).hexdigest(), 16) % 100
    return "test" if bucket < 50 else "dev" if bucket < 75 else "train"


def load_raw(raw_dir: Path) -> dict[str, dict]:
    docs: dict[str, dict] = {}
    for name, source in RAW_FILES.items():
        path = raw_dir / f"{name}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            key = f"{source}:{row['db_id']}"
            doc = docs.setdefault(key, {"key": key, "text": row["text"], "subsets": []})
            if doc["text"] != row["text"]:
                raise AnnotationError(f"{key}: same id, different text in {name}")
            doc["subsets"].append(name)
    return docs


def _occurrences(text: str, surface: str) -> list[int]:
    pattern = re.compile(rf"(?<!\w){re.escape(surface)}(?!\w)")
    return [m.start() for m in pattern.finditer(text)]


def resolve(text: str, entries: Iterable[list], required: bool, key: str = "") -> list[Span]:
    """Place surface-text annotations. Longest first; an occurrence overlapping a placed span is skipped
    ("Becker" inside "Kanzlei Becker & Partner"). ``required`` entries must be placed at least once."""
    placed: list[Span] = []
    ordered = sorted(entries, key=lambda e: -len(e[1]))
    for entry in ordered:
        label, surface = entry[0], entry[1]
        wanted = entry[2] if len(entry) > 2 else None
        if label not in LABELS:
            raise AnnotationError(f"{key}: unknown label {label!r}")
        if not surface or surface != surface.strip():
            raise AnnotationError(f"{key}: surface text must be non-empty without outer spaces: {surface!r}")
        found = _occurrences(text, surface)
        if wanted is not None:
            if any(i < 0 or i >= len(found) for i in wanted):
                raise AnnotationError(f"{key}: occurrence index out of range for {surface!r} ({len(found)} found)")
            found = [found[i] for i in wanted]
        hits = 0
        for start in found:
            span = Span(start, start + len(surface), label)
            if any(span.overlaps(p) for p in placed):
                if wanted is not None:
                    raise AnnotationError(f"{key}: requested occurrence of {surface!r} overlaps another span")
                continue
            placed.append(span)
            hits += 1
        if required and not hits:
            raise AnnotationError(f"{key}: {surface!r} not found as a separate word")
    return sorted(placed, key=lambda s: s.start)


def build(raw_dir: Path, annotation_file: Path) -> list[GoldDoc]:
    raw = load_raw(raw_dir)
    ann = json.loads(annotation_file.read_text(encoding="utf-8"))
    unknown = sorted(set(ann.get("docs", {})) - set(raw)) + sorted(set(ann.get("review", {})) - set(raw)) \
        + sorted(set(ann.get("exclude", {})) - set(raw))
    if unknown:
        raise AnnotationError(f"annotations for unknown documents: {unknown}")
    gold = []
    excluded = ann.get("exclude", {})
    for key in sorted(raw, key=lambda k: (k.split(":")[0], int(k.split(":")[1]))):
        if key in excluded:
            continue
        doc = raw[key]
        own = resolve(doc["text"], ann.get("docs", {}).get(key, []), required=True, key=key)
        glob = resolve(doc["text"], ann.get("global", []), required=False, key=key)
        spans = own + [g for g in glob if not any(g.overlaps(o) for o in own)]
        gold.append(GoldDoc(key, doc["text"], sorted(spans, key=lambda s: s.start), doc["subsets"],
                            ann.get("review", {}).get(key),
                            "test" if key.split(":")[0] in TEST_ONLY else split_of(doc["text"])))
    return gold


def write_gold(docs: list[GoldDoc], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for d in docs:
            f.write(json.dumps({
                "key": d.key, "split": d.split, "subsets": d.subsets, "review": d.review, "text": d.text,
                "spans": [{"start": s.start, "end": s.end, "label": s.label, "text": d.text[s.start:s.end]}
                          for s in d.spans],
            }, ensure_ascii=False) + "\n")


def read_gold(path: Path) -> list[GoldDoc]:
    docs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        spans = [Span(s["start"], s["end"], s["label"]) for s in row["spans"]]
        for s, raw in zip(spans, row["spans"]):
            if row["text"][s.start:s.end] != raw["text"]:
                raise AnnotationError(f"{row['key']}: span text mismatch at {s.start}")
        docs.append(GoldDoc(row["key"], row["text"], spans, row.get("subsets", []), row.get("review"),
                            row.get("split", "")))
    return docs


# ----------------------------------------------------------------------------- scoring
def keep_pattern(terms: Iterable[str]) -> re.Pattern | None:
    terms = [re.escape(t) for t in terms if t.strip()]
    return re.compile(rf"^(?:{'|'.join(terms)})(?![^\W_])", re.IGNORECASE) if terms else None


def relevant(pred: Span, text: str, gold: list[Span], keep: re.Pattern | None) -> bool:
    """Predictions on addresses or own brands are not scored."""
    if any(g.label in IGNORED and pred.overlaps(g) for g in gold):
        return False
    return not (keep and keep.match(text[pred.start:pred.end]))


@dataclass
class Score:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def add(self, other: Score) -> None:
        self.tp, self.fp, self.fn = self.tp + other.tp, self.fp + other.fp, self.fn + other.fn

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)


def score_doc(gold: list[Span], pred: list[Span], partial: bool,
              labels: Iterable[str] = SCORED) -> tuple[dict[str, Score], list[Span], list[Span]]:
    """Per-label counts plus the false positives and false negatives. Strict: same start, end and label.
    Partial: same label and overlapping; each gold span and each prediction is matched once.
    ``labels``: the scored gold labels (default PER, ORG, LOC); predictions must carry one of them."""
    labels = tuple(labels)
    scored = [g for g in gold if g.label in labels]
    used: set[int] = set()
    fps = []
    for p in sorted(pred, key=lambda s: (s.start, s.end)):
        match = next((i for i, g in enumerate(scored) if i not in used and g.label == p.label
                      and ((g.start, g.end) == (p.start, p.end) if not partial else g.overlaps(p))), None)
        if match is None:
            fps.append(p)
        else:
            used.add(match)
    fns = [g for i, g in enumerate(scored) if i not in used]
    out = {label: Score() for label in labels}
    for i, g in enumerate(scored):
        if i in used:
            out[g.label].tp += 1
    for p in fps:
        out[p.label].fp += 1
    for g in fns:
        out[g.label].fn += 1
    return out, fps, fns


def summarize(per_doc: list[tuple[str, dict[str, Score]]], labels: Iterable[str] = SCORED) -> dict[str, Any]:
    total: dict[str, Score] = {label: Score() for label in labels}
    by_source: dict[str, Score] = {}
    for key, scores in per_doc:
        src = key.split(":", 1)[0]
        for label, s in scores.items():
            total[label].add(s)
            by_source.setdefault(src, Score()).add(s)
    micro = Score()
    for s in total.values():
        micro.add(s)

    def fmt(s: Score) -> dict[str, Any]:
        r = lambda v: None if v is None else round(v, 3)  # noqa: E731
        return {"tp": s.tp, "fp": s.fp, "fn": s.fn, "precision": r(s.precision), "recall": r(s.recall),
                "f1": r(s.f1)}

    return {"micro": fmt(micro), "labels": {k: fmt(v) for k, v in total.items()},
            "sources": {k: fmt(v) for k, v in sorted(by_source.items())}}


def label_counts(docs: list[GoldDoc]) -> Counter:
    return Counter(s.label for d in docs for s in d.spans)
