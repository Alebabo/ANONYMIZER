from anonymizer.detect.engine import NER_STOPWORDS
from anonymizer.detect.ner import authority_type, clean_entity
from anonymizer.detect.recognizers import NAME_STOPWORDS
from anonymizer.models import EntityType as E

STOP = NAME_STOPWORDS | NER_STOPWORDS


def test_courts_and_authorities_are_organisations_without_register_suffix():
    assert authority_type("Amtsgericht Frankfurt HRB", E.LOCATION) == (E.ORGANIZATION, "Amtsgericht Frankfurt")
    assert authority_type("Amtsgerichts Köln", E.PERSON) == (E.ORGANIZATION, "Amtsgerichts Köln")
    assert authority_type("Staatsanwaltschaft Köln", E.LOCATION) == (E.ORGANIZATION, "Staatsanwaltschaft Köln")
    assert authority_type("Frankfurt am Main", E.LOCATION) == (E.LOCATION, "Frankfurt am Main")
    assert authority_type("Amtsgerichtsbezirk", E.LOCATION) == (E.LOCATION, "Amtsgerichtsbezirk")


def test_lower_case_chat_entities_only_with_a_chat_trained_model():
    assert clean_entity("schepers", 0, E.PERSON, STOP) is None
    assert clean_entity("schepers", 0, E.PERSON, STOP, allow_casual=True) == (0, "schepers")
    assert clean_entity("lea bank", 4, E.ORGANIZATION, STOP, allow_casual=True) == (4, "lea bank")
    assert clean_entity("drawable-xxxhdpi", 0, E.ORGANIZATION, STOP, allow_casual=True) is None
    assert clean_entity("hallo", 0, E.PERSON, STOP, allow_casual=True) is None


def test_mail_headers_and_sign_offs_are_not_names():
    assert clean_entity("Subject", 0, E.PERSON, STOP) is None
    assert clean_entity("Body", 0, E.PERSON, STOP) is None
    assert clean_entity("Babo", 0, E.PERSON, STOP) is None
    assert clean_entity("Freundliche Grüße Marco Flükiger", 10, E.PERSON, STOP) == (28, "Marco Flükiger")
