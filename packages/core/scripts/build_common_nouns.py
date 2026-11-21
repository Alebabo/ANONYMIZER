"""Build the German common-noun list used to reject one-word NER hits such as "Geld", "Dank" or "Betrag".

    python packages/core/scripts/build_common_nouns.py [--germeval local/ner/public/germeval14/train.tsv]

Source: GermEval 2014 NER train split (CC BY 4.0). A word is listed if it is capitalised, occurs at least three
times outside sentence starts with the tag O, and is part of an entity in at most one case in ten. Surnames that
are also words ("Koch", "Wolf", "Becker") are left out.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

OUT = Path(__file__).parents[1] / "src" / "anonymizer" / "detect" / "data" / "common_nouns_de.txt"
# Frequent German surnames that are also nouns or adjectives: a one-word hit on them may well be a name.
SURNAMES = {
    "Koch", "Wolf", "Fischer", "Schneider", "Becker", "Weber", "Meyer", "Wagner", "Bauer", "Richter", "Klein",
    "Schwarz", "Braun", "Lange", "Vogel", "Fuchs", "Hahn", "Kaiser", "König", "Graf", "Jung", "Frank", "Krause",
    "Schäfer", "Zimmermann", "Hoffmann", "Schmitt", "Herrmann", "Walter", "Peters", "Schulz", "Keller", "Berger",
    "Winter", "Sommer", "Engel", "Busch", "Stein", "Roth", "Kraft", "Lang", "Bach", "Brandt", "Haas", "Schuster",
    "Pohl", "Arnold", "Dietrich", "Kuhn", "Albrecht", "Schreiber", "Ludwig", "Vogt", "Beck", "Simon", "Kühn",
    "Baumann", "Seidel", "Heinrich", "Kaufmann", "Meier", "Mayer", "Huber", "Schuhmacher", "Schubert", "Frey",
    "Bergmann", "Pfeiffer", "Voigt", "Ernst", "Martin", "Thomas", "Paul", "Adam", "Glück", "Hase", "Strauß",
    "Storch", "Kranich", "Falke", "Adler", "Hirsch", "Bock", "Ochs", "Morgen", "Abend", "Freitag", "Sonntag",
    "Montag", "Kirch", "Kirchner", "Gärtner", "Fleischer", "Schmied", "Wirth", "Wirt", "Pfarrer", "Schulte",
    "Holz", "Kurz", "Groß", "Lustig", "Fröhlich", "Ehrlich", "Freund", "Gast", "Kind", "Mann", "Rose", "Blume",
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--germeval", type=Path, default=Path("local/ner/public/germeval14/train.tsv"))
    args = ap.parse_args()
    plain, in_entity = Counter(), Counter()
    for line in args.germeval.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        idx, tok, tag = int(cols[0]), cols[1], cols[2]
        if tag != "O" or (len(cols) > 3 and cols[3] != "O"):
            in_entity[tok] += 1
        elif idx > 1:
            plain[tok] += 1
    words = sorted(w for w, n in plain.items()
                   if n >= 3 and len(w) >= 3 and w.isalpha() and w[0].isupper() and not w.isupper()
                   and in_entity[w] * 10 <= n and w not in SURNAMES)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("# German common nouns from GermEval 2014 (CC BY 4.0), see scripts/build_common_nouns.py\n"
                   + "\n".join(words) + "\n", encoding="utf-8")
    print(f"{len(words)} words -> {OUT}")
    # Lower-case words (verbs, adjectives, function words) for chat typed in lower case ("kontomodell wechseln").
    lower = sorted(w for w, n in plain.items()
                   if n >= 5 and len(w) >= 2 and w.isalpha() and w.islower() and in_entity[w] * 10 <= n)
    out = OUT.with_name("common_words_de.txt")
    out.write_text("# Lower-case German words from GermEval 2014 (CC BY 4.0), see scripts/build_common_nouns.py\n"
                   + "\n".join(lower) + "\n", encoding="utf-8")
    print(f"{len(lower)} words -> {out}")


if __name__ == "__main__":
    main()
