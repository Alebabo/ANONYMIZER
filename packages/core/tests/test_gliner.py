"""Optional GLiNER detector: runs with a fake model, so neither the gliner package nor weights are needed."""

import sys

import pytest

from anonymizer.detect import Detector, DetectorConfig
from anonymizer.detect import gliner_ner
from anonymizer.detect.engine import resolve_overlaps
from anonymizer.models import Category, EntityType as E, make_detection

FAKE = "fake/gliner"


class FakeModel:
    """Returns every listed (substring, label, score) found in a piece, like GLiNER.inference."""

    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def inference(self, texts, labels, threshold=0.5, flat_ner=True, batch_size=8):
        self.calls.append((list(texts), list(labels), threshold))
        out = []
        for t in texts:
            found = []
            for value, label, score in self.hits:
                i = t.find(value)
                if i >= 0 and label in labels and score >= threshold:
                    found.append({"start": i, "end": i + len(value), "text": value, "label": label, "score": score})
            out.append(found)
        return out


@pytest.fixture
def fake(monkeypatch):
    def install(hits):
        model = FakeModel(hits)
        monkeypatch.setitem(gliner_ner._MODEL_CACHE, FAKE, model)
        return model
    return install


def scan(text, **cfg):
    return Detector(DetectorConfig(enable_ner=False, **cfg)).scan(text, "de")


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("ANONYMIZER_GLINER_MODEL", raising=False)
    det = Detector(DetectorConfig(enable_ner=False))
    assert det._gliner is None
    assert not det.scan("Die Nordwind Logistik hat gekündigt.", "de").warnings


def test_env_enables(monkeypatch, fake):
    fake([("Nordwind Logistik", "company", 0.9)])
    monkeypatch.setenv("ANONYMIZER_GLINER_MODEL", FAKE)
    monkeypatch.setenv("ANONYMIZER_GLINER_TYPES", "PER,ORG")
    monkeypatch.setenv("ANONYMIZER_GLINER_THRESHOLD", "0.7")
    cfg = DetectorConfig(enable_ner=False)
    assert (cfg.gliner_model, cfg.gliner_types, cfg.gliner_threshold) == (FAKE, "PER,ORG", 0.7)
    det = Detector(cfg).scan("Die Nordwind Logistik hat gekündigt.", "de").detections
    assert [(d.entity_type, d.text, d.recognizer) for d in det] == [(E.ORGANIZATION, "Nordwind Logistik", "gliner")]


def test_adds_organization_with_threshold(fake):
    model = fake([("Nordwind Logistik", "company", 0.9), ("Blauhaus", "organization", 0.4)])
    res = scan("Die Nordwind Logistik und Blauhaus haben gekündigt.", gliner_model=FAKE, gliner_threshold=0.5)
    assert [d.text for d in res.detections if d.entity_type == E.ORGANIZATION] == ["Nordwind Logistik"]
    assert res.detections[0].attributes["score"] == "0.90"
    # All labels are prompted, also when only organisations are kept.
    assert set(model.calls[0][1]) >= {"person", "organization", "company", "location"}


def test_types_filter_persons_and_places(fake):
    fake([("Karl Brenner", "person", 0.95), ("Nordwind Logistik", "company", 0.9), ("Oberhausen", "location", 0.9)])
    text = "Karl Brenner arbeitet bei der Nordwind Logistik in Oberhausen."
    only_org = scan(text, gliner_model=FAKE, gliner_types="organization").detections
    assert {d.entity_type for d in only_org if d.recognizer == "gliner"} == {E.ORGANIZATION}
    union = scan(text, gliner_model=FAKE, gliner_types="person,organization,location").detections
    assert {(d.entity_type, d.text) for d in union} >= {
        (E.PERSON, "Karl Brenner"), (E.ORGANIZATION, "Nordwind Logistik"), (E.LOCATION, "Oberhausen")}


def test_rules_win_over_gliner(fake):
    # Courts and statutes found by the rules are never replaced by a GLiNER organisation.
    fake([("Landgericht Hamburg", "organization", 0.99), ("BGB", "organization", 0.9)])
    res = scan("Das Landgericht Hamburg hat nach § 823 BGB entschieden.", gliner_model=FAKE)
    assert not [d for d in res.detections if d.recognizer == "gliner"]
    assert {d.entity_type for d in res.detections} >= {E.COURT, E.LEGAL_CITATION}


def test_spacy_wins_over_gliner():
    spacy_per = make_detection(E.PERSON, Category.PERSONAL_DATA, 0, 12, "Karl Brenner", 0.8, "spacy_ner")
    gliner_org = make_detection(E.ORGANIZATION, Category.PERSONAL_DATA, 0, 20, "Karl Brenner Bau Ost", 0.6, "gliner")
    accepted, suppressed = resolve_overlaps([gliner_org, spacy_per])
    assert [d.recognizer for d in accepted] == ["spacy_ner"]
    assert [s.detection.recognizer for s in suppressed] == ["gliner"]


def test_noise_is_cleaned(fake):
    fake([("Beklagten", "person", 0.9), ("die Firma", "company", 0.9)])
    res = scan("Die Beklagten und die Firma zahlen.", gliner_model=FAKE, gliner_types="person,organization")
    assert not [d for d in res.detections if d.recognizer == "gliner"]


def test_missing_package_keeps_rules(monkeypatch):
    monkeypatch.setitem(sys.modules, "gliner", None)  # import fails
    res = scan("Herr Max Mustermann, IBAN DE89 3704 0044 0532 0130 00", gliner_model="not/installed")
    assert any("GLiNER disabled" in w for w in res.warnings)
    assert any(d.entity_type == E.IBAN for d in res.detections)


def test_chunks_keep_offsets():
    text = " ".join(f"Satz {i} endet hier." for i in range(300))
    parts = gliner_ner.chunks(text, max_words=50)
    assert len(parts) > 1
    for offset, piece in parts:
        assert text[offset:offset + len(piece)] == piece
        assert len(piece.split()) <= 50
    long_word_run = "wort " * 130
    assert all(len(p.split()) <= 50 for _, p in gliner_ner.chunks(long_word_run, max_words=50))


def test_long_text_offsets(fake):
    fake([("Nordwind Logistik", "company", 0.9)])
    text = "Vorrede ohne Namen. " * 200 + "Die Nordwind Logistik zahlt."
    det = [d for d in scan(text, gliner_model=FAKE).detections if d.recognizer == "gliner"]
    assert len(det) == 1 and text[det[0].start:det[0].end] == "Nordwind Logistik"


def test_parse_types():
    assert gliner_ner.parse_types("PER, org,unknown") == (E.PERSON, E.ORGANIZATION)
    assert gliner_ner.parse_types("") == ()
