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
        Pattern(r"(?<![\w/.+])(?:\+49|0049)\s?(?:\(0\)\s?)?\(?\d{2,5}\)?(?:[\s/-]?\d{2,}){1,4}(?![\w/])", 0.8),
        # German national with separator after area code: 030 12345678, 0171/1234567
        Pattern(r"(?<![\w/.,])0\d{2,5}(?:\s?/\s?|\s|-)\d{2,}(?:[\s-]\d{2,})*(?![\w/.,]\d)", 0.7),
        # Area code in brackets: (030) 1234567, (0157) 86376363
        Pattern(r"(?<![\w(])\(0\d{2,5}\)\s?\d{2,}(?:[\s/-]\d{2,})*(?![\w/])", 0.75),
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
        # Federal Administrative Court (year after a dot): "6 C 6.15", "1 WB 42.09", "1 WDS-VR 9.17"
        Pattern(r"(?<![\w/.])\d{1,2}\s(?:A|AV|B|BN|C|CN|D|ER|F|KSt|P|PB|PKH|VR|WB|WD|WDB|WDS-VR|WNB|WRB)"
                r"\s\d{1,4}\.\d{2}(?![\w.])", 0.85),
        # Federal Patent Court: "25 W (pat) 14/14", "4 Ni 12/16 (EP)"
        Pattern(r"(?<![\w/])\d{1,2}\s[A-Z][a-z]?\s\((?:pat|Vas|EU)\)\s\d{1,5}/\d{2}(?![\w/])", 0.9),
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
# Any statute abbreviation after a § or Art. reference: at least two capitals ("TzBfG", "SGG", "BVerfGG",
# "SächsPersVG", "DesignG", "AO"), optionally a book number ("SGB V") or year ("StVereinfG 2011").
_LAW_ABBR = r"(?:SGB\s?[IVX]+|[A-ZÄÖÜ][a-zäöüß]*[A-ZÄÖÜ][A-Za-zÄÖÜäöüß]{0,12}(?:\s(?:19|20)\d{2})?)"
# Subdivisions, with or without dots (federal social court style "Abs 2 S 3"), and lists ("§§ 7, 8").
_SUBDIV = (r"(?:,?\s(?:Abs\.?|Absatz|S\.?|Satz|Nr\.?|Halbs(?:atz|\.)?|Hs\.?|Buchst\.?|lit\.?|Alt\.?|Var\.?|"
           r"Unterabs\.?|UAbs\.?)\s?\d*[a-z]?)")
_PARA = rf"\d+\s?[a-z]?(?:\s?(?:ff?\.|-\s?\d+[a-z]?))?{_SUBDIV}*"
_AUTHOR = r"(?:(?:v\.|von|de|van)\s)?[A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)?"
_AUTHORS = rf"{_AUTHOR}(?:\s?/\s?{_AUTHOR}){{0,5}}"
LEGAL_CITATION = RegexRecognizer(
    "legal_citation", E.LEGAL_CITATION,
    [
        Pattern(rf"§§?\s?{_PARA}(?:(?:,|\sund|\sbis|\si\.\s?V\.\s?m\.)\s§?\s?{_PARA})*\s(?:{_LAW_ABBR})(?![\w-])", 0.95),
        Pattern(rf"\bArt(?:\.|ikel)\s?{_PARA}\s(?:{_LAW_ABBR}|EU-?GRCharta|GRC)(?![\w-])", 0.95),
        # Named statutes: "Grundgesetz", "des Atomgesetzes", "Bewertungsgesetzes", "Wahlordnung".
        Pattern(r"\b[A-ZÄÖÜ][a-zäöüß]*(?:gesetz(?:es|buch(?:es|s)?)?|ordnung|verordnung)\b", 0.7),
        # Case reporters and journals: "BVerfGE 76, 253", "BGHZ 140, 1", "Buchholz 251.7", "NJW 2019, 123".
        Pattern(r"\b(?:BVerfGE|BVerfGK|BVerwGE|BGHZ|BGHSt|BAGE|BFHE|BSGE|BFH/NV|SozR\s?\d(?:-\d+)?|Buchholz|"
                r"NJW(?:-RR)?|NVwZ(?:-RR)?|NZA(?:-RR)?|GRUR(?:\sInt|-RR|-Prax)?|NStZ(?:-RR)?|ZIP|DStR|DStRE|MDR|WM|"
                r"JZ|FamRZ|ZfBR|BauR|LVerfGE|Slg\.)\s\d{1,4}(?:\.\d+)?(?:,\s?(?:I-)?\d+)?", 0.9),
        # Legal literature: author(s), optionally "in: editors", then edition, "a. a. O.", "§ x Rn." or a journal
        # with year. Only with one of these markers, so a name in running text is never taken for an author.
        Pattern(rf"\b{_AUTHORS}(?:,?\sin:?\s{_AUTHORS})?,?\s(?:a\.\s?a\.\s?O\.|aaO|"
                rf"[^;()<>\n]{{0,60}}?(?:\d+\.\sAufl(?:\.|age)?|§\s?\d+[a-z]?(?:\s[A-Z][\w-]{{1,10}})?\s(?:Rn|RdNr|Rdn|Rz)\b)|"
                rf"[A-Z][A-Za-z]{{1,6}}\s(?:19|20)\d{{2}},\s(?:S\.\s)?\d+)", 0.85),
        # A bare reference without statute ("§ 5 Abs. 1") is public, but it may also be a contract clause.
        Pattern(rf"§§?\s?\d+\s?[a-z]?{_SUBDIV}+", 0.6),
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
                r"Bundessozialgericht|Bundesfinanzhof|Bundespatentgericht|Bundesdisziplinargericht)(?:e?s)?\b", 0.9),
        Pattern(r"\b(?:(?:Europäische|Internationale)[nr]?\s)?Gerichtshof(?:e?s)?(?:\sfür\sMenschenrechte|"
                r"\sder\sEuropäischen\sUnion)?\b", 0.85),
        # Unambiguous court abbreviations, also without a city. "AG", "KG", "LG", "SG", "FG", "VG" alone are
        # company forms or other words too often; they only count with a city (pattern below).
        Pattern(r"\b(?:BGH|BVerfG|BAG|BVerwG|BSG|BFH|BPatG|EuGH|EuG|EGMR|IGH|BayObLG|BayVGH|VGH|VerfGH|OVG|OLG|LSG|LAG|"
                r"ArbG|StGH|LVerfG)\b(?!-)", 0.8),
        Pattern(r"\bTruppendienstgericht(?:e?s)?(?:\s(?:Nord|Süd))?\b", 0.85),
        Pattern(rf"\b(?:{_COURT_LONG})(?:\s{_DE_CITY})?", 0.9),
        Pattern(rf"\b(?:(?:Bay|Sächs|Hess|Nds|Thür|Bbg)?(?:AG|LG|OLG|VG|OVG|VGH|VerfGH|ArbG|LAG|SG|LSG|FG))\s{_DE_CITY}", 0.75),
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
            r"psychotherapy", r"disability", r"medication", r"addiction", r"sick leave",
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

# Latin letters of names common in Germany, not only German ones: García, Yıldız, Şahin, Wójcik, Đorđević,
# Nguyễn. A narrower class silently dropped such names after "Herr"/"Zeugin", a gap that hits migrants hardest.
_UPPER = "A-ZÀ-ÖØ-ÞĀĂĄĆĈĊČĎĐĒĖĘĚĞĠĢĪĮİĶĹĻĽŁŃŅŇŌŐŒŔŘŚŜŞŠŢŤŪŮŰŲŹŻŽ"
_LOWER = "a-zß-öø-ÿāăąćĉċčďđēėęěğġģīįıķĺļľłńņňōőœŕřśŝşšţťūůűųźżžơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ"
_LEADING_NOISE = {
    "Der", "Die", "Das", "Den", "Dem", "Des", "Ein", "Eine", "Einer", "Unsere", "Unser", "Ihre", "Ihr", "Mandantin",
    "Mandant", "Klägerin", "Kläger", "Beklagte", "Beklagten", "Gegen", "Für", "Von", "Mit", "Bei", "Firma", "Fa.",
    "The", "A", "An", "Our", "Your", "Client", "Defendant", "Plaintiff", "Against", "For", "By", "With",
}
# Longer forms first: "GmbH & Co. KG" must not stop at "GmbH" and leave "Co. KG" as a second company.
_LEGAL_FORMS = (
    r"(?:GmbH|AG|SE|UG \(haftungsbeschränkt\)) & Co\.? (?:KGaA|KG|OHG)|GmbH & atypisch [Ss]till|"
    r"gGmbH|GmbH|mbH|AG|KGaA|KG|OHG|GbR|EWIV|PartG mbB|PartGmbB|PartG|UG \(haftungsbeschränkt\)|UG|"
    r"e\.\s?V\.|e\.\s?K(?:fm|fr)?\.|eG|SE|Aktiengesellschaft|Kommanditgesellschaft|"
    r"Inc\.|Ltd\.|LLC|LLP|PLC|plc|Corp\.|B\.\s?V\.|N\.\s?V\.|S\.\s?A\.|S\.p\.A\.|Co\.? KG|Co\.? OHG"
)
# Attached with a hyphen: "Hartmann-GmbH", "X-EWIV", "Wójcik Kondensatoren-GmbH", "Mansour-Gruppe", "VW-Konzern".
_HYPHEN_FORMS = (
    r"(?:GmbH|AG|SE|UG) & Co\.? (?:KGaA|KG|OHG)|GmbH & atypisch [Ss]till|"
    r"gGmbH|GmbH|AG|KGaA|KG|OHG|GbR|EWIV|UG|SE|BV|KAG|Holding|Gruppe|Konzern|Werke"
)
# Hyphen compounds with "Gruppe"/"Konzern"/"Holding" that are no company ("Facebook-Gruppe", "Alters-Gruppe").
_GROUP_STEM_STOP = {
    "Facebook", "WhatsApp", "Telegram", "Signal", "Chat", "Ziel", "Alters", "Fall", "Arbeits", "Projekt", "Berufs",
    "Personen", "Risiko", "Vergleichs", "Entgelt", "Lohn", "Gehalts", "Tarif", "Wohn", "Fach", "Selbsthilfe",
    "Kontroll", "Test", "Ländern", "Länder", "Spiel", "Lern", "Eltern", "Jugend", "Kinder", "Senioren",
}
# A role, not a name: "die Holding-KG", "die Komplementär-GmbH", "eine Vorrats-GmbH".
_GENERIC_ORG_STEMS = {
    "Holding", "Komplementär", "Komplementärin", "Objekt", "Betriebs", "Besitz", "Grundstücks", "Verwaltungs",
    "Beteiligungs", "Vorrats", "Mantel", "Tochter", "Mutter", "Schwester", "Organ", "Ziel", "Erwerber", "Ein-Mann",
    "Familien", "Publikums", "Fonds", "Immobilien", "Service", "Personal", "Projekt", "Gründungs", "Auffang",
}
_ORG_TOKEN = rf"[{_UPPER}0-9][\w&.'’-]*"


def _strip_leading_noise(text: str, start: int, end: int) -> tuple[int, list[str]]:
    tokens = text[start:end].split(" ")
    offset = start
    while len(tokens) > 1 and tokens[0].strip(",") in _LEADING_NOISE:
        offset += len(tokens[0]) + 1
        tokens = tokens[1:]
    return offset, tokens


def _trim_org(text: str, start: int, end: int) -> tuple[int, int] | None:
    offset, tokens = _strip_leading_noise(text, start, end)
    if len(tokens) < 2 or (len(tokens) == 2 and tokens[0] in _GENERIC_ORG_STEMS):
        return None
    return offset, end


def _trim_hyphen_org(text: str, start: int, end: int) -> tuple[int, int] | None:
    offset, tokens = _strip_leading_noise(text, start, end)
    if tokens[0] in _LEADING_NOISE:
        return None
    value = text[offset:end]
    group = re.search(r"([^\s-]+)-(?:Gruppe|Konzern|Holding)$", value)
    if group and group.group(1) in _GROUP_STEM_STOP:
        return None
    if " " not in value and value.split("-")[0] in _GENERIC_ORG_STEMS:
        return None
    return offset, end


# "Firma Schreiber", "Fa. SCHÜCO", "der Firma Lorenz GmbH": a name after "Firma" is a company. Courts and
# authorities never follow "Firma". The name ends at the first lower-case word or a stop word.
_FIRM_CUE = re.compile(rf"(?<![\w-])(?:Firma|Fa\.)\s(?P<name>{_ORG_TOKEN}(?:\s(?:&\s)?{_ORG_TOKEN}){{0,3}})")
_FIRM_STOP = {"Firma", "Gesellschaft", "Unternehmen", "In", "Im", "Und", "Oder", "Mit", "Bei", "Von", "Vom", "Zu",
              "Zur", "Am", "An", "Auf", "Für", "Nach", "Seit", "Der", "Die", "Das", "Den", "Dem", "Des", "Ein",
              "Eine", "Es", "Er", "Sie", "Wir", "Ich", "Herr", "Herrn", "Frau"}


class FirmCueRecognizer:
    """Company names without a legal form, introduced by "Firma" or "Fa."."""

    name = "organization_cue"
    languages: frozenset[str] = frozenset({"de"})

    def analyze(self, text: str, language: str) -> Iterable[Detection]:
        for m in _FIRM_CUE.finditer(text):
            tokens = m.group("name").split(" ")
            kept: list[str] = []
            for tok in tokens:
                if tok in _FIRM_STOP or tok in NAME_STOPWORDS:
                    break
                kept.append(tok)
            while kept and kept[-1] == "&":
                kept.pop()
            if not kept:
                continue
            value = " ".join(kept)
            # A sentence-final full stop is no part of the name; an initial ("Firma B.") keeps its dot.
            if value.endswith(".") and not re.search(rf"(?:^|[\s-])[{_UPPER}]{{1,3}}\.$", value):
                value = value.rstrip(".")
            if len(value) < 2:
                continue
            start = m.start("name")
            yield make_detection(E.ORGANIZATION, Category.PERSONAL_DATA, start, start + len(value), value, 0.8,
                                 self.name)


FIRM_CUE = FirmCueRecognizer()


ORGANIZATION = RegexRecognizer(
    "organization_legal_form", E.ORGANIZATION,
    # Token-start lookbehind instead of \b keeps the scan linear on long
    # unbroken runs such as "1.000.000..." (see test_scan_scales_linearly).
    [Pattern(rf"(?<![\w&.'-])(?:{_ORG_TOKEN}\s){{1,4}}(?:{_LEGAL_FORMS})(?![\w])", 0.85)],
    postprocess=_trim_org,
)

ORGANIZATION_HYPHEN = RegexRecognizer(
    "organization_legal_form", E.ORGANIZATION,
    [Pattern(rf"(?<![\w&.'’-])(?:{_ORG_TOKEN}\s){{0,2}}[{_UPPER}0-9][\w&.'’]*(?:-[{_UPPER}][\w.'’]*)*"
             rf"-(?:{_HYPHEN_FORMS})(?![\w-])", 0.85)],
    postprocess=_trim_hyphen_org,
)

_NAME = rf"[{_UPPER}](?:['’][{_UPPER}])?[{_LOWER}]+(?:-[{_UPPER}][{_LOWER}]+)?"
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


# --------------------------------------------------------------------------
# Identifiers announced by a label ("Kundennummer: KD/1934232-WY", "Reisepass-Nr.: HVTH16F0K")
# --------------------------------------------------------------------------
# The label fixes the type, so the value pattern can be generic; it must contain a digit and ends at a line
# break, comma, semicolon or a following lower-case word. Measured on datasets/finance (finance_data.py).
# Optional owner between label and value: "Steuernummer der Kanzlei: …", "Kundennummer bei uns: …".
_LABEL_SEP = (r"(?:\s(?:der|des|von|für|bei|unserer?|Ihrer?|meiner?|seiner?)\s[\wÄÖÜäöüß.-]{2,30})?"
              r"\s*(?:[:#]|Nr\.?|-Nr\.?)?\s*:?\s*")
_ID_TOKEN = r"[A-Z0-9](?:[A-Z0-9/.\-]*[A-Z0-9])?"  # ends with a letter or digit, never with a full stop
_ID_VALUE = rf"(?P<v>{_ID_TOKEN}(?:\s{_ID_TOKEN}){{0,3}})"


def _labelled(name: str, entity_type: str, labels: str, value: str = _ID_VALUE, confidence: float = 0.85,
              validator=v.contains_digit, category: Category | None = None) -> RegexRecognizer:
    return RegexRecognizer(name, entity_type, [Pattern(rf"(?:{labels}){_LABEL_SEP}{value}(?![\w/-])", confidence, group="v")],
                           validator=validator, checksum=False, category=category)


LABELLED_IDS = [
    _labelled("customer_number_label", "customer_number",
              r"\b(?:Kunden(?:nummer|-?Nr\.?|kennung|-?ID|konto)|Mitgliedsnummer|Mitglieds-Nr\.?|Personalnummer|"
              r"Versichertennummer|Vertragsnummer|Vertrags-Nr\.?|Policennummer|Kontonummer|Konto-Nr\.?|Mandatsreferenz|"
              r"Customer (?:ID|No\.?|number)|Client (?:ID|number))"),
    _labelled("id_document_label", "id_document",
              r"\b(?:Personalausweis(?:nummer)?(?:\s(?:mit der|Nr\.))?(?:\sNummer)?|Ausweis(?:nummer)?|Reisepass(?:nummer)?|"
              r"Pass(?:nummer|-Nr\.?)|Führerschein(?:nummer)?|Passport (?:No\.?|number)|ID card (?:No\.?|number))"),
    _labelled("health_insurance_label", "health_insurance_number",
              r"\b(?:Krankenversichertennummer|Krankenversicherungsnummer|KVNR|Versicherten-?Nr\.?)",
              value=r"(?P<v>[A-Z]\d{9})"),
    _labelled("license_plate_label", "license_plate",
              r"\b(?:(?:Fahrzeug|amtliche[sn]?\s)?[Kk]ennzeichen|Kfz-Kennzeichen|License plate)",
              value=r"(?P<v>[A-ZÄÖÜ]{1,3}[-\s][A-Z]{1,2}\s?\d{1,4}[EH]?)"),
    _labelled("tax_number_label", E.TAX_NUMBER, r"\b(?:Steuernummer|St\.-?Nr\.?|Steuer-Nr\.?)",
              value=r"(?P<v>\d{2,3}/\d{3}/\d{4,5}|\d{10,13})"),
    # A labelled IBAN with a failed checksum is kept by the IBAN recognizer itself (validated=False, so a policy
    # can send it to review); BIC has no checksum, so a label is enough here.
    _labelled("bic_label", E.BIC, r"\b(?:BIC|SWIFT(?:-Code)?|Bankcode)", value=r"(?P<v>[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)",
              confidence=0.75, validator=None),
]

IP_ADDRESS = RegexRecognizer(
    "ip_address", "ip_address",
    [
        Pattern(r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\w.]\d|\.\d)", 0.8),
        Pattern(r"(?<![\w:])(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}(?![\w:])", 0.85),
    ],
    checksum=False,
)


def builtin_recognizers() -> list:
    return [
        EMAIL, PHONE, IBAN, BIC, CREDIT_CARD, MONEY, TAX_ID, TAX_NUMBER, VAT_ID, SOCIAL_SECURITY, US_SSN,
        ADDRESS, DATE, CASE_NUMBER, LEGAL_CITATION, COURT, HEALTH, BIOMETRIC, *SPECIAL, CRIMINAL_RECORD,
        PRIVILEGE, BUSINESS_SECRET, ORGANIZATION, ORGANIZATION_HYPHEN, FIRM_CUE, PERSON, SELF_INTRO, *LABELLED_IDS,
        IP_ADDRESS,
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
