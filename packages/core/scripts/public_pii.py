"""Public German texts with labelled personal data: measure the detector and feed the NER training.

    python packages/core/scripts/public_pii.py download   # fetch the sources, keep the German part
    python packages/core/scripts/public_pii.py eval [--data datasets/public] [--source all] [--limit N]
    python packages/core/scripts/ner_train.py ... --public datasets/public [--public-limit 3000]

Sources (German part only, converted to datasets/public/<source>/{train,test}.jsonl.gz, see datasets/public/README.md):
  smartdata  DFKI-SLT/smartdata-corpus (CC BY 4.0): news, tweets and traffic reports; companies are their own
             type (ORGANIZATION_COMPANY), which is what our company recall lacks.
  mapa       joelniklaus/mapa (CC BY 4.0): EUR-Lex judgments and opinions, annotated for anonymisation.
  e3jsi      E3-JSI/synthetic-multi-pii-ner-v1 (MIT): synthetic German texts (banking, finance, health, legal).
             No test split upstream: every fifth document is held out.
  urchade    urchade/synthetic-pii-ner-mistral-v1 (Apache-2.0): synthetic texts, German ones picked by function
             words. No test split upstream: every fifth document is held out.

Not included: ai4privacy open-pii-masking-500k (Llama community licence: model naming, "Built with Llama",
commercial use needs written permission).

Labels are mapped to our entity types at download (person, organization, location, address, date, ...);
labels without personal data (professions, diseases, triggers, numbers) are dropped. Courts, EU institutions and
other public bodies become "public_body": measured, never taught as ORG (LER leaves them out, too).
Person spans lose a leading salutation or title ("Frau Dr. Anna Müller" -> "Anna Müller"), as in our gold data.
"""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

HF = "https://huggingface.co/datasets"
SOURCES = ["smartdata", "mapa", "e3jsi", "urchade"]

# Source label (lower case) -> our label. Missing labels are dropped.
LABELS: dict[str, str] = {
    # smartdata, mapa (coarse)
    "person": "person", "organization_company": "organization", "organization": "public_body",
    "organisation": "public_body", "location": "location", "location_city": "location",
    "location_street": "address", "address": "address", "date": "date", "amount": "money",
    # e3jsi (German labels)
    "name": "person", "personenname": "person", "personennamen": "person", "arzt": "person", "patient": "person",
    "kunde": "person", "unternehmen": "organization", "firma": "organization", "bank": "organization",
    "bankname": "organization", "finanzinstitut": "organization", "versicherungsgesellschaft": "organization",
    "institution": "public_body", "gericht": "public_body", "behörde": "public_body", "krankenhaus": "public_body",
    "universität": "public_body", "einrichtung": "public_body",
    "stadt": "location", "ort": "location", "wohnort": "location", "geburtsort": "location", "land": "location",
    "adresse": "address", "straße": "address", "postleitzahl": "address", "datum": "date",
    "geburtsdatum": "date_of_birth", "telefonnummer": "phone", "email": "email", "iban": "iban", "betrag": "money",
    "kontonummer": "account_number", "konto": "account_number", "kreditkarte": "credit_card",
    "kreditkartennummer": "credit_card", "krankenversicherungsnummer": "insurance_number",
    "steuernummer": "tax_number", "steuer-id": "tax_id", "steueridentifikationsnummer": "tax_id",
    "sozialversicherungsnummer": "social_security_number", "identifikationsnummer": "id_number",
    # urchade (English labels)
    "company": "organization", "city": "location", "country": "location", "birth date": "date_of_birth",
    "birthdate": "date_of_birth", "date of birth": "date_of_birth", "phone number": "phone",
    "credit card number": "credit_card", "bank account number": "account_number", "account number": "account_number",
    "bic": "bic", "tax identification number": "tax_id", "tax id number": "tax_id", "tax id": "tax_id",
    "social security number": "social_security_number", "passport number": "id_number",
    "personal identification number": "id_number", "personal id number": "id_number", "id number": "id_number",
    "driver's license number": "id_number", "health insurance id number": "insurance_number",
    "health insurance number": "insurance_number", "insurance number": "insurance_number",
}

# Our label -> detector types that count as the right type (eval "typed").
TYPE_MAP: dict[str, set[str]] = {
    "person": {"person"}, "organization": {"organization"}, "location": {"location", "address"},
    "address": {"address", "location"}, "date": {"date", "date_of_birth"}, "date_of_birth": {"date_of_birth", "date"},
    "phone": {"phone"}, "email": {"email"}, "iban": {"iban"}, "bic": {"bic"}, "credit_card": {"credit_card"},
    "money": {"money"}, "tax_id": {"tax_id", "tax_number"}, "tax_number": {"tax_number", "tax_id"},
    "social_security_number": {"social_security_number"},
}

# Our label -> NER training label; None = left out of the loss ("missing"), absent = O.
NER_LABELS: dict[str, str | None] = {"person": "PER", "organization": "ORG", "location": "LOC",
                                     "public_body": None, "address": None}

_TITLE = re.compile(r"^(?:(?:Frau|Herrn?|Hr\.|Fr\.|Dr\.|Prof\.|med\.|jur\.|rer\.|nat\.|Mr\.|Mrs\.|Ms\.)\s+)+")
_MAPA_NOT_PERSON = {"TITLE", "ROLE", "NATIONALITY", "PROFESSION", "AGE", "MARITAL STATUS", "SEX", "ETHNIC CATEGORY"}
_DE_WORDS = {"der", "die", "das", "und", "ist", "nicht", "mit", "ein", "eine", "von", "zu", "den", "im", "für",
             "auf", "sich", "wurde", "hat"}


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url) as r:  # noqa: S310 - fixed Hugging Face URLs
        return r.read()


def _parquet(url: str) -> list[dict]:
    import pyarrow.parquet as pq  # noqa: PLC0415

    return pq.read_table(io.BytesIO(_fetch(url))).to_pylist()


def _held_out(key: str) -> bool:
    return int(hashlib.sha1(key.encode()).hexdigest(), 16) % 5 == 0


def _span(text: str, start: int, end: int, label: str) -> dict | None:
    """Our label for a source span; person spans without salutation and title."""
    ours = LABELS.get(label.lower())
    if not ours:
        return None
    if ours == "person" and (m := _TITLE.match(text[start:end])) and start + m.end() < end:
        start += m.end()
    return {"start": start, "end": end, "label": ours}


def from_bio(tokens: list[str], tags: list[str]) -> tuple[str, list[dict]]:
    """Tokens and BIO tags -> detokenized text and spans with our labels."""
    ents, cur = [], None
    for i, tag in enumerate(tags):
        if tag.startswith("B-") or (tag.startswith("I-") and (cur is None or cur[2] != tag[2:])):
            cur = [i, i, tag[2:]]
            ents.append(cur)
        elif tag.startswith("I-"):
            cur[1] = i
        else:
            cur = None
    return from_token_spans(tokens, ents)


def detokenize(tokens: list[str]) -> str:
    """Undo word/punctuation splitting, so that "15 . Mai", "max . muster @ web . de" and "+ 49 30" read as
    written ("15. Mai", "max.muster@web.de", "+49 30"); otherwise no detector could find them."""
    text = ""
    for i, tok in enumerate(tokens):
        prev = tokens[i - 1] if i else ""
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        glue = (not i or tok in {".", ",", ":", ";", "!", "?", ")", "%", "@"} or prev in {"(", "@", "+"}
                # "123 - 45", "12 / 34": the joiner sits between two words or numbers
                or (tok in {"-", "/"} and prev[-1:].isalnum() and (nxt[:1].islower() or nxt[:1].isdigit()))
                # after a glued joiner, a lower-case word or a number continues it: "max.muster", "25.05",
                # "123-45"; a capital starts the next word ("15. Mai", "Er kam. Dann")
                or (prev in {".", "-", "/"} and not text.endswith(" ") and i >= 2 and tokens[i - 2][-1:].isalnum()
                    and (tok[:1].islower() or tok[:1].isdigit())))
        text += tok if glue else " " + tok
    return text


def from_token_spans(tokens: list[str], ents: list, text: str | None = None) -> tuple[str, list[dict]] | None:
    """GLiNER style [first_token, last_token, label] -> spans. Tokens are located in ``text`` when given."""
    if text is None:
        text = detokenize(tokens)
    offsets, pos = [], 0
    for tok in tokens:
        i = text.find(tok, pos)
        if i < 0:
            return None
        offsets.append((i, i + len(tok)))
        pos = i + len(tok)
    spans = [s for a, b, lab in ents if (s := _span(text, offsets[a][0], offsets[b][1], lab))]
    return text, spans


def _bio_list(v) -> list[str]:
    return ast.literal_eval(v) if isinstance(v, str) else list(v)


def convert(source: str) -> dict[str, list[dict]]:
    """{split: [{id, text, entities}]} for the German part of one source."""
    out: dict[str, list[dict]] = {"train": [], "test": []}
    if source == "smartdata":
        for split in ("train", "test"):
            for r in _parquet(f"{HF}/DFKI-SLT/smartdata-corpus/resolve/main/ner/{split}-00000-of-00001.parquet"):
                text, spans = from_bio(_bio_list(r["tokens"]), _bio_list(r["ner_tags"]))
                out[split].append({"id": r["id"], "text": text, "entities": spans})
    elif source == "mapa":
        for split in ("train", "test"):
            docs: dict[str, list[dict]] = {}
            for line in _fetch(f"{HF}/joelniklaus/mapa/resolve/main/{split}.jsonl").decode("utf-8").splitlines():
                r = json.loads(line)
                if r["language"] == "de":
                    docs.setdefault(r["file_name"], []).append(r)
            for name, sents in docs.items():
                for r in sorted(sents, key=lambda r: int(r["sentence_number"])):
                    # Coarse PERSON also covers titles, roles and nationalities ("GENERALANWÄLTIN"): those are O.
                    tags = ["O" if f[2:] in _MAPA_NOT_PERSON else c
                            for c, f in zip(_bio_list(r["coarse_grained"]), _bio_list(r["fine_grained"]), strict=True)]
                    text, spans = from_bio(_bio_list(r["tokens"]), tags)
                    out[split].append({"id": f"{name}:{r['sentence_number']}", "text": text, "entities": spans})
    elif source == "e3jsi":
        rows = _parquet(f"{HF}/E3-JSI/synthetic-multi-pii-ner-v1/resolve/main/data/train-00000-of-00001.parquet")
        for i, r in enumerate(r for r in rows if r["language"] == "German"):
            conv = from_token_spans(list(r["gliner_tokenized_text"]), json.loads(r["gliner_entities"]), r["text"])
            if conv:
                key = f"e3jsi:{i}"
                out["test" if _held_out(r["text"]) else "train"].append({"id": key, "text": conv[0], "entities": conv[1]})
    elif source == "urchade":
        rows = json.loads(_fetch(f"{HF}/urchade/synthetic-pii-ner-mistral-v1/resolve/main/data.json"))
        for i, r in enumerate(rows):
            toks = r["tokenized_text"]
            if sum(t.lower() in _DE_WORDS for t in toks) < 3:
                continue
            text, spans = from_token_spans(toks, r["ner"])
            out["test" if _held_out(text) else "train"].append({"id": f"urchade:{i}", "text": text, "entities": spans})
    else:
        raise ValueError(source)
    return out


def cmd_download(data: Path, sources: list[str]) -> None:
    for source in sources:
        for split, docs in convert(source).items():
            path = data / source / f"{split}.jsonl.gz"
            path.parent.mkdir(parents=True, exist_ok=True)
            # mtime=0: the same data gives the same bytes, so a new download leaves git clean.
            with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
                gz.write("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in docs).encode("utf-8"))
            print(f"{path}: {len(docs)} docs, {sum(len(d['entities']) for d in docs)} spans")


def load(data: Path, source: str, split: str = "test") -> list[tuple[str, str, list[tuple[int, int, str]]]]:
    """(key, text, [(start, end, label)]) per document."""
    with gzip.open(data / source / f"{split}.jsonl.gz", "rt", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh]
    return [(f"{source}:{r['id']}", r["text"], [(e["start"], e["end"], e["label"]) for e in r["entities"]])
            for r in rows]


def ner_spans(data: Path, sources: list[str]) -> list[tuple[str, list[tuple[int, int, str]], list[tuple[int, int]]]]:
    """Training split as (text, spans with PER/ORG/LOC, missing) for ner_train.py."""
    out = []
    for source in sources:
        if not (data / source / "train.jsonl.gz").exists():
            continue
        for _, text, gold in load(data, source, "train"):
            spans = []
            # Synthetic sources may give one string two labels; spaCy needs non-overlapping entities.
            for s, e, lab in sorted(gold, key=lambda g: (g[0], -g[1])):  # the longer span wins
                if NER_LABELS.get(lab) and not any(s < e2 and s2 < e for s2, e2, _ in spans):
                    spans.append((s, e, NER_LABELS[lab]))
            missing = [(s, e) for s, e, lab in gold if lab in NER_LABELS and NER_LABELS[lab] is None
                       and not any(s < e2 and s2 < e for s2, e2, _ in spans)]
            out.append((text, spans, missing))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["download", "eval"])
    ap.add_argument("--data", type=Path, default=Path("datasets/public"))
    ap.add_argument("--source", default="all", choices=["all", *SOURCES])
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    sources = SOURCES if a.source == "all" else [a.source]
    if a.cmd == "download":
        cmd_download(a.data, sources)
        return
    from finance_data import cmd_eval, print_report  # noqa: PLC0415 - same scripts folder

    print_report(cmd_eval(a.data, sources, a.limit, load_fn=load, type_map=TYPE_MAP, title="public"))

if __name__ == "__main__":
    sys.exit(main())
