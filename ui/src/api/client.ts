import type { ApiErrorBody } from './types'

/**
 * Always same-origin. Vite proxies `/api` in development and nginx proxies it in
 * production, so no API host is ever baked into the bundle and CORS never
 * enters the deployed path.
 */
const BASE = '/api/v1'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  /** A filing that is not indexed yet is a state the UI recovers from, not a crash. */
  get isNotIndexed() {
    return this.code === 'filing_not_indexed'
  }

  get isAuth() {
    return this.status === 401 || this.status === 403
  }
}

/** Set by the auth store so every request carries the session. */
let authToken: string | null = null
export function setAuthToken(token: string | null) {
  authToken = token
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  /** Skip JSON encoding — used for multipart uploads. */
  raw?: BodyInit
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, raw, headers, ...rest } = options
  const finalHeaders = new Headers(headers)
  if (authToken) finalHeaders.set('Authorization', `Bearer ${authToken}`)

  let payload: BodyInit | undefined = raw
  if (body !== undefined) {
    finalHeaders.set('Content-Type', 'application/json')
    payload = JSON.stringify(body)
  }

  const response = await fetch(`${BASE}${path}`, {
    ...rest,
    headers: finalHeaders,
    body: payload,
  })

  if (!response.ok) {
    throw await toApiError(response)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = 'http_error'
  let message = `Request failed with ${response.status}`
  try {
    const payload = (await response.json()) as Partial<ApiErrorBody> & {
      detail?: unknown
    }
    if (payload.error) {
      code = payload.error.code
      message = payload.error.message
    } else if (payload.detail) {
      // FastAPI's own validation errors have a different shape.
      code = 'validation_error'
      message = Array.isArray(payload.detail)
        ? 'That request was not valid.'
        : String(payload.detail)
    }
  } catch {
    /* a non-JSON body (a proxy error page) keeps the generic message */
  }
  return new ApiError(response.status, code, message)
}

export const api = {
  get: <T,>(path: string) => request<T>(path, { method: 'GET' }),
  post: <T,>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  patch: <T,>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  delete: <T,>(path: string) => request<T>(path, { method: 'DELETE' }),
  upload: <T,>(path: string, form: FormData) =>
    request<T>(path, { method: 'POST', raw: form }),
}
