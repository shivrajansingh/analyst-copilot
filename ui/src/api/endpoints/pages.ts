import { api } from '../client'
import type { PageResponse } from '../types'

export const pagesApi = {
  /**
   * Read one segment behind a citation.
   *
   * A document indexed inside a folder lives under that folder's storage, so
   * the folder has to be part of the address. Without it the top-level route
   * looks in the wrong place and reports the page as missing.
   */
  get: (docName: string, page: number, collection?: string | null) =>
    collection
      ? api.get<PageResponse>(
          `/collections/${encodeURIComponent(collection)}/documents/${encodeURIComponent(
            docName,
          )}/pages/${page}`,
        )
      : api.get<PageResponse>(`/filings/${encodeURIComponent(docName)}/pages/${page}`),
}
