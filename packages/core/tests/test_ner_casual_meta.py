import json

from anonymizer.detect.ner import CATO, SpacyRecognizer, _casual_meta, model_label


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


def test_model_label(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"name": "cato", "version": "1.1.0"}), encoding="utf-8")
    assert model_label(str(tmp_path)) == "Cato 1.1"
    assert model_label("en_core_web_lg") == "en_core_web_lg"
    if (CATO / "meta.json").is_file():
        assert model_label(str(CATO)) == "Cato 1.1"
