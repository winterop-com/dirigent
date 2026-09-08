import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

import { apiPrefix, applyExample, seedUser, signIn, signInAs, signOut } from './support.ts'

/**
 * What a viewer is offered, and what a refused write looks like.
 *
 * WHAT THESE SPECS ARE FOR is the pair a Node test cannot see: that every control a viewer's
 * role would have refused is shut with the sentence saying why, and that a write the server
 * does refuse says so on screen instead of nothing at all. Role gating in this app is a
 * courtesy -- the server is what refuses -- so both halves have to hold.
 *
 * THE VIEWER IS THIS RUN'S OWN. It is made through the API on the admin session the suite
 * already signs in with, and replaced every time, so what it may do is what this run set.
 */

const VIEWER = 'e2e-viewer'
const VIEWER_PASSWORD = 'a-viewer-password'

const CRON = { file: 'examples/triggers/cron-nightly.yaml', schedule: 'nightly', title: 'Nightly, Oslo time' }

const CONNECTION = 'e2e-role-http'

/** What a control shut by a role says: that this account cannot, and nothing more. */
const SHUT = 'Not available to a viewer.'

/** One connection to press Check on. The health path answers on this very instance. */
async function seedConnection(request: APIRequestContext, baseURL: string): Promise<void> {
    const prefix = await apiPrefix(request)
    await request.delete(`${prefix}/connections/${CONNECTION}`)
    const created = await request.post(`${prefix}/connections`, {
        data: { code: CONNECTION, kind: 'http', config: { base_url: baseURL, health_path: '/health' } },
    })
    expect(created.ok(), await created.text()).toBe(true)
}

/** The table row one code is in. */
function rowOf(page: Page, code: string) {
    return page.getByRole('row').filter({ hasText: code })
}

/** Refuse one request the way the server refuses an account whose role may not make it. */
async function refuse(page: Page, path: RegExp): Promise<void> {
    await page.route(path, (route) =>
        route.fulfill({
            status: 403,
            contentType: 'application/problem+json',
            body: JSON.stringify({
                status: 403,
                title: 'Forbidden',
                detail: 'not permitted for your role',
                problems: [],
                instance: null,
            }),
        }),
    )
}

test('a viewer is offered no write control, and each shut one says why', async ({ page, baseURL }) => {
    await signIn(page)
    await seedUser(page.request, VIEWER, VIEWER_PASSWORD, 'viewer')
    await seedConnection(page.request, baseURL ?? '')
    await applyExample(page.request, CRON.file)

    await signOut(page)
    await signInAs(page, VIEWER, VIEWER_PASSWORD)

    // Connections are an admin's: minting one, and opening a credential to ask an external
    // system about it. What each shut control says is that this account cannot, and no more.
    await page.goto('/connections')
    const create = page.getByRole('button', { name: 'New connection' })
    await expect(create).toBeDisabled()
    await expect(create).toHaveAttribute('title', SHUT)
    const check = rowOf(page, CONNECTION).getByRole('button', { name: 'Check' })
    await expect(check).toBeDisabled()
    await expect(check).toHaveAttribute('title', SHUT)

    // Triggers are an operator's, on the listing and in the panel both.
    await page.goto('/triggers')
    const schedule = page.getByRole('button', { name: 'New schedule' })
    await expect(schedule).toBeDisabled()
    await expect(schedule).toHaveAttribute('title', SHUT)
    await expect(page.getByRole('button', { name: 'New webhook' })).toBeDisabled()

    await rowOf(page, CRON.title).getByText(CRON.title, { exact: true }).click()
    const pause = page.getByRole('tabpanel').getByRole('button', { name: /Pause|Resume/ })
    await expect(pause).toBeDisabled()
    await expect(pause).toHaveAttribute('title', SHUT)

    // Writing a pipeline is an operator's, and so are the two verbs the editor sends.
    await page.goto('/pipelines')
    const newPipeline = page.getByRole('button', { name: 'New pipeline' })
    await expect(newPipeline).toBeDisabled()
    await expect(newPipeline).toHaveAttribute('title', SHUT)
})

test('a check the server refuses says so, and the row keeps what it had', async ({ page, baseURL }) => {
    await signIn(page)
    await seedConnection(page.request, baseURL ?? '')
    await refuse(page, /\$check$/)

    await page.goto('/connections')
    const row = rowOf(page, CONNECTION)
    await row.getByRole('button', { name: 'Check' }).click()

    await expect(page.getByText('not permitted for your role')).toBeVisible()
    await expect(row).toContainText('never checked')
})

test('a pause the server refuses says so, and the panel stays open', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, CRON.file)
    await refuse(page, /schedules\/[^/]+\/\$pause$/)

    await page.goto('/triggers')
    await rowOf(page, CRON.title).getByText(CRON.title, { exact: true }).click()

    const panel = page.getByRole('tabpanel')
    await panel.getByRole('button', { name: 'Pause' }).click()

    await expect(page.getByText('not permitted for your role')).toBeVisible()
    // The schedule was not paused, and what says so is still on screen.
    await expect(panel.getByRole('button', { name: 'Pause' })).toBeVisible()
})
