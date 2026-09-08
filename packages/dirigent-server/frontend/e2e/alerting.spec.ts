import { expect, test, type Page } from '@playwright/test'

import { apiPrefix, signIn } from './support.ts'

/**
 * The alerting screen: the channels, the rules, and the queue.
 *
 * EVERY TEST HERE GOES THROUGH THE LOG CHANNEL, which needs no credential and is delivered by
 * the worker `dg dev` runs in the same process. That is the whole point of the built-in
 * channel: an instance with no connection minted can still prove the path end to end, so this
 * suite proves the screen against a real delivery rather than against a stubbed one.
 *
 * THE SUITE SHARES ONE INSTANCE, so every rule this file declares is coded for this file and
 * removed when it is done with it.
 */

const RULE = { code: 'e2e-page-ops', name: 'Page the on-call' }

test.beforeEach(async ({ page }) => {
    await signIn(page)
    await page.goto('/admin/alerting')
    await expect(page.getByRole('heading', { name: 'Alerting' })).toBeVisible()
})

test.afterEach(async ({ page }) => {
    const prefix = await apiPrefix(page.request)
    await page.request.delete(`${prefix}/alert-rules/${RULE.code}`)
})

function ruleRow(page: Page) {
    return page.getByRole('row').filter({ hasText: RULE.code })
}

test('the channel strip says what an alert can leave by, and that log needs nothing', async ({ page }) => {
    const strip = page.getByRole('heading', { name: 'Channels' }).locator('..')
    await expect(strip.getByText('log', { exact: true })).toBeVisible()
    await expect(strip.getByText('built in')).toBeVisible()
    // A notifier with no credential minted for it is a channel nothing can reach, and the strip
    // is where that is visible rather than a rule failing later.
    await expect(strip.getByText('no connection').first()).toBeVisible()
})

test('a rule is declared from the screen, and appears in the listing it was declared on', async ({ page }) => {
    await page.getByRole('button', { name: 'New rule' }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: 'New rule' })).toBeVisible()

    // Create is shut until the rule says enough to be one, and says why.
    const create = dialog.getByRole('button', { name: 'Create' })
    await expect(create).toBeDisabled()
    await expect(create).toHaveAttribute('title', 'A rule is addressed by its code, and this one has none.')

    await dialog.getByLabel('Code').fill(RULE.code)
    await dialog.getByLabel('Name').fill(RULE.name)
    await dialog.getByRole('button', { name: 'Failed' }).click()
    await dialog.getByRole('button', { name: 'Every pipeline' }).click()

    // The notifier is a picker over the installed channels, and log is the one that needs no
    // connection beside it -- so no connection picker is drawn at all.
    await dialog.getByLabel('Notifier').click()
    await page.getByRole('option', { name: 'log', exact: true }).click()
    await expect(dialog.getByLabel('Connection')).toHaveCount(0)

    await dialog.getByLabel('Throttle').fill('15m')
    await expect(create).toBeEnabled()
    await create.click()

    await expect(page.getByRole('dialog')).toHaveCount(0)
    const row = ruleRow(page)
    await expect(row).toContainText(RULE.name)
    await expect(row).toContainText(RULE.code)
    await expect(row).toContainText('Failed')
    await expect(row).toContainText('every pipeline')
    await expect(row).toContainText('15m')
    await expect(row).toContainText('active')
})

test('a rule is paused from its panel, and the row says so', async ({ page }) => {
    await declareRule(page)
    await page.reload()

    await ruleRow(page).getByText(RULE.name, { exact: true }).click()
    const panel = page.getByRole('tabpanel')
    await expect(panel.getByText(RULE.code)).toBeVisible()

    await panel.getByRole('button', { name: 'Pause' }).click()
    await expect(panel.getByRole('button', { name: 'Resume' })).toBeVisible()
    await expect(ruleRow(page)).toContainText('paused')

    // Pausing is instance state on the row, so a re-read finds it still held.
    await page.reload()
    await expect(ruleRow(page)).toContainText('paused')

    await ruleRow(page).getByText(RULE.name, { exact: true }).click()
    await page.getByRole('tabpanel').getByRole('button', { name: 'Resume' }).click()
    await expect(ruleRow(page)).toContainText('active')
})

test('a test stays open until the row settles, and reaches sent through the log channel', async ({ page }) => {
    await page.getByRole('button', { name: 'Send a test' }).click()

    const dialog = page.getByRole('dialog')
    const send = dialog.getByRole('button', { name: 'Send', exact: true })
    await expect(send).toBeDisabled()
    await expect(send).toHaveAttribute('title', 'A test goes through a channel, and this one names none.')

    await dialog.getByLabel('Notifier').click()
    await page.getByRole('option', { name: 'log', exact: true }).click()
    await dialog.getByLabel('Subject').fill('e2e test alert')
    await send.click()

    // The dialog does not close on "queued": it reads the row back until a worker has tried it.
    const outcome = dialog.getByTestId('test-delivery')
    await expect(outcome).toBeVisible()
    await expect(outcome).toContainText('e2e test alert')
    await expect(outcome.locator('.status-chip')).toContainText('sent', { timeout: 30_000 })
    await expect(outcome).toContainText('Delivered')

    // And having sent one, the verb is to send another rather than to send.
    await expect(dialog.getByRole('button', { name: 'Send again' })).toBeVisible()

    await dialog.getByRole('button', { name: 'Open in the queue' }).click()
    const panel = page.getByRole('tabpanel')
    await expect(panel.getByText('e2e test alert')).toBeVisible()
    await expect(panel.getByText('a test, not a rule')).toBeVisible()
})

test("a delivered notification is put back on the queue, and its attempts start over", async ({ page }) => {
    const subject = `e2e retry ${String(Date.now())}`
    await sendTest(page, subject)

    const row = page.getByRole('row').filter({ hasText: subject })
    await expect(row.locator('.status-chip')).toContainText('sent', { timeout: 30_000 })

    await row.getByText(subject, { exact: true }).click()
    const panel = page.getByRole('tabpanel')
    await expect(panel).toContainText('Attempts')

    // A retry starts the delivery over rather than adding one try to a spent budget: the row
    // goes back to pending, due now, with its counter at nothing and its last refusal gone.
    await panel.getByRole('button', { name: 'Retry now' }).click()
    await expect(panel.locator('.status-chip')).toContainText('pending')
    await expect(panel).toContainText('0 of')
})

test('the queue narrows by status and by notifier', async ({ page }) => {
    const subject = `e2e filter ${String(Date.now())}`
    await sendTest(page, subject)
    await expect(page.getByRole('row').filter({ hasText: subject }).locator('.status-chip')).toContainText('sent', {
        timeout: 30_000,
    })

    await page.getByRole('button', { name: /^Status:/ }).click()
    await page.getByRole('menuitemradio', { name: /failed/ }).click()
    await expect(page.getByRole('row').filter({ hasText: subject })).toHaveCount(0)

    await page.getByRole('button', { name: /^Status:/ }).click()
    await page.getByRole('menuitemradio', { name: 'Any status' }).click()
    await expect(page.getByRole('row').filter({ hasText: subject })).toHaveCount(1)
})

/** Declare the rule this file works with, over the API, so the screen tests stay about the screen. */
async function declareRule(page: Page): Promise<void> {
    const prefix = await apiPrefix(page.request)
    const answer = await page.request.post(`${prefix}/alert-rules`, {
        data: { code: RULE.code, name: RULE.name, event: 'run_failed', notifier: 'log', throttle: '15m' },
    })
    expect(answer.status()).toBe(201)
}

/** Queue one message through the log channel and close the dialog behind it. */
async function sendTest(page: Page, subject: string): Promise<void> {
    await page.getByRole('button', { name: 'Send a test' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Notifier').click()
    await page.getByRole('option', { name: 'log', exact: true }).click()
    await dialog.getByLabel('Subject').fill(subject)
    await dialog.getByRole('button', { name: 'Send', exact: true }).click()
    // Closed only once the row has settled, so the listing behind has been read again with it.
    await expect(dialog.getByTestId('test-delivery').locator('.status-chip')).toContainText('sent', {
        timeout: 30_000,
    })
    await dialog.getByRole('button', { name: 'Close' }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
}
