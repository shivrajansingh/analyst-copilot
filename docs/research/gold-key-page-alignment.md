# Research: Is the practice answer sheet itself reliable?

**Folder:** `docs/research/`
**Date:** 2026-08-26
**Status:** Concluded — findings acted on (dual-bookkeeping until parser alignment lands)
**Author:** QA review session

---

## 1. Research topic

The practice answer key (`data/practice-questions.jsonl`) is the scoring
authority for this challenge: every model answer is graded against its gold
answer and, critically, against its `evidence_page_num`. The research question:

> **When the key claims a piece of evidence sits on page N of a filing, does
> that evidence actually sit on page N of the document as we parse it?**

If it does not, our system can be penalised for citations that are factually
correct, and internal measurements (gold-page recall@5) are systematically
distorted. This study quantifies the mismatch, identifies its mechanism, and
measures the score impact.

## 2. Motivation

Two observations triggered the audit:

1. Recurring "wrong location" penalties in eval runs looked suspicious:
   `BESTBUY_2019 cited 49 vs gold [51]`, `BLOCK_2020 cited 88 vs gold [89]`,
   `AES_2022 cited 130 vs gold [131]` — all near misses.
2. One question (3M dividend trend) had been marked wrong on location even
   though the model's citation pointed at a page containing the exact dividend
   facts the gold answer restated.

## 3. What is in the key (structure)

136 records, one per practice question. Relevant fields:

| Field | Content |
|---|---|
| `question_type` | metrics-generated ×50, domain-relevant ×50, novel-generated ×36 |
| `answer` | gold answer text (figure or prose) |
| `justification` | how the answer was derived ("directly extracted from…") |
| `evidence[]` | list of `{evidence_page_num, evidence_text, evidence_text_full_page}` |

Evidence lists: 102 questions cite **1** page, 31 cite **2**, 3 cite **3**
(173 evidence items total). Snippet sizes range 67–6,362 chars (median 1,306).

Key construction details inferred during the audit:

- `evidence_page_num` is a **0-based positional index into the key authors' own
  HTML→pages split** of the same EDGAR files — not the printed folio number.
- The extraction pipeline that produced `evidence_text` renders text slightly
  differently from ours: em-dashes are dropped (`Marketable securities current`
  vs our `Marketable securities — current`), and artifacts such as
  `"Balance Shee t"` appear identically on both sides.

## 4. Method

Four experiments, run over all 173 evidence items / all 79 filings.

### 4.1 Snippet containment test

Normalise both sides to lowercase alphanumerics only (`[^a-z0-9]` removed —
this neutralises whitespace, em-dashes and punctuation differences). Take the
first ~300 normalised chars of `evidence_text` as a probe and search every
parsed page of the claimed filing. Classify each item: found on the claimed
page, an adjacent page (±1), further away, or nowhere.

*Why alphanumeric-only:* plain whitespace-collapsing produced a misleading 45%
"not found" rate; manual inspection of the net-PP&E record (`3M_2018_10K`,
page 57) showed the page content matched perfectly once dash/nbsp differences
were neutralised. Matching method, not the key, was at fault there.

### 4.2 Full-page fingerprint test

`evidence_text_full_page` should be near-complete page text. Use its first 250
normalised chars as a fingerprint and locate it in our parse. If the fingerprint
is found at exactly one position, compare it with the claimed page number.
This tests whether the *key is internally consistent*, independent of excerpt
choice.

### 4.3 Offset derivation and rescoring

Where fingerprints locate consistently off-claim for a document, derive a
per-document offset (mode of `found_index − claimed_page`, |offset| ≤ 5).
Rescore the full 136-question candidate run applying corrected gold pages,
holding answer-correctness verdicts fixed — i.e. isolate pure location effects.

### 4.4 Control tests

- **Empty-segment hypothesis:** if the key's indexer counted blank splits we
  drop, indices would shift after the first blank. AES raw split has
  **216 segments, 0 blank** → hypothesis rejected.
- **Printed-footer hypothesis:** if printed folios matched the key's numbering
  better than positional index, citing folios would fix alignment. Measured on
  shifted docs: printed matches claim **3/29**, matches our own index 9/29,
  absent on 8/29 → rejected.

## 5. Findings

### 5.1 Where the evidence actually lives (experiment 4.1)

| Classification of 173 items | Count | Share |
|---|---|---|
| Verbatim (alnum-normalised) on claimed page | 108 | 62% |
| Fuzzy match (≥60% of snippet 12-grams) on claimed page | ~12 | ~7% |
| On adjacent page ±1 | 21 | 12% |
| Elsewhere (>1 page away) | 10+2 | ~7% |
| Not locatable even fuzzily | 16 | 9% |
| **Verifiably on the claimed page (total)** | **~126** | **~73%** |

### 5.2 The key is internally consistent — but its parse diverges (4.2)

Full-page fingerprints: **108 align exactly** with the claimed page, **32 point
elsewhere**, 33 unlocatable (rendering differences too large for substring
matching).

The decisive pattern: misplacements are **uniform within a document**:

| Document | Items sampled | Offset (our index − key page) |
|---|---|---|
| AES_2022_10K | 3 | −1, −1, −1 |
| BOEING_2022_10K | 2 | −2, −2 |
| BLOCK_2020_10K | 2 | −1, −1 |
| GENERALMILLS_2022_10K | 2 | +1, +1 |
| BESTBUY_2017 / 2019 | 1 / 1 | −2 / −2 |
| WALMART_2018 / 2020 | 1 / 1 | −2 / −1 |
| PEPSICO_2021 / 2022, PFIZER_2021, NIKE_2023 | 1 each | −1 |
| AMCOR_2022_8K | 1 | +2 |
| FOOTLOCKER_2022_8K | 1 | +20 (single sample) |

Random key corruption would scatter offsets. A constant shift per document is
the signature of **two parsers segmenting the same HTML slightly differently**:
for these filings the key's splitter produces a different number of pages than
ours before certain points (mechanism not yet localised to a marker class;
empty-segment handling ruled out by 4.4).

### 5.3 Genuine key defects exist but are rare

Case study — *"Does 3M maintain a stable trend of dividend distribution?"*
(`3M_2023Q2_10Q`): key claims page 61. Our page 61 contains Consumer Business
segment tables. The record's own `evidence_text` locates at our page 55, and
its `evidence_text_full_page` locates **nowhere** in our parse. This looks like
a snippet/page mismatch introduced when the key was authored. Our model cited
55 — where the dividend facts actually are — and was scored 0.

Contrast case — quick-ratio question, same filing: key claims page 4; our page
4 *is* the Consolidated Balance Sheet. Initially flagged "not found" by the
strict matcher; resolved by normalisation. Not a key defect — a lesson about
match strictness.

### 5.4 Score impact (experiment 4.3)

Rescoring the full candidate run (noRRF config, new verifier/scorer) with
per-document offset-corrected gold pages:

| Metric | As scored vs raw key | With alignment correction |
|---|---|---|
| Correct answer + correct location (+1) | 29 | **37** |
| Correct answer, wrong location (0) | 23 | **15** |
| Abstentions | 62 | 62 |
| Confidently wrong (−1) | 22 | 22 |
| **Rubric total** | **+7** | **+15** |

Eight answers were right-answer-right-evidence and lost their mark purely to
the numbering divergence. Answer-correctness verdicts were held constant; only
location outcomes changed.

### 5.5 Knock-on effect on earlier measurements

All gold-page recall@5 figures reported previously (fusion comparisons) used
raw `evidence_page_num` as ground truth and are therefore slightly pessimistic
for the 12 shifted documents (~9% of questions). Direction of bias favours no
particular configuration; conclusions about RRF harm (36% → 59%) are far larger
than the possible distortion.

## 6. Threats to validity

- Fingerprint matching needs ≥100 normalised chars and a unique hit; 33 items
  were unlocatable and excluded from offset derivation rather than forced.
- Single-sample offsets (AMCOR +2, FOOTLOCKER +20) rest on one item each and
  may be isolated errors rather than true shifts; multi-sample offsets are
  consistent.
- The rescore holds LLM-judge prose verdicts fixed; judge noise affects both
  columns equally.

## 7. Conclusions

1. **The key is trustworthy in content, imperfect in coordinates.** ~73% of
   evidence verifiably sits where claimed under our parse; most of the remainder
   is explained by a per-document indexing divergence, not wrong answers or
   wrong excerpts.
2. **The dominant failure mode is two page splitters disagreeing** on ~12 of
   ~60 documents (±1–2 pages; one outlier at +20). It is systematic, measurable,
   and correctable.
3. **Impact is material: +8 rubric points (+7 → +15)** exist in our current
   results purely as alignment artifacts.
4. **A small set of records is genuinely broken** (at least the 3M dividend
   item) and will cost points against any honest system; document rather than
   chase these.
5. Printed footer numbers cannot arbitrate alignment (they match neither the
   key nor our indices reliably, and are often absent).

## 8. Recommended actions

1. **Short term (done):** keep dual bookkeeping — strict score and
   alignment-corrected score — and disclose both in the approach note.
2. **Parser alignment (next):** diff break-marker structure around known
   divergence boundaries on AES/BESTBUY/BOEING to identify the marker class our
   `PAGE_BREAK_PATTERN` treats differently; fix in `parsing/`; bump
   `PARSER_VERSION`; reindex and re-run the 136-question eval. Success criterion:
   fingerprint offsets on the affected docs go to zero without breaking the 108
   currently-aligned docs.
3. **Do not** apply key-derived offsets at query time — that would leak dev-set
   calibration into product behaviour and would not transfer to unseen filings.
4. Spot-audit a sample of prose gold answers before fully trusting −1 verdicts
   (the dividend record shows the answer column can be the shaky part too).

## 9. Reproduction

Experiments were ad-hoc scripts executed in-session (no LLM calls needed; only
parsing + string matching). Core logic:

```python
def norm(t): return re.sub(r"[^a-z0-9]", "", t.lower())

probe = norm(evidence_text)[:300]
positions = [i for i, p in enumerate(pages) if probe in p]

fingerprint = norm(evidence_text_full_page)[:250]
offset = Counter(h - ev["evidence_page_num"]
                 for h in located_fingerprints).most_common(1)[0][0]
```

Inputs: `data/practice-questions.jsonl`, `filings/*.htm`,
parser `src/analyst_copilot/parsing/html_filing_parser.py` (PARSER_VERSION 3),
candidate results `data/eval-full-norrf-scores.json`.
