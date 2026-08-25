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
}

export interface Evidence {
  doc_name: string
  page: number
  display_page: number
  snippet: string
}

export interface RetrievedPage {
  page: number
  display_page: number
  rank: number
  fused_score: number
  bm25_score: number | null
  vector_score: number | null
  cited: boolean
}

export interface ChatResponse {
  doc_name: string
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
