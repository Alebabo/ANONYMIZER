# Anonymization & Vault

`packages/core/src/anonymizer/anonymize/` transforms detected values. `packages/core/src/anonymizer/vault/` stores the re-identification mapping in encrypted form.

## Methods

| Method | Example | Reversible |
|---|---|---|
| `keep` | unchanged | – |
| `redact` | Max Mustermann → `[REDACTED]` (optionally `[REDACTED:PERSON]`) | no |
| `replace` | Max Mustermann → `PERSON_001`, numbered per occurrence, no linkage | no |
| `pseudonymize` | same entity → same placeholder, also across documents within a namespace | with vault |
| `generalize` | 15.03.1985 → `1985`, address → city, 4.850,00 EUR → `1.000–10.000 EUR` | no |
| `mask` | `DE89 **** **** **** **30 00`, `e***@example.org` | no |
| `tokenize` | opaque random token `TKN_3f9a0c1b2d4e` | with vault |

### Default methods per type

The policy engine (step 4) overrides these defaults with a plan per detection.

| Types | Method |
|---|---|
| person, organization, email, phone, address, case number, location | `pseudonymize` |
| IBAN, card, BIC, tax ID, social security number, VAT ID | `redact` |
| special categories (health, criminal record, ...) | `redact` |
| date of birth | `generalize` |
| court, legal citation, date, amount, privilege/business-secret markers | `keep` |
| unknown or custom types | `redact` (fail closed) |

## Consistency

- **Within a document:** all mentions of a person share the same placeholder. "Max Mustermann" and "Mustermann" both become `PERSON_001`, via the `ref` from detection.
- **Across documents:** consistency runs through the vault, per namespace (e.g. one namespace per matter). The key is an HMAC of the normalized canonical value.
  - **Limitation:** if a second document only says "Mustermann", that's a different canonical value and gets a new placeholder.
- **Roles:** `include_role=True` adds the procedural role to the placeholder (`PERSON_001 (Mandant)`). This keeps plaintiff, defendant and counsel distinguishable for the LLM.

## Vault: security properties

- **AES-256-GCM** per entry, with namespace and placeholder as authenticated data. Swapping entries between placeholders is detected.
- **Separate key management:** the master key comes from `ANONYMIZER_VAULT_KEY` (base64, 32 bytes) or a KMS, never from the vault file. HKDF derives separate keys for encryption and the index.
- **No plaintext in storage:** values and namespace names appear only as HMACs or ciphertext. Tests check the vault file for this, and also that it has permissions `0600`.
- **Namespace isolation:** a placeholder from `matter-1` can't be resolved in `matter-2`.
- **Wrong key or tampered data** raise a `VaultError` instead of returning wrong values.
- **The anonymization result holds no mapping.** It contains only the transformed text, the replacements and offsets. A vault is a separate object and stays inside the trusted boundary.
- **Without a vault**, pseudonyms are consistent within one call but can't be restored (ephemeral key).

Generate a key:

```bash
export ANONYMIZER_VAULT_KEY=$(python -c "from anonymizer.vault import VaultKey; print(VaultKey.generate().to_b64())")
```

## Safety net

1. **Sweep:** further occurrences of a transformed value that detection missed get the same replacement (`swept=true`). Matching ignores case and tolerates a line break inside the value, so it covers what the leak check would otherwise reject. Side effect: a value that is also a common word (city "Essen" vs. verb "essen") is replaced in both places.
2. **Leak check:** after the transformation, every transformed original value is searched in the output (normalized, case-insensitive). In `strict` mode (the default) any hit raises a `LeakError`, so nothing goes out.

The leak check only finds values that were **detected**. A name that detection misses completely won't be found by the leak check either. Detection quality remains the limiting factor.

## Restore

`restore(text, vault, namespace)` replaces placeholders and tokens, e.g. in an LLM answer.

- Placeholder-shaped strings that the model invented (`PERSON_042`) stay unchanged and are reported in `unresolved`.
- A pseudonym is restored to the canonical value, i.e. the longest mention ("Mustermann" → "Max Mustermann").
- Use it only inside the protected environment and only for authorized users. The API (step 5) secures `/v1/restore` with its own admin key.

## Diff

`build_diff(original_text, result)` returns segments (`equal`/`changed`) for the original / anonymized / diff view in the dashboard. The original text has to be supplied by the caller, because the result deliberately doesn't contain it.

## CLI

```bash
anonymizer anonymize brief.txt                                   # ephemeral, not reversible
anonymizer anonymize brief.txt --vault vault.json --namespace matter-17
anonymizer restore answer.txt --vault vault.json --namespace matter-17
```

## Known limitations

- **Placeholders are only consistent across documents for identical canonical values** (see above).
- **Generalizing addresses** only works with a postcode + city (DE) or "City, ST" (US). Otherwise the type label `[ADDRESS]` is used.
- **Plain text only.** Preserving structure and formatting for PDF/DOCX requires a parser that maps offsets back. That's not part of step 3.
- **FileVault is for single-node self-hosting.** Concurrent writers from several processes are not synchronized; Postgres storage comes later.

## Documents (PDF, DOCX)

`anonymizer.documents.protect_document()`, `POST /v1/documents/protect` and the MCP tool `read_document_protected` process documents.

| Format | Processing |
|---|---|
| DOCX | Anonymized in place: formatting of untouched text and of the run containing the replacement is preserved. Covers tables, headers and footers. Document properties (author, title, ...) are cleared |
| PDF | Text layer only. The result is anonymized **text**, not a redacted PDF |
| TXT/MD | Like text |

### Safety rules

- **Format by content:** the format is detected from the file content (magic bytes), not from the file name. A false extension is rejected.
- **Size and zip bombs:** uploads are size-limited. DOCX is checked for zip bombs before parsing.
- **Into review:** these situations go to review (`review`), because they can't be anonymized safely:
  - comments, tracked changes and embedded objects in DOCX;
  - PDF pages without a text layer (scans): read by local OCR and flagged for review; without OCR reported as unreadable.
  - Images (PNG, JPEG, TIFF): OCR only, always flagged for review.
- **Independent check:** after rewriting a DOCX, its text is extracted again and checked for remaining original values.
- **Images in DOCX** stay unchanged and are not inspected (`notes`).

### Limitations

- **OCR is local Tesseract (German).** Scanned PDF pages and images are rendered and recognized on the machine
  (`anonymizer/ocr.py`): input via stdin, no temporary files, minimal environment, and on Linux in a network
  namespace without network (`ANONYMIZER_OCR_ISOLATION=auto|require|off`). Docker blocks unprivileged
  namespaces by default; there the container's network policy is the barrier. Recognition errors
  ("Mustermarm") can hide names from detection, so every OCR page is a document warning and goes to review
  under policies that review uncertain documents. Handwriting and poor scans are read badly.
  Install: `apt-get install tesseract-ocr tesseract-ocr-deu` and `pip install -e "packages/core[ocr]"`.
- **PDF output is plain text.** A visually redacted PDF would need a PDF library with real content removal. The common option, PyMuPDF, is AGPL-licensed and therefore deliberately not used.
- **Hyperlinks and fields in DOCX:** if an affected paragraph contains them, it is rebuilt as a single run. Inline formatting of that one paragraph is lost.
