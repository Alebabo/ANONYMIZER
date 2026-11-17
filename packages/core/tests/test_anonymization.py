import json
import os
import stat

import pytest

from anonymizer import scan
from anonymizer.anonymize import (
    Anonymizer, AnonymizerConfig, LeakError, Method, build_diff, restore,
)
from anonymizer.anonymize.transforms import generalize, mask
from anonymizer.models import Category, make_detection
from anonymizer.vault import FileVault, InMemoryVault, VaultError, VaultKey

LETTER = (
    "Unser Mandant Herr Max Mustermann, geb. 15.03.1985, wohnt in der Lindenstraße 12, 10115 Berlin.\n"
    "IBAN DE89 3704 0044 0532 0130 00. Später erschien Mustermann persönlich.\n\n"
    "Die Zeugin Frau Erika Musterfrau (erika@example.org) bestätigte dies."
)
SECRETS = ["Max Mustermann", "Mustermann", "15.03.1985", "Lindenstraße", "DE89 3704", "Erika Musterfrau",
           "erika@example.org"]


@pytest.fixture
def vault():
    return InMemoryVault(VaultKey.generate())


def anonymize(text, vault=None, namespace=None, **cfg):
    return Anonymizer(AnonymizerConfig(**cfg), vault=vault).anonymize(text, scan(text, "de"), namespace=namespace)


# --- methods -------------------------------------------------------------------

def test_default_methods_and_no_secrets_in_output(vault):
    r = anonymize(LETTER, vault, "matter-1")
    for s in SECRETS:
        assert s not in r.text
    assert "PERSON_001" in r.text and "PERSON_002" in r.text
    assert "[REDACTED]" in r.text  # IBAN
    assert "geb. 1985" in r.text     # DOB generalized to year
    assert r.leaks == [] and r.reversible


def test_same_person_same_placeholder_within_document(vault):
    r = anonymize(LETTER, vault, "matter-1")
    persons = [t for t in r.transformations if t.entity_type == "person"]
    by_ref = {}
    for t in persons:
        by_ref.setdefault(t.attributes["ref"], set()).add(t.replacement)
    assert all(len(v) == 1 for v in by_ref.values())
    assert r.text.count("PERSON_001") == 2  # "Max Mustermann" and "Mustermann"


def test_consistent_across_documents_in_namespace(vault):
    a = anonymize("Herr Max Mustermann klagt.", vault, "matter-1")
    b = anonymize("Gegen Herrn Erika Beispiel und Herrn Max Mustermann.", vault, "matter-1")
    assert "PERSON_001" in a.text
    assert "PERSON_001" in b.text and "PERSON_002" in b.text


def test_namespaces_are_isolated(vault):
    a = anonymize("Herr Max Mustermann klagt.", vault, "matter-1")
    anonymize("Herr Paul Fiktiv klagt.", vault, "matter-2")
    assert restore(a.text, vault, "matter-1").text == "Herr Max Mustermann klagt."
    assert restore(a.text, vault, "matter-2").text == "Herr Paul Fiktiv klagt."  # different mapping
    assert restore("PERSON_001", vault, "matter-2").text == "Paul Fiktiv"
    assert restore("PERSON_001", vault, "matter-1").text == "Max Mustermann"
    assert restore("PERSON_001", vault, "matter-3").unresolved == ["PERSON_001"]


def test_replace_numbers_occurrences_without_linkage():
    r = anonymize("Herr Max Mustermann und später Mustermann.", methods={"person": Method.REPLACE})
    assert "PERSON_001" in r.text and "PERSON_002" in r.text and not r.reversible


def test_redaction_with_type():
    r = anonymize("IBAN DE89 3704 0044 0532 0130 00", redaction_with_type=True)
    assert r.text == "IBAN [REDACTED:IBAN]"


def test_mask_and_generalize_helpers():
    assert mask("DE89 3704 0044 0532 0130 00", "iban") == "DE89 **** **** **** **30 00"
    assert mask("4111 1111 1111 1111", "credit_card") == "**** **** **** 1111"
    assert mask("erika@example.org", "email") == "e***@example.org"
    assert generalize("15.03.1985", "date_of_birth") == "1985"
    assert generalize("Lindenstraße 12, 10115 Berlin", "address") == "Berlin"
    assert generalize("4.850,00 EUR", "money") == "1.000–10.000 EUR"
    assert generalize("$250,000.00", "money") == "100.000–1.000.000 USD"
    assert generalize("Max Mustermann", "person") is None


def test_generalize_falls_back_to_type_label():
    r = anonymize("Herr Max Mustermann", methods={"person": Method.GENERALIZE})
    assert r.text == "Herr [PERSON]"


def test_tokenize_is_reversible_and_stable(vault):
    a = anonymize("Herr Max Mustermann", vault, "m", methods={"person": Method.TOKENIZE})
    b = anonymize("Herr Max Mustermann", vault, "m", methods={"person": Method.TOKENIZE})
    token = a.text.split()[-1]
    assert token.startswith("TKN_") and a.text == b.text
    assert restore(a.text, vault, "m").text == "Herr Max Mustermann"


def test_plan_overrides_type_defaults():
    text = "Herr Max Mustermann, IBAN DE89 3704 0044 0532 0130 00"
    result = scan(text, "de")
    iban = next(d for d in result.detections if d.entity_type == "iban")
    r = Anonymizer().anonymize(text, result, plan={iban.id: Method.MASK})
    assert "DE89 **** **** **** **30 00" in r.text


def test_unknown_types_fail_closed():
    det = make_detection("client_number", Category.LEGAL_DATA, 4, 14, "MDT-004711", 0.9, "custom:client_number")
    r = Anonymizer().anonymize("Nr. MDT-004711", [det])
    assert r.text == "Nr. [REDACTED]"


def test_role_label_optional(vault):
    r = anonymize("Unser Mandant Herr Max Mustermann.", vault, "m", include_role=True)
    assert "PERSON_001 (Mandant)" in r.text


# --- structure -------------------------------------------------------------------

def test_structure_and_untouched_text_preserved(vault):
    r = anonymize(LETTER, vault, "matter-1")
    assert r.text.count("\n") == LETTER.count("\n")
    assert r.text.startswith("Unser Mandant Herr ")
    for t in r.transformations:
        assert r.text[t.out_start:t.out_end] == t.replacement


def test_diff_reconstructs_both_sides(vault):
    r = anonymize(LETTER, vault, "matter-1")
    diff = build_diff(LETTER, r)
    assert "".join(s.original for s in diff) == LETTER
    assert "".join(s.anonymized for s in diff) == r.text


# --- safety net ------------------------------------------------------------------

def test_sweep_catches_missed_repetitions():
    text = "Herr Max Mustermann. Max Mustermann hat unterschrieben."
    first = [d for d in scan(text, "de").detections if d.start < 20]  # simulate detector missing 2nd mention
    r = Anonymizer().anonymize(text, first)
    assert "Max Mustermann" not in r.text
    assert any(t.swept for t in r.transformations)


def test_sweep_catches_case_and_line_wrap_variants():
    text = "Herr Max Mustermann. MAX MUSTERMANN unterschrieb, ebenso Max\nMustermann."
    first = [d for d in scan(text, "de").detections if d.start < 20]
    r = Anonymizer().anonymize(text, first)
    assert r.text == "Herr PERSON_001. PERSON_001 unterschrieb, ebenso PERSON_001."
    assert [t.swept for t in r.transformations] == [False, True, True]


def test_leak_check_raises_in_strict_mode():
    text = "Herr Max Mustermann. MAX MUSTERMANN unterschrieb."
    first = [d for d in scan(text, "de").detections if d.start < 20]
    with pytest.raises(LeakError):
        Anonymizer(AnonymizerConfig(sweep=False)).anonymize(text, first)
    r = Anonymizer(AnonymizerConfig(sweep=False, strict=False)).anonymize(text, first)
    assert r.leaks


def test_file_vault_batch_writes_once(tmp_path, monkeypatch):
    key = VaultKey.generate()
    v = FileVault(tmp_path / "vault.json", key)
    writes = []
    persist = v._persist
    monkeypatch.setattr(v, "_persist", lambda: (writes.append(1), persist()))
    text = "Herr Max Mustermann und Frau Erika Musterfrau, max@example.org, erika@example.org."
    r = Anonymizer(vault=v).anonymize(text, scan(text, "de"), namespace="m")
    assert len(writes) == 1 and len(v.known_placeholders("m")) >= 4
    reloaded = FileVault(tmp_path / "vault.json", key)
    assert restore(r.text, reloaded, "m").text == text


# --- mapping never leaves the trusted boundary -----------------------------------

def test_result_contains_no_mapping_or_originals(vault):
    r = anonymize(LETTER, vault, "matter-1")
    dump = json.dumps(r.model_dump(mode="json"))
    for s in SECRETS:
        assert s not in dump
    assert "ct" not in r.model_dump() and "nonce" not in dump


def test_without_vault_pseudonyms_are_not_restorable():
    r = anonymize("Herr Max Mustermann")
    assert r.text == "Herr PERSON_001" and not r.reversible and r.namespace is None


def test_vault_requires_namespace(vault):
    with pytest.raises(VaultError):
        anonymize("Herr Max Mustermann", vault)


def test_file_vault_has_no_plaintext_and_restricted_permissions(tmp_path):
    key = VaultKey.generate()
    path = tmp_path / "vault.json"
    v = FileVault(path, key)
    r = anonymize(LETTER, v, "matter-1")
    raw = path.read_text(encoding="utf-8")
    for s in SECRETS + ["matter-1", key.to_b64()]:
        assert s not in raw
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    # Reload with the same key: mapping persists
    assert restore(r.text, FileVault(path, key), "matter-1").text.startswith("Unser Mandant Herr Max Mustermann")


def test_wrong_key_cannot_decrypt(tmp_path):
    path = tmp_path / "vault.json"
    r = anonymize("Herr Max Mustermann", FileVault(path, VaultKey.generate()), "m")
    other = FileVault(path, VaultKey.generate())
    # Different key -> different namespace HMAC -> nothing resolvable
    assert restore(r.text, other, "m").restored == 0


def test_tampered_ciphertext_is_rejected(tmp_path):
    key = VaultKey.generate()
    path = tmp_path / "vault.json"
    r = anonymize("Herr Max Mustermann", FileVault(path, key), "m")
    data = json.loads(path.read_text())
    ns = next(iter(data["namespaces"].values()))
    entry = next(iter(ns["entries"].values()))
    entry["ct"] = entry["ct"][:-4] + ("AAAA" if not entry["ct"].endswith("AAAA") else "BBBB")
    path.write_text(json.dumps(data))
    with pytest.raises(VaultError):
        restore(r.text, FileVault(path, key), "m")


def test_vault_key_from_env(monkeypatch):
    key = VaultKey.generate()
    monkeypatch.setenv("ANONYMIZER_VAULT_KEY", key.to_b64())
    assert VaultKey.from_env().master == key.master
    assert "***" in repr(key) and key.to_b64() not in repr(key)
    monkeypatch.delenv("ANONYMIZER_VAULT_KEY")
    with pytest.raises(VaultError):
        VaultKey.from_env()


def test_restore_reports_invented_placeholders(vault):
    anonymize("Herr Max Mustermann", vault, "m")
    res = restore("PERSON_001 und PERSON_042 trafen sich.", vault, "m")
    assert res.text == "Max Mustermann und PERSON_042 trafen sich."
    assert res.unresolved == ["PERSON_042"]
