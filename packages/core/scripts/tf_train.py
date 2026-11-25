"""Fine-tune a transformer token classifier (Hugging Face) as German NER, on the data of ner_train.py.

    python -I packages/core/scripts/tf_train.py --model deepset/gbert-base --ler datasets/ler --courts datasets/courts \
        --org-repeat 2 --public datasets/public --epochs 3 --out local/ner/models/cato-tf-gbert

Experiment (see docs/research/transformer-ner.md). Same data, same flags and the same dev selection as
ner_train.py (collect()); every ner_train.py flag works here. Tokens come from Cato's tokenizer, so the words seen
in training are the words the pipeline passes at runtime (detect/hf_ner.py). Missing tokens ("-", e.g. addresses,
unchecked capitalised words in court decisions) are left out of the loss. Labels: B-/I- of PER, ORG, LOC, MISC.

Each epoch is scored with the full pipeline (rules + Cato tagger + this NER) on the dev split; the best epoch is
saved to --out as a Hugging Face model directory. Measure it like Cato:

    ANONYMIZER_NER_MODEL_DE="packages/core/models/cato-1.1+local/ner/models/cato-tf-gbert" \
        python packages/core/scripts/ler_data.py eval --split test

The path must contain "cato" (signature-line check in detect/ner.py), as for ner_train.py models.
Needs torch and transformers. Uses a CUDA GPU when there is one (mixed precision). gbert-base on the full data
(about 55,000 windows): about 10 s per step of 16 on a 4-core laptop CPU (9.5 h per epoch); on a GPU minutes.
--max-steps for a smoke test. Cloud run: notebooks/tf_train_kaggle.ipynb.
"""

from __future__ import annotations

import json
import math
import random
import shutil
import sys
import time
from pathlib import Path

import spacy

sys.path.insert(0, str(Path(__file__).parent))
from ner_train import build_parser, collect, evaluate  # noqa: E402

from anonymizer.detect.hf_ner import replace_ner  # noqa: E402
from anonymizer.detect.ner import CATO  # noqa: E402

LABELS = ["O", "B-PER", "I-PER", "B-ORG", "I-ORG", "B-LOC", "I-LOC", "B-MISC", "I-MISC"]
IGNORE = -100


def to_bio(tags: list[str]) -> list[str | None]:
    """BILUO with "-" (missing) -> BIO, None = left out of the loss. Unknown labels become O."""
    out: list[str | None] = []
    for t in tags:
        if t == "-" or t is None:
            out.append(None)
            continue
        kind, _, name = t.partition("-")
        if t == "O" or f"B-{name}" not in LABELS:
            out.append("O")
        else:
            out.append(("B-" if kind in ("B", "U") else "I-") + name)
    return out


def windows(tokenizer, examples, max_length: int, stride: int) -> list[dict]:
    """Examples -> windows of subword ids with labels on the first subword of each word."""
    label_id = {lab: i for i, lab in enumerate(LABELS)}
    out = []
    for ex in examples:
        doc = ex.reference
        tags = to_bio(ex.to_dict()["doc_annotation"]["entities"])
        keep = [t.i for t in doc if not t.is_space]  # as detect/hf_ner.py at runtime
        words = [doc[i].text for i in keep]
        labels = [tags[i] for i in keep]
        if not words or all(lab is None for lab in labels):
            continue
        enc = tokenizer(words, is_split_into_words=True, truncation=True, max_length=max_length, stride=stride,
                        return_overflowing_tokens=True)
        for w in range(len(enc["input_ids"])):
            prev, ids = None, []
            for wid in enc.word_ids(w):
                if wid is None or wid == prev:
                    ids.append(IGNORE)
                else:
                    ids.append(IGNORE if labels[wid] is None else label_id[labels[wid]])
                prev = wid
            if any(i != IGNORE for i in ids):
                out.append({"input_ids": enc["input_ids"][w], "labels": ids})
    return out


def batches(rows: list[dict], size: int, pad_id: int, rng: random.Random):
    """Batches of similar length (less padding on CPU): sort in shuffled chunks, then shuffle the batches."""
    import torch  # noqa: PLC0415

    rows = rows[:]
    rng.shuffle(rows)
    chunk = size * 50
    groups = []
    for i in range(0, len(rows), chunk):
        part = sorted(rows[i:i + chunk], key=lambda r: len(r["input_ids"]))
        groups += [part[j:j + size] for j in range(0, len(part), size)]
    rng.shuffle(groups)
    for g in groups:
        n = max(len(r["input_ids"]) for r in g)
        ids = torch.full((len(g), n), pad_id)
        lab = torch.full((len(g), n), IGNORE)
        mask = torch.zeros((len(g), n), dtype=torch.long)
        for k, r in enumerate(g):
            m = len(r["input_ids"])
            ids[k, :m] = torch.tensor(r["input_ids"])
            lab[k, :m] = torch.tensor(r["labels"])
            mask[k, :m] = 1
        yield {"input_ids": ids, "attention_mask": mask, "labels": lab}


def local_base(name: str, cache: Path) -> str:
    """Hub id or path -> a directory transformers can load. Old German models (deepset/gbert-*) ship a config.json
    without "model_type"; a copy with "model_type": "bert" is made under ``cache``."""
    if Path(name).is_dir():
        return name
    from huggingface_hub import snapshot_download  # noqa: PLC0415

    src = Path(snapshot_download(name, allow_patterns=["*.json", "*.txt", "*.model", "model.safetensors"]))
    config = json.loads((src / "config.json").read_text(encoding="utf-8"))
    if "model_type" in config:
        return str(src)
    dst = cache / name.replace("/", "__")
    if not (dst / "config.json").is_file():
        shutil.copytree(src, dst, dirs_exist_ok=True)
        arch = " ".join(config.get("architectures", [])).lower()
        config["model_type"] = "electra" if "electra" in arch else "bert"
        (dst / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return str(dst)


def score(path: Path, dev_docs, limit: int) -> dict:
    nlp = replace_ner(spacy.load(CATO, disable=["parser", "lemmatizer"]), str(path))
    return evaluate(nlp, dev_docs[:limit or None], str(CATO))


def main() -> None:
    ap = build_parser()
    ap.description = __doc__
    ap.add_argument("--model", default="deepset/gbert-base", help="Hugging Face encoder to fine-tune")
    ap.add_argument("--max-length", type=int, default=256, help="subword tokens per training window")
    ap.add_argument("--stride", type=int, default=64)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--warmup", type=float, default=0.06, help="share of steps with rising learning rate")
    ap.add_argument("--max-steps", type=int, default=0, help="stop after N steps (smoke test); 0 = all epochs")
    ap.add_argument("--dev-limit", type=int, default=0, help="dev docs scored per epoch (0 = all)")
    ap.add_argument("--no-fp16", action="store_true", help="on a GPU, train in float32 instead of mixed precision")
    ap.add_argument("--threads", type=int, default=0, help="torch CPU threads (0 = torch default)")
    ap.set_defaults(base=str(CATO), epochs=3, out=Path("local/ner/models/cato-tf"))
    args = ap.parse_args()

    import torch  # noqa: PLC0415
    from transformers import AutoModelForTokenClassification, AutoTokenizer, get_linear_schedule_with_warmup  # noqa: PLC0415

    if args.threads:
        torch.set_num_threads(args.threads)
    rng = random.Random(args.seed)
    torch.manual_seed(args.seed)
    nlp = spacy.load(args.base, disable=["parser", "lemmatizer"])
    examples, dev_docs, data = collect(args, nlp, rng)

    base = local_base(args.model, Path("local/hf/models"))
    tokenizer = AutoTokenizer.from_pretrained(base)
    rows = windows(tokenizer, examples, args.max_length, args.stride)
    print(f"{len(examples)} examples -> {len(rows)} windows, "
          f"{sum(len(r['input_ids']) for r in rows)} subword tokens", flush=True)
    model = AutoModelForTokenClassification.from_pretrained(
        base, num_labels=len(LABELS), id2label=dict(enumerate(LABELS)),
        label2id={lab: i for i, lab in enumerate(LABELS)})
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    amp = device == "cuda" and not args.no_fp16
    scaler = torch.amp.GradScaler("cuda", enabled=amp)
    print(f"device {device}, fp16 {amp}", flush=True)
    steps_per_epoch = math.ceil(len(rows) / args.batch_size)
    total = min(args.max_steps or 10**12, steps_per_epoch * args.epochs)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    sched = get_linear_schedule_with_warmup(opt, int(total * args.warmup), total)

    args.out.mkdir(parents=True, exist_ok=True)
    ckpt = args.out.parent / f"{args.out.name}.epoch"
    history, best, best_f1, step, t0 = [], 0, -1.0, 0, time.time()
    for epoch in range(args.epochs):
        model.train()
        loss_sum = 0.0
        for k, batch in enumerate(batches(rows, args.batch_size, tokenizer.pad_token_id, rng)):
            batch = {k: v.to(device) for k, v in batch.items()}
            with torch.autocast(device_type=device, dtype=torch.float16, enabled=amp):
                loss = model(**batch).loss
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            opt.zero_grad()
            loss_sum += loss.item()
            step += 1
            if step % 50 == 0:
                rate = (time.time() - t0) / step
                print(f"epoch {epoch + 1} step {k + 1}/{steps_per_epoch} loss {loss_sum / (k + 1):.4f} "
                      f"{rate:.2f}s/step, rest of run ~{(total - step) * rate / 3600:.1f} h", flush=True)
            if step >= total:
                break
        model.eval()
        model.save_pretrained(ckpt)
        tokenizer.save_pretrained(ckpt)
        dev = score(ckpt, dev_docs, args.dev_limit)
        f1 = dev["micro"]["f1"] or 0.0
        history.append({"epoch": epoch + 1, "loss": round(loss_sum / max(1, k + 1), 4), "dev": dev["micro"]})
        print(f"epoch {epoch + 1}: dev F1={f1} P={dev['micro']['precision']} R={dev['micro']['recall']}", flush=True)
        if f1 > best_f1:
            best, best_f1 = epoch + 1, f1
            shutil.rmtree(args.out, ignore_errors=True)
            shutil.copytree(ckpt, args.out)
        if step >= total:
            break
    shutil.rmtree(ckpt, ignore_errors=True)
    (args.out / "training.json").write_text(json.dumps({
        "model": args.model, "seed": args.seed, "max_length": args.max_length, "batch_size": args.batch_size,
        "lr": args.lr, "steps": step, "best_epoch": best, "history": history, "data": data,
        "public_sources": args.public_sources if args.public else [],
    }, indent=2), encoding="utf-8")
    print(f"best epoch {best}, dev F1 {best_f1}; model saved to {args.out}")


if __name__ == "__main__":
    main()
