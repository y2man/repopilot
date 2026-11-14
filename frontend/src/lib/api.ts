/** Shared authenticated API client. Never place provider credentials in browser code. */
const API = (import.meta.env.VITE_API_URL || '').trim().replace(/\/+$/, '')
const missingProductionApi = import.meta.env.PROD && !API

export async function request<T>(path: string, token: string | null, init: RequestInit = {}): Promise<T> {
  if (missingProductionApi) {
    throw new Error('Backend URL is not configured. Set VITE_API_URL to your Render API origin in Vercel, then redeploy.')
  }

  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  let response: Response
  try {
    response = await fetch(`${API}${path}`, { ...init, headers })
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(`Could not reach the backend${API ? ` at ${API}` : ''}. Check the API URL, backend availability, and CORS settings.`)
    }
    throw error
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const data = await response.json() as { detail?: string }
      detail = data.detail || detail
    } catch { /* preserve the HTTP status fallback for non-JSON responses */ }
    throw new Error(detail)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
