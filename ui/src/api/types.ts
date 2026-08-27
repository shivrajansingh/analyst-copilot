/**
 * Mirrors of the API's response models.
 *
 * Hand-written rather than generated so the shapes stay readable, and kept in
 * one file so a backend change surfaces as a compile error in exactly one place.
 */

export type IndexState = 'ready' | 'building' | 'stale' | 'missing' | 'failed'

export type JobStatus =
  | 'queued'
  | 'parsing'
  | 'embedding'
  | 'saving'
  | 'ready'
  | 'failed'

export interface IndexInfo {
  state: IndexState
  page_count: number | null
  parser_version: string | null
  model: string | null
  dimensions: number | null
  built_at: number | null
  size_bytes: number | null
}

export interface FilingSummary {
  doc_name: string
  page_count: number | null
  status: IndexState
  bm25: IndexInfo
  vector: IndexInfo
}

export interface FilingListResponse {
  filings: FilingSummary[]
}

export interface IndexingJob {
  job_id: string
  doc_name: string
  status: JobStatus
  elapsed_seconds: number
  budget_seconds: number
  over_budget: boolean
  page_count: number | null
  error: string | null
  /** The folder this document is being indexed into, or null at the top level. */
  collection: string | null
  source_format: SourceFormat | null
}

export type SourceFormat =
  | 'pdf'
  | 'html'
  | 'docx'
  | 'xlsx'
  | 'csv'
  | 'markdown'
  | 'text'

/**
 * What one unit of retrieval is in its source document.
 *
 * Only `page` has a page number worth showing. A workbook has sheets and a CSV
 * has row blocks, and calling either "page 4" names a place the analyst cannot
 * go and look - so the UI reads `label` rather than formatting a page itself.
 */
export type SegmentKind = 'page' | 'sheet' | 'table' | 'section'

/** How a citation relates to the page the model named. See Evidence.location_match. */
export type LocationMatch = 'exact' | 'adjusted' | 'relocated' | 'inferred'

/**
 * Which tier answered.
 *
 * `conversational` has nothing to cite — it was not a question about a
 * document. Branch on this before `found`: a conversational reply is neither an
 * evidenced answer nor a decline.
 */
export type AnswerMode = 'conversational' | 'fast' | 'deep'

export type Intent = 'smalltalk' | 'capability' | 'document_question'

/** One figure a computed answer was derived from, and where it was read. */
export interface EvidenceInput {
  label: string
  value: string
  doc_name: string
  page: number | null
  display_page: number | null
}

/** One sub-question of a compound question, answered and cited on its own. */
export interface AnswerPart {
  question: string
  answer: string
  found: boolean
  mode: AnswerMode
  evidence: Evidence | null
  abstention_reason: string | null
  computation: string
  inputs: EvidenceInput[]
}

/** A progress milestone from POST /chat/stream. */
export interface StageEvent {
  stage:
    | 'routing'
    | 'decomposing'
    | 'retrieving'
    | 'reading'
    | 'validating'
    | 'escalating'
    | 'deep_search'
    | 'synthesizing'
    | 'verifying'
    | 'done'
  detail: string
  done?: number
  total?: number
  part?: number
  part_total?: number
}

export interface CollectionDocumentInfo {
  doc_name: string
  source_file: string
  source_format: SourceFormat | null
  segment_count: number | null
  added_at: number
  state: IndexState
}

export interface CollectionSummary {
  name: string
  description: string
  created_at: number
  updated_at: number
  document_count: number
  ready_count: number
  /** True once at least one document is indexed; a filing need not be complete. */
  searchable: boolean
  /**
   * The embedding model this filing's indices were built with.
   *
   * Compare against the configured model: they differ after a model change, and
   * every index has to be rebuilt before it can be searched again.
   */
  index_model: string | null
  documents: CollectionDocumentInfo[]
}

export interface CollectionListResponse {
  collections: CollectionSummary[]
}

export interface RejectedUpload {
  filename: string
  code: string
  message: string
}

/** Partial success is the normal case: one bad file must not discard the rest. */
export interface CollectionUploadResponse {
  collection: string
  accepted: IndexingJob[]
  rejected: RejectedUpload[]
}

export interface Evidence {
  doc_name: string
  page: number
  display_page: number
  snippet: string
  /** How the source names this place: "page 61", "sheet 'Q4 Revenue'". */
  label: string
  segment_kind: SegmentKind
  /**
   * `exact` when the model's page carried the evidence. `adjusted`/`relocated`
   * when verification found it elsewhere and moved the citation there -
   * disclose that, do not treat it as an error. `inferred` when the model
   * named no page at all.
   */
  location_match: LocationMatch
  model_cited_page: number | null
  page_shift: number
}

export interface RetrievedPage {
  /** Page numbers repeat across a folder, so a page without a document names nothing. */
  doc_name: string
  page: number
  display_page: number
  label: string
  rank: number
  fused_score: number
  bm25_score: number | null
  vector_score: number | null
  cited: boolean
}

export interface ChatResponse {
  /** The document the evidence came from - never the folder. */
  doc_name: string
  /** The folder searched, when the question was folder-scoped. */
  collection: string | null
  searched_documents: number
  question: string
  found: boolean
  answer: string
  evidence: Evidence | null
  retrieval: RetrievedPage[]
  abstention_reason: string | null
  /** Present when the exchange was recorded in Postgres. */
  conversation_id: string | null
  user_message_id: string | null
  message_id: string | null
  latency_ms: number | null

  /** Which tier answered. Check this before `found`. */
  mode: AnswerMode
  intent: Intent
  /** Every place the answer can be checked — one per answered part. */
  citations: Evidence[]
  /** Set only when the question was split into several questions. */
  parts: AnswerPart[]
  /** The arithmetic behind a derived figure, re-evaluated during verification. */
  computation: string
  inputs: EvidenceInput[]
  /** What the checking step concluded, and why. */
  validation: string | null
  /** Pages read by the deep path. 0 when it did not run. */
  pages_read: number
  /** Reader agents used by the deep path. 0 when it did not run. */
  shards_run: number
}

export interface ConversationSummary {
  id: string
  /** The filing this thread is pinned to. */
  collection: string | null
  title: string
  created_at: string
  updated_at: string
}

export interface MessageResponse {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  found: boolean | null
  page: number | null
  abstention_reason: string | null
  latency_ms: number | null
  retrieval: RetrievedPage[] | null
  /** The full ChatResponse as served, so history re-renders verbatim. */
  result: ChatResponse | null
}

export interface ConversationDetail extends ConversationSummary {
  messages: MessageResponse[]
}

export interface ConversationListResponse {
  conversations: ConversationSummary[]
}

export interface HealthResponse {
  status: string
  version: string
  chat_model: string
  embedding_model: string
  indexed_filings: number
}

export interface ApiErrorBody {
  error: { code: string; message: string }
}

export interface PageResponse {
  doc_name: string
  page: number
  display_page: number
  page_count: number
  text: string
  char_count: number
  /** How much of this page the vector index actually embedded. */
  embedded_chars: number
  truncated: boolean
  label: string
  segment_kind: SegmentKind
  source_format: SourceFormat | null
  /** The stored Markdown for this segment, when it is on disk. */
  markdown: string | null
}
