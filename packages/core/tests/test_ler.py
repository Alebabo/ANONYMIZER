"""German LER conversion: offsets stay exact, anonymized values get synthetic names, splits never share names."""

from anonymizer.ler import Names, Sentence, build_docs, detokenize, read_conll, sentence_doc

CONLL = """Herrn O
Rechtsanwalt O
F B-AN
wurde O
beigeordnet O
. O

Die O
D B-UN
P I-UN
T I-UN
S I-UN
GmbH I-UN
mit O
Sitz O
in O
B. B-ST
klagt O
vor O
dem O
Bundesgerichtshof B-GRT
( O
§ B-GS
823 I-GS
BGB I-GS
) O
. O
"""


def test_detokenize_keeps_offsets():
    text, offs = detokenize(["Urteil", "(", "§", "823", "BGB", ")", ",", "rechtskräftig", "."])
    assert text == "Urteil (§ 823 BGB), rechtskräftig."
    assert [text[a:b] for a, b in offs] == ["Urteil", "(", "§", "823", "BGB", ")", ",", "rechtskräftig", "."]


def test_anonymized_values_get_synthetic_names_and_exact_spans():
    sents = list(read_conll(CONLL.splitlines(keepends=True)))
    names = Names(seed=1, held_out=False)
    text, spans = sentence_doc(sents[0], names)
    per = next(s for s in spans if s.label == "PER")
    assert text[per.start:per.end] in names.last  # after "Rechtsanwalt" a surname
    text, spans = sentence_doc(sents[1], names)
    got = {s.label: text[s.start:s.end] for s in spans}
    assert got["ORG"].endswith(" GmbH") and len(got["ORG"].split()) == 2  # "D P T S" became one name
    assert got["LOC"] in names.cities and got["GRT"] == "Bundesgerichtshof" and got["GS"] == "§ 823 BGB"


def test_train_and_held_out_names_are_disjoint():
    a, b = Names(1, held_out=False), Names(1, held_out=True)
    assert not set(a.last) & set(b.last) and not set(a.cities) & set(b.cities)


def test_docs_group_sentences_and_spans_match_text():
    sents = list(read_conll(CONLL.splitlines(keepends=True))) * 4
    docs = build_docs(sents, "dev", per_doc=3)
    assert [len(d.text) > 0 for d in docs] == [True, True, True] and docs[0].split == "dev"
    for d in docs:
        for s in d.spans:
            assert d.text[s.start:s.end] == d.text[s.start:s.end].strip() and s.end > s.start
    plain = build_docs([Sentence(["Rechtsanwalt", "F"], ["O", "B-AN"])], "test", reinsert=False)[0]
    assert plain.text == "Rechtsanwalt F" and plain.spans[0].label == "PER"
