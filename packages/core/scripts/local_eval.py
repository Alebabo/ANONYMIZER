"""Lokales Mess-Kit: Erkennungsqualität auf echten Kanzleitexten messen, offline und ohne Cloud.

    python packages/core/scripts/local_eval.py setup                 # Ordner anlegen, Schutz prüfen
    python packages/core/scripts/local_eval.py annotate              # Vorannotation durch die Erkennung
    python packages/core/scripts/local_eval.py check                 # Markierungen prüfen (nach dem Korrigieren)
    python packages/core/scripts/local_eval.py eval                  # Messen; Details nur lokal
    python packages/core/scripts/local_eval.py report                # Kennzahlen ohne Text, zum Weitergeben
    python packages/core/scripts/local_eval.py selbsttest            # Einrichtung prüfen, nur synthetische Texte

Ablauf (Anleitung: docs/local-eval.md):

1. Originale (.txt, .md, .docx, .pdf mit Textebene) nach local/messung/dokumente/ legen, optional in Unterordnern
   (z. B. schriftsaetze/, mails/), die im Bericht als Gruppen erscheinen.
2. ``annotate`` schreibt für jedes Dokument eine Textdatei nach local/messung/annotiert/, in der alles, was die
   Erkennung als schützenswert ansieht, so markiert ist: ``[[Max Mustermann|PERSON]]``.
3. Die berechtigte Person korrigiert diese Dateien in einem Texteditor: fehlende Werte einklammern, falsche
   Markierungen entfernen (Klammern und ``|TYP`` löschen, Wort stehen lassen), falschen Typ ändern.
4. ``eval`` lässt die Erkennung erneut über den (markierungsfreien) Text laufen und vergleicht. Verpasste und
   falsche Werte stehen mit Kontext in local/messung/ergebnis/details.md, nur auf diesem Gerät.
5. ``report`` erzeugt local/messung/bericht.md: nur Zahlen, keine Textausschnitte, keine Dateinamen.

Formatwahl: Inline-Markierung im Text statt JSONL mit Zeichenpositionen. Wer korrigiert, sieht jeden Wert in
seinem Zusammenhang, braucht nur einen Texteditor und kann keine Positionen verrechnen; Tippfehler in der
Markierung meldet ``check`` mit Zeilennummer. Gezählt wird jedes Vorkommen einzeln, weil die Erkennung jedes
Vorkommen einzeln finden muss.

Sicherheit: Alle Pfade müssen, wenn sie in einem Git-Repository liegen, unter ``local/`` liegen und von Git
ignoriert werden; sonst bricht das Skript ab. Das Skript nutzt kein Netzwerk. Gemessen wird mit
anonymizer.ner_dataset.score_doc (wie ler_data.py, überlappende Treffer zählen) und dem Maß "verdeckt" aus
finance_data.py (ein Wert gilt als geschützt, wenn irgendeine schützenswerte Erkennung ihn überlappt).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BASE = REPO / "local" / "messung"
CATO = REPO / "models" / "cato-1.1"
SELFTEST = REPO / "examples" / "local-eval"  # synthetic, already corrected annotations (committed)
SUFFIXES = (".txt", ".md", ".docx", ".pdf")

# Annotation labels (what a reader marks) and the detector types that belong to them.
LABEL_TYPES: dict[str, set[str]] = {
    "PERSON": {"person"},
    "FIRMA": {"organization"},
    "ORT": {"location"},
    "ADRESSE": {"address"},
    "EMAIL": {"email"},
    "TELEFON": {"phone"},
    "AKTENZEICHEN": {"case_number"},
    "GEBURTSDATUM": {"date_of_birth"},
    "BANK": {"iban", "bic", "credit_card"},
}
OTHER = "NUMMER"  # every other identifying detection: tax ids, customer numbers, plates, own patterns, ...
LABELS = (*LABEL_TYPES, OTHER)
ALIASES = {
    "NAME": "PERSON", "PERSONEN": "PERSON", "ORGANISATION": "FIRMA", "UNTERNEHMEN": "FIRMA", "ORG": "FIRMA",
    "STADT": "ORT", "ANSCHRIFT": "ADRESSE", "E-MAIL": "EMAIL", "MAIL": "EMAIL", "TEL": "TELEFON",
    "AZ": "AKTENZEICHEN", "IBAN": "BANK", "KONTO": "BANK", "ID": "NUMMER", "KENNUNG": "NUMMER",
}
# Detector types that stay readable under the legal-default policy (public references, dates, amounts) or are
# keywords rather than values (special categories, markers). They are neither marked nor scored.
NOT_MARKED = {"court", "legal_citation", "date", "money", "privilege_marker", "business_secret_marker",
              "health_data", "biometric_data", "special_category", "criminal_record"}
# Group names that may appear in the shareable report; any other folder name becomes "gruppe_N".
SAFE_GROUPS = {"schriftsaetze", "schriftsätze", "mails", "emails", "vertraege", "verträge", "gutachten", "briefe",
               "notizen", "protokolle", "urteile", "beschluesse", "beschlüsse", "vermerke", "sonstige", "alle"}

# Salutations and titles in front of a marked name. The detector leaves them readable, so they are cut off before
# scoring; otherwise a reader who marks "Dr. Erika Musterfrau" would see a fully hidden name counted as partial.
TITLES = re.compile(r"(?:(?:Herrn?|Frau|Dr\.|Prof\.|Dipl\.-[\wäöü]+\.?|med\.|jur\.|rer\.\s?nat\.|h\.\s?c\.|"
                    r"RAin|RA|Rechtsanwalt|Rechtsanwältin|Notar|Notarin)\s+)+", re.IGNORECASE)
# Characters that signal a broken text layer (missing font mapping in a PDF, wrong encoding).
BROKEN_CHARS = re.compile(r"[\ufffd\u25a0]|\(cid:\d+\)")

MARK = re.compile(r"\[\[(?P<value>(?:(?!\[\[|\]\]).)+?)\|(?P<label>[^\[\]|\n]+?)\]\]", re.S)


class KitError(Exception):
    """A problem the user must fix; printed without traceback."""


# ----------------------------------------------------------------------------- paths
def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def _existing_ancestor(path: Path) -> Path:
    while not path.exists():
        path = path.parent
    return path if path.is_dir() else path.parent


def ensure_private(path: Path) -> Path:
    """Refuse a path that could end up in a Git repository: inside a work tree it must lie under local/ and be
    ignored by Git. Outside any repository the path is accepted with a note."""
    path = path.resolve()
    anc = _existing_ancestor(path)
    top_run = _git("rev-parse", "--show-toplevel", cwd=anc)
    if top_run is None:  # git not installed: look for a .git folder ourselves
        top = next((p for p in (anc, *anc.parents) if (p / ".git").exists()), None)
    else:
        top = Path(top_run.stdout.strip()).resolve() if top_run.returncode == 0 else None
    if top is None:
        print(f"Hinweis: {path} liegt in keinem Git-Repository. Bitte selbst sicherstellen, dass dieser Ordner "
              "nicht synchronisiert oder geteilt wird.", file=sys.stderr)
        return path
    rel = path.relative_to(top)
    if not rel.parts or rel.parts[0] != "local":
        raise KitError(f"{path} liegt im Repository, aber nicht unter local/. Echte Texte und Ergebnisse dürfen "
                       f"nur unter {top / 'local'} liegen (von Git ignoriert).")
    if top_run is None:
        gi = top / ".gitignore"
        if not (gi.exists() and any(line.strip() in ("local/", "/local/", "local") for line in gi.read_text().splitlines())):
            raise KitError(f"local/ ist in {gi} nicht als ignoriert eingetragen. Abbruch.")
        print("Hinweis: Git ist nicht installiert; Schutz über .gitignore-Eintrag local/ geprüft.", file=sys.stderr)
        return path
    if _git("check-ignore", "-q", rel.as_posix(), cwd=top).returncode != 0:
        raise KitError(f"{rel} wird von Git nicht ignoriert. Eintrag 'local/' in .gitignore prüfen. Abbruch.")
    tracked = _git("ls-files", "--", rel.as_posix(), cwd=top).stdout.strip()
    if tracked:
        raise KitError(f"Unter {rel} sind Dateien in Git eingecheckt ({tracked.splitlines()[0]} ...). Abbruch.")
    return path


# ----------------------------------------------------------------------------- reading documents
def read_document(path: Path) -> tuple[str, list[str]]:
    """Text and warnings (e.g. PDF pages without text layer)."""
    suffix = path.suffix.lower()
    data = path.read_bytes()
    if suffix in (".txt", ".md"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")  # Windows editors
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text, _broken_text_warning(text)
    if suffix == ".pdf":
        try:
            import pypdf  # noqa: F401, PLC0415
        except ImportError as exc:
            raise KitError("PDF wird nicht unterstützt, weil das Paket 'pypdf' fehlt. Den Text bitte als .txt "
                           "speichern oder 'pip install pypdf' ausführen.") from exc
    if suffix == ".docx":
        try:
            import docx  # noqa: F401, PLC0415
        except ImportError as exc:
            raise KitError("DOCX wird nicht unterstützt, weil das Paket 'python-docx' fehlt.") from exc
    from anonymizer.documents import DocumentError, extract  # noqa: PLC0415

    try:
        ex = extract(data, path.name)
    except DocumentError as exc:
        raise KitError(f"{path.name}: nicht lesbar ({exc})") from exc
    return ex.text, [*ex.warnings, *_broken_text_warning(ex.text)]


def _broken_text_warning(text: str) -> list[str]:
    n = len(BROKEN_CHARS.findall(text))
    if not n:
        return []
    return [f"{n} unlesbare Zeichen (■, � oder (cid:..)). Die Textebene ist fehlerhaft, Namen mit Sonderzeichen "
            "werden falsch gemessen. Das Dokument besser als .txt speichern (Text kopieren) und das Original entfernen."]


def find_documents(src: Path) -> list[Path]:
    return sorted(p for p in src.rglob("*") if p.is_file() and p.suffix.lower() in SUFFIXES
                  and not p.name.startswith(("~$", ".")))


# ----------------------------------------------------------------------------- detection
def label_of(det) -> str | None:
    """Annotation label of a detection, or None if it stays readable (court, statute, date, ...)."""
    t = det.entity_type
    if t in NOT_MARKED:
        return None
    if t == "case_number" and "case_law_citation" in getattr(det, "signals", ()):
        return None  # number of a cited published decision: public, the policy keeps it
    return next((label for label, types in LABEL_TYPES.items() if t in types), OTHER)


def model_choice(choice: str) -> tuple[dict[str, str] | None, str]:
    """(ner_models for DetectorConfig, short name for the report)."""
    if choice == "standard":
        return None, "standard"
    legal_ok = (CATO / "ner" / "model").exists() and (CATO / "ner" / "model").stat().st_size > 100_000
    if choice == "recht" and not legal_ok:
        raise KitError(f"Modell Cato fehlt unter {CATO} (Git LFS: 'git lfs pull').")
    if legal_ok:
        return {"de": str(CATO), "en": "en_core_web_lg"}, "cato-1.1"
    print("Hinweis: Rechtsmodell nicht gefunden, es wird das Standardmodell verwendet.", file=sys.stderr)
    return None, "standard"


def make_detector(args: argparse.Namespace):
    from anonymizer.detect import Detector, DetectorConfig, load_custom_patterns  # noqa: PLC0415

    custom = load_custom_patterns(args.muster) if args.muster else []
    if args.ohne_ner:
        return Detector(DetectorConfig(enable_ner=False, custom_entities=custom)), "ohne NER", len(custom)
    models, name = model_choice(args.modell)
    return Detector(DetectorConfig(ner_models=models, custom_entities=custom)), name, len(custom)


def marked_detections(detector, text: str, language: str | None) -> tuple[list, bool]:
    """Detections to mark/score, sorted, without overlaps; plus whether NER ran."""
    result = detector.scan(text, language)
    ner_ok = detector.config.enable_ner and not any("NER" in w for w in result.warnings)
    out, end = [], -1
    for d in sorted(result.detections, key=lambda d: (d.start, -(d.end - d.start))):
        if label_of(d) is None or d.start < end:
            continue
        out.append(d)
        end = d.end
    return out, ner_ok


# ----------------------------------------------------------------------------- markup
@dataclass
class Annotated:
    name: str          # path relative to the annotation folder
    group: str
    text: str          # without markup
    spans: list        # anonymizer.ner_dataset.Span
    errors: list[str] = field(default_factory=list)


def to_markup(text: str, dets: list) -> str:
    """Text with ``[[value|LABEL]]`` around each detection. Brackets already in the text are loosened so they
    cannot be mistaken for markup."""
    out, pos = [], 0
    for d in dets:
        value = text[d.start:d.end]
        if "[[" in value or "]]" in value or "|" in value:
            continue
        out += [text[pos:d.start], f"[[{value}|{label_of(d)}]]"]
        pos = d.end
    out.append(text[pos:])
    return "".join(re.sub(r"\[\[|\]\]", lambda m: m.group()[0] + " " + m.group()[0], s) if i % 2 == 0 else s
                   for i, s in enumerate(out))


def _line(markup: str, pos: int) -> int:
    return markup.count("\n", 0, pos) + 1


def normalize_label(raw: str) -> str | None:
    label = raw.strip().upper().replace("Ä", "AE").replace("Ö", "OE").replace("Ü", "UE")
    label = ALIASES.get(label, label)
    return label if label in LABELS else None


def parse_markup(markup: str, name: str = "", group: str = "alle") -> Annotated:
    from anonymizer.ner_dataset import Span  # noqa: PLC0415

    parts: list[str] = []
    spans, errors = [], []
    length = pos = 0

    def plain(chunk: str, offset: int) -> None:
        nonlocal length
        for m in re.finditer(r"\[\[|\]\]", chunk):
            errors.append(f"Zeile {_line(markup, offset + m.start())}: unvollständige Markierung "
                          f"'{m.group()}' (Format: [[Wert|TYP]])")
        parts.append(chunk)
        length += len(chunk)

    for m in MARK.finditer(markup):
        plain(markup[pos:m.start()], pos)
        value = m.group("value")
        label = normalize_label(m.group("label"))
        if label is None:
            errors.append(f"Zeile {_line(markup, m.start())}: unbekannter Typ '{m.group('label').strip()}' "
                          f"(erlaubt: {', '.join(LABELS)})")
        lead = len(value) - len(value.lstrip())
        core = value.strip()
        title = TITLES.match(core) if label == "PERSON" else None
        if title and title.end() < len(core):
            lead += title.end()
            core = core[title.end():]
        if label and core:
            spans.append(Span(length + lead, length + lead + len(core), label))
        parts.append(value)
        length += len(value)
        pos = m.end()
    plain(markup[pos:], pos)
    return Annotated(name, group, "".join(parts), spans, errors)


def unmarked_repeats(doc: Annotated, limit: int = 20) -> list[str]:
    """Places where a marked value occurs again without a marking: often forgotten, sometimes right."""
    hints, seen = [], set()
    for s in doc.spans:
        value = doc.text[s.start:s.end]
        if len(value) < 3 or value in seen:
            continue
        seen.add(value)
        for m in re.finditer(rf"(?<!\w){re.escape(value)}(?!\w)", doc.text):
            if not any(m.start() < g.end and g.start < m.end() for g in doc.spans):
                hints.append(f"Zeile {_line(doc.text, m.start())}: '{value}' ({s.label}) steht hier ohne Markierung")
                if len(hints) >= limit:
                    return hints
    return hints


def group_of(rel: Path) -> str:
    return rel.parts[0] if len(rel.parts) > 1 else "alle"


def load_annotated(folder: Path) -> list[Annotated]:
    files = sorted(p for p in folder.rglob("*.txt") if p.is_file() and p.name != "LIESMICH.txt")
    if not files:
        raise KitError(f"Keine annotierten Dateien in {folder}. Zuerst 'annotate' ausführen.")
    docs = []
    for p in files:
        rel = p.relative_to(folder)
        markup = p.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        docs.append(parse_markup(markup, rel.as_posix(), group_of(rel)))
    return docs


# ----------------------------------------------------------------------------- scoring
def _rate(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def score(docs: list[Annotated], detector, language: str | None) -> tuple[dict, list[str], bool]:
    """Metrics (numbers only) and the local detail lines (with values)."""
    from anonymizer.ner_dataset import Span, score_doc, summarize  # noqa: PLC0415

    per_doc: dict[str, list] = {"strict": [], "partial": []}
    gold_n, masked, full, pred_n, pred_hit = Counter(), Counter(), Counter(), Counter(), Counter()
    groups: dict[str, dict] = {}
    details: list[str] = []
    ner_all = True
    chars = words = 0
    t0 = time.perf_counter()
    for doc in docs:
        dets, ner_ok = marked_detections(detector, doc.text, language)
        ner_all &= ner_ok
        chars += len(doc.text)
        words += len(doc.text.split())
        pred = [Span(d.start, d.end, label_of(d)) for d in dets]
        key = f"{doc.group}:{doc.name}"
        s, _, _ = score_doc(doc.spans, pred, partial=False, labels=LABELS)
        per_doc["strict"].append((key, s))
        s, fps, fns = score_doc(doc.spans, pred, partial=True, labels=LABELS)
        per_doc["partial"].append((key, s))
        g = groups.setdefault(doc.group, {"docs": 0, "gold": Counter(), "masked": Counter(), "pred": 0, "hit": 0})
        g["docs"] += 1
        lines: list[str] = []
        for gs in doc.spans:
            over = [p for p in pred if p.overlaps(gs)]
            covered = set()
            for p in over:
                covered.update(range(max(p.start, gs.start), min(p.end, gs.end)))
            gold_n[gs.label] += 1
            g["gold"][gs.label] += 1
            masked[gs.label] += bool(over)
            g["masked"][gs.label] += bool(over)
            full[gs.label] += len(covered) == gs.end - gs.start
            ctx = _context(doc.text, gs.start, gs.end)
            if not over:
                lines.append(f"- VERPASST {gs.label} `{doc.text[gs.start:gs.end]}` (Zeile {_line(doc.text, gs.start)}): {ctx}")
            elif len(covered) < gs.end - gs.start:
                lines.append(f"- TEILWEISE {gs.label} `{doc.text[gs.start:gs.end]}`, erkannt nur "
                             f"{', '.join(repr(doc.text[p.start:p.end]) for p in over)} (Zeile {_line(doc.text, gs.start)})")
            elif gs in fns:
                lines.append(f"- FALSCHER TYP `{doc.text[gs.start:gs.end]}`: markiert {gs.label}, erkannt "
                             f"{'/'.join(sorted({p.label for p in over}))} (Zeile {_line(doc.text, gs.start)})")
        for p in pred:
            pred_n[p.label] += 1
            hit = any(p.overlaps(gs) for gs in doc.spans)
            pred_hit[p.label] += hit
            g["pred"] += 1
            g["hit"] += hit
            if not hit:
                lines.append(f"- FALSCHER TREFFER {p.label} `{doc.text[p.start:p.end]}` (Zeile "
                             f"{_line(doc.text, p.start)}): {_context(doc.text, p.start, p.end)}")
        if lines:
            details += [f"\n## {doc.name}\n", *lines]
    partial, strict = summarize(per_doc["partial"], LABELS), summarize(per_doc["strict"], LABELS)

    def block(label: str | None) -> dict:
        keys = [label] if label else list(LABELS)
        sel = lambda c: sum(c[k] for k in keys)  # noqa: E731
        src_p = partial["labels"][label] if label else partial["micro"]
        src_s = strict["labels"][label] if label else strict["micro"]
        return {
            "markiert": sel(gold_n), "treffer": sel(pred_n),
            "verdeckt_recall": _rate(sel(masked), sel(gold_n)),
            "vollstaendig_verdeckt_recall": _rate(sel(full), sel(gold_n)),
            "verdeckt_praezision": _rate(sel(pred_hit), sel(pred_n)),
            "typ_genau": {k: src_p[k] for k in ("tp", "fp", "fn", "precision", "recall", "f1")},
            "typ_genau_streng": {k: src_s[k] for k in ("precision", "recall", "f1")},
        }

    metrics = {
        "dokumente": len(docs), "zeichen": chars, "woerter": words, "ner_aktiv": ner_all,
        "sekunden": round(time.perf_counter() - t0, 1),
        "gesamt": block(None),
        "typen": {label: block(label) for label in LABELS if gold_n[label] or pred_n[label]},
        "gruppen": {name: {
            "dokumente": g["docs"],
            "markiert": sum(g["gold"].values()),
            "verdeckt_recall": _rate(sum(g["masked"].values()), sum(g["gold"].values())),
            "verdeckt_praezision": _rate(g["hit"], g["pred"]),
            "person_markiert": g["gold"]["PERSON"],
            "person_verdeckt_recall": _rate(g["masked"]["PERSON"], g["gold"]["PERSON"]),
        } for name, g in sorted(groups.items())},
    }
    return metrics, details, ner_all


def _context(text: str, start: int, end: int, width: int = 50) -> str:
    return ("…" + text[max(0, start - width):end + width] + "…").replace("\n", " ")


# ----------------------------------------------------------------------------- report
def _fmt(v) -> str:
    return "–" if v is None else (f"{v:.3f}".replace(".", ",") if isinstance(v, float) else str(v))


def _num(v) -> float | int | bool | None:
    if v is None or isinstance(v, (bool, int, float)):
        return v
    raise KitError("Kennzahlen-Datei enthält unerwartete Werte; Bericht wird nicht erstellt.")


def render_report(m: dict) -> str:
    """Only whitelisted keys and numbers; labels and group names come from fixed lists."""
    g = m["gesamt"]
    person = m["typen"].get("PERSON")
    lines = [
        "# OpenAnonymizer: lokale Messung (nur Kennzahlen)", "",
        f"Erstellt: {dt.date.today().isoformat()}  ",
        f"Werkzeug: anonymizer-core {m['werkzeug']['version']}, Commit {m['werkzeug']['commit']}  ",
        f"Modell: {m['modell']}, NER aktiv: {'ja' if _num(m['ner_aktiv']) else 'NEIN'}, eigene Muster: {_num(m['eigene_muster'])}  ",
        f"Dokumente: {_num(m['dokumente'])}, Wörter: {_num(m['woerter'])}, markierte Werte: {_num(g['markiert'])}, "
        f"Treffer der Erkennung: {_num(g['treffer'])}", "",
        "Der Bericht enthält keine Textausschnitte, keine Werte und keine Dateinamen.", "",
        "## Personen", "",
    ]
    if person:
        lines += [f"- markiert: {_num(person['markiert'])}",
                  f"- verdeckt (Recall): {_fmt(_num(person['verdeckt_recall']))}",
                  f"- vollständig verdeckt: {_fmt(_num(person['vollstaendig_verdeckt_recall']))}",
                  f"- als Person erkannt: Präzision {_fmt(_num(person['typ_genau']['precision']))}, "
                  f"Recall {_fmt(_num(person['typ_genau']['recall']))}", ""]
    else:
        lines += ["- keine Personen markiert", ""]
    lines += ["## Alle Typen", "",
              "| Typ | markiert | Treffer | verdeckt R | vollst. R | verdeckt P | Typ P | Typ R | Typ F1 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for label, b in [("GESAMT", g), *[(k, m["typen"][k]) for k in LABELS if k in m["typen"]]]:
        t = b["typ_genau"]
        lines.append(f"| {label} | {_num(b['markiert'])} | {_num(b['treffer'])} | {_fmt(_num(b['verdeckt_recall']))} | "
                     f"{_fmt(_num(b['vollstaendig_verdeckt_recall']))} | {_fmt(_num(b['verdeckt_praezision']))} | "
                     f"{_fmt(_num(t['precision']))} | {_fmt(_num(t['recall']))} | {_fmt(_num(t['f1']))} |")
    if len(m["gruppen"]) > 1:
        lines += ["", "## Gruppen", "", "| Gruppe | Dokumente | markiert | verdeckt R | verdeckt P | Personen | Personen R |",
                  "|---|---|---|---|---|---|---|"]
        for i, (name, b) in enumerate(sorted(m["gruppen"].items()), 1):
            shown = name if name.lower() in SAFE_GROUPS else f"gruppe_{i}"
            lines.append(f"| {shown} | {_num(b['dokumente'])} | {_num(b['markiert'])} | {_fmt(_num(b['verdeckt_recall']))} | "
                         f"{_fmt(_num(b['verdeckt_praezision']))} | {_num(b['person_markiert'])} | "
                         f"{_fmt(_num(b['person_verdeckt_recall']))} |")
    lines += ["", "Begriffe: verdeckt R = Anteil der markierten Werte, die eine Erkennung überlappt (wären geschützt); "
              "vollst. R = ganz verdeckt; verdeckt P = Anteil der Treffer auf markierten Werten; "
              "Typ P/R/F1 = mit richtigem Typ (überlappend).", ""]
    return "\n".join(lines)


def leaked_values(report: str, docs: list[Annotated]) -> list[str]:
    """Marked values that occur in the report text (should never happen)."""
    found = []
    for d in docs:
        for s in d.spans:
            v = d.text[s.start:s.end].strip()
            if len(v) >= 3 and re.search(rf"(?<!\w){re.escape(v)}(?!\w)", report, re.IGNORECASE):
                found.append(s.label)
    return found


def _commit() -> str:
    r = _git("rev-parse", "--short", "HEAD", cwd=REPO)
    return r.stdout.strip() if r and r.returncode == 0 else "unbekannt"


# ----------------------------------------------------------------------------- commands
README = """So korrigieren Sie diese Dateien (Anleitung: docs/local-eval.md)

Jede Datei ist der Text eines Dokuments. Was die Erkennung schützen würde, ist so markiert:
    [[Max Mustermann|PERSON]]

1. Fehlender Wert: mit [[ und |TYP]] einklammern, z. B.  [[Erika Musterfrau|PERSON]]
2. Falsche Markierung: Klammern und |TYP löschen, das Wort selbst stehen lassen.
3. Falscher Typ: nur den Typ hinter dem senkrechten Strich ändern.
Jedes Vorkommen zählt einzeln: steht ein Name dreimal im Text, wird er dreimal markiert.
Gerichte, Gesetze, zitierte Urteile, Datumsangaben und Beträge werden NICHT markiert.

Typen: PERSON, FIRMA, ORT, ADRESSE, EMAIL, TELEFON, AKTENZEICHEN, GEBURTSDATUM, BANK, NUMMER
Den übrigen Text nicht ändern. Datei als UTF-8 speichern.
Danach prüfen: python packages/core/scripts/local_eval.py check
"""


def cmd_setup(args: argparse.Namespace) -> int:
    for p in (args.dokumente, args.annotiert, args.ergebnis):
        ensure_private(p).mkdir(parents=True, exist_ok=True)
    print(f"Bereit. Dokumente (.txt, .md, .docx, .pdf) hierher kopieren:\n  {args.dokumente.resolve()}\n"
          "Danach: python packages/core/scripts/local_eval.py annotate")
    return 0


def cmd_annotate(args: argparse.Namespace) -> int:
    src, dst = ensure_private(args.dokumente), ensure_private(args.annotiert)
    files = find_documents(src) if src.exists() else []
    if not files:
        raise KitError(f"Keine Dokumente in {src} ({', '.join(SUFFIXES)}).")
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "LIESMICH.txt").write_text(README, encoding="utf-8")
    detector, model, _ = make_detector(args)
    written = skipped = failed = 0
    ner_all = True
    for f in files:
        rel = f.relative_to(src)
        target = dst / rel.parent / f"{rel.name}.txt"
        if target.exists() and not args.neu:
            skipped += 1
            continue
        try:
            text, warnings = read_document(f)
        except KitError as exc:
            print(f"Übersprungen: {exc}", file=sys.stderr)
            failed += 1
            continue
        for w in warnings:
            print(f"Warnung {rel}: {w}", file=sys.stderr)
        dets, ner_ok = marked_detections(detector, text, args.sprache)
        ner_all &= ner_ok
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(to_markup(text, dets), encoding="utf-8")
        written += 1
    print(f"Modell: {model}. Vorannotiert: {written}, schon vorhanden (nicht überschrieben): {skipped}, "
          f"nicht lesbar: {failed}.\nJetzt die Dateien in {dst} korrigieren (siehe LIESMICH.txt), dann 'check'.")
    if not ner_all:
        print("WARNUNG: Die Namenserkennung (NER) lief nicht; es fehlen deshalb viele Namen.", file=sys.stderr)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    docs = load_annotated(ensure_private(args.annotiert))
    bad = 0
    for d in docs:
        hints = unmarked_repeats(d)
        if d.errors or hints:
            print(f"\n{d.name}")
        for e in d.errors:
            print(f"  FEHLER  {e}")
        for h in hints:
            print(f"  Hinweis {h}")
        bad += bool(d.errors)
    counts = Counter(s.label for d in docs for s in d.spans)
    print(f"\n{len(docs)} Dateien, {bad} mit Fehlern. Markiert: {dict(counts.most_common())}")
    print("Hinweise sind keine Fehler: bitte nur prüfen, ob die Stelle markiert werden muss.")
    return 1 if bad else 0


def cmd_eval(args: argparse.Namespace) -> int:
    docs = load_annotated(ensure_private(args.annotiert))
    out = ensure_private(args.ergebnis)
    if any(d.errors for d in docs):
        raise KitError("Die Markierungen enthalten Fehler. Zuerst 'check' ausführen und korrigieren.")
    import anonymizer  # noqa: PLC0415

    detector, model, n_custom = make_detector(args)
    metrics, details, ner_ok = score(docs, detector, args.sprache)
    metrics = {"werkzeug": {"version": anonymizer.__version__, "commit": _commit()}, "modell": model,
               "eigene_muster": n_custom, **metrics}
    out.mkdir(parents=True, exist_ok=True)
    (out / "kennzahlen.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "details.md").write_text("# Verpasste und falsche Werte (VERTRAULICH, nur auf diesem Gerät)\n"
                                    + "\n".join(details) + "\n", encoding="utf-8")
    g, p = metrics["gesamt"], metrics["typen"].get("PERSON")
    print(f"{metrics['dokumente']} Dokumente, {g['markiert']} markierte Werte, Modell {model}")
    print(f"Alle Typen: verdeckt {_fmt(g['verdeckt_recall'])} (Recall), Präzision {_fmt(g['verdeckt_praezision'])}")
    if p:
        print(f"Personen:   verdeckt {_fmt(p['verdeckt_recall'])}, vollständig {_fmt(p['vollstaendig_verdeckt_recall'])}, "
              f"als Person P {_fmt(p['typ_genau']['precision'])} R {_fmt(p['typ_genau']['recall'])}")
    for label, b in metrics["typen"].items():
        print(f"  {label:13} markiert {b['markiert']:4}  Treffer {b['treffer']:4}  verdeckt R {_fmt(b['verdeckt_recall'])}"
              f"  P {_fmt(b['verdeckt_praezision'])}")
    print(f"Einzelheiten (mit Textstellen, nicht weitergeben): {out / 'details.md'}\n"
          "Bericht zum Weitergeben: python packages/core/scripts/local_eval.py report")
    if not ner_ok:
        print("WARNUNG: Die Namenserkennung (NER) lief nicht. Die Zahlen sind nicht aussagekräftig.", file=sys.stderr)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    src = ensure_private(args.ergebnis) / "kennzahlen.json"
    target = ensure_private(args.bericht)
    if not src.exists():
        raise KitError(f"{src} fehlt. Zuerst 'eval' ausführen.")
    report = render_report(json.loads(src.read_text(encoding="utf-8")))
    annot = ensure_private(args.annotiert)
    if annot.exists():
        leaked = leaked_values(report, load_annotated(annot))
        if leaked:
            raise KitError(f"Der Bericht enthielte {len(leaked)} markierte Werte ({', '.join(sorted(set(leaked)))}). "
                           "Er wurde nicht geschrieben. Bitte dem Entwicklerteam nur diese Meldung schicken.")
    else:
        print("Hinweis: annotierte Dateien nicht gefunden; Gegenprüfung auf Werte entfällt.", file=sys.stderr)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8")
    print(report)
    print(f"Geschrieben: {target}\nDiese Datei enthält nur Zahlen und kann an das Entwicklerteam gehen. "
          "Bitte vor dem Versand einmal lesen.")
    return 0


def cmd_selbsttest(args: argparse.Namespace) -> int:
    """Check the installation on synthetic, already corrected documents. Writes nothing."""
    docs = load_annotated(SELFTEST)
    detector, model, _ = make_detector(args)
    m, _, ner_ok = score(docs, detector, args.sprache)
    g, p = m["gesamt"], m["typen"].get("PERSON", {})
    print(f"Selbsttest mit {len(docs)} synthetischen Dokumenten ({SELFTEST.relative_to(REPO)}), Modell {model}")
    print(f"Alle Typen: verdeckt {_fmt(g['verdeckt_recall'])}, Präzision {_fmt(g['verdeckt_praezision'])}; "
          f"Personen verdeckt {_fmt(p.get('verdeckt_recall'))}; {m['sekunden']} s")
    problems = []
    if args.ohne_ner:
        problems.append("Mit --ohne-ner gestartet; die Namenserkennung wurde nicht geprüft.")
    elif not ner_ok:
        problems.append("Die Namenserkennung (NER) lief nicht: spaCy-Modell de_core_news_lg fehlt "
                        "(python -m spacy download de_core_news_lg).")
    if not args.ohne_ner and args.modell != "standard" and model == "standard":
        problems.append("Das Rechtsmodell fehlt (git lfs pull). Gemessen würde nur das Standardmodell.")
    if ner_ok and (p.get("verdeckt_recall") or 0) < SELFTEST_MIN_PERSON_RECALL:
        problems.append(f"Personen-Recall unter {SELFTEST_MIN_PERSON_RECALL}: Einrichtung prüfen "
                        "(Modellversion, Git-LFS-Dateien).")
    for msg in problems:
        print(f"PROBLEM: {msg}", file=sys.stderr)
    if problems:
        return 1
    print("Einrichtung in Ordnung. Die Messung an echten Texten kann beginnen (Schritt 1 in docs/local-eval.md).")
    return 0


SELFTEST_MIN_PERSON_RECALL = 0.7


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["setup", "annotate", "check", "eval", "report", "selbsttest"])
    ap.add_argument("--dokumente", type=Path, default=BASE / "dokumente", help="Originale (Standard: local/messung/dokumente)")
    ap.add_argument("--annotiert", type=Path, default=BASE / "annotiert", help="markierte Textdateien")
    ap.add_argument("--ergebnis", type=Path, default=BASE / "ergebnis", help="Kennzahlen und Details (lokal)")
    ap.add_argument("--bericht", type=Path, default=BASE / "bericht.md", help="Bericht zum Weitergeben")
    ap.add_argument("--modell", choices=["auto", "recht", "standard"], default="auto",
                    help="NER-Modell: recht = Cato 1.1 (Standard, wenn vorhanden)")
    ap.add_argument("--muster", type=Path, default=None, help="eigene Muster (YAML), z. B. local/patterns.yaml")
    ap.add_argument("--sprache", default="de", help="de, en oder auto (Standard: de)")
    ap.add_argument("--ohne-ner", action="store_true", help="nur Regeln (schnell, für Tests)")
    ap.add_argument("--neu", action="store_true", help="annotate: vorhandene annotierte Dateien überschreiben")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.sprache == "auto":
        args.sprache = None
    commands = {"setup": cmd_setup, "annotate": cmd_annotate, "check": cmd_check, "eval": cmd_eval,
                "report": cmd_report, "selbsttest": cmd_selbsttest}
    try:
        return commands[args.cmd](args)
    except KitError as exc:
        print(f"Abbruch: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
