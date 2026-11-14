// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App, { FileTree } from './App'

afterEach(cleanup)

beforeEach(() => {
  sessionStorage.removeItem('rp-token')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ status: 'ok' }),
  }))
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
})

describe('RepoPilot authentication screen', () => {
  it('renders the sign-in form with accessible credential fields', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Welcome back.' })).toBeTruthy()
    expect(screen.getByLabelText('Email address')).toBeTruthy()
    expect(screen.getByLabelText('Password')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeTruthy()
  })

  it('switches between sign-in and account creation modes', () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'New to RepoPilot? Create an account' }))
    expect(screen.getByRole('heading', { name: 'Create your workspace.' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Create account' })).toBeTruthy()
  })
})

describe('workspace navigation', () => {
  it('opens AI Workspace from Overview and other sections, hiding the link on its destination', async () => {
    sessionStorage.setItem('rp-token', 'test-token')
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      const data = url.endsWith('/auth/me')
        ? { id: 1, email: 'member@example.com' }
        : url.endsWith('/auth/github/status')
          ? { connected: false }
          : url.endsWith('/health')
            ? { status: 'ok', ai_configured: false }
            : []
      return { ok: true, status: 200, json: async () => data } as Response
    }))

    render(<App />)
    const accountButton = await screen.findByRole('button', { name: 'View account settings' })
    expect(accountButton.textContent).toContain('member@example.com')
    expect(screen.getByRole('button', { name: 'Go to AI Workspace' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Go to AI Workspace' }))
    expect(screen.getByText('AI Workspace', { selector: 'strong' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Go to AI Workspace' })).toBeNull()
    expect(screen.queryByText('My workspace')).toBeNull()
    expect(screen.queryByRole('button', { name: /api docs/i })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'View account settings' }))
    expect(screen.getByText('Settings', { selector: 'strong' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Code Explorer' }))
    expect(screen.getByText('Code Explorer', { selector: 'strong' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Go to AI Workspace' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Go to AI Workspace' }))
    expect(screen.getByText('AI Workspace', { selector: 'strong' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Go to AI Workspace' })).toBeNull()
  })
})

describe('AI question submission', () => {
  it('sends an Overview prompt to the selected repository', async () => {
    sessionStorage.setItem('rp-token', 'test-token')
    const repository = {
      id: 42,
      name: 'sample-repo',
      source: 'upload',
      status: 'ready',
      file_count: 1,
      chunk_count: 1,
      created_at: '2026-01-01T00:00:00Z',
    }
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder()
        controller.enqueue(encoder.encode('data: {"status":"generating","token":"Answer"}\n\n'))
        controller.enqueue(encoder.encode('data: {"done":true,"conversation_id":9,"sources":[]}\n\n'))
        controller.close()
      },
    })
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      const data = url.endsWith('/auth/me')
        ? { id: 1, email: 'member@example.com' }
        : url.endsWith('/auth/github/status')
          ? { connected: false }
          : url.endsWith('/health')
            ? { status: 'ok', ai_configured: true }
            : url.endsWith('/api/v1/repositories')
              ? [repository]
              : url.includes('/api/v1/conversations?')
                ? []
                : []
      if (url.endsWith('/api/v1/chat/stream')) {
        return { ok: true, status: 200, body: stream } as Response
      }
      return { ok: true, status: 200, json: async () => data } as Response
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await screen.findByRole('button', { name: 'View account settings' })
    fireEvent.change(screen.getByPlaceholderText('How does authentication work?'), {
      target: { value: 'How does authentication work?' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send question to AI' }))

    expect(await screen.findByText('AI Workspace', { selector: 'strong' })).toBeTruthy()
    await waitFor(() => {
      const chatCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith('/api/v1/chat/stream'))
      expect(chatCall).toBeTruthy()
      expect(JSON.parse((chatCall?.[1] as RequestInit).body as string)).toMatchObject({
        repository_id: 42,
        question: 'How does authentication work?',
      })
    })
  })

  it('explains that a repository is required instead of silently ignoring the send', async () => {
    sessionStorage.setItem('rp-token', 'test-token')
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      const data = url.endsWith('/auth/me')
        ? { id: 1, email: 'member@example.com' }
        : url.endsWith('/auth/github/status')
          ? { connected: false }
          : url.endsWith('/health')
            ? { status: 'ok', ai_configured: true }
            : []
      return { ok: true, status: 200, json: async () => data } as Response
    }))

    render(<App />)
    await screen.findByRole('button', { name: 'View account settings' })
    fireEvent.change(screen.getByPlaceholderText('Select or upload a repository first'), {
      target: { value: 'How does authentication work?' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send question to AI' }))

    expect(await screen.findByText('AI Workspace', { selector: 'strong' })).toBeTruthy()
    expect(await screen.findByText('Select a repository in AI Workspace before sending your question.')).toBeTruthy()
    expect(screen.getByDisplayValue('How does authentication work?')).toBeTruthy()
  })
})

describe('repository file tree', () => {
  it('expands folders and opens a selected source file', () => {
    const onSelect = vi.fn()
    render(<FileTree
      files={[
        { id: 1, path: 'src/auth/login.ts', language: 'TypeScript', line_count: 12 },
      ]}
      onSelect={onSelect}
      emptyMessage="No files"
    />)

    expect(screen.queryByRole('treeitem', { name: /login\.ts/ })).toBeNull()
    fireEvent.click(screen.getByRole('treeitem', { name: 'auth' }))
    fireEvent.click(screen.getByRole('treeitem', { name: /login\.ts/ }))

    expect(onSelect).toHaveBeenCalledWith('src/auth/login.ts')
  })
})
