"""Optional newmean-pii detector: runs with a fake redactor, so neither the package nor model files are needed."""

from types import SimpleNamespace

import pytest

from anonymizer.detect import Detector, DetectorConfig
from anonymizer.detect import newmean_ner
from anonymizer.models import EntityType as E


class FakeRedactor:
    """Returns a span for every listed (substring, label) found in the text, like Redactor.detect."""

    def __init__(self, hits):
        self.hits = hits

    def detect(self, text):
        out = []
        for value, label in self.hits:
            i = text.find(value)
            if i >= 0:
                out.append(SimpleNamespace(start=i, end=i + len(value), label=label, source="model"))
        return sorted(out, key=lambda s: s.start)


@pytest.fixture
def fake(monkeypatch):
    def install(hits, size="medium", labels=None, sensitivity=0.0):
        key = (size, None, sensitivity, newmean_ner.parse_labels(labels))
        monkeypatch.setitem(newmean_ner._MODEL_CACHE, key, FakeRedactor(hits))
    return install


def scan(text, **cfg):
    return Detector(DetectorConfig(enable_ner=False, **cfg)).scan(text, "de")


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("ANONYMIZER_NEWMEAN_MODEL", raising=False)
    det = Detector(DetectorConfig(enable_ner=False))
    assert det._newmean is None


def test_env_enables(monkeypatch, fake):
    fake([("Nordlicht", "PERSON")])
    monkeypatch.setenv("ANONYMIZER_NEWMEAN_MODEL", "Medium")
    cfg = DetectorConfig(enable_ner=False)
    assert cfg.newmean_model == "medium"
    det = Detector(cfg)
    assert det._newmean is not None and det._newmean.size == "medium"
    result = det.scan("Gruß von Nordlicht", "de")
    assert ("person", "Nordlicht") in {(e.entity_type, e.text) for e in result.detections}


def test_label_mapping(fake):
    fake([("Anna Berger", "PERSON"), ("X7Q-88231", "ID_NUMBER"), ("anna_b", "USERNAME"), ("pw-Hx9!", "SECRET")])
    rec = newmean_ner.NewmeanRecognizer("medium")
    got = {(d.text, d.entity_type, d.recognizer) for d in rec.analyze("Anna Berger X7Q-88231 anna_b pw-Hx9!", "de")}
    assert got == {("Anna Berger", "person", "newmean"), ("X7Q-88231", "id_number", "newmean"),
                   ("anna_b", "username", "newmean"), ("pw-Hx9!", "secret", "newmean")}


def test_rules_win_overlap(fake):
    fake([("DE89 3704 0044 0532 0130 00", "FINANCIAL")])
    result = scan("IBAN DE89 3704 0044 0532 0130 00 bitte", newmean_model="medium")
    iban = [e for e in result.detections if "DE89" in e.text]
    assert len(iban) == 1 and iban[0].entity_type == E.IBAN and iban[0].recognizer != "newmean"


def test_stopwords_filtered(fake):
    fake([("Hallo", "PERSON")])
    result = scan("Hallo, wie geht es?", newmean_model="medium")
    assert not [e for e in result.detections if e.recognizer == "newmean"]


def test_label_filter():
    assert newmean_ner.parse_labels("person, org,unknown") == ("PERSON", "ORG")
    assert newmean_ner.parse_labels("") == tuple(newmean_ner.LABELS)


def test_unknown_size_warns():
    result = scan("Anna Berger", newmean_model="huge")
    assert any("newmean disabled" in w for w in result.warnings)


def test_disabled_recognizer(fake):
    fake([("Anna Berger", "PERSON")])
    det = Detector(DetectorConfig(enable_ner=False, newmean_model="medium", disabled_recognizers=["newmean"]))
    assert det._newmean is None
