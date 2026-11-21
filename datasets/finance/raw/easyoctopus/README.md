---
language:
- de
license: apache-2.0
task_categories:
- token-classification
configs:
- config_name: default
  default: true
  data_files:
  - split: train
    path: data/train.jsonl
  - split: validation
    path: data/validation.jsonl
  - split: test
    path: data/test.jsonl
- config_name: replay
  data_files:
  - split: train
    path: replay/replay.jsonl
---

# German support PII synthetic dataset

Apache-2.0. Scenario families and their 2 phrasing templates were assigned to a split before rendering. Normalised exact text comparisons found zero overlaps between the new splits and the earlier datasets named in provenance.json. The optional replay configuration contains 1,024 prior training rows. It is intentionally shared with v1 training and is outside the new train, validation and test splits.

| Split | Messages | Scenarios | Templates | Annotations |
|---|---:|---:|---:|---:|
| train | 784 | 14 | 28 | 1,120 |
| validation | 112 | 7 | 14 | 160 |
| test | 176 | 11 | 22 | 256 |

The gold array contains ordered half-open Unicode code-point spans with service labels. Protection requires hiding every non-whitespace character, including punctuation. Hard negatives include public dates, prices, routes and product references. The new scenarios annotate person, organization, address, email, phone, date of birth, customer ID, order ID, account ID, tax ID, insurance ID, IP address, IBAN, BIC and payment card.

The training messages and newly generated test messages are fictional. Repeated slot draws within a template are correlated. Split families are disjoint but use the same authoring process. These results do not measure protection or dictation quality on customer messages.

## Download and use

This dataset was created by **Mahir Isikli (EasyOctopus)**. Its companion checkpoint is [EasyOctopus/german-support-pii-model](https://huggingface.co/EasyOctopus/german-support-pii-model).

Install Hugging Face Datasets and load the public repository by ID.

```python
from datasets import load_dataset

dataset = load_dataset("EasyOctopus/german-support-pii-data", "default")
message = dataset["test"][0]
print(message["text"], message["gold"])
replay = load_dataset("EasyOctopus/german-support-pii-data", "replay", split="train")
```

The repository includes `example.py --self-test` to check annotation alignment, hashes and split separation. Run `uv run --script generate.py --output new-splits` from a downloaded copy to regenerate the 3 scenario splits. A different seed changes slot values while retaining the scenario assignments. LICENSE, NOTICE and provenance.json record source attribution.
