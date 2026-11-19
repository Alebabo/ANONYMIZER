"""Built-in recognizers for German and English legal text.

All recognizers are deterministic. Known limitations are documented in
``docs/detection.md`` and in the test corpus (``known_false_negatives`` /
``known_false_positives``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from anonymizer.detect import validators as v
from anonymizer.detect.base import Pattern, RegexRecognizer, lexicon
from anonymizer.models import DEFAULT_CATEGORIES, Category, Detection, EntityType as E, make_detection

I = re.IGNORECASE

# --------------------------------------------------------------------------
# Contact data
# --------------------------------------------------------------------------

EMAIL = RegexRecognizer(
    "email", E.EMAIL,
    [Pattern(r"(?<![\w.+%-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])", 0.95)],
)

PHONE = RegexRecognizer(
    "phone", E.PHONE,
    [
        # German international: +49 30 1234567, 0049 (0)171 123 4567
        Pattern(r"(?<![\w/.+])(?:\+49|0049)\s?(?:\(0\)\s?)?\d{2,5}(?:[\s/-]?\d{2,}){1,4}(?![\w/])", 0.8),
        # German national with separator after area code: 030 12345678, 0171/1234567
        Pattern(r"(?<![\w/.,])0\d{2,5}(?:\s?/\s?|\s|-)\d{3,}(?:[\s-]\d{2,})*(?![\w/.,]\d)", 0.7),
        # Other international numbers
        Pattern(r"(?<![\w+])\+(?!49)\d{1,3}[\s-]?\(?\d{1,4}\)?(?:[\s-]?\d{2,}){2,5}(?!\w)", 0.75),
        # US: (555) 123-4567, 555-123-4567
        Pattern(r"(?<![\w(])(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?!\w)", 0.6),
    ],
    validator=v.phone_digit_count_ok,
    checksum=False,
    context_words=[r"tel\.?", r"telefon", r"phone", r"mobil", r"mobile", r"handy", r"fax", r"rufnummer"],
    context_boost=0.15,
)

# --------------------------------------------------------------------------
# Financial
# --------------------------------------------------------------------------


class IbanRecognizer:
    """Finds IBANs and trims greedy matches to the country-specific length."""

    name = "iban"
    languages: frozenset[str] = frozenset()
    _candidate = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,32}")
    _label = re.compile(r"iban|konto|account", I)

    def analyze(self, text: str, language: str) -> Iterable[Detection]:
        for m in self._candidate.finditer(text):
            raw = m.group(0)
            country = raw[:2]
            length = v.IBAN_LENGTHS.get(country)
            end = self._cut(raw, length) if length else len(raw.rstrip())
            if end is None:
                continue
            value = raw[:end]
            start = m.start()
            valid = v.iban_is_valid(value)
            labeled = self._label.search(text[max(0, start - 40):start]) is not None
            if not valid and not labeled:
                continue
            yield make_detection(
                E.IBAN, Category.FINANCIAL_DATA, start, start + end, value,
                0.99 if valid else 0.5, self.name, validated=valid,
            )

    @staticmethod
    def _cut(raw: str, length: int) -> int | None:
        count = 0
        for i, ch in enumerate(raw):
            if ch != " ":
                count += 1
                if count == length:
                    return i + 1
        return None


IBAN = IbanRecognizer()

BIC = RegexRecognizer(
    "bic", E.BIC,
    [Pattern(r"(?i:\b(?:BIC|SWIFT)(?:[- ]?Code)?\s*:?\s*)(?P<v>[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b", 0.9, group="v")],
)

CREDIT_CARD = RegexRecognizer(
    "credit_card", E.CREDIT_CARD,
    [Pattern(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])", 0.9)],
    validator=v.luhn_is_valid,
    context_words=[r"kreditkarte", r"karte", r"credit card", r"card", r"visa", r"mastercard", r"amex"],
)

_AMOUNT = r"\d+(?:[.,\u00a0 ]\d{3})*(?:[.,]\d{1,2})?"
MONEY = RegexRecognizer(
    "money", E.MONEY,
    [
        Pattern(rf"(?:€|EUR|USD|CHF|GBP|£|\$)\s?{_AMOUNT}(?!\d)", 0.85),
        Pattern(rf"(?<![\d.,]){_AMOUNT}\s?(?:€|EUR\b|Euro\b|USD\b|CHF\b|GBP\b|US-Dollar\b|Dollar\b)", 0.85),
    ],
)

TAX_ID = RegexRecognizer(
    "de_tax_id", E.TAX_ID,
    [Pattern(r"(?<![\d/])[1-9]\d(?: ?\d{3}){3}(?![\d/])", 0.95)],
    languages=["de", "en"],
    validator=v.german_tax_id_is_valid,
    context_words=[r"steuer-?id", r"steueridentifikationsnummer", r"identifikationsnummer", r"idnr\.?", r"tin\b", r"tax id"],
    context_boost=0.04,
    invalid_confidence=0.6,
)

TAX_NUMBER = RegexRecognizer(
    "de_tax_number", E.TAX_NUMBER,
    [Pattern(r"(?i:\b(?:Steuernummer|St\.?-?Nr\.?)\s*:?\s*)(?P<v>\d{2,3}/\d{3,4}/\d{4,5})", 0.95, group="v")],
)

VAT_ID = RegexRecognizer(
    "vat_id", E.VAT_ID,
    [Pattern(r"\b(?:DE\s?\d{9}|ATU\d{8}|FR[A-Z0-9]{2}\d{9}|NL\d{9}B\d{2})\b", 0.85)],
    context_words=[r"ust-?id(?:nr)?\.?", r"umsatzsteuer", r"vat"],
)

SOCIAL_SECURITY = RegexRecognizer(
    "social_security", E.SOCIAL_SECURITY_NUMBER,
    [
        # German Rentenversicherungsnummer: 12 150385 M 012
        Pattern(r"\b\d{2}\s?\d{6}\s?[A-Z]\s?\d{3}\b", 0.85),
    ],
    context_words=[r"sozialversicherungs?(?:nummer|-nr\.?)", r"rentenversicherungsnummer", r"sv-nr\.?", r"svnr"],
)

US_SSN = RegexRecognizer(
    "us_ssn", E.SOCIAL_SECURITY_NUMBER,
    [Pattern(r"(?<![\d-])\d{3}-\d{2}-\d{4}(?![\d-])", 0.6)],
    languages=["en"],
    validator=v.us_ssn_is_plausible,
    checksum=False,
    context_words=[r"ssn", r"social security"],
    context_boost=0.3,
)

# --------------------------------------------------------------------------
# Addresses
# --------------------------------------------------------------------------

_CAP = r"[A-ZÄÖÜ][a-zäöüß]+"
_STREET_SUFFIX = r"(?:straße|strasse|str\.|weg|platz|allee|gasse|ring|damm|ufer|chaussee|steig|pfad|markt|hof)"
_STREET_WORD = r"(?:Straße|Strasse|Str\.|Weg|Platz|Allee|Gasse|Ring|Damm|Ufer|Chaussee)"
_DE_CITY = rf"{_CAP}(?:[\s-](?:am|an der|im|a\.\s?d\.)?\s?{_CAP})?"

ADDRESS = RegexRecognizer(
    "address", E.ADDRESS,
    [
        Pattern(
            # Start only at a token start: with a plain \b every part of a long
            # hyphenated chain is a start and the scan becomes quadratic.
            rf"(?<![\w-])(?:{_CAP}(?:-{_CAP})*{_STREET_SUFFIX}|{_CAP}(?:\s{_CAP})?\s{_STREET_WORD})"
            rf"\s\d{{1,4}}\s?[a-z]?(?:,?\s+\d{{5}}\s+{_DE_CITY})?(?!\w)",
            0.85,
        ),
        Pattern(
            r"\b\d{1,5}\s(?:[A-Z][a-z]+\s){1,3}(?:Street|St\.|Avenue|Ave\.|Road|Rd\.|Lane|Ln\.|Boulevard|Blvd\.|Drive|Way|Place)"
            r"(?:,\s[A-Z][a-z]+(?:\s[A-Z][a-z]+)?(?:,\s[A-Z]{2}\s\d{5})?)?",
            0.8,
        ),
    ],
)

# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mär": 3, "mae": 3, "mar": 3, "apr": 4, "mai": 5, "may": 5,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "okt": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12,
}
_MONTH_NAMES = (
    r"(?:Januar|Jänner|Februar|März|Maerz|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember"
    r"|January|February|March|May|June|July|October|December"
    r"|Jan|Feb|Mär|Mar|Apr|Jun|Jul|Aug|Sept?|Okt|Oct|Nov|Dez|Dec)\.?"
)
_DOB_LABEL = re.compile(
    r"(?:geb\.|geboren(?:\s+am)?|geburtsdatum|geburtstag|born(?:\s+on)?|date of birth|d\.?o\.?b\.?)\s*[:,]?\s*$",
    I,
)


class DateRecognizer:
    """Calendar dates. Promoted to ``date_of_birth`` when labelled as such."""

    name = "date"
    languages: frozenset[str] = frozenset()
    _patterns = [
        re.compile(r"(?<![\d.])(?P<d>\d{1,2})\.\s?(?P<m>\d{1,2})\.\s?(?P<y>\d{4}|\d{2})(?![\d.]\d)"),
        re.compile(r"(?<!\d)(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})(?!\d)"),
        re.compile(rf"(?<!\d)(?P<d>\d{{1,2}})\.?\s(?P<mn>{_MONTH_NAMES})\s(?P<y>\d{{4}})(?!\d)"),
        re.compile(rf"\b(?P<mn>{_MONTH_NAMES})\s(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,\s(?P<y>\d{{4}})(?!\d)"),
        re.compile(r"(?<![\d/])(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{4})(?![\d/])"),
    ]

    def analyze(self, text: str, language: str) -> Iterable[Detection]:
        for regex in self._patterns:
            for m in regex.finditer(text):
                groups = m.groupdict()
                month = int(groups["m"]) if groups.get("m") else _MONTHS.get(groups["mn"].lower()[:3])
                day = int(groups["d"])
                if not month or not 1 <= month <= 12 or not 1 <= day <= 31:
                    continue
                start, end = m.span()
                is_dob = _DOB_LABEL.search(text[max(0, start - 30):start]) is not None
                yield make_detection(
                    E.DATE_OF_BIRTH if is_dob else E.DATE,
                    Category.PERSONAL_DATA, start, end, m.group(0),
                    0.95 if is_dob else 0.85, self.name,
                )


DATE = DateRecognizer()

# --------------------------------------------------------------------------
# Legal references
# --------------------------------------------------------------------------

_SHORT_TOKEN = r"[A-Z][A-Za-z]{0,3}"
CASE_NUMBER = RegexRecognizer(
    "case_number", E.CASE_NUMBER,
    [
        # Labelled reference: "Az.: 2 O 123/24", "Case No. 1:23-cv-01234"
        Pattern(
            r"(?i:\b(?:Az\.|AZ:|Aktenzeichen|Gesch(?:äfts)?zeichen|Gz\.|Unser Zeichen|Ihr Zeichen|"
            r"Case No\.|Case Number|Docket No\.|File No\.|Matter No\.))\s*:?\s*"
            r"(?P<v>[A-Z0-9][\w./:-]*(?:\s(?=[\w./:-]*\d|[A-Z][A-Za-z]{0,3}\b)[A-Z0-9][\w./:-]*){0,4})",
            0.92, group="v",
        ),
        # German court files: "2 O 123/24", "VI ZR 12/23", "1 StR 123/22"
        Pattern(rf"(?<![\w/])(?:\d{{1,3}}|[IVX]{{1,5}})\s?{_SHORT_TOKEN}\s\d{{1,5}}/\d{{2}}(?![\w/])", 0.8),
        # Prosecutor files: "123 Js 4567/24"
        Pattern(r"(?<![\w/])\d{1,4}\s(?:Js|Ds|Ls|Cs|UJs|VRs)\s\d{1,6}/\d{2}(?![\w/])", 0.9),
        # US federal docket: "1:23-cv-01234"
        Pattern(r"(?<![\w:])\d:\d{2}-[a-z]{2}-\d{3,5}(?![\w-])", 0.9),
    ],
    validator=v.contains_digit,
    checksum=False,
)

_LAWS = (
    r"BGB|StGB|ZPO|StPO|GG|HGB|AO|GmbHG|AktG|VwGO|VwVfG|ArbGG|KSchG|BetrVG|InsO|UWG|UrhG|MarkenG|"
    r"PatG|BDSG|DSGVO|DS-GVO|GDPR|TMG|TTDSG|GWB|EStG|UStG|SGB\s?[IVX]+|FamFG|WEG|BRAO|AEUV|EUV|EMRK|GRCh"
)
LEGAL_CITATION = RegexRecognizer(
    "legal_citation", E.LEGAL_CITATION,
    [
        Pattern(
            rf"§§?\s?\d+[a-z]?(?:\s?(?:ff?\.|-\s?\d+[a-z]?))?(?:,?\s(?:Abs\.|Absatz)\s?\d+)?(?:,?\s(?:S\.|Satz)\s?\d+)?"
            rf"(?:,?\s(?:Nr\.)\s?\d+)?\s(?:{_LAWS})\b",
            0.95,
        ),
        Pattern(rf"\bArt(?:\.|ikel)\s?\d+(?:\s?(?:Abs\.|para\.)\s?\d+)?(?:\s?(?:lit\.)\s?[a-z])?\s(?:{_LAWS})\b", 0.95),
        Pattern(r"\b\d+\s(?:U\.S\.C\.|USC)\s§+\s?\d+[a-z]?\b", 0.9),
    ],
)

_COURT_LONG = (
    r"Amtsgericht|Landgericht|Oberlandesgericht|Verwaltungsgericht|Oberverwaltungsgericht|Arbeitsgericht|"
    r"Landesarbeitsgericht|Sozialgericht|Landessozialgericht|Finanzgericht|Kammergericht"
)
COURT = RegexRecognizer(
    "court", E.COURT,
    [
        Pattern(r"\b(?:Bundesgerichtshof|Bundesverfassungsgericht|Bundesarbeitsgericht|Bundesverwaltungsgericht|"
                r"Bundessozialgericht|Bundesfinanzhof|Europäische[nr]? Gerichtshof|BGH|BVerfG|BAG|BVerwG|BSG|BFH|EuGH)\b", 0.9),
        Pattern(rf"\b(?:{_COURT_LONG})(?:\s{_DE_CITY})?", 0.9),
        Pattern(rf"\b(?:AG|LG|OLG|VG|OVG|ArbG|LAG|SG|LSG|FG)\s{_DE_CITY}", 0.75),
        Pattern(r"\b(?:Supreme Court|Court of Appeals?|High Court|Crown Court|County Court|"
                r"(?:United States )?District Court)(?:\sfor the\s[A-Z][a-z]+(?:\s(?:of\s(?:the\s)?)?[A-Z][a-z]+){0,4})?", 0.85),
    ],
)

# --------------------------------------------------------------------------
# Special categories (Art. 9 / Art. 10 GDPR) and confidentiality markers
# --------------------------------------------------------------------------

HEALTH = RegexRecognizer(
    "health_lexicon", E.HEALTH_DATA,
    [
        Pattern(lexicon([
            r"Diagnosen?", r"diagnostiziert\w*", r"Depressionen?", r"depressiv\w*", r"Krebserkrankung", r"Krebs",
            r"Tumor\w*", r"psychotherap\w*", r"HIV", r"AIDS", r"Diabetes", r"Schwangerschaft", r"schwanger", r"Psychotherapie\w*",
            r"psychiatrisch\w*", r"Psychiatrie", r"Arbeitsunfähigkeit\w*", r"arbeitsunfähig", r"Krankschreibung\w*",
            r"Schwerbehinderung", r"Behinderung", r"Grad der Behinderung", r"Medikation", r"Alkoholabhängigkeit",
            r"Drogenabhängigkeit", r"Suchterkrankung", r"Burn-?out", r"Bandscheibenvorfall", r"Herzinfarkt",
            r"Schlaganfall", r"Demenz", r"Reha(?:bilitation)?", r"Klinikaufenthalt", r"Krankheit", r"erkrankt",
            r"Erkrankung",
            r"diagnos(?:is|ed)", r"depression", r"cancer", r"tumou?r", r"pregnan(?:t|cy)", r"psychiatric",
            r"psychotherapy", r"disability", r"disabled", r"medication", r"addiction", r"sick leave",
            r"medical condition", r"illness", r"heart attack", r"stroke", r"dementia", r"chemotherapy",
        ]), 0.8, flags=I),
        Pattern(r"(?i:\bICD(?:-10)?(?:-Code)?\s*:?\s*)(?P<v>[A-TV-Z]\d{2}(?:\.\d{1,2})?)\b", 0.95, group="v"),
    ],
)

BIOMETRIC = RegexRecognizer(
    "biometric_lexicon", E.BIOMETRIC_DATA,
    [Pattern(lexicon([
        r"biometrisch\w*", r"Fingerabdr(?:uck|ücke)\w*", r"Gesichtserkennung", r"Iris-?Scan", r"DNA-?(?:Analyse|Probe|Profil)",
        r"genetisch\w*", r"Gentest", r"biometric\w*", r"fingerprints?", r"facial recognition", r"DNA (?:sample|profile|test)",
        r"genetic\w*",
    ]), 0.8, flags=I)],
)


def _special(subtype: str, terms: list[str]) -> RegexRecognizer:
    return RegexRecognizer(
        f"special_{subtype}", E.SPECIAL_CATEGORY,
        [Pattern(lexicon(terms), 0.75, flags=I)],
        attributes={"subtype": subtype},
    )


SPECIAL = [
    _special("religion", [r"Religionszugehörigkeit", r"Konfession", r"konfessionslos", r"muslimisch", r"jüdisch", r"katholisch",
                          r"evangelisch", r"religious (?:belief|affiliation)", r"muslim", r"jewish", r"catholic"]),
    _special("political_opinion", [r"Parteimitglied\w*", r"politische (?:Meinung|Überzeugung|Gesinnung)",
                                   r"political (?:opinion|affiliation)", r"party member\w*"]),
    _special("trade_union", [r"Gewerkschaftsmitglied\w*", r"Gewerkschaftszugehörigkeit", r"trade union member\w*",
                             r"union membership"]),
    _special("sexual_orientation", [r"sexuelle Orientierung", r"homosexuell\w*", r"bisexuell\w*", r"transgender",
                                    r"sexual orientation", r"gay", r"lesbian"]),
    _special("ethnic_origin", [r"ethnische Herkunft", r"Abstammung", r"ethnic origin", r"racial origin"]),
]

CRIMINAL_RECORD = RegexRecognizer(
    "criminal_record", E.CRIMINAL_RECORD,
    [Pattern(lexicon([
        r"vorbestraft", r"Vorstrafen?", r"Bundeszentralregister", r"Führungszeugnis", r"Strafregister",
        r"verurteilt", r"Verurteilung(?:en)?", r"Haftstrafe", r"Bewährungsstrafe",
        r"criminal record", r"prior conviction\w*", r"convicted", r"previous convictions?",
    ]), 0.8, flags=I)],
)

PRIVILEGE = RegexRecognizer(
    "privilege_marker", E.PRIVILEGE_MARKER,
    [Pattern(lexicon([
        r"Mandatsgeheimnis", r"anwaltliche Schweigepflicht", r"Verschwiegenheitspflicht", r"Berufsgeheimnis",
        r"Anwaltsgeheimnis", r"streng vertraulich", r"vertrauliche Mandanteninformation\w*", r"Verteidigerpost",
        r"attorney[- ]client privilege\w*", r"privileged(?: (?:and|&) confidential)?", r"legal(?:ly)? privilege\w*",
        r"attorney work product", r"without prejudice",
    ]), 0.9, flags=I)],
)

BUSINESS_SECRET = RegexRecognizer(
    "business_secret_marker", E.BUSINESS_SECRET_MARKER,
    [Pattern(lexicon([
        r"Geschäftsgeheimnis\w*", r"Betriebsgeheimnis\w*", r"nur für den internen Gebrauch", r"interne Preis\w*",
        r"Preiskalkulation", r"Übernahmepläne", r"Geschäftsstrategie", r"vertraulich",
        r"trade secrets?", r"internal use only", r"confidential", r"internal pricing", r"business strategy",
    ]), 0.75, flags=I)],
)

# --------------------------------------------------------------------------
# Organizations and persons (rule-based; spaCy NER can be added on top)
# --------------------------------------------------------------------------

_LEADING_NOISE = {
    "Der", "Die", "Das", "Den", "Dem", "Des", "Ein", "Eine", "Einer", "Unsere", "Unser", "Ihre", "Ihr", "Mandantin",
    "Mandant", "Klägerin", "Kläger", "Beklagte", "Beklagten", "Gegen", "Für", "Von", "Mit", "Bei", "Firma",
    "The", "A", "An", "Our", "Your", "Client", "Defendant", "Plaintiff", "Against", "For", "By", "With",
}
_LEGAL_FORMS = (
    r"GmbH & Co\. KG|GmbH & Co\. KGaA|gGmbH|GmbH|AG|KGaA|KG|OHG|PartG mbB|PartG|UG \(haftungsbeschränkt\)|UG|"
    r"e\.\s?V\.|eG|SE|Inc\.|Ltd\.|LLC|LLP|PLC|plc|Corp\.|Co\. KG"
)


def _trim_org(text: str, start: int, end: int) -> tuple[int, int] | None:
    tokens = text[start:end].split(" ")
    offset = start
    while len(tokens) > 1 and tokens[0].strip(",") in _LEADING_NOISE:
        offset += len(tokens[0]) + 1
        tokens = tokens[1:]
    return (offset, end) if len(tokens) > 1 else None


ORGANIZATION = RegexRecognizer(
    "organization_legal_form", E.ORGANIZATION,
    # Token-start lookbehind instead of \b keeps the scan linear on long
    # unbroken runs such as "1.000.000..." (see test_scan_scales_linearly).
    [Pattern(rf"(?<![\w&.'-])(?:[A-ZÄÖÜ0-9][\w&.'-]*\s){{1,4}}(?:{_LEGAL_FORMS})(?![\w])", 0.85)],
    postprocess=_trim_org,
)

_NAME = r"[A-ZÄÖÜ][a-zäöüßéèáàç]+(?:-[A-ZÄÖÜ][a-zäöüßéèáàç]+)?"
_PARTICLE = r"(?:von der|van der|von|van|de la|de|zu|del)"
_FULL_NAME = rf"{_NAME}(?:\s(?:{_PARTICLE}\s)?{_NAME}){{0,2}}"
_TITLES = r"(?:(?:Dr\.|Prof\.|Dipl\.-[A-Za-z]+\.?|med\.|jur\.|rer\.\s?nat\.)\s)*"

ROLE_TERMS: dict[str, str] = {
    r"Mandant(?:in|en)?": "client",
    r"Kläger(?:in)?": "plaintiff",
    r"Beklagte[rn]?": "defendant",
    r"Beschuldigte[rn]?": "accused",
    r"Angeklagte[rn]?": "accused",
    r"Angeschuldigte[rn]?": "accused",
    r"Zeug(?:e|in|en)": "witness",
    r"Geschädigte[rn]?": "injured_party",
    r"Antragsteller(?:in)?": "applicant",
    r"Antragsgegner(?:in)?": "respondent",
    r"Erblasser(?:in)?": "decedent",
    r"Arbeitnehmer(?:in)?": "employee",
    r"Arbeitgeber(?:in)?": "employer",
    r"(?:Rechtsanw(?:alt|ältin)|RAin|RA|Verteidiger(?:in)?|Prozessbevollmächtigte[rn]?)": "counsel",
    r"(?:Richter(?:in)?|Vorsitzende[rn]?)": "judge",
    r"[Cc]lient": "client",
    r"[Pp]laintiff": "plaintiff",
    r"[Cc]laimant": "plaintiff",
    r"[Dd]efendant": "defendant",
    r"[Rr]espondent": "respondent",
    r"(?:the )?[Aa]ccused": "accused",
    r"[Ww]itness": "witness",
    r"[Vv]ictim": "injured_party",
    r"(?:[Cc]ounsel|[Aa]ttorney|[Ll]awyer|[Ss]olicitor)": "counsel",
    r"[Jj]udge": "judge",
    r"[Ee]mployee": "employee",
}
_HONORIFICS = r"Herrn?|Frau|Hr\.|Fr\.|Mr\.|Mrs\.|Ms\.|Mx\.|Dr\.|Prof\."
_ROLE_ALT = "|".join(ROLE_TERMS)
_ROLE_LOOKUP = [(re.compile(rf"^(?:{k})$"), r) for k, r in ROLE_TERMS.items()]

# Capitalised German nouns frequently following role words; never names.
NAME_STOPWORDS = {
    "Firma", "Gesellschaft", "Kanzlei", "Partei", "Parteien", "Gericht", "Klage", "Vertrag", "Anwalt", "Rechtsanwalt",
    "Mandant", "Mandantin", "Beklagte", "Kläger", "Zeuge", "Staatsanwaltschaft", "Unternehmen", "Bank", "Kollege",
    "Kollegin", "Richter", "Richterin", "Vorsitzende", "Verteidiger", "Polizei", "Antrag", "Schreiben", "Seite",
    "Mutter", "Vater", "Ehefrau", "Ehemann", "Sohn", "Tochter", "Erben", "Erbin", "Herr", "Frau", "Herrn",
    "Ihnen", "Sie", "Ihr", "Ihre", "Wir", "Uns", "Es", "Er", "Sein", "Seine", "Am", "Im", "In", "Zu", "Bei", "Nach",
    "Vom", "Laut", "Gemäß", "Wegen", "Und", "Oder", "Aber", "Hat", "Ist", "War", "Wird", "Wurde", "Habe", "Haben",
    "Company", "Court", "The", "This", "That", "Client", "Party", "Counsel", "Defendant", "Plaintiff", "Witness",
    "Mandantschaft", "Gegenseite", "Gegner", "Verfahren", "Strafverfahren", "Ermittlungsverfahren", "Akte",
}


def _role_for(term: str) -> str | None:
    for regex, role in _ROLE_LOOKUP:
        if regex.match(term):
            return role
    return None


class PersonRecognizer:
    """Names introduced by an honorific or a procedural role.

    Bare names without such a cue are only found by the optional spaCy NER
    recognizer or by mention propagation (``anonymizer.detect.engine``).
    """

    name = "person_rules"
    languages: frozenset[str] = frozenset()
    _pattern = re.compile(
        rf"(?<![\w-])(?P<trigger>{_HONORIFICS}|{_ROLE_ALT})(?:\s?,\s?|\s)(?:(?:{_HONORIFICS})\s)?{_TITLES}(?P<name>{_FULL_NAME})"
    )
    _role_before = re.compile(rf"(?<![\w-])(?P<role>{_ROLE_ALT})(?![\w-])[^.\n;]{{0,25}}$")
    _role_after = re.compile(rf"^\s?(?:\(|,\s?(?:die|der|the|our|unsere?r?)?\s?)(?P<role>{_ROLE_ALT})(?![\w-])")
    # Rubrum style: name and address, then a line such as "– Kläger –"
    _role_rubrum = re.compile(rf"^[^\n]{{0,80}}\n\s*[–—-]\s*(?P<role>{_ROLE_ALT})\s*[–—-]")

    def analyze(self, text: str, language: str) -> Iterable[Detection]:
        for m in self._pattern.finditer(text):
            tokens = m.group("name").split(" ")
            start = m.start("name")
            # Strip leading/trailing stop words ("Klage", "Sie", ...)
            while tokens and tokens[0] in NAME_STOPWORDS:
                start += len(tokens[0]) + 1
                tokens = tokens[1:]
            while tokens and tokens[-1] in NAME_STOPWORDS:
                tokens = tokens[:-1]
            if not tokens or all(re.fullmatch(_PARTICLE, t) for t in tokens):
                continue
            value = " ".join(tokens)
            end = start + len(value)
            trigger = m.group("trigger")
            role = _role_for(trigger)
            if role is None:
                before = self._role_before.search(text[max(0, m.start() - 40):m.start()])
                after = self._role_after.search(text[end:end + 40]) or self._role_rubrum.search(text[end:end + 120])
                hit = before or after
                role = _role_for(hit.group("role")) if hit else None
            attributes = {"role": role} if role else {}
            confidence = 0.85 if len(tokens) > 1 else 0.75
            yield make_detection(E.PERSON, Category.PERSONAL_DATA, start, end, value, confidence, self.name,
                                 attributes=attributes)


PERSON = PersonRecognizer()


class SelfIntroductionRecognizer:
    """Names in self-introductions, typical for chats: "mein Name ist Anna Müller", "ich heiße anna",
    "my name is John Doe", "ich bin Anna Müller", "this is John Doe".

    Strong cues ("mein Name ist", "ich heiße", "my name is") also accept lowercase names, because chat
    users often do not capitalise. Weak cues ("ich bin", "I am", "this is") need at least two
    capitalised tokens, otherwise "ich bin Kunde" would be a name. False positives cost readability;
    misses leak a name, so the strong cues are deliberately generous."""

    name = "person_self_intro"
    languages: frozenset[str] = frozenset()
    _word = r"[A-Za-zÄÖÜäöüßéèáàç]+(?:-[A-Za-zÄÖÜäöüßéèáàç]+)?"
    _strong = re.compile(
        rf"(?i:\b(?:mein\s+name\s+ist|ich\s+hei(?:ß|ss)e|my\s+name\s+is|my\s+name's|name\s*:)\s+)"
        rf"(?P<name>{_word}(?:\s(?:{_PARTICLE}\s)?{_word}){{0,2}})")
    _weak = re.compile(
        rf"(?i:\b(?:ich\s+bin|hier\s+ist|hier\s+spricht|i\s+am|i'm|this\s+is)\s+)"
        rf"(?P<name>{_NAME}(?:\s(?:{_PARTICLE}\s)?{_NAME}){{1,2}})")
    # Words that end a lowercase name ("mein name ist anna und ich ...").
    _stop = {"und", "and", "ich", "i", "aus", "from", "bei", "mit", "with", "habe", "have", "hatte", "bin", "am",
             "wohne", "live", "komme", "come", "möchte", "would", "want", "will", "wollte", "brauche", "need",
             "der", "die", "das", "the", "ein", "eine", "a", "an", "kunde", "kundin", "customer", "hier", "here",
             "nicht", "not", "auch", "also", "aber", "but", "oder", "or", "zu", "to", "für", "for", "es", "it"}

    def analyze(self, text: str, language: str) -> Iterable[Detection]:
        for regex, strong in ((self._strong, True), (self._weak, False)):
            for m in regex.finditer(text):
                tokens = m.group("name").split(" ")
                kept: list[str] = []
                for tok in tokens:
                    if tok.lower() in self._stop or tok in NAME_STOPWORDS:
                        break
                    kept.append(tok)
                while kept and re.fullmatch(_PARTICLE, kept[-1]):
                    kept.pop()
                if not kept or (not strong and len(kept) < 2):
                    continue
                value = " ".join(kept)
                start = m.start("name")
                confidence = 0.85 if len(kept) > 1 else 0.7
                yield make_detection(E.PERSON, Category.PERSONAL_DATA, start, start + len(value), value, confidence,
                                     self.name)


SELF_INTRO = SelfIntroductionRecognizer()


def builtin_recognizers() -> list:
    return [
        EMAIL, PHONE, IBAN, BIC, CREDIT_CARD, MONEY, TAX_ID, TAX_NUMBER, VAT_ID, SOCIAL_SECURITY, US_SSN,
        ADDRESS, DATE, CASE_NUMBER, LEGAL_CITATION, COURT, HEALTH, BIOMETRIC, *SPECIAL, CRIMINAL_RECORD,
        PRIVILEGE, BUSINESS_SECRET, ORGANIZATION, PERSON, SELF_INTRO,
    ]


def custom_recognizer(spec: dict) -> RegexRecognizer:
    """Build a recognizer from config, e.g. ``{"name": "client_number", "pattern": "MDT-\\d{6}",
    "category": "legal_data", "confidence": 0.9, "context_words": ["Mandantennr"]}``."""
    entity_type = spec.get("entity_type", spec["name"])
    category = Category(spec["category"]) if "category" in spec else DEFAULT_CATEGORIES.get(entity_type, Category.PERSONAL_DATA)
    flags = I if spec.get("ignore_case") else 0
    return RegexRecognizer(
        f"custom:{spec['name']}", entity_type,
        [Pattern(spec["pattern"], float(spec.get("confidence", 0.8)), flags=flags)],
        category=category,
        languages=spec.get("languages", ()),
        context_words=spec.get("context_words", ()),
    )
