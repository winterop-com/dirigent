import { expect, test } from '@playwright/test'

import { DEV_PASSWORD, DEV_USERNAME } from './support.ts'

/**
 * The one thing that has to be true before any screen is worth building: a person can reach
 * this instance, sign in, and land on a screen the server answered for.
 */

test('a deep link is answered with the shell rather than a 404', async ({ page }) => {
    const response = await page.goto('/runs')
    expect(response?.status()).toBe(200)
})

test('signing in lands on the dashboard', async ({ page }) => {
    await page.goto('/pipelines')
    await expect(page.getByRole('heading', { name: 'dirigent', exact: true })).toBeVisible()

    await page.getByLabel('Username').fill(DEV_USERNAME)
    await page.getByLabel('Password', { exact: true }).fill(DEV_PASSWORD)
    await page.getByRole('button', { name: 'Sign in' }).click()

    // The front door, not a listing: the root is a screen of its own and it is where a session
    // with no address behind it begins.
    await expect(page).toHaveURL(/^https?:\/\/[^/]+\/$/)
    await expect(page.getByRole('heading', { name: 'Dashboard', level: 1 })).toBeVisible()
    // The rail is drawn from the identity the shell read back, so its admin section standing
    // there is the whole round trip having worked.
    await expect(page.getByRole('link', { name: 'Users' })).toBeVisible()
})

test('a wrong password is refused in the server own words', async ({ page }) => {
    await page.goto('/login')
    await page.getByLabel('Username').fill(DEV_USERNAME)
    await page.getByLabel('Password', { exact: true }).fill('not the password')
    await page.getByRole('button', { name: 'Sign in' }).click()

    await expect(page.getByRole('alert')).toHaveText('invalid username or password')
})

test('the reveal toggle shows the password and puts it back', async ({ page }) => {
    await page.goto('/login')
    const password = page.getByLabel('Password', { exact: true })
    await password.fill(DEV_PASSWORD)
    await expect(password).toHaveAttribute('type', 'password')

    await page.getByRole('button', { name: 'Show password' }).click()
    await expect(password).toHaveAttribute('type', 'text')

    await page.getByRole('button', { name: 'Hide password' }).click()
    await expect(password).toHaveAttribute('type', 'password')
})
