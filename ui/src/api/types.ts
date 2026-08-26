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
  /** True once at least one document is indexed; a folder need not be complete. */
  searchable: boolean
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
