# Filings — many documents, one question

**Modules:** `analyst_copilot.collections`
**Entry points:** `CollectionStore` · `CollectionIndexer` · `CollectionSearcher`

An analyst's question is rarely about one file. *"How did operating margin move
over three years"* spans three annual reports, and making them pick one first is
asking them to answer half the question themselves.

A **filing** is that grouping made explicit: a named set of documents that are
indexed together and searched together. Retrieval spans every indexed document
in it; the answer still cites exactly one.

> **Terminology.** The product calls these *filings* and their members
> *documents*. The code calls them **collections** — `CollectionStore`,
> `/api/v1/collections` — because "filing" already means a single 10-K
> everywhere else in this codebase, and reusing it for the container would make
> `filing.filings` a sentence someone has to decode. The boundary is the API
> client; past it, the UI says filing throughout.

---

## Layout

The filing is mirrored on both sides of the pipeline:

```text
filings/{filing}/{doc}.pdf              the uploaded originals

storage/{filing}/
    collection.json                     name, timestamps, members
    markdown/{doc}/page-001.md
    bm25/{doc}/...
    vector_indices/{doc}/...
```

The filing sits directly under `storage/`, so the directory an analyst named is
the directory on disk.

Mirroring rather than flattening buys two things. A filing can be deleted,
copied or inspected as one directory. And two filings can hold documents of the
same name without colliding — which they will, because `10-K` and `Q1` are what
people actually call files.

Filings share `storage/` with the per-document stores the bulk CLI writes —
`storage/markdown/`, `storage/bm25/`, `storage/vector_indices/`. Those names are
reserved, so a filing can never be created on top of one: a filing called
`markdown` would be indistinguishable from the top-level Markdown store and
would swallow it on delete.

---

## Searching across documents

[`collections/searcher.py`](../src/analyst_copilot/collections/searcher.py)

The whole difficulty is **comparability of scores**.

Per-document retrieval min-max normalizes each retriever over one filing's
pages, which is sound: the only question is which of *those* pages wins. Run
that per document and merge, and every filing's best page normalizes to ~1.0 —
the merge degenerates into "one page from each document", ranked by nothing.

So candidates are pooled **before** normalization. Raw scores from every
document go into one dictionary keyed by `(doc_name, page_index)`, and
normalization happens once over the pool.

```text
question
   │
   ├─ expand              once, for the whole filing
   ├─ embed query         once — not once per document
   │
   ├─ per document        BM25 top-80  +  vector top-80   (raw scores)
   │                      keyed (doc_name, page_index)
   │
   ├─ pool + normalise    one min-max over every candidate in the filing
   ├─ weighted fuse       0.1 lexical / 0.9 semantic
   ├─ statement boost     ×1.25
   └─ rank                top 5 → the model sees pages from several documents
```

Two properties of that, stated plainly:

- **Cosine similarity is comparable across documents by construction.** Same
  model, same vector space; 0.71 means the same thing in every filing. This is
  the signal the ranking rests on, and it carries weight 0.9.
- **BM25 is not.** Its idf is computed over one document's pages, so a term rare
  in a 10-K and common in an 8-K scores differently for reasons unrelated to
  relevance. Pooling raw BM25 across documents is therefore approximate. It is
  done anyway, at weight 0.1, because dropping lexical search from filing-wide
  queries would lose exact line-item matching entirely. Worth revisiting if that
  weight ever rises.

The query is embedded **once** and reused. Per-document embedding would be one
network round trip per filing for a single question.

Indices are cached per document, keyed by the index's mtime, so a rebuild
mid-session invalidates the entry rather than answering from the embeddings it
replaced.

---

## A citation names one document

Widening retrieval widens **where the system may look**, not what it may claim.

Page numbers repeat: page 59 exists in every document in the filing, so a page
without a document names nothing. Three things change to keep citations honest:

1. **The prompt names each excerpt's document** and asks the model to echo it in
   a `document` field — but only when there is more than one, so a
   single-document question is never invited to cite anything else.
2. **The verifier resolves on `(document, page)`**, not page alone. Document
   names are matched loosely, because a model asked to echo `AMD_2022_10K` will
   sometimes return `AMD 2022 10-K`.
3. **Page tolerance does not cross a document boundary.** The verifier may move
   a citation up to `evidence_page_tolerance` pages to land on the page that
   actually carries the evidence — but only *within* one document. Page 60 of a
   different filing is not "near" page 61 of this one. Without that rule, a
   filing holding one company's annual reports would let a citation drift between
   years, since the same line item sits at a similar page in each.

A distant page in another document is still reachable, but only on verbatim
evidence: if the quoted snippet appears there word for word, the text outranks
the coordinates.

---

## Indexing

One job per document, not one per filing. A filing of twelve documents should
report which one is slow and which has failed, and a single job covering all of
them can report neither.

Membership is recorded **at upload**, before indexing starts. Waiting until the
job finishes would leave a filing reporting zero documents while twelve of them
are embedding, which reads as a lost upload. The indexer fills in the format and
segment count once it knows them.

A filing is **searchable as soon as one document is ready**. Blocking a
twelve-document filing on its slowest member helps nobody — the other eleven can
already answer. The UI shows `9 of 12 ready` so the analyst knows the answer may
not have seen everything yet.

Partial upload failure is normal and is reported as such: dropping twelve files
and losing all of them because one was a PNG is the wrong behaviour, so the
response lists what was accepted and what was refused.

---

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/collections` | Every filing, with per-document state |
| `POST` | `/api/v1/collections` | Create a filing (idempotent) |
| `GET` | `/api/v1/collections/{name}` | One filing and its documents |
| `DELETE` | `/api/v1/collections/{name}` | Delete a filing (`?remove_uploads=true` for the originals too) |
| `POST` | `/api/v1/collections/{name}/documents` | Upload **many** files at once |
| `DELETE` | `/api/v1/collections/{name}/documents/{doc}` | Remove one document |
| `GET` | `/api/v1/collections/{name}/documents/{doc}/pages/{n}` | Read the segment behind a citation |
| `GET` | `/api/v1/collections/{name}/jobs` | Indexing progress, one row per document |

`POST /api/v1/chat` takes **exactly one** of `collection` or `doc_name`. On a
filing-scoped question the response carries `collection`, `searched_documents`, and a
`doc_name` naming the member document the evidence came from.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/collections \
  -H 'Content-Type: application/json' -d '{"name": "3M multi-year"}'

curl -X POST "http://127.0.0.1:8000/api/v1/collections/3M%20multi-year/documents" \
  -F "files=@filings/3M_2018_10K.htm" -F "files=@filings/3M_2022_10K.htm"

curl -X POST http://127.0.0.1:8000/api/v1/chat -H 'Content-Type: application/json' \
  -d '{"collection": "3M multi-year", "question": "What is the FY2018 capital expenditure?"}'
```

Measured on that filing: the FY2018 question cited `3M_2018_10K` page 59 and the
FY2022 question cited `3M_2022_10K` page 33, with pages from both filings in the
retrieved set each time.

---

## Deletion

Deleting a filing removes its **derived data** — Markdown and both indices. The
uploaded originals are kept unless `remove_uploads=true` is passed. Indices are
regenerable and source files are not, and deleting both on one click is the kind
of thing an analyst only discovers is irreversible afterwards.

A filing deleted while one of its documents is still indexing fails that job
with a message saying so, rather than a bare `CollectionNotFound`.

---

## Known limits

**1. BM25 across documents is approximate.** See above. Weight 0.1 bounds it.

**2. Every member is loaded per question.** A filing of 20 documents deserializes
20 vector indices on the first question. The per-document cache (24 entries)
makes subsequent questions cheap, but the first is slow and the cache is
per-process — it does not survive a restart.

**3. No cross-filing search.** By design: a citation is only checkable against
the document it names, and a question spanning unrelated filings has no
coherent scope.

**4. Job state is in-process.** A restart loses the progress log. The indices
themselves are durable, so a finished document survives; a job that was running
is simply gone and must be re-uploaded.
