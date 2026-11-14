// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
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
  it('removes the inert workspace card and lets the breadcrumb return to overview', async () => {
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
    expect(screen.queryByRole('button', { name: 'Go to overview' })).toBeNull()
    expect(screen.queryByText('My workspace')).toBeNull()
    expect(screen.queryByRole('button', { name: /api docs/i })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'View account settings' }))
    expect(screen.getByText('Settings', { selector: 'strong' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Code Explorer' }))
    expect(screen.getByText('Code Explorer', { selector: 'strong' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Go to overview' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Go to overview' }))
    expect(screen.getByText('Overview', { selector: 'strong' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Go to overview' })).toBeNull()
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
