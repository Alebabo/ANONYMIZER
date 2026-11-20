"""Well-known organisations that statistical NER misses or mistypes ("amazon", "Schufa-Daten", "DKB").

Public knowledge only: banks, payment providers, credit agencies, insurers, merchants, carriers and authorities that
customers of a German bank name all the time. Names that are also common words or first names (Otto, dm, Sky,
Bild, Hermes, Apple, Ergo, Saturn, Hilton) are left out, or matched in their exact spelling only.
"""

from __future__ import annotations

import re

# Matched case-insensitively: distinctive brand names that are no German word ("amazon", "paypal", "schufa").
_ANY_CASE = [
    "Deutsche Bank", "Commerzbank", "Postbank", "HypoVereinsbank", "UniCredit", "Targobank", "Santander",
    "Norisbank", "Consorsbank", "comdirect", "DKB", "ING-DiBa", "N26", "Revolut", "bunq", "Monzo",
    "Trade Republic", "Scalable Capital", "Openbank", "Creditplus", "Advanzia", "Barclays", "Sparda-Bank",
    "1822direkt", "Volkswagen Bank", "VW Bank", "Audi Bank", "BMW Bank", "Mercedes-Benz Bank", "Bank of Scotland",
    "PayPal", "Klarna", "Riverty", "Vinted", "Western Union", "MoneyGram",
    "Schufa", "Creditreform", "Crif", "Infoscore", "Intrum", "Coeo",
    "Allianz", "AXA", "ARAG", "HUK-Coburg", "HUK24", "Generali", "DEVK", "Debeka", "Signal Iduna", "Gothaer",
    "Amazon", "Zalando", "eBay", "Temu", "Shein", "AliExpress", "Netflix", "Spotify", "Disney+", "DAZN",
    "Lieferando", "Wolt", "Uber Eats", "Airbnb", "Booking.com", "Ryanair", "Eurowings", "Lufthansa", "Flixbus",
    "Telekom", "Vodafone", "Telefónica", "Congstar", "1&1", "Lidl", "Aldi", "Aldi Süd", "Aldi Nord", "Rewe",
    "Edeka", "Kaufland", "Rossmann", "MediaMarkt", "IKEA", "Tchibo", "Decathlon", "Primark",
    "Sixt", "Europcar", "Aral", "McFit", "Fitness First", "Deutsche Bahn", "Deutsche Post", "DHL",
    "BaFin", "Bundesanstalt für Finanzdienstleistungsaufsicht", "Bundeszentralamt für Steuern",
    "Deutsche Rentenversicherung", "Bundeskriminalamt", "Google Play", "Apple Store", "WEB.DE", "GMX",
    "Kleinanzeigen", "Finanzfluss",
]
# Exact spelling only: common words, names or abbreviations in other spellings ("ing", "wise", "shell", "netto").
_EXACT = ["ING", "E.ON", "O2", "GLS", "UPS", "dm-drogerie markt", "Wise", "Shell", "Zara", "Payback", "EOS",
          "Lowell", "Bürgel"]


def _alternation(names: list[str]) -> str:
    parts = []
    for name in sorted(names, key=len, reverse=True):
        p = r"\s+".join(re.escape(word) for word in name.split(" "))
        # "Deutschen Bank", "Deutscher Post": inflected adjective.
        p = p.replace("Deutsche", "Deutsche[nr]?")
        parts.append(p)
    return "|".join(parts)


# A name stands alone or as the first part of a compound ("Schufa-Daten", "PayPal-Konto"), never inside a word.
# A web address of the brand ("Temu.com") belongs to the name.
_KNOWN = re.compile(rf"(?<![\w-])(?:(?i:{_alternation(_ANY_CASE)})|{_alternation(_EXACT)})"
                    r"(?:\.(?:com|de|net|eu))?(?![\w+&])")


def known_orgs(text: str) -> list[tuple[int, int]]:
    """Character spans of well-known organisations in ``text``."""
    return [(m.start(), m.end()) for m in _KNOWN.finditer(text)]


# One to four capitalised words before a legal form: "ACME Software GmbH", "H&A Schneider Immobilien GbR".
_LEGAL_FORM = (r"GmbH\s*&\s*Co\.\s*KG|gGmbH|GmbH|KGaA|AG|KG|GbR|OHG|PartG(?:\s*mbB)?|UG(?:\s*\(haftungsbeschränkt\))?"
               r"|eG|e\.\s?K\.|e\.\s?V\.|SE|Inc\.|Ltd\.?|LLC")
_LEGAL = re.compile(rf"(?<![\w&.-])((?:[A-ZÄÖÜ0-9][\w&.'+-]*[ \t]+){{1,4}}(?:{_LEGAL_FORM}))(?![\w])")


def legal_entities(text: str, stopwords: set[str]) -> list[tuple[int, int]]:
    """Company names ending in a legal form. Leading function words ("Die", "Bei", "Firma") are not part of it."""
    out = []
    for m in _LEGAL.finditer(text):
        start, words = m.start(), m.group(1).split()
        while len(words) > 1 and (words[0].lower() in stopwords or words[0].lower() in _ARTICLES):
            start = text.index(words[1], start + len(words[0]))
            words = words[1:]
        if len(words) > 1:
            out.append((start, m.end()))
    return out


_TAIL_WORD = re.compile(r"[ \t]+([A-ZÄÖÜ][\w&'-]*|&|da|di|del|la|il|zum|zur|am|im)(?![\w])")
# A town adjective before an institution: "Würzburger Versicherungen", "Hamburger Sparkasse", "Kieler Nachrichten".
_TOWN_INSTITUTION = re.compile(
    r"(?<![\w-])[A-ZÄÖÜ][a-zäöüß]+er[ \t]+(?:Versicherung(?:en)?|Sparkasse|Volksbank|Bank|Stadtwerke|Verkehrsbetriebe"
    r"|Zeitung|Nachrichten|Rundschau|Anzeiger|Allgemeine|Wohnungsbaugesellschaft|Tafel|Bäder)(?![\w-])")


def headed_orgs(text: str, heads: set[str], nouns: frozenset[str]) -> list[tuple[int, int]]:
    """A trade or institution word followed by a name: "Hausverwaltung Schmidt", "Trattoria Bella Napoli",
    "Sparkasse Krefeld". Up to three name words; common nouns and particles at the end are not part of it."""
    out = []
    for m in re.finditer(rf"(?<![\w-])(?:{'|'.join(map(re.escape, heads))})(?![\w-])", text):
        end, words = m.end(), []
        for _ in range(3):
            w = _TAIL_WORD.match(text, end)
            if not w or w.group(1) in heads:
                break
            words.append((w.group(1), w.end()))
            end = w.end()
        # Register abbreviations ("Amtsgericht Frankfurt HRB") and common nouns end the name.
        cut = next((i for i, (w, _) in enumerate(words) if len(w) > 1 and w.isupper() and w != "&"), len(words))
        words = words[:cut]
        while words and (words[-1][0] in nouns or not words[-1][0][:1].isupper()):
            words.pop()
        if words and words[0][0] not in nouns:
            out.append((m.start(), words[-1][1]))
    out += [(m.start(), m.end()) for m in _TOWN_INSTITUTION.finditer(text)
            if text[m.start():m.end()].split()[0] not in nouns]
    return out


_ARTICLES = {"die", "der", "das", "den", "dem", "des", "ein", "eine", "einer", "meine", "meiner", "unsere", "ihre",
             "ihrer", "bei", "von", "an", "für", "mit", "über", "firma", "von", "zur", "zum"}
