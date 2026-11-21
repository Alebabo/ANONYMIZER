"""Mess-Kit für echte Kanzleitexte (scripts/local_eval.py), nur mit synthetischen Texten."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "local_eval.py"
_spec = importlib.util.spec_from_file_location("local_eval", SCRIPT)
le = importlib.util.module_from_spec(_spec)
sys.modules["local_eval"] = le
_spec.loader.exec_module(le)

TEXT = """Rechtsanwältin Dr. Erika Musterfrau
Hauptstraße 12, 10115 Berlin

In Sachen Hans Beispielmann ./. Kraftwerk Nord GmbH, Az.: 12 C 345/24
Der Kläger ist erreichbar unter hans.beispielmann@example.org oder 0221 1234567.
Vgl. BGH, Urteil vom 12.05.2021 - VI ZR 12/20; § 433 Abs. 2 BGB. Zahlung von 4.500,00 EUR.
"""


def run(*argv: str) -> int:
    return le.main(list(argv))


# ----------------------------------------------------------------------------- markup
def test_parse_markup_offsets_and_labels():
    doc = le.parse_markup("Frau [[ Erika Musterfrau |person]] wohnt in [[Ulm|Stadt]].")
    assert doc.errors == []
    assert doc.text == "Frau  Erika Musterfrau  wohnt in Ulm."
    assert [(doc.text[s.start:s.end], s.label) for s in doc.spans] == [("Erika Musterfrau", "PERSON"), ("Ulm", "ORT")]


def test_parse_markup_multiline_value():
    doc = le.parse_markup("[[Hauptstraße 12\n10115 Berlin|ADRESSE]] x")
    assert doc.text == "Hauptstraße 12\n10115 Berlin x"
    assert doc.spans[0].label == "ADRESSE" and doc.spans[0].end == len("Hauptstraße 12\n10115 Berlin")


@pytest.mark.parametrize("markup, needle", [
    ("Zeile eins\n[[Erika Musterfrau]] hier", "Zeile 2: unvollständige Markierung"),
    ("[[Erika Musterfrau|PERSN]]", "unbekannter Typ 'PERSN'"),
    ("Erika Musterfrau|PERSON]]", "unvollständige Markierung ']]'"),
])
def test_parse_markup_reports_errors_with_line(markup, needle):
    doc = le.parse_markup(markup)
    assert any(needle in e for e in doc.errors), doc.errors


def test_markup_round_trip_without_ner():
    from anonymizer.detect import Detector, DetectorConfig

    det = Detector(DetectorConfig(enable_ner=False))
    dets, _ = le.marked_detections(det, TEXT, "de")
    markup = le.to_markup(TEXT, dets)
    doc = le.parse_markup(markup)
    assert doc.errors == [] and doc.text == TEXT
    labels = {(TEXT[s.start:s.end], s.label) for s in doc.spans}
    assert ("hans.beispielmann@example.org", "EMAIL") in labels
    assert any(v.startswith("12 C 345/24") and lab == "AKTENZEICHEN" for v, lab in labels)
    marked = {v for v, _ in labels}
    # Public references, dates and amounts stay unmarked.
    assert not any(v in marked for v in ("VI ZR 12/20", "§ 433 Abs. 2 BGB", "4.500,00 EUR"))
    assert not any("BGH" in v for v in marked)


def test_brackets_in_source_text_are_loosened():
    markup = le.to_markup("Liste [[a]] und b|c", [])
    assert "[[" not in markup and le.parse_markup(markup).errors == []


def test_unmarked_repeats_hint():
    doc = le.parse_markup("[[Hans Beispielmann|PERSON]] schreibt. Hans Beispielmann zahlt.")
    hints = le.unmarked_repeats(doc)
    assert len(hints) == 1 and "Zeile 1" in hints[0]


# ----------------------------------------------------------------------------- scoring
class _Det:
    def __init__(self, text, value, entity_type, signals=()):
        self.start = text.index(value)
        self.end = self.start + len(value)
        self.entity_type = entity_type
        self.signals = signals


class _Result:
    def __init__(self, dets):
        self.detections = dets
        self.warnings = []


class _FakeDetector:
    """Predictions fixed by hand, so the metrics can be checked exactly."""

    class config:  # noqa: N801
        enable_ner = True

    def __init__(self, spec):
        self.spec = spec

    def scan(self, text, language=None):
        return _Result([_Det(text, v, t) for v, t in self.spec if v in text])


def test_score_counts_masked_partial_and_false_hits():
    doc = le.parse_markup("[[Erika Musterfrau|PERSON]] und [[Hans Beispielmann|PERSON]] bei "
                          "[[Kraftwerk Nord GmbH|FIRMA]] in Gericht.", "a.txt", "schriftsaetze")
    det = _FakeDetector([("Erika", "person"), ("Kraftwerk Nord GmbH", "location"), ("Gericht", "person"),
                         ("Gericht.", "court")])
    m, details, ner = le.score([doc], det, "de")
    p = m["typen"]["PERSON"]
    assert (p["markiert"], p["treffer"]) == (2, 2)
    assert p["verdeckt_recall"] == 0.5                 # Hans missed
    assert p["vollstaendig_verdeckt_recall"] == 0.0    # Erika only partly covered
    assert p["verdeckt_praezision"] == 0.5             # "Gericht" is a false hit
    f = m["typen"]["FIRMA"]
    assert f["verdeckt_recall"] == 1.0 and f["typ_genau"]["recall"] == 0.0  # hidden, but as a place
    assert m["gesamt"]["markiert"] == 3 and ner is True
    text = "\n".join(details)
    assert "VERPASST PERSON `Hans Beispielmann`" in text
    assert "TEILWEISE PERSON `Erika Musterfrau`" in text
    assert "FALSCHER TYP `Kraftwerk Nord GmbH`" in text
    assert "FALSCHER TREFFER PERSON `Gericht`" in text


def test_cited_case_number_is_not_marked():
    text = "BGH, Urteil vom 12.05.2021 - VI ZR 12/20"
    own = _Det(text, "VI ZR 12/20", "case_number")
    cited = _Det(text, "VI ZR 12/20", "case_number", signals=("case_law_citation",))
    assert le.label_of(own) == "AKTENZEICHEN" and le.label_of(cited) is None
    assert le.label_of(_Det(text, "BGH", "court")) is None
    assert le.label_of(_Det(text, "BGH", "license_plate")) == "NUMMER"


# ----------------------------------------------------------------------------- paths
def test_paths_inside_repo_must_be_under_ignored_local():
    with pytest.raises(le.KitError, match="nicht unter local/"):
        le.ensure_private(le.REPO / "docs" / "messung")
    with pytest.raises(le.KitError):
        le.ensure_private(le.REPO / "packages" / "core" / "tests" / "x.txt")
    assert le.ensure_private(le.REPO / "local" / "messung" / "x") == (le.REPO / "local" / "messung" / "x").resolve()


def test_commands_refuse_repo_paths_outside_local(tmp_path):
    assert run("setup", "--dokumente", str(le.REPO / "docs" / "kanzlei"), "--annotiert", str(tmp_path / "a"),
               "--ergebnis", str(tmp_path / "e")) == 2
    assert not (le.REPO / "docs" / "kanzlei").exists()


# ----------------------------------------------------------------------------- end to end
def _args(tmp_path: Path) -> list[str]:
    return ["--dokumente", str(tmp_path / "dok"), "--annotiert", str(tmp_path / "ann"),
            "--ergebnis", str(tmp_path / "erg"), "--bericht", str(tmp_path / "bericht.md"), "--ohne-ner"]


def test_end_to_end_report_has_numbers_only(tmp_path, capsys):
    a = _args(tmp_path)
    assert run("setup", *a) == 0
    (tmp_path / "dok" / "schriftsaetze").mkdir()
    (tmp_path / "dok" / "schriftsaetze" / "Klage_Beispielmann.txt").write_text(TEXT, encoding="utf-8")
    (tmp_path / "dok" / "Mandant Quast.txt").write_bytes(
        "Sehr geehrte Frau Quast,\r\nwir bestätigen Ihren Auftrag. Rückfragen: petra.quast@example.org\r\n".encode("cp1252"))
    assert run("annotate", *a) == 0
    ann = tmp_path / "ann" / "schriftsaetze" / "Klage_Beispielmann.txt.txt"
    assert ann.exists() and (tmp_path / "ann" / "LIESMICH.txt").exists()

    # The reader adds the names the rules missed (no NER in this test).
    markup = ann.read_text(encoding="utf-8")
    markup = markup.replace("Sachen Hans Beispielmann", "Sachen [[Hans Beispielmann|PERSON]]")
    if "[[Erika Musterfrau|PERSON]]" not in markup:
        markup = markup.replace("Erika Musterfrau", "[[Erika Musterfrau|PERSON]]")
    ann.write_text(markup, encoding="utf-8")
    assert run("check", *a) == 0

    # Annotations are kept: a second annotate does not overwrite them.
    assert run("annotate", *a) == 0
    assert ann.read_text(encoding="utf-8") == markup

    assert run("eval", *a) == 0
    metrics = json.loads((tmp_path / "erg" / "kennzahlen.json").read_text(encoding="utf-8"))
    assert metrics["dokumente"] == 2 and metrics["typen"]["PERSON"]["markiert"] >= 2
    assert metrics["ner_aktiv"] is False
    details = (tmp_path / "erg" / "details.md").read_text(encoding="utf-8")
    assert "Hans Beispielmann" in details  # missed values stay local

    capsys.readouterr()
    assert run("report", *a) == 0
    report = (tmp_path / "bericht.md").read_text(encoding="utf-8")
    for secret in ("Beispielmann", "Musterfrau", "Quast", "example.org", "12 C 345/24", "Klage", "Mandant",
                   "Hauptstraße", "0221"):
        assert secret not in report, secret
    assert "| PERSON |" in report and "schriftsaetze" in report
    assert "NER aktiv: NEIN" in report


def test_report_refuses_unknown_group_names_and_text_values(tmp_path):
    metrics = {
        "werkzeug": {"version": "0", "commit": "x"}, "modell": "m", "eigene_muster": 0, "ner_aktiv": True,
        "dokumente": 1, "zeichen": 1, "woerter": 1, "sekunden": 0.1,
        "gesamt": {"markiert": 1, "treffer": 1, "verdeckt_recall": 1.0, "vollstaendig_verdeckt_recall": 1.0,
                   "verdeckt_praezision": 1.0, "typ_genau": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
                   "typ_genau_streng": {}},
        "typen": {},
        "gruppen": {name: {"dokumente": 1, "markiert": 1, "verdeckt_recall": 1.0, "verdeckt_praezision": 1.0,
                           "person_markiert": 1, "person_verdeckt_recall": 1.0}
                    for name in ("Akte Beispielmann", "mails")},
    }
    report = le.render_report(metrics)
    assert "Beispielmann" not in report and "gruppe_1" in report and "| mails |" in report
    metrics["dokumente"] = "Hans Beispielmann"
    with pytest.raises(le.KitError):
        le.render_report(metrics)


def test_leaked_values_detects_marked_value():
    doc = le.parse_markup("[[Erika Musterfrau|PERSON]]")
    assert le.leaked_values("Bericht über Erika Musterfrau", [doc]) == ["PERSON"]
    assert le.leaked_values("| PERSON | 1 |", [doc]) == []


def test_docx_input(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("Sehr geehrte Frau Musterfrau,")
    d.add_paragraph("bitte überweisen Sie auf DE89 3704 0044 0532 0130 00.")
    path = tmp_path / "brief.docx"
    d.save(path)
    text, warnings = le.read_document(path)
    assert "Musterfrau" in text and "DE89" in text and warnings == []
