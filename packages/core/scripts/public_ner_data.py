"""Download the public NER corpora that ner_train.py reads from local/ner/public/ (not committed).

    python packages/core/scripts/public_ner_data.py download [--dir local/ner] [--force]
    python packages/core/scripts/public_ner_data.py check

Files and licences (both CC BY 4.0, see THIRD_PARTY_NOTICES.md):
  - GermEval 2014 NER, original TSV files, mirrored by stefan-it on Hugging Face
    -> local/ner/public/germeval14/{train,dev,test}.tsv   (ner_train.py uses train.tsv automatically)
  - MultiCoNER v2, German part
    -> local/ner/public/hf/multiconer2/de_{train,dev}.conll (ner_train.py --multiconer <de_train.conll>)

Every file is checked against a pinned SHA-256; a mismatch is an error and the file is not kept. Behind a company
proxy set HTTPS_PROXY (and, if needed, SSL_CERT_FILE for the company CA).

Internal training data (gold.jsonl, OCR letters, test-customer names) is not public and is never downloaded here.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

HF = "https://huggingface.co/datasets"
FILES: list[tuple[str, str, str]] = [
    ("public/germeval14/train.tsv", f"{HF}/stefan-it/germeval14_no_wikipedia/resolve/main/original/NER-de-train.tsv",
     "98682c21700e5bd7959ac361150679929e4af5d91e4dd7c379cc89133a810994"),
    ("public/germeval14/dev.tsv", f"{HF}/stefan-it/germeval14_no_wikipedia/resolve/main/original/NER-de-dev.tsv",
     "2ffe8405acc6bb6111b62a88623aa1e1f2e6db16b77fc005c54163541807aa05"),
    ("public/germeval14/test.tsv", f"{HF}/stefan-it/germeval14_no_wikipedia/resolve/main/original/NER-de-test.tsv",
     "ec6e6adce5ed71cee119ae758e569ea4be54c6be5319b3b49dfcdcb05e51301b"),
    ("public/hf/multiconer2/de_train.conll", f"{HF}/MultiCoNER/multiconer_v2/resolve/main/DE-German/de_train.conll",
     "4bc6b1b2ae3cc59daa1f5fa8c8b403768fd224e6565b4aae580d3de434694256"),
    ("public/hf/multiconer2/de_dev.conll", f"{HF}/MultiCoNER/multiconer_v2/resolve/main/DE-German/de_dev.conll",
     "f998cedd47546190bfb0afc95671a6209f7849e16e36570968df9b6b0a3d6f43"),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check(base: Path) -> int:
    missing = 0
    for rel, _, digest in FILES:
        path = base / rel
        state = "ok" if path.exists() and sha256(path) == digest else "missing" if not path.exists() else "WRONG HASH"
        missing += state != "ok"
        print(f"{state:10} {path}")
    return missing


def download(base: Path, force: bool) -> None:
    for rel, url, digest in FILES:
        path = base / rel
        if path.exists() and not force and sha256(path) == digest:
            print(f"ok         {path}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        print(f"download   {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "openanonymizer-data/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:  # noqa: S310 - fixed https URLs
            while block := resp.read(1 << 20):
                out.write(block)
        got = sha256(tmp)
        if got != digest:
            tmp.unlink()
            sys.exit(f"SHA-256 mismatch for {url}: expected {digest}, got {got}")
        tmp.replace(path)
        print(f"saved      {path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["download", "check"])
    ap.add_argument("--dir", default="local/ner", type=Path)
    ap.add_argument("--force", action="store_true", help="download again even if the file is present and valid")
    args = ap.parse_args()
    if args.cmd == "download":
        download(args.dir, args.force)
    sys.exit(1 if check(args.dir) else 0)


if __name__ == "__main__":
    main()
