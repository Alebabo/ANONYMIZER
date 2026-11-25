import json

from anonymizer.detect.ner import SpacyRecognizer, _casual_meta


def test_casual_meta_reads_flag(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"anonymizer": {"casual": True}}), encoding="utf-8")
    assert _casual_meta(str(tmp_path))
    assert SpacyRecognizer(models={"de": str(tmp_path)})._casual == {"de"}


def test_casual_meta_absent(tmp_path):
    assert not _casual_meta("de_core_news_lg")
    (tmp_path / "meta.json").write_text(json.dumps({"name": "core_news_md"}), encoding="utf-8")
    assert not _casual_meta(str(tmp_path))
    (tmp_path / "meta.json").write_text("[]", encoding="utf-8")
    assert not _casual_meta(str(tmp_path))
