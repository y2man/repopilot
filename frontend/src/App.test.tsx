// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App, { FileTree } from './App'

afterEach(cleanup)

beforeEach(() => {
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
