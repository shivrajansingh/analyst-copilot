# Question answering

> **This is tier 1.** It is what runs first and answers most questions, and it
> is unchanged. What happens when it cannot produce an answer that survives
> checking — a second reader over the whole cited page, then every page of the
> filing read by parallel agents, then verification that can prove a *computed*
> figure — is in [Agent harness](16-agent-harness.md).

**Modules:** `analyst_copilot.llm`, `analyst_copilot.services.qa`

Turns hybrid retrieval into a grounded answer: chat LLM extracts a value from retrieved pages, then a verifier accepts it or the system abstains with **“not found in this filing.”**

## Flow

```text
question + doc_name
  → load hybrid indices (or build)
  → HybridSearcher top_k pages
  → if no hits / fused score too low → abstain
  → chat LLM (JSON only)
  → parse JSON
  → verify (cited page in results; numbers on that page)
  → answer + page  or  “not found in this filing”
```

## Pieces

| Path | Role |
|------|------|
| `llm/openai.py` | OpenAI-compatible `POST /chat/completions` using `OPENAI_URL` / `OPENAI_MODEL` |
| `qa/prompts.py` | System + excerpt prompt |
| `qa/parser.py` | JSON parse (fences / extra text) |
| `qa/verifier.py` | Page must be retrieved; answer numbers must appear on that page |
| `qa/service.py` | `QuestionAnsweringService.answer(...)` |

## Abstention reasons

`no_retrieval_hits`, `model_abstain`, `empty_answer`, `page_not_in_retrieval`, `number_not_on_page`, `snippet_not_on_page`.

## Demo

```bash
PYTHONPATH=src python scripts/examples/qa_example.py
```

Requires chat settings in `.env` (`OPENAI_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`) and embedding settings for retrieval if indices are not already saved.
