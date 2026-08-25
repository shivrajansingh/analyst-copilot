import { api } from '../client'
import type { HealthResponse } from '../types'

export const healthApi = {
  get: () => api.get<HealthResponse>('/health'),
}
