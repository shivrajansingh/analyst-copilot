import { api } from '../client'
import type { PageResponse } from '../types'

export const pagesApi = {
  get: (docName: string, page: number) =>
    api.get<PageResponse>(`/filings/${encodeURIComponent(docName)}/pages/${page}`),
}
