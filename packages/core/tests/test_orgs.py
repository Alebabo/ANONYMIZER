"""Organisation rules from NER v6 (detect/orgs.py) and the adjustments made when merging them for legal text."""

from anonymizer.detect.ner import ORG_HEADS, common_nouns
from anonymizer.detect.orgs import headed_orgs, known_orgs, legal_entities


def _headed(text: str) -> list[str]:
    return [text[s:e] for s, e in headed_orgs(text, ORG_HEADS, common_nouns())]


def test_trade_heads_take_the_name():
    assert _headed("Von: Hausverwaltung Schmidt") == ["Hausverwaltung Schmidt"]
    assert _headed("Kanzlei Becker & Partner") == ["Kanzlei Becker"]


def test_courts_and_authorities_are_no_heads():
    # Public bodies are not pseudonymised (legal-default, LER: INN/GRT); "Staatsanwaltschaft München I" is no firm.
    for head in ("Staatsanwaltschaft", "Amtsgericht", "Landgericht", "Finanzamt", "Jobcenter", "Polizeipräsidium"):
        assert head not in ORG_HEADS
        assert _headed(f"bei der {head} Köln eingegangen") == []


def test_title_ends_a_headed_name():
    # "Dr. Gude" is the owner, a person; the firm must not swallow the title and drop the name.
    assert _headed("Zahnarztpraxis Dr. Gude\nKurze Gasse 1") == []


def test_authorities_and_schufa_are_not_known_orgs():
    text = ("Die Bundesanstalt für Finanzdienstleistungsaufsicht (BaFin), die Deutsche Rentenversicherung und das "
            "Bundeszentralamt für Steuern; Schufa-Auskunft liegt vor. Zahlung an PayPal.")
    assert [text[s:e] for s, e in known_orgs(text)] == ["PayPal"]


def test_generic_legal_entity_is_a_role():
    text = "Die Holding KG wird verschmolzen. Die ACME Software GmbH und die Becker KG."
    assert [text[s:e] for s, e in legal_entities(text, set())] == ["ACME Software GmbH", "Becker KG"]
