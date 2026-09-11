import { readFile } from 'node:fs/promises'

import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

import { applyExample, ranToCompletion, signIn, startRun } from './support.ts'

/**
 * The run terminal, against a run this suite really started on a real `dg dev`.
 *
 * THE EXAMPLE IS CHOSEN FOR WHAT IT WRITES. `examples/transform/jq-stream-through-storage.yaml`
 * is three pure transforms -- no network, no allowlisted block, settled in under a second -- and
 * two of them save their result to storage, which is a log line each. So a settled run of it has
 * lines from more than one step, in an order the document fixes: `generate` writes before `cold`
 * can read what it wrote.
 */

const EXAMPLE = 'examples/transform/jq-stream-through-storage.yaml'
const PIPELINE = 'jq-stream-through-storage'

/** What each of the two writing steps says, which is one line apiece; `summary` saves
 * nothing, so its one line is the engine's own settlement trace. */
const SAVED = 'transform result saved'

/** The labels this screen's own controls carry, spelled as the components export them. */
const TOGGLE = "Show or hide this run's terminal"
const STEP_FILTER = 'Filter by step'
const LEVEL_FILTER = 'Least level shown'
const MATCH_FILTER = 'Filter lines by text'
const RESIZE = 'Resize the terminal'

/** Apply the example, run it, and wait for it to settle, answering with the run's id. */
async function settledRun(request: APIRequestContext): Promise<string> {
    await applyExample(request, EXAMPLE)
    const runId = await startRun(request, PIPELINE)
    await ranToCompletion(request, runId)
    return runId
}

/** Open the drawer from the run screen's own strip, and wait for it to be there. */
async function openTerminal(page: Page): Promise<void> {
    await page.getByRole('button', { name: TOGGLE }).click()
    await expect(page.getByRole('region', { name: 'Run terminal' })).toBeVisible()
}

/** The step each line on screen is prefixed with, in the order the lines are drawn. */
async function stepsOnScreen(page: Page): Promise<string[]> {
    return page
        .locator('[data-log-line] button')
        .allTextContents()
        .then((names) => names.map((name) => name.trim()))
}

test('the terminal draws every step of a run, interleaved in the order it wrote them', async ({ page }) => {
    await signIn(page)
    const runId = await settledRun(page.request)

    await page.goto(`/runs/${runId}`)
    await openTerminal(page)

    const terminal = page.getByRole('region', { name: 'Run terminal' })
    await expect(terminal.getByText(SAVED).first()).toBeVisible({ timeout: 30_000 })
    await expect(terminal.locator('[data-log-line]')).toHaveCount(3)

    // MORE THAN ONE STEP, IN THE RUN'S OWN ORDER. generate writes the file cold reads, so the
    // order on screen is the order the run happened in rather than a grouping by step.
    expect(await stepsOnScreen(page)).toEqual(['generate', 'cold', 'summary'])
    await expect(terminal.getByText('3 of 3 lines')).toBeVisible()
})

test('the three filters narrow the lines, and the count says how far', async ({ page }) => {
    await signIn(page)
    const runId = await settledRun(page.request)

    await page.goto(`/runs/${runId}`)
    await openTerminal(page)
    const terminal = page.getByRole('region', { name: 'Run terminal' })
    await expect(terminal.locator('[data-log-line]')).toHaveCount(3)

    // ONE STEP.
    await page.getByLabel(STEP_FILTER).click()
    await page.getByRole('option', { name: 'cold', exact: true }).click()
    await expect(terminal.locator('[data-log-line]')).toHaveCount(1)
    expect(await stepsOnScreen(page)).toEqual(['cold'])
    await expect(terminal.getByText('1 of 3 lines')).toBeVisible()

    // AND A MATCH ON TOP OF IT, because the three compose rather than replace one another.
    await page.getByLabel(MATCH_FILTER).fill('nothing writes this')
    await expect(terminal.locator('[data-log-line]')).toHaveCount(0)
    await expect(terminal.getByText(/No line matches these filters/)).toBeVisible()

    // AND A THRESHOLD NO LINE MEETS, which says the same thing rather than "nothing logged".
    await page.getByLabel(MATCH_FILTER).fill('')
    await page.getByLabel(LEVEL_FILTER).click()
    await page.getByRole('option', { name: 'Errors only' }).click()
    await expect(terminal.locator('[data-log-line]')).toHaveCount(0)
    await expect(terminal.getByText(/No line matches these filters/)).toBeVisible()
})

test("a line's step prefix opens that step in the panel", async ({ page }) => {
    await signIn(page)
    const runId = await settledRun(page.request)

    await page.goto(`/runs/${runId}`)
    await openTerminal(page)
    await expect(page.locator('[data-log-line]')).toHaveCount(3)

    // Put the reader on another tab first, so what is asserted is the prefix moving them rather
    // than the panel happening to open on its first tab.
    await page.locator('.react-flow__node').getByText('summary', { exact: true }).click()
    const panel = page.locator('aside')
    await panel.getByRole('tab', { name: 'Run' }).click()
    await expect(panel.getByRole('tab', { name: 'Run' })).toHaveAttribute('aria-selected', 'true')

    await page.locator('[data-log-line] button', { hasText: 'generate' }).click()

    await expect(panel.getByRole('tab', { name: 'Step' })).toHaveAttribute('aria-selected', 'true')
    await expect(panel.getByText('generate', { exact: true })).toBeVisible()
})

test('the drawer keeps the height it was dragged to, across a reload', async ({ page }) => {
    await signIn(page)
    const runId = await settledRun(page.request)

    await page.goto(`/runs/${runId}`)
    await openTerminal(page)

    const terminal = page.getByRole('region', { name: 'Run terminal' })
    const before = (await terminal.boundingBox())?.height ?? 0
    expect(before).toBeGreaterThan(0)

    // The top edge dragged upward makes the drawer taller, which is what `grows: -1` means.
    const handle = page.getByRole('separator', { name: RESIZE })
    const grip = await handle.boundingBox()
    expect(grip).not.toBeNull()
    if (grip === null) return
    await page.mouse.move(grip.x + grip.width / 2, grip.y + grip.height / 2)
    await page.mouse.down()
    await page.mouse.move(grip.x + grip.width / 2, grip.y - 90, { steps: 10 })
    await page.mouse.up()

    const dragged = (await terminal.boundingBox())?.height ?? 0
    expect(dragged).toBeGreaterThan(before + 40)

    // PX-INTENT SURVIVES THE RELOAD, and so does the drawer being open at all.
    await page.reload()
    await expect(page.getByRole('region', { name: 'Run terminal' })).toBeVisible()
    const held = (await page.getByRole('region', { name: 'Run terminal' }).boundingBox())?.height ?? 0
    expect(Math.abs(held - dragged)).toBeLessThan(4)
})

test("download raw saves the run's whole log as NDJSON", async ({ page }) => {
    await signIn(page)
    const runId = await settledRun(page.request)

    await page.goto(`/runs/${runId}`)
    await openTerminal(page)
    await expect(page.locator('[data-log-line]')).toHaveCount(3)

    // FETCHED AND BLOBBED, NOT LINKED. `$logs` answers a page of JSON with no
    // content-disposition, so the pages are walked and written out here -- which is why this
    // asserts on what arrives rather than on where an anchor points.
    const saving = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Download every line as NDJSON' }).click()
    await expect(page.getByText('3 lines saved')).toBeVisible()
    const saved = await saving

    expect(saved.suggestedFilename()).toBe(`dirigent-run-${runId}.ndjson`)
    const path = await saved.path()
    const text = await readFile(path, 'utf8')
    const lines = text.split('\n').filter((line) => line !== '')
    expect(lines).toHaveLength(3)
    expect(lines.map((line) => (JSON.parse(line) as { step_name: string }).step_name)).toEqual([
        'generate',
        'cold',
        'summary',
    ])
})

test('opening the terminal opens no second stream', async ({ page }) => {
    await signIn(page)
    const runId = await settledRun(page.request)

    const asked: string[] = []
    page.on('request', (request) => {
        asked.push(request.url())
    })

    await page.goto(`/runs/${runId}`)
    await expect(page.locator('.react-flow__node').first()).toBeVisible()
    const streamsBefore = asked.filter((url) => url.includes('%24events') || url.includes('$events')).length

    await openTerminal(page)
    await expect(page.locator('[data-log-line]')).toHaveCount(3)

    // THE ONE STREAM IS THE ONE STREAM. The drawer draws the run's whole log off the connection
    // the screen already holds, so opening it costs neither a second event stream nor a log tail.
    const streamsAfter = asked.filter((url) => url.includes('%24events') || url.includes('$events')).length
    expect(streamsAfter).toBe(streamsBefore)
    expect(asked.filter((url) => url.includes('%24logs') || url.includes('$logs'))).toEqual([])
})

test('the bare `t` shows and hides the drawer, and never out of a box being typed into', async ({ page }) => {
    await signIn(page)
    const runId = await settledRun(page.request)

    await page.goto(`/runs/${runId}`)
    await expect(page.locator('.react-flow__node').first()).toBeVisible()

    const terminal = page.getByRole('region', { name: 'Run terminal' })
    await expect(terminal).toBeHidden()

    await page.locator('body').press('t')
    await expect(terminal).toBeVisible()
    await expect(terminal.locator('[data-log-line]')).toHaveCount(3)

    await page.locator('body').press('t')
    await expect(terminal).toBeHidden()

    // A `t` typed into the drawer's own match box is a letter, not the key that shuts it.
    await page.getByRole('button', { name: TOGGLE }).click()
    await expect(terminal).toBeVisible()
    await page.getByLabel(MATCH_FILTER).fill('t')
    await expect(terminal).toBeVisible()
    await expect(page.getByLabel(MATCH_FILTER)).toHaveValue('t')
})
