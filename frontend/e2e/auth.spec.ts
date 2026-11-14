import { expect, test } from '@playwright/test'

test('authentication screen is usable and account mode can be switched', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Welcome back.' })).toBeVisible()
  await expect(page.getByLabel('Email address')).toBeVisible()
  await expect(page.getByLabel('Password')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
  await page.getByRole('button', { name: 'New to RepoPilot? Create an account' }).click()
  await expect(page.getByRole('heading', { name: 'Create your workspace.' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Create account' })).toBeVisible()
})

test('authentication form remains usable on a narrow mobile viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByLabel('Email address')).toBeVisible()
  await expect(page.getByLabel('Password')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
  const password = await page.getByLabel('Password').getAttribute('minlength')
  expect(password).toBe('10')
})

test('account creation can return to sign-in without losing the page', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'New to RepoPilot? Create an account' }).click()
  await page.getByRole('button', { name: 'Already have an account? Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Welcome back.' })).toBeVisible()
})
