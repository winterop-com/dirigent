import { expect, test, type Page } from '@playwright/test'

import { LABELS } from '../src/lib/labels.ts'
import { applyDocument, applyExample, ranToCompletion, signIn, startRun } from './support.ts'

/**
 * The two listing screens, against a real instance this suite applied documents to and ran one
 * of.
 *
 * WHAT THESE SPECS ARE FOR is the half a Node test cannot reach: that a row on the pipelines
 * screen carries facts the listing query computes -- the version, what fires it, how the last
 * run went -- and that a row on the runs screen opens the run it stands for.
 *
 * The two examples are pure transforms with no network and no allowlisted block, so a run of
 * one settles in well under a second and this spec asserts on a finished run without waiting.
 */

// TITLE ELSE CODE: every shipped example names itself, so those rows are headed by their
// names; the nameless document below is the row headed by its code.
const RAN = {
    file: 'examples/transform/std-convert-fan-out.yaml',
    code: 'std-convert-fan-out',
    title: 'Convert and fan out',
}

/** The opening line of that example's description, which the pane renders as markdown. */
const IDLE = { file: 'examples/transform/jq-reshape.yaml', code: 'jq-reshape', title: 'Reshape with jq' }

/** A document with no name, whose row is therefore headed by its code. */
const NAMELESS = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: 'headed-by-its-code',
    requires: { blocks: ['transform.jq'] },
    steps: { total: { block: 'transform.jq', config: { input: [1, 2, 3], program: 'add' } } },
}

/** A line no renderer would put back, so seeing it proves the pane holds the file's own text. */
const TYPED_COMMENT = '# Typed, comment and all, then picked off disk.'

/**
 * A document small enough to type, applied through the dialog rather than through the API.
 *
 * The description carries the moment this run wrote it, because the scratch database outlives
 * one invocation of this suite: without it the second run of the file applies a document the
 * instance already holds, and the plan is `unchanged` rather than the write being asserted on.
 */
const TYPED = `${TYPED_COMMENT}
format: dirigent/v1
kind: pipeline
code: typed-in-the-browser
name: Typed in the browser
description: Applied from the pipelines screen at ${String(Date.now())}.
requires:
  blocks:
    - transform.jq
steps:
  total:
    block: transform.jq
    config:
      input: [1, 2, 3]
      program: add
`

/** The row a pipeline is drawn on, found by the title it is headed with. */
function rowOf(page: Page, title: string) {
    return page.getByTestId('pipeline-row').filter({ has: page.getByTitle(title, { exact: true }) })
}

/**
 * The newest run of one pipeline on the runs listing, headed the way every screen heads one.
 *
 * The scratch database outlives an invocation of this suite, so a pipeline this file has run
 * before has rows from those runs too; the listing is newest first, so the first row is this
 * run's.
 */
function runRowOf(page: Page, code: string) {
    return page.getByRole('row').filter({ hasText: code }).first()
}

/** Every row of the runs listing standing for a run of one pipeline. */
function runRowsOf(page: Page, code: string) {
    return page.getByRole('row').filter({ hasText: code })
}

test('the pipelines listing carries the identity, the shape and the last run', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, RAN.file)
    await applyExample(page.request, IDLE.file)
    await applyDocument(page.request, NAMELESS)
    const runId = await startRun(page.request, RAN.code)
    await ranToCompletion(page.request, runId)

    await page.goto('/pipelines?examples=all')

    // Each is headed by its name where it has one, with the code it is addressed by on the row,
    // and led by its miniature graph.
    await expect(rowOf(page, RAN.title)).toContainText(RAN.code)
    await expect(rowOf(page, RAN.title)).not.toContainText('v1')
    await expect(rowOf(page, IDLE.title)).toContainText(IDLE.code)
    await expect(rowOf(page, NAMELESS.code)).toBeVisible()
    await expect(rowOf(page, RAN.title).locator('svg.mini-graph')).toBeVisible()

    // The one that ran says how it went; the one that has not run says nothing there at all.
    await expect(rowOf(page, RAN.title).locator('.status-chip')).toBeVisible()
    await expect(rowOf(page, IDLE.title).locator('.status-chip')).toHaveCount(0)

    // The row is the link to the pipeline's page.
    await rowOf(page, RAN.title).click()
    await expect(page).toHaveURL(new RegExp(`/pipelines/${RAN.code}$`))
})

/**
 * TAGS ARE THE CORPUS'S OWN WORDS, and the filter beside the search box is a question put to
 * the server rather than a squint at the rows already loaded -- so a row the filter excludes is
 * one the listing never asked for, and this is the seam a Node test cannot reach.
 */
test('a tag in the address narrows the pipelines listing, and its chip widens it again', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, RAN.file)
    await applyExample(page.request, IDLE.file)

    // Both examples are tagged transform; only the fan-out one is tagged graph.
    await page.goto('/pipelines?examples=all&tag=graph')
    await expect(rowOf(page, RAN.title)).toBeVisible()
    await expect(rowOf(page, IDLE.title)).toHaveCount(0)

    // The filter stands above the lists as a chip that removes itself, and removing it asks the
    // wide question again.
    await page.getByRole('button', { name: 'Stop filtering by graph' }).click()
    await expect(rowOf(page, IDLE.title)).toBeVisible()
    await expect(page).not.toHaveURL(/tag=/)
})

test('two tags narrow the pipelines listing, and the address carries what they narrowed to', async ({
    page,
}) => {
    await signIn(page)
    await applyExample(page.request, RAN.file)
    await applyExample(page.request, IDLE.file)

    // A filtered listing is a link somebody sends, so the address is where the filter can start.
    await page.goto('/pipelines?examples=all&tag=transform')
    await expect(rowOf(page, RAN.title)).toBeVisible()
    await expect(rowOf(page, IDLE.title)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Stop filtering by transform' })).toBeVisible()

    // The option wears what its value wears: the menu rows are the chips the listing draws.
    await page.getByRole('button', { name: LABELS.shell.tag_filter.label }).click()
    await page.getByRole('menuitemcheckbox', { name: 'graph', exact: true }).click()

    await expect(page).toHaveURL(/tag=transform&tag=graph$/)
    await expect(rowOf(page, RAN.title)).toBeVisible()
    await expect(rowOf(page, IDLE.title)).toHaveCount(0)
})

/**
 * The runs listing asks the pipeline, so this is the join a Node test cannot reach: the rows it
 * leaves out are runs whose pipeline does not wear the tag, not runs missing a field.
 */
test('the runs listing narrows by the tags the runs pipeline wears, and no row repeats them', async ({
    page,
}) => {
    await signIn(page)
    await applyExample(page.request, RAN.file)
    await applyDocument(page.request, NAMELESS)
    const graphed = await startRun(page.request, RAN.code)
    const untagged = await startRun(page.request, NAMELESS.code)
    await ranToCompletion(page.request, graphed)
    await ranToCompletion(page.request, untagged)

    await page.goto('/runs')
    await expect(runRowOf(page, RAN.code)).toBeVisible()
    await expect(runRowOf(page, NAMELESS.code)).toBeVisible()

    await page.getByRole('button', { name: LABELS.shell.tag_filter.label }).click()
    await page.getByRole('menuitemcheckbox', { name: 'graph', exact: true }).click()
    await page.keyboard.press('Escape')

    await expect(runRowOf(page, RAN.code)).toBeVisible()
    await expect(runRowsOf(page, NAMELESS.code)).toHaveCount(0)

    // A run row names its pipeline, so the vocabulary that pipeline wears is not repeated here.
    await expect(runRowOf(page, RAN.code)).not.toContainText('transform')
})

test('a run on the listing wears its state, and the row opens it', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, RAN.file)
    const runId = await startRun(page.request, RAN.code)
    await ranToCompletion(page.request, runId)

    await page.goto('/runs')

    // NOTHING DRAWS THE ID. A run row is headed by its pipeline and opened by the row itself.
    const row = runRowOf(page, RAN.code)
    await expect(row).not.toContainText(runId.slice(-8))
    await expect(row.locator('.status-chip[data-status="succeeded"]')).toBeVisible()

    // TITLE ELSE CODE, HERE TOO. A run row carries its pipeline's code and nothing else, so the
    // screen reads the names and heads the row the way the pipelines listing heads its own --
    // with the code it is addressed by still under it.
    await expect(row).toContainText(RAN.title)
    await expect(row).toContainText(RAN.code)

    await row.click()
    await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`))
    await expect(page.locator('.react-flow__node').getByText('parse', { exact: true })).toBeVisible()
})

test('a file picked on the listing lands in the new-document editor, and applying lists it', async ({
    page,
}) => {
    await signIn(page)
    await page.goto('/pipelines')

    // From a file… lives behind the split button's chevron and opens the OS picker directly.
    await page.getByRole('button', { name: LABELS.pipelines.more_ways }).click()
    const picking = page.waitForEvent('filechooser')
    await page.getByRole('menuitem', { name: LABELS.pipelines.from_file }).click()
    const chooser = await picking
    await chooser.setFiles({ name: 'typed.yaml', mimeType: 'text/yaml', buffer: Buffer.from(TYPED) })

    // The document arrives in the editor, and the source pane holds the file's own text --
    // comments and all, because nothing has re-rendered it from the document yet.
    await expect(page).toHaveURL(/\/pipelines\/\$new$/)
    await page.locator('aside').getByRole('tab', { name: LABELS.word.source }).click()
    const lines = page.getByTestId('code-editor').locator('.view-lines')
    await expect(lines).toContainText('typed-in-the-browser')
    await expect(lines).toContainText(TYPED_COMMENT)

    await page.getByRole('button', { name: LABELS.action.apply, exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText(/Apply (creates|writes version)/)).toBeVisible()
    await dialog.getByRole('button', { name: LABELS.action.apply }).click()
    await expect(page).toHaveURL(/\/pipelines\/typed-in-the-browser$/)

    // TITLE ELSE CODE: this document gave itself a name, so the row's link wears the name and
    // the code it is addressed by is beside it in mono.
    await page.goto('/pipelines')
    const applied = rowOf(page, 'Typed in the browser')
    await expect(applied).toBeVisible()
    await expect(applied).toContainText('typed-in-the-browser')
})

/** A parent that starts three child runs, each triggered by a step of it. */
const PARENT = { file: 'examples/patterns/pipeline-run-with-params.yaml', code: 'pipeline-run-with-params' }
const CHILD = { file: 'examples/patterns/pipeline-run-child.yaml', code: 'pipeline-run-child' }

test.describe('a run started by a step of another run', () => {
    test.use({ viewport: { width: 1024, height: 768 } })

    test('names its parent briefly, holds the table in its box, and opens the parent', async ({ page }) => {
        await signIn(page)
        await applyExample(page.request, CHILD.file)
        await applyExample(page.request, PARENT.file)
        const parent = await startRun(page.request, PARENT.code)
        await ranToCompletion(page.request, parent)

        await page.goto('/runs')
        const row = runRowOf(page, CHILD.code)
        await expect(row).toBeVisible()
        // At a desk width the listing is still a table: the trigger cell yields rather than
        // pushing the columns past the box.
        await expect(page.getByRole('table')).toBeVisible()

        // The parent is named by the tail of its id, and the whole of what was recorded is on
        // hover.
        const trigger = row.locator('td').nth(2).locator('[title]')
        await expect(trigger).toContainText(parent.slice(-8))
        await expect(trigger).not.toContainText(parent)
        await expect(trigger).toHaveAttribute('title', new RegExp(parent))

        // NOTHING SCROLLS SIDEWAYS: the listing's content fits its own box.
        const overflow = await page
            .locator('.list-scroll')
            .first()
            .evaluate((box) => box.scrollWidth - box.clientWidth)
        expect(overflow).toBeLessThanOrEqual(0)

        // The run's own panel names the parent the same way, and is the way to it. The panel
        // stands beside the graph at a desk width.
        await page.setViewportSize({ width: 1280, height: 720 })
        await row.click()
        await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+$/)
        await expect(page.locator('.react-flow__node').first()).toBeVisible()
        await page.getByRole('button', { name: LABELS.shell.toggle_panel }).click()
        const panel = page.locator('aside')
        await panel.getByRole('tab', { name: 'Run' }).click()
        const toParent = panel.getByRole('link', { name: `a step of run ${parent.slice(-8)}` })
        await expect(toParent).toBeVisible()
        await toParent.click()
        await expect(page).toHaveURL(new RegExp(`/runs/${parent}$`))
    })
})
