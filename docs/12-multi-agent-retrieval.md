# Multi-agent parallel retrieval — assessment and recommendation

**Status:** recommendation only. Nothing in this document is implemented.
**Question:** should the single QA call be replaced by many agents reading the
document's Markdown pages in parallel, with a synthesis agent combining them?

**Recommendation: yes to parallel readers, no to reading every page.** Build the
hybrid — retrieve a shortlist, fan out over the shortlist, synthesize — and size
the shortlist from a measurement that has not been taken yet. Reasons below.

---

## 1. What runs today

One question, one LLM call:

```
question → hybrid retrieval → top 5 pages × 2,200 chars → 1 chat call → verify
```

Measured on the 136 practice questions: **+7** on the challenge rubric — 29
correct-with-location, 62 abstentions, 23 correct-answer-wrong-page, 22
confidently wrong. Retrieval finds the gold page in the top 5 for **58%** of
questions and the top 10 for **66%**.

That 58% is a hard ceiling. No prompt can cite a page the model was never shown,
so **41 of the 62 abstentions are structurally unreachable by the current
architecture.** That is the case for fanning out, and it is a strong one.

---

## 2. The two architectures, costed

A typical 10-K in this corpus is ~160 pages at ~3,800 characters — call it
**150k tokens** for the whole document. The largest, `JPMORGAN_2022_10K`, is 306
segments.

| | Today | Hybrid fan-out | Full fan-out |
|---|---|---|---|
| Pages read per question | 5 | 30 | all (~160) |
| Reader agents | 1 | 5-6 (6 pages each) | ~32 (5 pages each) |
| Input tokens / question | ~3k | ~21k | ~160k |
| Cost vs today | 1× | **~7×** | **~55×** |
| Wall clock (16 concurrent) | ~3s | ~7s | ~12s |
| Retrieval ceiling | 58% | recall@30 (unmeasured) | **100%** |

Latency is not the deciding factor — even full fan-out finishes inside a
reasonable wait. **Cost is**, and so is the failure mode in §4.

---

## 3. Why not read every page

**The recall curve is the whole argument, and we have not measured the part that
matters.** Known: recall@5 = 58%, recall@10 = 66%. Unknown: recall@30, @50.
If recall@30 is 85%, the hybrid captures nearly all the available gain at an
eighth of the cost of reading everything. If it is 65%, the tail is genuinely
where the answers are and full fan-out earns its price.

**This is a cheap measurement** — no LLM calls, just replaying stored retrieval
scores against the practice key — and it should be taken before anything is
built. It is also blocked on the same reindex the Markdown parser change already
requires, so it costs nothing extra in wall-clock terms.

**Scaling is per-question, not per-corpus.** Questions are scoped to one
document, so full fan-out is bounded at ~60 agents for the largest filing rather
than unbounded. That makes it *possible*; it does not make it wise.

---

## 4. The failure mode that decides it

An agent shown 5 pages and asked "does this answer the question?" has no way to
know that a better page exists elsewhere. Financial figures repeat: the same
revenue number appears in the income statement, in MD&A, in a segment footnote
and in the five-year selected data. Reading all 160 pages does not surface one
answer — **it surfaces a dozen agents all reporting "found it", each pointing at
a different page.**

That is not a hypothetical. It is precisely the failure already measured in the
current system: of the 23 correct-answer-wrong-page results, **6 had the gold
page in the top 5 and the model cited a different supporting page anyway**:

```
AMD_2022_10K        cited 53  gold 42   retrieved [42, 4, 59, 53, 0]   gold was rank 1
GENERALMILLS_2020   cited 16  gold 51   retrieved [16, 51, 27, 52, 92]
JPMORGAN_2022_10K   cited 47  gold  2   retrieved [47, 2, 134, 0, 162]
```

Fanning out over 160 pages multiplies the number of plausible-looking candidates
by roughly thirty. **Unless synthesis resolves authority correctly, full fan-out
converts a recall problem into a precision problem and the rubric punishes the
second one harder** — a wrong page scores 0, and a wrong answer confidently
asserted scores −1, against a current tally of 22.

The synthesis agent therefore is not a merge step. It is the component the whole
architecture stands on, and it needs an explicit authority policy:

- the question names a statement → cite that statement
- a bare figure → the primary financial statement, not a narrative page
- "what drove / why" → management discussion
- what the company does → the business description

(That policy now exists in the system prompt; fan-out would move it into
synthesis, where it can compare candidates instead of guessing among excerpts.)

---

## 5. Recommended architecture

```
question
  │
  ├─ 1. shortlist      existing hybrid retrieval, top N (N from §3's measurement)
  │                    no LLM cost, no accuracy risk
  │
  ├─ 2. parallel read  ceil(N / 6) agents, 6 Markdown pages each
  │                    each returns: answer | nothing-here, evidence quote,
  │                    page, and why this page is the right source
  │
  ├─ 3. synthesize     one agent over candidates only (never raw pages):
  │                    agree/conflict, pick the authoritative location,
  │                    combine evidence when the answer spans pages
  │
  └─ 4. verify         the existing deterministic verifier, unchanged
                       → answer + citation, or "not found in this filing"
```

Four properties worth keeping:

1. **Stage 4 does not move.** The deterministic verifier stays the last word.
   Agents propose; it disposes. Nothing reaches the analyst that a page's own
   text does not support, however many agents voted for it.
2. **Readers return "nothing here" cheaply.** Most slices contain nothing, and
   a reader that must justify a positive is far less likely to invent one.
3. **Synthesis sees candidates, not pages.** Its input stays small and constant
   regardless of document size, which is what makes the shape scale.
4. **Multi-page answers become expressible.** 34 of the 136 gold records cite
   2-3 pages; a single call over 5 excerpts can barely represent that, and
   synthesis over candidates can.

**The Markdown page store makes this cheap to build.** Readers can be handed
`storage/markdown/{doc}/page-042.md` paths rather than text blobs, so a fan-out
run is a list of file paths and costs nothing to shard.

---

## 6. Trade-offs, stated plainly

| Dimension | Hybrid fan-out | Full fan-out |
|---|---|---|
| Accuracy ceiling | recall@N — unmeasured, likely 80%+ | 100%, the only architecture without a recall ceiling |
| Cost | ~7× today | ~55× today |
| Latency | ~7s | ~12s |
| −1 risk | moderate; N candidates to adjudicate | **high**; ~30× the candidates, same adjudicator |
| Scalability | flat in document size after the shortlist | linear in document size |
| Duplicate evidence | manageable | the dominant problem |
| Build cost | reuses retrieval; new reader + synthesis | same, plus sharding and rate-limit handling |

---

## 7. Before building anything

1. **Measure recall@{10, 20, 30, 50} on the practice key.** No LLM calls. This
   single number sizes the shortlist and decides whether full fan-out has a case
   at all. Do it as part of the post-reindex baseline.
2. **Re-baseline first.** The Markdown parser and the evidence-first verifier
   both landed since the +7 run. Fan-out must be measured against the new
   number, not the old one, or its gains will be credited with theirs.
3. **Then A/B one filing set**, scoring +1 / 0 / −1 exactly as `score.py` does,
   and watch the −1 column at least as closely as the +1 column. An architecture
   that adds four +1s and three −1s has gained one point, not four.

If recall@30 turns out to be ≥ 85%, build the hybrid and stop. If the curve is
still climbing at 50, revisit full fan-out — with a synthesis stage that has
already been shown to pick authority correctly on the smaller problem.
