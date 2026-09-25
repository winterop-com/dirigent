import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

import { apiPrefix, applyExample, signIn } from './support.ts'

/**
 * The two screens that show what an instance is wired to, against a real one.
 *
 * WHAT THESE SPECS ARE FOR is the half a Node test cannot reach: that a credential's row says
 * what it is and never a word of what it holds, that pressing Check really opens the credential
 * and really moves the row, and that a token minted in the browser is readable in the dialog
 * that mints it and nowhere afterwards.
 *
 * THE CHECK REACHES THIS INSTANCE. The connection points at the server this suite already
 * runs, so a health check is a real request over a real credential with no external network
 * and nothing to be flaky about.
 */

/** The example documents that carry a trigger each. */
const CRON = {
    file: 'examples/triggers/cron-nightly.yaml',
    pipeline: 'cron-nightly',
    schedule: 'nightly',
    // The document names this clock, so the row is headed by the name and carries the code.
    title: 'Nightly, Oslo time',
    // What the pipeline itself is called, which is how the picker heads its row.
    pipelineTitle: 'Nightly load',
}
const HOOK = {
    file: 'examples/triggers/webhook-trigger.yaml',
    pipeline: 'webhook-trigger',
    webhook: 'upstream-publish',
    // The document names the pipeline, so the picker heads its row by the name.
    pipelineTitle: 'Started by a webhook',
}

/** What a secret is drawn as. `DOTS` in lib/connections. */
const DOTS = '●●●'

const CONNECTION = 'e2e-http'

/** The credential the dialog spec types, which must be nowhere on any screen afterwards. */
const MINTED = 'a credential the dialog must never show'

/**
 * Put one connection on the instance, with a secret set and a health path that answers.
 *
 * Minted fresh every time: whether it has been checked is what two of these specs are about,
 * and a row left behind by an earlier run has been.
 */
async function seedConnection(request: APIRequestContext, baseURL: string): Promise<void> {
    const prefix = await apiPrefix(request)
    await request.delete(`${prefix}/connections/${CONNECTION}`)
    const created = await request.post(`${prefix}/connections`, {
        data: {
            code: CONNECTION,
            kind: 'http',
            description: 'This very instance, so a check is a real request.',
            config: {
                base_url: baseURL,
                basic_username: 'dev',
                basic_password: 'a credential nothing may ever show',
                health_path: '/health',
            },
        },
    })
    expect(created.ok(), await created.text()).toBe(true)
}

/**
 * Pick one row of a combobox by typing at it, the way somebody finds a pipeline.
 *
 * The list is portalled out of the dialog, so the option is reached on the page rather than
 * inside it.
 */
async function pick(page: Page, field: string, query: string, option: string): Promise<void> {
    const box = page.getByRole('dialog').getByLabel(field, { exact: true })
    // Emptied first: a box already holding what is about to be typed into it is a box nothing
    // changed, and the list opens on the change.
    await box.fill('')
    await box.fill(query)
    await page.getByRole('option', { name: option }).click()
}

/** The table row one code is in. */
function rowOf(page: Page, code: string) {
    return page.getByRole('row').filter({ hasText: code })
}

test('a connection row is its code, its kind and its health, and nothing else', async ({ page, baseURL }) => {
    await signIn(page)
    await seedConnection(page.request, baseURL ?? '')

    await page.goto('/connections')

    const row = rowOf(page, CONNECTION)
    await expect(row).toContainText('http')

    // The kind is marked as well as named, the way it is on every other screen.
    await expect(row.locator('[data-slot="mark"]')).toHaveCount(1)

    // One line: what the credential is pointed at, what it says about itself and whether a
    // secret is set are read on its own page, beside the boxes that change them.
    await expect(row).not.toContainText('base_url')
    await expect(row).not.toContainText(DOTS)
    await expect(row).not.toContainText('This very instance, so a check is a real request.')

    // The credential itself is nowhere on the screen, in any form.
    await expect(page.locator('body')).not.toContainText('a credential nothing may ever show')

    // It has never been checked until something checks it.
    await expect(row).toContainText('never checked')

    // And the page behind the row is where all of that is.
    await row.click()
    const panel = page.getByRole('tabpanel')
    await expect(panel).toContainText('This very instance, so a check is a real request.')
    await expect(panel.getByLabel('base_url')).toHaveValue(baseURL ?? '')

    // The panel heads the credential the way the row does, mark and all.
    await expect(panel.locator('[data-slot="mark"]')).toHaveCount(1)
})

test('checking a connection moves its own row, and the sentence is on the tooltip', async ({
    page,
    baseURL,
}) => {
    await signIn(page)
    await seedConnection(page.request, baseURL ?? '')

    await page.goto('/connections')
    const row = rowOf(page, CONNECTION)
    await row.getByRole('button', { name: `Check ${CONNECTION}` }).click()

    await expect(row).toContainText('healthy')
    await expect(row).not.toContainText('never checked')

    // What the check said is not on the row: reaching the health cell is what says it. The
    // tooltip primitive describes its trigger rather than carrying a role, so it is found by
    // the slot it is drawn in.
    await expect(row).not.toContainText('HTTP 200')
    await row.getByText('healthy').hover()
    await expect(page.locator('[data-slot="tooltip-content"]')).toContainText('HTTP 200')

    // And it is on the connection's own page in full, where there is room for it.
    await row.click()
    await expect(page.getByRole('tabpanel')).toContainText('HTTP 200')
})

test('the connections listing fits 1024 without scrolling sideways', async ({ page, baseURL }) => {
    await signIn(page)
    await seedConnection(page.request, baseURL ?? '')

    await page.setViewportSize({ width: 1024, height: 768 })
    await page.goto('/connections')
    await expect(rowOf(page, CONNECTION)).toBeVisible()

    // The table's own scroll box rather than the window: a listing wider than the box it is
    // drawn in is the sideways scroll, whether or not the page itself moves.
    const listing = page.locator('.list-scroll')
    expect(await listing.evaluate((box) => box.scrollWidth - box.clientWidth)).toBeLessThanOrEqual(0)

    const sideways = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(sideways).toBeLessThanOrEqual(0)
})

test('the listing beside an open panel draws cards rather than scrolling', async ({ page, baseURL }) => {
    await signIn(page)
    await seedConnection(page.request, baseURL ?? '')

    await page.setViewportSize({ width: 1024, height: 768 })
    await page.goto('/connections')
    await rowOf(page, CONNECTION).click()
    await expect(page.getByRole('tabpanel')).toBeVisible()

    // The panel takes half of what the listing had, and the listing answers for its own box:
    // the same rows drawn as cards rather than a table scrolled sideways inside its card.
    await expect(page.getByRole('listitem').filter({ hasText: CONNECTION })).toBeVisible()
    await expect
        .poll(async () => page.locator('.list-scroll').evaluate((box) => box.scrollWidth - box.clientWidth))
        .toBe(0)

    const sideways = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(sideways).toBeLessThanOrEqual(0)
})

test('a connection opens a form whose secret box is empty and whose kind is fixed', async ({
    page,
    baseURL,
}) => {
    await signIn(page)
    await seedConnection(page.request, baseURL ?? '')

    await page.goto('/connections')
    await rowOf(page, CONNECTION).click()

    // The panel holds the connection's own settings, and the password box starts empty --
    // there is nothing to put in it, because no read anywhere returns a credential.
    const panel = page.getByRole('tabpanel')
    const secret = panel.getByLabel('basic_password')
    await expect(secret).toHaveValue('')
    await expect(secret).toHaveAttribute('type', 'password')
    await expect(panel.getByLabel('base_url')).toHaveValue(baseURL ?? '')
})

test('a connection is minted through the form its own kind publishes', async ({ page, baseURL }) => {
    await signIn(page)
    await page.goto('/connections')

    const code = `minted-${String(Date.now())}`
    await page.getByRole('button', { name: 'New connection' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Code', { exact: true }).fill(code)

    // The kind is a choice over what this instance has installed, and choosing one is what
    // draws the config: every box below is the kind's own schema, its secrets excepted.
    await dialog.getByLabel('Kind').click()
    // Every kind the dialog offers is marked as well as named.
    const kindRow = page.getByRole('option', { name: 'http', exact: true })
    await expect(kindRow.locator('[data-slot="mark"]')).toHaveCount(1)
    await kindRow.click()
    await dialog.getByLabel('base_url').fill(baseURL ?? '')
    await dialog.getByLabel('basic_password').fill(MINTED)

    // A secret is written and never read, here as much as in the panel.
    await expect(dialog.getByLabel('basic_password')).toHaveAttribute('type', 'password')

    await dialog.getByRole('button', { name: 'Create' }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)

    // The row is on the listing, saying which kind it is and never a word of the credential.
    const row = rowOf(page, code)
    await expect(row).toContainText('http')
    await expect(page.locator('body')).not.toContainText(MINTED)

    // And the panel says the same: a stored credential, and an empty box to replace it with.
    await row.click()
    const panel = page.getByRole('tabpanel')
    const secret = panel.getByLabel('basic_password')
    await expect(secret).toHaveValue('')
    await expect(secret).toHaveAttribute('placeholder', /stored/)
    await expect(panel.getByLabel('base_url')).toHaveValue(baseURL ?? '')
})

test('a schedule shows its clock and its zone, and a webhook shows its prefix', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, CRON.file)
    await applyExample(page.request, HOOK.file)

    await page.goto('/triggers')

    const schedule = rowOf(page, CRON.title)
    await expect(schedule).toContainText(CRON.schedule)
    await expect(schedule).toContainText('0 5 * * *')
    await expect(schedule).toContainText('Europe/Oslo')
    await expect(schedule).toContainText(CRON.pipeline)
    await expect(schedule).toContainText('managed')

    // The next firing is an instant like any other: read relatively, and ahead of now.
    await expect(schedule.getByTestId('next-fire')).toHaveText(/^in \d+[mhd]$/)

    const webhook = rowOf(page, HOOK.webhook)
    await expect(webhook).toContainText('POST /hooks/')
    await expect(webhook).toContainText('unsigned')
    await expect(webhook).toContainText('60/min')

    // The foot counts what has been read, and there is no page number anywhere on the screen.
    await expect(page.getByText(/\d+ schedules?/)).toBeVisible()
    await expect(page.getByText(/\d+ webhooks?/)).toBeVisible()
})

test('a schedule opens its own facts and its firing history beside the listing', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, CRON.file)

    await page.goto('/triggers')
    // The row's own heading, rather than its middle: the middle of a row is whichever
    // cell happens to be there, and one of them is a link to the pipeline.
    await rowOf(page, CRON.title).getByText(CRON.title, { exact: true }).click()

    // The panel's own tab, rather than the aside: the navigation rail is an aside too.
    const panel = page.getByRole('tabpanel')
    await expect(panel).toContainText('Europe/Oslo')
    await expect(panel).toContainText('Firings')
    await expect(panel).toContainText('Not fired.')

    // A paused schedule fires at no instant. The row keeps the one the scheduler computed, so
    // that it has somewhere to resume from, and the screen says what is true of it instead.
    await expect(panel.getByTestId('next-fire')).toHaveText(/^in \d+[mhd]$/)
    await panel.getByRole('button', { name: 'Pause' }).click()
    await expect(panel.getByTestId('next-fire')).toHaveText('paused')

    await panel.getByRole('button', { name: 'Resume' }).click()
    await expect(panel.getByTestId('next-fire')).toHaveText(/^in \d+[mhd]$/)
})

test('a webhook minted in the browser shows its token once and never again', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, HOOK.file)

    await page.goto('/triggers')
    await page.getByRole('button', { name: 'New webhook', exact: true }).click()

    const code = `minted-${String(Date.now())}`
    const dialog = page.getByRole('dialog')
    await pick(page, 'Pipeline', HOOK.pipeline, HOOK.pipelineTitle)
    await dialog.getByLabel('Code', { exact: true }).fill(code)

    // The mapping is the pipeline's own parameters, one row each, and a path is written
    // against the one the payload carries.
    await expect(dialog.getByLabel('environment', { exact: true })).toBeVisible()
    await dialog.getByLabel('day', { exact: true }).fill('$.published.date')

    await dialog.getByRole('button', { name: 'Create' }).click()

    // The token is readable exactly here: the instance keeps only its hash.
    const token = page.getByTestId('webhook-token')
    await expect(token).toBeVisible()
    const minted = (await token.textContent()) ?? ''
    expect(minted.length).toBeGreaterThan(8)
    await expect(page.getByRole('dialog')).toContainText('/hooks/')

    await page.getByRole('button', { name: 'Done' }).click()
    await expect(page.getByTestId('webhook-token')).toHaveCount(0)

    // The listing has the webhook, with only the prefix of the token that was minted.
    const row = rowOf(page, code)
    await expect(row).toContainText('POST /hooks/')
    await expect(page.locator('body')).not.toContainText(minted)

    // The row a parameter was left empty on is not in the declaration at all.
    const prefix = await apiPrefix(page.request)
    const read = await page.request.get(`${prefix}/pipelines/${HOOK.pipeline}/triggers/webhooks/${code}`)
    expect((await read.json()).params_from_payload).toEqual({ day: '$.published.date' })
})

test('a schedule is created by picking its pipeline and reading its clock back', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, CRON.file)

    await page.goto('/triggers')
    await page.getByRole('button', { name: 'New schedule', exact: true }).click()

    const code = `picked-${String(Date.now())}`
    const dialog = page.getByRole('dialog')
    await pick(page, 'Pipeline', CRON.pipeline, CRON.pipelineTitle)
    await dialog.getByLabel('Code', { exact: true }).fill(code)
    await pick(page, 'Timezone', 'Europe/Oslo', 'Europe/Oslo')
    await dialog.getByLabel('Cron', { exact: true }).fill('0 5 * * *')

    // The clock is read back by the instance: three firings, in the zone that was chosen.
    const reading = dialog.getByTestId('clock-reading')
    await expect(reading).toContainText('05:00')
    expect(((await reading.textContent()) ?? '').split(' · ')).toHaveLength(3)

    // Choosing the pipeline drew its own parameter form, and a pinned value is sent with it.
    await dialog.getByLabel('day', { exact: true }).fill('2026-02-02')

    await dialog.getByRole('button', { name: 'Create' }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)

    const row = rowOf(page, code)
    await expect(row).toContainText('0 5 * * *')
    await expect(row).toContainText('Europe/Oslo')

    const prefix = await apiPrefix(page.request)
    const read = await page.request.get(`${prefix}/pipelines/${CRON.pipeline}/triggers/schedules/${code}`)
    expect((await read.json()).params).toEqual({ day: '2026-02-02' })
})

test('a clock nothing can read says so where its firings would be, and shuts Create', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, CRON.file)

    await page.goto('/triggers')
    await page.getByRole('button', { name: 'New schedule', exact: true }).click()

    const dialog = page.getByRole('dialog')
    await pick(page, 'Pipeline', CRON.pipeline, CRON.pipelineTitle)
    await dialog.getByLabel('Code', { exact: true }).fill('never')
    await dialog.getByLabel('Cron', { exact: true }).fill('not a cron expression')

    await expect(dialog.getByTestId('clock-reading')).toContainText('is not a cron expression')
    await expect(dialog.getByRole('button', { name: 'Create' })).toBeDisabled()
})
