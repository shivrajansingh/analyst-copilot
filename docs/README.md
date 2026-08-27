# Documentation

Guides for work that is **already implemented**. For remaining work and how to finish it, see [`../PLAN.md`](../PLAN.md).

| Doc | Topic |
|-----|--------|
| [Project setup](01-project-setup.md) | Layout, install, run tests |
| [Configuration](02-configuration.md) | `.env`, settings, URL resolution |
| [HTML parsing](03-html-parsing.md) | SEC HTML → pages with page numbers |
| [Document parsing](13-document-parsing.md) | **Multi-format intake**: PDF/HTML/Word/Excel/CSV → Markdown pages |
| [Filings](14-collections.md) | **Filings**: many documents, one question, one citation |
| [Embeddings](04-embeddings.md) | OpenAI-compatible `/v1/embeddings` |
| [BM25 retrieval](05-bm25-retrieval.md) | Lexical index and search |
| [Vector retrieval](06-vector-retrieval.md) | Dense page embeddings |
| [Document retrieval](07-hybrid-retrieval.md) | **End-to-end retrieval logic**, fusion, measured recall, limits |
| [Indexing services](08-indexing-services.md) | Orchestration and storage |
| [Question answering](09-qa-pipeline.md) | LLM extract + verify + abstain |
| [Evaluation](10-evaluation.md) | Answer runners + rubric scorer (+1 / 0 / −1) |
| [HTTP API](11-api.md) | FastAPI service: add filing, status, chat |
| [What changed in this round](17-enhancements.md) | **Start here**: the enhancements, what each fixed, what it measured |
| [Agent harness](16-agent-harness.md) | **Routing, validation and whole-document deep search** |
| [Multi-agent retrieval](12-multi-agent-retrieval.md) | The assessment that led to the harness |
| [Docker](15-docker.md) | **Running the stack**: api + ui containers, compose, nginx |
| [Design system](18-design-system.md) | Colour tokens, accent themes, why colour means something |
