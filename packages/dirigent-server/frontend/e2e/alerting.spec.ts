import { expect, test, type Page } from '@playwright/test'

import { apiPrefix, signIn, writeInEditor } from './support.ts'

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

/** A channel whose picker row is wider than the box the picker hangs from, on a phone. */
const CHANNEL = { code: 'e2e-ops-alert', name: 'On-call mobile' }

/** A rule whose name is long enough to be cut in the column a 1024 window leaves the table. */
const WIDE = { code: 'e2e-wide-row', name: 'Page the on-call when the nightly load fails' }

test.beforeEach(async ({ page }) => {
    await signIn(page)
    await page.goto('/admin/alerting')
    await expect(page.getByRole('heading', { name: 'Alerting' })).toBeVisible()
})

test.afterEach(async ({ page }) => {
    const prefix = await apiPrefix(page.request)
    await page.request.delete(`${prefix}/alert-rules/${RULE.code}`)
    await page.request.delete(`${prefix}/connections/${CHANNEL.code}`)
    await page.request.delete(`${prefix}/alert-rules/${WIDE.code}`)
})

/**
 * The rule's own row, in whichever form the listing is drawing.
 *
 * A listing beside an open panel has half the width it had and draws its rows as cards, so a
 * test that opens one is asserting about a `listitem` from that moment on.
 */
function ruleRow(page: Page) {
    return page.getByRole('row').or(page.getByRole('listitem')).filter({ hasText: RULE.code })
}

test('the channel strip is one chip per channel, and the words are on the tooltip', async ({ page }) => {
    const strip = page.getByRole('heading', { name: 'Channels' }).locator('..')
    // A chip carries the code and nothing else: the log channel has no credential to name, and
    // a kind nothing is set up for names itself.
    await expect(strip.getByText('log', { exact: true })).toBeVisible()
    await expect(strip.getByText('webhook', { exact: true })).toBeVisible()
    await expect(strip.getByText('not set up')).toBeHidden()

    // The tooltip primitive describes its trigger rather than carrying a role, so it is found
    // by the slot the design system gives it.
    await strip.getByText('log', { exact: true }).hover()
    await expect(page.locator('[data-slot="tooltip-content"]')).toContainText('log · ready')
})

test('a chip of a kind nothing is set up for opens the dialog on that kind', async ({ page }) => {
    const strip = page.getByRole('heading', { name: 'Channels' }).locator('..')
    await strip.getByRole('link', { name: 'webhook' }).click()
    await expect(page).toHaveURL(/\/connections\?new=webhook$/)
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: 'New connection' })).toBeVisible()
    await expect(dialog.getByLabel('Kind')).toContainText('webhook')
})

test('a rule is declared from the screen, and appears in the listing it was declared on', async ({
    page,
}) => {
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

    // A rule names one target and the sender follows from it: one picker, opened on the log.
    await expect(dialog.getByLabel('Deliver through')).toHaveValue('The process log')
    await expect(dialog.getByLabel('Notifier')).toHaveCount(0)

    // A target is a channel, so every row of the picker wears its kind's mark.
    await dialog.getByLabel('Deliver through').click()
    const logRow = page.getByRole('option', { name: 'The process log' })
    await expect(logRow.locator('[data-slot="mark"]')).toHaveCount(1)
    await logRow.click()
    await expect(dialog.getByLabel('Deliver through')).toHaveValue('The process log')

    await dialog.getByLabel('Throttle').fill('15m')
    await expect(create).toBeEnabled()
    await create.click()

    await expect(page.getByRole('dialog')).toHaveCount(0)
    const row = ruleRow(page)
    await expect(row).toContainText(RULE.name)
    await expect(row).toContainText(RULE.code)
    await expect(row).toContainText('Failed')
    await expect(row).toContainText('every pipeline')
    await expect(row).toContainText('log')
    await expect(row).toContainText('15m')
    await expect(row).toContainText('active')
    // The target cell wears the same mark the picker offered it under.
    await expect(row.locator('td').filter({ hasText: 'log' }).locator('[data-slot="mark"]')).toHaveCount(1)
})

test.describe('on a phone', () => {
    test.use({ viewport: { width: 390, height: 844 } })

    test('the four events wrap to two rows, and nothing scrolls sideways', async ({ page }) => {
        await page.getByRole('button', { name: 'New rule' }).click()
        const events = page.getByRole('group', { name: 'Event' }).getByRole('button')
        await expect(events).toHaveCount(4)

        const boxes = await events.evaluateAll((found) =>
            found.map((one) => {
                const box = one.getBoundingClientRect()
                return { top: Math.round(box.top), height: Math.round(box.height) }
            }),
        )
        expect(new Set(boxes.map((box) => box.top)).size).toBe(2)
        expect(Math.min(...boxes.map((box) => box.height))).toBeGreaterThanOrEqual(42)

        const sideways = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
        expect(sideways).toBeLessThanOrEqual(0)
    })

    test('a target row wider than the picker is read whole, and the popup stays on screen', async ({
        page,
    }) => {
        await declareChannel(page)
        await page.reload()

        await page.getByRole('button', { name: 'New rule' }).click()
        const dialog = page.getByRole('dialog')
        const field = dialog.getByLabel('Deliver through')
        await field.click()

        const row = page.getByRole('option', { name: CHANNEL.name })
        await expect(row).toBeVisible()

        // The popup scales in, so its box is read once every animation on it has finished. It
        // outgrew the box it hangs from, and it did it without leaving the screen.
        const popup = page.locator('[data-slot="combobox-content"]')
        await expect
            .poll(async () => {
                const box = await popup.boundingBox()
                const anchor = await field.boundingBox()
                if (box === null || anchor === null) return null
                return {
                    wider: box.width > anchor.width,
                    inside: box.x >= 0 && box.x + box.width <= 390,
                }
            })
            .toEqual({ wider: true, inside: true })

        // Nothing in the row is cut: the popup grew to the label rather than the label to it.
        const cut = await row.evaluate((node) =>
            Math.max(
                ...[node, ...node.querySelectorAll('*')].map((one) => one.scrollWidth - one.clientWidth),
            ),
        )
        expect(cut).toBeLessThanOrEqual(0)

        // And neither the popup nor the page under it has anything to scroll sideways.
        expect(await popup.evaluate((node) => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(0)
        const sideways = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
        expect(sideways).toBeLessThanOrEqual(0)
    })
})

test.describe('in a column narrower than the table', () => {
    // A 1024 window, the rail in front of the screen and the page's own padding either side
    // leave the rules table 712px to be drawn 830px wide in.
    test.use({ viewport: { width: 1024, height: 768 } })

    test('the rules listing draws cards rather than scrolling sideways inside its card', async ({ page }) => {
        const prefix = await apiPrefix(page.request)
        const made = await page.request.post(`${prefix}/alert-rules`, {
            data: { code: WIDE.code, name: WIDE.name, event: 'run_failed', throttle: '15m' },
        })
        expect(made.status()).toBe(201)
        await page.reload()

        const rules = page
            .locator('section')
            .filter({ has: page.getByRole('heading', { name: 'Rules', exact: true }) })
        await expect(rules.getByText(WIDE.code)).toBeVisible()

        // The listing's own scroller rather than the window: a table wider than the box it is
        // drawn in is the sideways scroll, whether or not the page itself moves.
        await expect
            .poll(async () =>
                rules.locator('.list-scroll').evaluate((box) => box.scrollWidth - box.clientWidth),
            )
            .toBe(0)

        // What fits it is the card form, and the header row is gone with the table.
        await expect(rules.getByRole('listitem').filter({ hasText: WIDE.code })).toBeVisible()
        await expect(rules.getByRole('table')).toHaveCount(0)

        const sideways = await page.evaluate(
            () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        )
        expect(sideways).toBeLessThanOrEqual(0)
    })
})

test("a rule's body is written in the dialog and edited in its panel", async ({ page }) => {
    await page.getByRole('button', { name: 'New rule' }).click()
    const dialog = page.getByRole('dialog')

    await dialog.getByLabel('Code').fill(RULE.code)
    await dialog.getByLabel('Name').fill(RULE.name)
    await dialog.getByLabel('Subject').fill('{{ run.pipeline }} failed')

    // The body is a Jinja pane rather than a box: it is written on the lines it was written on,
    // and the window beside it carries the reference for what a template may read.
    const pane = dialog.getByTestId('code-editor').first()
    await writeInEditor(page, pane, 'The run of {{ run.pipeline }} ended {{ run.status }}.')
    await dialog.getByLabel('Open body in a window').click()
    const window = page.getByRole('dialog').filter({ hasText: 'Jinja reference' })
    await expect(window).toBeVisible()
    await page.keyboard.press('Escape')

    await dialog.getByRole('button', { name: 'Create' }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)

    // The panel says what the rule sends, subject and body both.
    await ruleRow(page).getByText(RULE.name, { exact: true }).click()
    const panel = page.getByRole('tabpanel')
    await expect(panel).toContainText('{{ run.pipeline }} failed')
    await expect(panel).toContainText('The run of {{ run.pipeline }} ended {{ run.status }}.')

    // Editing happens under the facts it is about rather than in a second dialog.
    await panel.getByRole('button', { name: 'Edit' }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await writeInEditor(page, panel.getByTestId('code-editor').first(), 'Rewritten for {{ run.status }}.')
    await panel.getByRole('button', { name: 'Save' }).click()

    await expect(panel).toContainText('Rewritten for {{ run.status }}.')
    await expect(panel.getByRole('button', { name: 'Edit' })).toBeVisible()

    // It is the rule that changed, not the screen: a re-read finds the body as it was saved.
    await page.reload()
    await ruleRow(page).getByText(RULE.name, { exact: true }).click()
    await expect(page.getByRole('tabpanel')).toContainText('Rewritten for {{ run.status }}.')
})

test('a rule is paused from its panel, and the row says so', async ({ page }) => {
    await declareRule(page)
    await page.reload()

    await ruleRow(page).getByText(RULE.name, { exact: true }).click()
    const panel = page.getByRole('tabpanel')
    await expect(panel.getByText(RULE.code)).toBeVisible()
    // The panel says the target the same way the listing does: the log, for a rule naming nothing,
    // wearing the channel's own mark.
    await expect(panel.getByText('Delivers through')).toBeVisible()
    const target = panel.locator('dt', { hasText: 'Delivers through' }).locator('xpath=following-sibling::dd')
    await expect(target).toContainText('log')
    await expect(target.locator('[data-slot="mark"]')).toHaveCount(1)

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

test('a test stays open until the row settles, and reaches sent through the log channel', async ({
    page,
}) => {
    await page.getByRole('button', { name: 'Send a test' }).click()

    const dialog = page.getByRole('dialog')
    const send = dialog.getByRole('button', { name: 'Send', exact: true })

    // A test names one target the way a rule does: one picker, opened on the log, and nothing
    // to fill in before it can be sent.
    await expect(dialog.getByLabel('Deliver through')).toHaveValue('The process log')
    await expect(dialog.getByLabel('Notifier')).toHaveCount(0)
    await expect(dialog.getByLabel('Connection')).toHaveCount(0)
    await expect(send).toBeEnabled()

    // A target is a channel, so every row of the picker wears its kind's mark.
    await dialog.getByLabel('Deliver through').click()
    const logRow = page.getByRole('option', { name: 'The process log' })
    await expect(logRow.locator('[data-slot="mark"]')).toHaveCount(1)
    await logRow.click()

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

test('a delivered notification is put back on the queue, and its attempts start over', async ({ page }) => {
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
    await expect(page.getByRole('row').filter({ hasText: subject }).locator('.status-chip')).toContainText(
        'sent',
        {
            timeout: 30_000,
        },
    )

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
        data: { code: RULE.code, name: RULE.name, event: 'run_failed', throttle: '15m' },
    })
    expect(answer.status()).toBe(201)
}

/** Mint the channel whose picker row is longer than a phone's field. */
async function declareChannel(page: Page): Promise<void> {
    const prefix = await apiPrefix(page.request)
    const answer = await page.request.post(`${prefix}/connections`, {
        data: {
            code: CHANNEL.code,
            name: CHANNEL.name,
            kind: 'webhook',
            config: { url: 'https://alerts.invalid/on-call' },
        },
    })
    expect(answer.status()).toBe(201)
}

/** Queue one message through the log channel, which the dialog opens on, and close it behind. */
async function sendTest(page: Page, subject: string): Promise<void> {
    await page.getByRole('button', { name: 'Send a test' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByLabel('Deliver through')).toHaveValue('The process log')
    await dialog.getByLabel('Subject').fill(subject)
    await dialog.getByRole('button', { name: 'Send', exact: true }).click()
    // Closed only once the row has settled, so the listing behind has been read again with it.
    await expect(dialog.getByTestId('test-delivery').locator('.status-chip')).toContainText('sent', {
        timeout: 30_000,
    })
    await dialog.getByRole('button', { name: 'Close' }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
}
