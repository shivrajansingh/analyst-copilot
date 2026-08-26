import { api } from '../client'
import type {
  CollectionListResponse,
  CollectionSummary,
  CollectionUploadResponse,
  IndexingJob,
} from '../types'

const path = (name: string) => `/collections/${encodeURIComponent(name)}`

export const collectionsApi = {
  list: () => api.get<CollectionListResponse>('/collections'),

  get: (name: string) => api.get<CollectionSummary>(path(name)),

  create: (name: string, description = '') =>
    api.post<CollectionSummary>('/collections', { name, description }),

  remove: (name: string, removeUploads = false) =>
    api.delete<void>(`${path(name)}?remove_uploads=${removeUploads}`),

  /**
   * Upload any number of documents into one folder, in one request.
   *
   * The response reports accepted and rejected files separately: dropping
   * twelve files and losing all of them because one was a PNG is the wrong
   * behaviour, so the server keeps the eleven and names the one it refused.
   */
  addDocuments: (name: string, files: File[]) => {
    const form = new FormData()
    for (const file of files) form.append('files', file)
    return api.upload<CollectionUploadResponse>(`${path(name)}/documents`, form)
  },

  /**
   * Add a document by URL. The server downloads it, so the browser never sees
   * the bytes and cross-origin rules never enter into it.
   *
   * A URL that cannot be fetched comes back in `rejected` with a reason rather
   * than as an error: a 404 or a JPEG is bad input, not a broken service.
   */
  fetchDocument: (name: string, url: string, docName?: string) =>
    api.post<CollectionUploadResponse>(`${path(name)}/documents/fetch`, {
      url,
      doc_name: docName ?? null,
    }),

  removeDocument: (name: string, docName: string) =>
    api.delete<void>(`${path(name)}/documents/${encodeURIComponent(docName)}`),

  jobs: (name: string) => api.get<IndexingJob[]>(`${path(name)}/jobs`),
}
