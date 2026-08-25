import { api } from '../client'
import type { FilingListResponse, IndexingJob } from '../types'

export const filingsApi = {
  list: () => api.get<FilingListResponse>('/filings'),

  status: (docName: string) =>
    api.get<IndexingJob>(`/filings/${encodeURIComponent(docName)}/status`),

  job: (jobId: string) => api.get<IndexingJob>(`/jobs/${encodeURIComponent(jobId)}`),

  add: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.upload<IndexingJob>('/filings', form)
  },
}
