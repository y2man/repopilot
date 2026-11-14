import { afterEach, describe, expect, it, vi } from 'vitest'
import { request } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('request API client', () => {
  it('adds bearer auth and JSON content type for JSON requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"ok":true}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const result = await request<{ ok: boolean }>('/api/v1/example', 'token-123', {
      method: 'POST', body: JSON.stringify({ value: 1 }),
    })
    expect(result.ok).toBe(true)
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    const headers = new Headers(init.headers)
    expect(headers.get('Authorization')).toBe('Bearer token-123')
    expect(headers.get('Content-Type')).toBe('application/json')
  })

  it('surfaces the API detail for failed responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response('{"detail":"Repository not found"}', { status: 404 })))
    await expect(request('/api/v1/repositories/999', 'token')).rejects.toThrow('Repository not found')
  })

  it('handles 204 responses without attempting JSON parsing', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    await expect(request<void>('/api/v1/repositories/1', 'token', { method: 'DELETE' })).resolves.toBeUndefined()
  })
})
