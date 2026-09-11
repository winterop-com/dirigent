import { expect, test, type Locator, type Page } from '@playwright/test'

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
const DESCRIPTION = 'Store an inline csv, re-encode it as json'
const IDLE = { file: 'examples/transform/jq-reshape.yaml', code: 'jq-reshape', title: 'Reshape with jq' }

/** A document with no name, whose row is therefore headed by its code. */
const NAMELESS = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: 'headed-by-its-code',
    requires: { blocks: ['transform.jq'] },
    steps: { total: { block: 'transform.jq', config: { input: [1, 2, 3], program: 'add' } } },
}

/**
 * A document small enough to type, applied through the dialog rather than through the API.
 *
 * The description carries the moment this run wrote it, because the scratch database outlives
 * one invocation of this suite: without it the second run of the file applies a document the
 * instance already holds, and the plan is `unchanged` rather than the write being asserted on.
 */
const TYPED = `format: dirigent/v1
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

/** The table row a pipeline's own title link is in. */
function rowOf(page: Page, title: string) {
    return page.getByRole('row').filter({ has: page.getByRole('link', { name: title, exact: true }) })
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

test('the pipelines listing carries the identity, the triggers and the last run', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, RAN.file)
    await applyExample(page.request, IDLE.file)
    await applyDocument(page.request, NAMELESS)
    const runId = await startRun(page.request, RAN.code)
    await ranToCompletion(page.request, runId)

    await page.goto('/pipelines')

    // Both documents are here, each headed by its name where it has one -- with the code it
    // is addressed by still on the row. The version lives in the editor, not on every row.
    await expect(rowOf(page, RAN.title)).toContainText(RAN.code)
    await expect(rowOf(page, RAN.title)).not.toContainText('v1')
    await expect(rowOf(page, IDLE.title)).toContainText(IDLE.code)
    await expect(rowOf(page, NAMELESS.code)).toContainText(NAMELESS.code)

    // The one that ran says how it went, and says it as a link to that very run.
    await expect(rowOf(page, RAN.title).locator(`a[href="/runs/${runId}"]`)).toBeVisible()
    await expect(rowOf(page, RAN.title).locator('.status-dot')).toBeVisible()

    // The one that has not run says so rather than showing an empty cell.
    await expect(rowOf(page, IDLE.title)).toContainText('never run')

    // The foot counts what has been read, and there is no page number anywhere on the screen.
    await expect(page.getByText(/\d+ pipelines/)).toBeVisible()
})

/**
 * TAGS ARE THE CORPUS'S OWN WORDS, and the filter beside the search box is a question put to
 * the server rather than a squint at the rows already loaded -- so a row the filter excludes is
 * one the listing never asked for, and this is the seam a Node test cannot reach.
 */
test('the pipelines listing wears its tags and a chip on a row narrows to that tag', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, RAN.file)
    await applyExample(page.request, IDLE.file)

    await page.goto('/pipelines')

    // Both examples are tagged transform; only the fan-out one is tagged graph.
    await expect(rowOf(page, RAN.title)).toContainText('graph')
    await expect(rowOf(page, RAN.title)).toContainText('transform')
    await expect(rowOf(page, IDLE.title)).toContainText('transform')

    // A chip on the row is the filter reached from the thing that shows what to reach for.
    await rowOf(page, RAN.title).getByRole('button', { name: 'Filter by graph' }).click()

    await expect(page).toHaveURL(/\?tag=graph$/)
    await expect(rowOf(page, RAN.title)).toBeVisible()
    await expect(rowOf(page, IDLE.title)).toHaveCount(0)

    // The filter stands above the table as a chip that removes itself, and removing it asks the
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
    await page.goto('/pipelines?tag=transform')
    await expect(rowOf(page, RAN.title)).toBeVisible()
    await expect(rowOf(page, IDLE.title)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Stop filtering by transform' })).toBeVisible()

    // The option wears what its value wears: the menu rows are the chips the listing draws.
    await page.getByRole('button', { name: 'Filter by tag' }).click()
    await page.getByRole('menuitemcheckbox', { name: 'graph', exact: true }).click()

    await expect(page).toHaveURL(/\?tag=transform&tag=graph$/)
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

    await page.getByRole('button', { name: 'Filter by tag' }).click()
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

    // From file… lives behind the split button's chevron and opens the OS picker directly.
    await page.getByRole('button', { name: 'More ways to start a pipeline' }).click()
    const picking = page.waitForEvent('filechooser')
    await page.getByRole('menuitem', { name: 'From file…' }).click()
    const chooser = await picking
    await chooser.setFiles({ name: 'typed.yaml', mimeType: 'text/yaml', buffer: Buffer.from(TYPED) })

    // The document arrives in the editor, which opens on the step tab; the file's own text is
    // on the source pane a tab away.
    await expect(page).toHaveURL(/\/pipelines\/\$new$/)
    await page.locator('aside').getByRole('tab', { name: 'Source' }).click()
    await expect(page.getByTestId('code-editor').locator('.view-lines')).toContainText('typed-in-the-browser')

    await page.getByRole('button', { name: 'Apply', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText(/Apply (creates|writes version)/)).toBeVisible()
    await dialog.getByRole('button', { name: 'Apply' }).click()
    await expect(page).toHaveURL(/\/pipelines\/typed-in-the-browser$/)

    // TITLE ELSE CODE: this document gave itself a name, so the row's link wears the name and
    // the code it is addressed by is beside it in mono.
    await page.goto('/pipelines')
    const applied = rowOf(page, 'Typed in the browser')
    await expect(applied).toBeVisible()
    await expect(applied).toContainText('typed-in-the-browser')
})

/**
 * A ROW OPENS BESIDE THE TABLE, AND ITS TITLE OPENS THE EDITOR.
 *
 * Choosing a row is a request to read that pipeline, and the panel is where a pipeline is read:
 * its description, what it takes, what it requires, what has been applied. Going to the editor
 * is the louder intent, and the title is the link that carries it -- so the two gestures on one
 * row do two different things, and neither is the other by accident.
 */
test('choosing a pipeline row reads it beside the listing, and its title opens the editor', async ({
    page,
}) => {
    await signIn(page)
    await applyExample(page.request, RAN.file)

    await page.goto('/pipelines')
    const row = rowOf(page, RAN.title)
    await expect(row).toBeVisible()

    // The row itself, away from the link: the listing stays on screen and the panel answers.
    await row.getByText(RAN.code, { exact: true }).click()

    const panel = page.locator('aside')
    await expect(panel.getByText('Parameters', { exact: true })).toBeVisible()
    await expect(panel.getByText('Recent runs', { exact: true })).toBeVisible()
    await expect(panel.getByText('Versions', { exact: true })).toBeVisible()
    await expect(panel.getByText(DESCRIPTION, { exact: false })).toBeVisible()
    // Reading a row did not leave the listing.
    await expect(page).toHaveURL(/\/pipelines$/)
    await expect(row).toHaveAttribute('aria-selected', 'true')

    // The title is the link, and it is what goes to the editor.
    await row.getByRole('link', { name: RAN.title, exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/pipelines/${RAN.code}$`))
})

/**
 * Two documents that file themselves under more words than a column can hold.
 *
 * THEY ARE FIXTURES, NOT EXAMPLES. Nothing in `examples/` teaches anything by wearing fifteen
 * tags, and what these are for is the width those tags would take from the identity beside
 * them -- so this spec applies them and they live nowhere else.
 */
const FIFTEEN = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: 'many-tags-fifteen',
    name: 'GDACS disaster updates, joined and reshaped for the weekly bulletin',
    description:
        'Disaster alerts from the GDACS feed, narrowed to the countries this instance reports on, ' +
        'joined against the population figures and reshaped into the rows the weekly bulletin reads.',
    tags: [
        'gdacs',
        'disasters',
        'alerts',
        'humanitarian',
        'ingest',
        'hourly',
        'geo',
        'emergency',
        'feeds',
        'public',
        'climate',
        'reporting',
        'bulletin',
        'weekly',
        'joined',
    ],
    requires: { blocks: ['transform.jq'] },
    steps: { total: { block: 'transform.jq', config: { input: [1, 2, 3], program: 'add' } } },
}

const TEN = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: 'many-tags-ten',
    name: 'GDACS disaster updates, the daily half',
    description: 'The same feed read once a day, for the countries the weekly bulletin leaves out.',
    tags: [
        'gdacs',
        'disasters',
        'alerts',
        'humanitarian',
        'ingest',
        'daily',
        'geo',
        'emergency',
        'feeds',
        'public',
    ],
    requires: { blocks: ['transform.jq'] },
    steps: { total: { block: 'transform.jq', config: { input: [1, 2, 3], program: 'add' } } },
}

/** How wide one cell of a row is, by the column it is in. */
async function cellWidth(page: Page, title: string, index: number): Promise<number> {
    const box = await rowOf(page, title).locator('td').nth(index).boundingBox()
    expect(box, 'the row has no cell there').not.toBeNull()
    return box?.width ?? 0
}

/** How wide the table itself is, which every share on a row is measured against. */
async function tableWidth(page: Page): Promise<number> {
    const box = await page.getByRole('table').boundingBox()
    expect(box, 'there is no table').not.toBeNull()
    return box?.width ?? 0
}

/** The chip the rest of a row's tags fold into. */
function foldOf(page: Page, title: string) {
    return rowOf(page, title).getByRole('button', { name: /more tags/ })
}

/** How many words that chip is holding, read off the words it spells on hover. */
async function foldedWords(fold: Locator): Promise<string[]> {
    const said = (await fold.getAttribute('title')) ?? ''
    const listed = /^(\d+) more tags: (.+)$/.exec(said)
    expect(listed, `the fold says nothing about what it holds: ${said}`).not.toBeNull()
    const words = (listed?.[2] ?? '').split(', ')
    expect(words).toHaveLength(Number(listed?.[1]))
    await expect(fold).toHaveText(`+${String(words.length)}`)
    return words
}

/** How many lines the chips of one row are drawn on. */
async function chipLines(page: Page, title: string): Promise<number> {
    return rowOf(page, title)
        .locator('td')
        .nth(1)
        .evaluate((cell) => {
            const tops = [...cell.querySelectorAll('span > span, span > button')].map((chip) =>
                Math.round(chip.getBoundingClientRect().top),
            )
            return new Set(tops).size
        })
}

test.describe('a row filed under more words than the column can hold', () => {
    test.use({ viewport: { width: 1440, height: 900 } })

    test('the identity takes the width and the tags take what is left', async ({ page }) => {
        await signIn(page)
        await applyDocument(page.request, FIFTEEN)
        await applyDocument(page.request, TEN)

        await page.goto('/pipelines')
        const row = rowOf(page, FIFTEEN.name)
        await expect(row).toBeVisible()

        // THE TITLE IS NOT CUT. The lead column takes the width, so the whole of the name is on
        // screen rather than truncated to make room for a vocabulary.
        const title = row.getByRole('link', { name: FIFTEEN.name, exact: true })
        const cut = await title.evaluate((link) => link.scrollWidth - link.clientWidth)
        expect(cut).toBeLessThanOrEqual(0)

        // Half the table is the identity's, and the tags take at most a quarter of it.
        const table = await tableWidth(page)
        const lead = await cellWidth(page, FIFTEEN.name, 0)
        const tags = await cellWidth(page, FIFTEEN.name, 1)
        expect(lead).toBeGreaterThanOrEqual(table * 0.5)
        expect(tags).toBeLessThanOrEqual(table * 0.27)

        // ONE LINE OF CHIPS, because this table is under the width a second one is allowed at.
        expect(await chipLines(page, FIFTEEN.name)).toBe(1)

        // What does not fit folds into one chip, which says how many and spells them on hover.
        const fold = foldOf(page, FIFTEEN.name)
        const hidden = await foldedWords(fold)
        const drawn = await row
            .locator('td')
            .nth(1)
            .getByRole('button', { name: /^Filter by / })
            .count()
        expect(drawn + hidden.length).toBe(FIFTEEN.tags.length)

        // The ten-tag row folds its own count, so what a fold says is what it is holding.
        const fewer = await foldedWords(foldOf(page, TEN.name))
        expect(fewer.length).toBeLessThan(hidden.length)

        // It is the door every other chip on the row is: the same filter, reached from the words
        // the column could not draw.
        await fold.click()
        // A word only the fifteen-tag document wears, so what it narrowed to is not in doubt.
        const only = 'climate'
        expect(hidden).toContain(only)
        expect(TEN.tags).not.toContain(only)
        await page.getByRole('menuitem', { name: only, exact: true }).click()
        await expect(page).toHaveURL(new RegExp(`\\?tag=${only}$`))
        await expect(rowOf(page, FIFTEEN.name)).toBeVisible()
        await expect(rowOf(page, TEN.name)).toHaveCount(0)
    })
})

/**
 * WHAT A NARROW WINDOW LEAVES THE TABLE is where the identity is squeezed first: a rail, the
 * page's padding and four columns out of 1050px leave about 730 for the table, and that is the
 * width at which a vocabulary used to take the name's place.
 */
test.describe('the same row on a narrow window', () => {
    test.use({ viewport: { width: 1050, height: 800 } })

    test('the identity still keeps half the table, and the tags fold hard', async ({ page }) => {
        await signIn(page)
        await applyDocument(page.request, FIFTEEN)
        await applyDocument(page.request, TEN)

        await page.goto('/pipelines')
        await expect(rowOf(page, FIFTEEN.name)).toBeVisible()

        const table = await tableWidth(page)
        const lead = await cellWidth(page, FIFTEEN.name, 0)
        expect(lead).toBeGreaterThanOrEqual(table * 0.5)

        // The chips give way rather than the name: one line, most of it behind the fold.
        expect(await chipLines(page, FIFTEEN.name)).toBe(1)
        const hidden = await foldedWords(foldOf(page, FIFTEEN.name))
        expect(hidden.length).toBeGreaterThanOrEqual(10)
    })
})

test.describe('the same row as a card', () => {
    test.use({ viewport: { width: 390, height: 844 } })

    test('every tag is drawn, wrapped, and nothing scrolls sideways', async ({ page }) => {
        await signIn(page)
        await applyDocument(page.request, FIFTEEN)

        await page.goto('/pipelines')
        const card = page.getByRole('listitem').filter({ hasText: FIFTEEN.code })
        await expect(card.getByRole('link', { name: FIFTEEN.name })).toBeVisible()

        // A card has a row of its own for the tags, so there is nothing to take width from and
        // nothing folds.
        await expect(card.getByRole('button', { name: /more tags/ })).toHaveCount(0)
        for (const tag of FIFTEEN.tags) {
            await expect(card.getByRole('button', { name: `Filter by ${tag}` })).toBeVisible()
        }

        // NOTHING SCROLLS SIDEWAYS, whatever is in it.
        const sideways = await page.evaluate(
            () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        )
        expect(sideways).toBeLessThanOrEqual(0)
    })
})
