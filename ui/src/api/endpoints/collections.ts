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

  removeDocument: (name: string, docName: string) =>
    api.delete<void>(`${path(name)}/documents/${encodeURIComponent(docName)}`),

  jobs: (name: string) => api.get<IndexingJob[]>(`${path(name)}/jobs`),
}
