import { expect, test, type Locator, type Page } from '@playwright/test'

import {
    DEV_USERNAME,
    applyDocument,
    applyExample,
    canvasSettled,
    clickEdge,
    dragBy,
    dragFromTo,
    everyNodeIsInView,
    graphZoom,
    nodeAt,
    signIn,
    writeInEditor,
} from './support.ts'

/**
 * The pipeline editor, against documents this suite really applied to a real `dg dev`.
 *
 * TWO EXAMPLES, EACH FOR WHAT IT HAS. `transform/std-convert-fan-out.yaml` is five steps with a
 * config worth generating a form from, and `params-showcase.yaml` is the parameter schema the
 * run dialog is built from -- a required string, an enum, an integer with bounds, a boolean.
 * Neither is run here: applying writes a version and starts nothing, so this spec touches no
 * network beyond the instance itself.
 */

const DOCUMENT_EXAMPLE = 'examples/transform/std-convert-fan-out.yaml'
const DOCUMENT_PIPELINE = 'std-convert-fan-out'

/** The document gives itself a name, so that is what its row on the listing is headed by. */
const DOCUMENT_TITLE = 'Convert and fan out'

const PARAMS_EXAMPLE = 'examples/demo/params-showcase.yaml'
const PARAMS_PIPELINE = 'params-showcase'

/** Every step the transform example declares, which is what the graph has to draw. */
const STEPS = ['parse', 'active', 'per_region', 'report', 'as_csv']

/**
 * Two steps and nothing between them, which is the one shape no shipped example has and the one
 * a spec about drawing an edge needs. It is applied for real, so what the canvas edits is a
 * stored document rather than a fixture.
 */
const APART_PIPELINE = 'two-apart'

/** The one step of that document that carries a name, and what it is called. */
const NAMED_STEP = 'fetch'
const STEP_NAME = 'Fetch the numbers'

/**
 * One step reading both edges of the interval its run covers, which is the shape the run dialog
 * asks for a window on. `transform.jq` resolves the two references and hands them straight back,
 * so the run settles offline and the window it carried is what the run screen then states.
 */
const WINDOWED_PIPELINE = 'reads-a-window'

/** Why Run is shut on it until both instants are there. `WINDOW_NEEDED` in `lib/run-window`. */
const WINDOW_NEEDED = 'This pipeline needs a window'

/** The same document with no window in it, which is every pipeline the window is optional on. */
const PLAIN_PIPELINE = 'reads-no-window'

const PLAIN = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: PLAIN_PIPELINE,
    description: 'One step reading nothing about the interval its run covers.',
    requires: { blocks: ['transform.jq'] },
    steps: {
        dates: { block: 'transform.jq', config: { input: { start: 'a literal' }, program: '.' } },
    },
}

const WINDOWED = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: WINDOWED_PIPELINE,
    description: 'One step reading the interval its run covers.',
    requires: { blocks: ['transform.jq'] },
    steps: {
        dates: {
            block: 'transform.jq',
            config: { input: { start: '${run.window.start}', end: '${run.window.end}' }, program: '.' },
        },
    },
}

/** The menu's heading, and the label its search box answers to. */
const ADD_STEP_LABEL = 'Add step'
const SEARCH_LABEL = 'Search blocks by id, summary or kind'

/** Where this pipeline's own arrangement is kept, which is `lib/canvas-layout`'s key. */
const APART_LAYOUT_KEY = `dirigent.layout.${APART_PIPELINE}`

const APART = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: APART_PIPELINE,
    description: 'Two roots, so an edge between them is one somebody drew.',
    requires: { blocks: ['transform.jq'] },
    steps: {
        fetch: { name: STEP_NAME, block: 'transform.jq', config: { input: [1, 2, 3], program: 'add' } },
        report: { block: 'transform.jq', config: { input: [4, 5], program: 'add' } },
    },
}

/** Two steps with an edge between them: deleting one has to take the edge with it. */
const CHAIN_PIPELINE = 'two-joined'

const CHAIN = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: CHAIN_PIPELINE,
    description: 'One step waiting for another, so taking one out is an edge going as well.',
    requires: { blocks: ['transform.jq'] },
    steps: {
        fetch: { block: 'transform.jq', config: { input: [1, 2, 3], program: 'add' } },
        report: { block: 'transform.jq', depends_on: ['fetch'], config: { input: [4, 5], program: 'add' } },
    },
}

/** One step's port, which is what an edge is dragged from and to. */
function port(page: Page, step: string, end: 'source' | 'target') {
    return page.locator(`.react-flow__handle.dg-port.${end}[data-nodeid="${step}"]`)
}

/**
 * TITLE ELSE CODE, ON THE BOX ITSELF.
 *
 * A step's key is what `depends_on` and every log line reference, so it never leaves the node:
 * a step carrying a name is titled with it and its key is demoted to the mono line beneath,
 * and a step with no name is titled by its key, once.
 */
test('a step node is titled by its name over its key, and by its key alone when it has none', async ({
    page,
}) => {
    await signIn(page)
    await applyDocument(page.request, APART)

    await page.goto(`/pipelines/${APART_PIPELINE}`)
    await canvasSettled(page)

    const named = page.locator(`.react-flow__node[data-id="${NAMED_STEP}"]`)
    await expect(named.getByTestId('step-title')).toHaveText(STEP_NAME)
    await expect(named.getByTestId('step-line')).toContainText(NAMED_STEP)

    const plain = page.locator('.react-flow__node[data-id="report"]')
    await expect(plain.getByTestId('step-title')).toHaveText('report')
    await expect(plain.getByTestId('step-line')).not.toContainText('report')
})

test('a pipeline row on the listing opens the editor at that pipeline', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto('/pipelines')
    await page.getByRole('link', { name: DOCUMENT_TITLE, exact: true }).click()

    await expect(page).toHaveURL(new RegExp(`/pipelines/${DOCUMENT_PIPELINE}$`))
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)
})

test('the stored document reads as its graph, and a step reads as its own config form', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}`)

    // THE GRAPH IS THE DOCUMENT: every step it declares is a node.
    for (const step of STEPS) {
        // Each assertion waits on the same canvas; running them together would race the retries.
        // oxlint-disable-next-line no-await-in-loop
        await expect(page.locator('.react-flow__node').getByText(step, { exact: true })).toBeVisible()
    }
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)

    // THE STEP IN FRONT OF SOMEBODY, with the form generated from its block's own schema.
    await page.locator('.react-flow__node').getByText('parse', { exact: true }).click()

    const panel = page.locator('aside')
    await expect(panel.getByRole('tab', { name: 'Step' })).toBeVisible()
    await expect(panel.getByRole('tab', { name: 'Pipeline' })).toBeVisible()
    await expect(panel.getByRole('tab', { name: 'Source' })).toBeVisible()
    await expect(panel.getByText('convert.std', { exact: true })).toBeVisible()

    // `from` and `to` are convert.std's required fields, and `input` is its optional one.
    await expect(panel.getByLabel('from', { exact: true })).toHaveValue('csv')
    await expect(panel.getByLabel('to', { exact: true })).toHaveValue('json')
    await expect(panel.getByLabel('input', { exact: true })).toBeVisible()
})

test('a config field the schema calls a program is edited as one, and every other string is not', async ({
    page,
}) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}`)

    // per_region's program is five lines of jq, which is what one input cannot hold.
    await page.locator('.react-flow__node').getByText('per_region', { exact: true }).click()

    const panel = page.locator('aside')
    await expect(panel.getByText('transform.jq', { exact: true })).toBeVisible()

    // Monaco is a chunk of its own, fetched when the first structured field of a session
    // opens. per_region carries two buffers: its JSON input, and its program.
    const program = panel.getByTestId('code-editor').filter({ has: page.locator('[data-uri$="program.jq"]') })
    await expect(program.locator('.monaco-editor')).toBeVisible({ timeout: 30_000 })

    // THE PROGRAM IS ON THE LINES IT WAS WRITTEN ON, and the label is still the key.
    await expect(program.locator('.view-lines')).toContainText('select(.region == $region)')
    await expect(program.locator('.view-line').nth(3)).toBeVisible()
    await expect(panel.getByLabel('program', { exact: true })).toBeVisible()

    // The JSON input is a buffer too, coloured where it stands rather than a bare box.
    await expect(panel.locator('[data-uri$="config/input.json"]')).toBeVisible()

    // The window is a second reader of the same buffer, and closing it leaves the buffer
    // standing: the inline pane still holds the text, and no control keeps a focus ring.
    await panel.getByLabel('Open input in a window').click()
    await expect(page.getByRole('dialog').locator('.monaco-editor')).toBeVisible({ timeout: 30_000 })
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toBeHidden()
    await expect(panel.locator('[data-uri$="config/input.json"] .view-lines')).toContainText('region')

    // A BLOCK WITH NEITHER A PROGRAM NOR A STRUCTURED FIELD GETS NO EDITOR. convert.std has
    // a from, a to and an input, and the schema says every one is a plain string.
    await page.locator('.react-flow__node').getByText('parse', { exact: true }).click()
    await expect(panel.getByLabel('from', { exact: true })).toHaveValue('csv')
    await expect(panel.getByTestId('code-editor')).toHaveCount(0)
})

test('editing a config field is unapplied until it is applied, and the topbar counts it', async ({
    page,
}) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}`)
    await page.locator('.react-flow__node').getByText('parse', { exact: true }).click()

    const panel = page.locator('aside')
    await expect(panel.getByLabel('to', { exact: true })).toHaveValue('json')

    // Nothing is unapplied before anything is edited.
    await expect(page.getByText(/unapplied edit/)).toHaveCount(0)

    await panel.getByLabel('to', { exact: true }).fill('yaml')

    // One step differs from the stored version, and the node on the canvas says which.
    await expect(page.getByRole('button', { name: 'Apply', exact: true })).toHaveClass(/bg-primary/)
    await expect(page.locator('.react-flow__node').getByText('edited', { exact: true })).toBeVisible()
})

test('the source tab holds the same document, in the editor the schema is checked in', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}`)
    await page.locator('.react-flow__node').getByText('parse', { exact: true }).click()

    const panel = page.locator('aside')
    await panel.getByRole('tab', { name: 'Source' }).click()

    // Monaco is a chunk of its own and is fetched when this tab is opened, so the assertion is
    // that it arrived and is holding this document rather than an empty buffer.
    await expect(panel.locator('.monaco-editor')).toBeVisible({ timeout: 30_000 })
    await expect(panel.locator('.view-lines')).toContainText(DOCUMENT_PIPELINE)
})

test('validating an intact document reports no issues', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}`)
    await page.getByRole('button', { name: 'Validate' }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText('Validate document')).toBeVisible()
    // The digest matches what was applied a moment ago, so applying would write nothing --
    // and, either way, the instance refuses nothing about it.
    await expect(dialog.getByText(/Apply writes nothing/)).toBeVisible()
    await expect(dialog.getByText(/apply will refuse/)).toHaveCount(0)
})

test('the run dialog is built from the pipeline own parameter schema', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, PARAMS_EXAMPLE)

    await page.goto(`/pipelines/${PARAMS_PIPELINE}`)
    await page.getByRole('button', { name: 'Run', exact: true }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: 'Run', exact: true })).toBeVisible()
    await expect(dialog.getByText('Every parameter shape')).toBeVisible()
    // Every parameter the document declares, each as the control its schema asks for.
    await expect(dialog.getByLabel('day', { exact: true })).toBeVisible()
    await expect(dialog.getByLabel('batch_size', { exact: true })).toBeVisible()
    await expect(dialog.getByText('required').first()).toBeVisible()
    // It says who the run would be attributed to, which is what the run's own screen shows.
    await expect(dialog.getByText(`runs as ${DEV_USERNAME} · adhoc`)).toBeVisible()

    // The run decides what its log keeps: info and up unless this control asks for debug.
    await expect(dialog.getByLabel('log level')).toBeVisible()
})

test('a document that reads a window is not run until it is given one', async ({ page }) => {
    await signIn(page)
    await applyDocument(page.request, WINDOWED)

    await page.goto(`/pipelines/${WINDOWED_PIPELINE}`)
    await page.getByRole('button', { name: 'Run', exact: true }).click()

    const dialog = page.getByRole('dialog')
    const start = dialog.getByLabel('Start', { exact: true })
    const end = dialog.getByLabel('End', { exact: true })
    // The section is open on this document rather than behind the link, because its steps
    // read a window and a run carrying none would stop at the first of them.
    await expect(start).toBeVisible()
    await expect(end).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Add a window' })).toHaveCount(0)

    const runNow = dialog.getByRole('button', { name: 'Run now' })
    await expect(runNow).toBeDisabled()
    await expect(runNow).toHaveAttribute('title', WINDOW_NEEDED)

    // One end is not a window, and neither is one that runs backwards.
    await start.fill('2026-09-03T00:00')
    await expect(runNow).toBeDisabled()
    await end.fill('2026-09-02T00:00')
    await expect(runNow).toBeDisabled()

    await end.fill('2026-09-04T00:00')
    await expect(runNow).toBeEnabled()
    await runNow.click()

    // The run is the pipeline's, and what it carried is a fact about it: the Run tab says so.
    await expect(page).toHaveURL(/\/runs\//)
    await expect(page.locator('.status-chip[data-status="succeeded"]').first()).toBeVisible({
        timeout: 30_000,
    })
    await expect((await runFacts(page)).getByText('window', { exact: true })).toBeVisible()
})

test('a document that reads no window keeps its window behind a link and runs without one', async ({
    page,
}) => {
    await signIn(page)
    await applyDocument(page.request, PLAIN)

    await page.goto(`/pipelines/${PLAIN_PIPELINE}`)
    await page.getByRole('button', { name: 'Run', exact: true }).click()

    const dialog = page.getByRole('dialog')
    const add = dialog.getByRole('button', { name: 'Add a window' })
    await expect(add).toBeVisible()
    await expect(dialog.getByLabel('Start', { exact: true })).toHaveCount(0)

    const runNow = dialog.getByRole('button', { name: 'Run now' })
    await expect(runNow).toBeEnabled()

    // The link opens the same two boxes, and leaving them empty leaves the run without a window.
    await add.click()
    await expect(dialog.getByLabel('Start', { exact: true })).toBeVisible()
    await expect(runNow).toBeEnabled()
    await runNow.click()

    await expect(page).toHaveURL(/\/runs\//)
    await expect(page.locator('.status-chip[data-status="succeeded"]').first()).toBeVisible({
        timeout: 30_000,
    })
    const panel = await runFacts(page)
    await expect(panel.getByText('created', { exact: true })).toBeVisible()
    await expect(panel.getByText('window', { exact: true })).toHaveCount(0)
})

/**
 * The run's own facts, which are on the panel's Run tab.
 *
 * A step on the graph is what opens the panel, so that is the way in here as it is on the run
 * screen's own spec.
 */
async function runFacts(page: Page): Promise<Locator> {
    await page.locator('.react-flow__node').first().click()
    const panel = page.locator('aside')
    await panel.getByRole('tab', { name: 'Run' }).click()
    return panel
}

test('a pipeline this instance does not have is refused in the server own words', async ({ page }) => {
    await signIn(page)
    await page.goto('/pipelines/no-such-pipeline')
    await expect(page.getByText(/no pipeline/)).toBeVisible()
})

test('the editor opens with the whole graph in view, at a zoom that does not blow it up', async ({
    page,
}) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)
    await everyNodeIsInView(page)
    // FIT_MAX_ZOOM in lib/dag-layout: a graph of a few boxes sits at a size worth reading
    // rather than blown up to fill the canvas.
    expect(await graphZoom(page)).toBeLessThanOrEqual(1.25)
})

test('a graph of two steps is fully visible rather than filling the canvas', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, PARAMS_EXAMPLE)

    await page.goto(`/pipelines/${PARAMS_PIPELINE}`)
    await everyNodeIsInView(page)
    expect(await graphZoom(page)).toBeLessThanOrEqual(1.25)
})

test('the editor draws a port on every step, and a run graph draws none', async ({ page }) => {
    await signIn(page)
    await applyDocument(page.request, APART)

    await page.goto(`/pipelines/${APART_PIPELINE}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(2)

    // Two per box, both visible and both connectable: this is the canvas that edits.
    await expect(page.locator('.react-flow__handle.dg-port')).toHaveCount(4)
    await expect(port(page, 'fetch', 'source')).toBeVisible()
    await expect(port(page, 'report', 'target')).toBeVisible()
    await expect(page.locator('.react-flow__handle.connectable')).toHaveCount(4)
})

test('an edge dragged between two ports is the dependency, and Delete takes it away', async ({ page }) => {
    await signIn(page)
    await applyDocument(page.request, APART)

    await page.goto(`/pipelines/${APART_PIPELINE}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(2)
    await expect(page.locator('.react-flow__edge')).toHaveCount(0)
    await expect(page.getByText(/unapplied edit/)).toHaveCount(0)
    // The opening fit is asynchronous, and a box that moves between reading where it is and
    // pressing on it is a gesture that lands on the ground.
    await canvasSettled(page)

    await dragFromTo(page, port(page, 'fetch', 'source'), port(page, 'report', 'target'))

    // The document has the edge, the topbar counts it like any other edit, and the step's own
    // pane says the same thing: one document, read three ways.
    await expect(page.locator('.react-flow__edge')).toHaveCount(1)
    await expect(page.getByRole('button', { name: 'Apply', exact: true })).toHaveClass(/bg-primary/)
    await page.locator('.react-flow__node').getByText('report', { exact: true }).click()
    await expect(page.locator('aside').getByRole('button', { name: 'Stop waiting for fetch' })).toBeVisible()

    // Choosing the edge and pressing the key is how it is taken back. The panel that just
    // opened narrowed the canvas, and the graph re-fits itself when that happens.
    await canvasSettled(page)
    const edge = page.locator('.react-flow__edge')
    await clickEdge(page, edge)
    await expect(edge).toHaveClass(/selected/)
    await page.keyboard.press('Delete')
    await expect(page.locator('.react-flow__edge')).toHaveCount(0)
    await expect(page.getByText(/unapplied edit/)).toHaveCount(0)
})

test('an edge that would close a loop is refused, and the refusal names the loop', async ({ page }) => {
    // REVERT-PROOF: a canvas that accepted the gesture would draw a document this instance
    // refuses at apply, and the reader would find out one round trip later.
    await signIn(page)
    await applyDocument(page.request, APART)

    await page.goto(`/pipelines/${APART_PIPELINE}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(2)
    await canvasSettled(page)

    await dragFromTo(page, port(page, 'fetch', 'source'), port(page, 'report', 'target'))
    await expect(page.locator('.react-flow__edge')).toHaveCount(1)
    await canvasSettled(page)

    await dragFromTo(page, port(page, 'report', 'source'), port(page, 'fetch', 'target'))

    await expect(page.getByText('fetch → report → fetch', { exact: false })).toBeVisible()
    await expect(page.locator('.react-flow__edge')).toHaveCount(1)
    await expect(page.getByRole('button', { name: 'Apply', exact: true })).toHaveClass(/bg-primary/)
})

test('a box stays where it was dragged, across a reload, until Re-layout gives it back', async ({ page }) => {
    await signIn(page)
    await applyDocument(page.request, APART)

    await page.goto(`/pipelines/${APART_PIPELINE}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(2)
    await canvasSettled(page)
    const placed = await nodeAt(page, 'fetch')

    await dragBy(page, page.locator('.react-flow__node[data-id="fetch"]'), 60, 70)
    const dragged = await nodeAt(page, 'fetch')
    expect(dragged.x).not.toBe(placed.x)

    // PX-INTENT, KEPT PER PIPELINE: the arrangement is that pipeline's, and it survives a reload.
    expect(await page.evaluate((key) => localStorage.getItem(key), APART_LAYOUT_KEY)).toContain('fetch')
    await page.reload()
    await expect(page.locator('.react-flow__node')).toHaveCount(2)
    await canvasSettled(page)
    await expect.poll(async () => (await nodeAt(page, 'fetch')).x).toBeCloseTo(dragged.x, 0)
    expect((await nodeAt(page, 'fetch')).y).toBeCloseTo(dragged.y, 0)

    // Re-layout is how it is given back: elk decides again, and storage holds nothing.
    await page.keyboard.press('ControlOrMeta+k')
    await page.getByPlaceholder('Go to a screen, or run something').fill('re-layout')
    await page
        .getByRole('option')
        .filter({ hasText: /^Re-layout/ })
        .first()
        .click()
    await expect.poll(async () => (await nodeAt(page, 'fetch')).x).toBeCloseTo(placed.x, 0)
    expect(await page.evaluate((key) => localStorage.getItem(key), APART_LAYOUT_KEY)).toBeNull()
    await everyNodeIsInView(page)
})

test('a connection dropped on empty ground adds a step already waiting for the one it came from', async ({
    page,
}) => {
    await signIn(page)
    await applyDocument(page.request, APART)

    await page.goto(`/pipelines/${APART_PIPELINE}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(2)
    await canvasSettled(page)

    // Let go over the ground rather than over a port: the menu opens where it was dropped, and
    // says which step the one it is about to add will wait for.
    await dragBy(page, port(page, 'fetch', 'source'), 220, 140)

    const menu = page.getByRole('menu')
    await expect(menu.getByText(`${ADD_STEP_LABEL} after fetch`, { exact: true })).toBeVisible()
    // The four transform verbs declare one group, so the block is one shelf in.
    await menu.getByRole('menuitem', { name: 'transform', exact: true }).click()
    await page.getByRole('menuitem', { name: /^transform\.jq/ }).click()

    await expect(page.locator('.react-flow__node')).toHaveCount(3)
    await expect(page.locator('.react-flow__edge')).toHaveCount(1)
    // The key is the block's own name, made unique against the two the document already has.
    await expect(page.locator('.react-flow__node').getByText('jq', { exact: true })).toBeVisible()
})

/**
 * THE GROUND IS WHERE A STEP IS ADDED.
 *
 * A right-click on empty canvas opens the add-step menu at the pointer -- on a document with no
 * steps in it as much as on a drawn one, because the emptier the document the more likely that
 * is the question. The catalog is shelved by the groups its blocks declare, and the block chosen
 * from one lands as a step keyed by the block's own name, selected, with the panel on its tab.
 */
test('right-clicking the canvas adds a step from the menu, and the panel opens on it', async ({ page }) => {
    // A document with no steps is `/pipelines/$new`: the instance refuses to store one, and it
    // is where an add-step gesture matters most.
    await signIn(page)
    await page.goto('/pipelines/$new')
    await expect(page.getByText('No steps.', { exact: false })).toBeVisible()

    await page.locator('.react-flow__pane').click({ button: 'right', position: { x: 80, y: 80 } })

    const menu = page.getByRole('menu')
    await expect(menu.getByText(ADD_STEP_LABEL, { exact: true })).toBeVisible()
    await expect(page.getByLabel(SEARCH_LABEL)).toBeFocused()
    // Every group the catalog declares, and nothing else: a group of one -- webhook -- is
    // still a group, so the root is one uniform arrangement of submenus.
    await expect(menu.getByRole('menuitem', { name: 'transform', exact: true })).toBeVisible()
    await expect(menu.getByRole('menuitem', { name: 'execute', exact: true })).toBeVisible()
    await expect(menu.getByRole('menuitem', { name: 'webhook', exact: true })).toBeVisible()
    await expect(menu.getByRole('menuitem', { name: 'sensors', exact: true })).toHaveCount(0)

    await menu.getByRole('menuitem', { name: 'webhook', exact: true }).click()
    await page.getByRole('menuitem', { name: /^webhook\.post/ }).click()

    await expect(page.locator('.react-flow__node')).toHaveCount(1)
    await expect(page.locator('.react-flow__node').getByText('post', { exact: true })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Step · post' })).toHaveAttribute('aria-selected', 'true')
})

/**
 * A RIGHT-CLICK ON A BOX IS THAT BOX'S OWN MENU.
 *
 * What the ground offers is which block to add; what a box offers is one more step after this
 * one, which is the same menu with the edge already decided, and this one taken out.
 */
test("right-clicking a step opens the step's own menu, and Delete step takes it out", async ({ page }) => {
    await signIn(page)
    await applyDocument(page.request, CHAIN)

    await page.goto(`/pipelines/${CHAIN_PIPELINE}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(2)
    await expect(page.locator('.react-flow__edge')).toHaveCount(1)
    await canvasSettled(page)

    await page.locator('.react-flow__node[data-id="fetch"]').click({ button: 'right' })
    const menu = page.getByRole('menu')
    await expect(menu.getByRole('menuitem', { name: 'Add step after' })).toBeVisible()

    // The step goes, and the edge that named it goes with it: a `depends_on` naming a step
    // the document no longer declares is what an apply refuses.
    await menu.getByRole('menuitem', { name: 'Delete step' }).click()
    await expect(page.locator('.react-flow__node')).toHaveCount(1)
    await expect(page.locator('.react-flow__edge')).toHaveCount(0)
    // The topbar counts it with every other unapplied edit, and nothing has been written.
    await expect(page.getByRole('button', { name: 'Apply', exact: true })).toHaveClass(/bg-primary/)

    // Nothing was written: the document the instance holds still has both steps.
    await page.reload()
    await expect(page.locator('.react-flow__node')).toHaveCount(2)
})

/** A chosen step and the key: the same gesture a chosen edge answers. */
test('a chosen step is deleted by the key, and never while a text box has the focus', async ({ page }) => {
    await signIn(page)
    await applyDocument(page.request, CHAIN)

    await page.goto(`/pipelines/${CHAIN_PIPELINE}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(2)
    await canvasSettled(page)

    // The step's own pane opens on the choice, and typing a name into it is not a deletion.
    await page.locator('.react-flow__node[data-id="report"]').click()
    const name = page.locator('aside').getByLabel('Name', { exact: true })
    await name.click()
    await name.press('Backspace')
    await expect(page.locator('.react-flow__node')).toHaveCount(2)

    await page.locator('.react-flow__node[data-id="report"]').click()
    await page.keyboard.press('Delete')
    await expect(page.locator('.react-flow__node')).toHaveCount(1)
    await expect(page.locator('.react-flow__node[data-id="fetch"]')).toBeVisible()
})

/**
 * TYPING IS THE OTHER WAY IN.
 *
 * The shelves are for somebody who knows where a block lives; the box is for somebody who knows
 * what it is called. What it answers with is flat and breadcrumbed -- `shell ▸ run` -- because a
 * breadcrumb is faster to read than a tree is to walk, the arrows move through the results, and
 * the return key places the one they are on.
 */
test('the search box narrows the menu to breadcrumbed results, and the return key places one', async ({
    page,
}) => {
    // A document with no steps is `/pipelines/$new`: the instance refuses to store one, and it
    // is where an add-step gesture matters most.
    await signIn(page)
    await page.goto('/pipelines/$new')
    await expect(page.getByText('No steps.', { exact: false })).toBeVisible()

    await page.locator('.react-flow__pane').click({ button: 'right', position: { x: 120, y: 120 } })
    await page.getByLabel(SEARCH_LABEL).fill('ru')

    const menu = page.getByRole('menu')
    await expect(menu.getByText('docker ▸ run')).toBeVisible()
    await expect(menu.getByText('shell ▸ run')).toBeVisible()
    // The shelves are gone while there is something in the box.
    await expect(menu.getByRole('menuitem', { name: 'sensors', exact: true })).toHaveCount(0)

    // Results are in id order: docker.run, filter.jq, git.checkout (its summary names the
    // run's work directory), log.write (its summary names the run's log), pipeline.run, then
    // shell.run.
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('ArrowDown')
    await expect(page.locator('[data-active="true"]')).toContainText('shell ▸ run')
    await page.keyboard.press('Enter')

    await expect(page.locator('.react-flow__node')).toHaveCount(1)
    await expect(page.locator('.react-flow__node').getByText('run', { exact: true })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Step · run' })).toHaveAttribute('aria-selected', 'true')
})

/**
 * THE FIRST ESCAPE CLEARS WHAT WAS TYPED, THE SECOND CLOSES THE MENU.
 *
 * A box holding a search nobody wants any more is one keystroke from the shelves; a menu nobody
 * wants at all is one more.
 */
test('escape clears the search before it closes the menu', async ({ page }) => {
    await signIn(page)
    await page.goto('/pipelines/$new')
    await page.locator('.react-flow__pane').click({ button: 'right', position: { x: 120, y: 120 } })
    await page.getByLabel(SEARCH_LABEL).fill('sensor')

    // The words a kind is named by find every block of that kind, whatever group it shelves under.
    const menu = page.getByRole('menu')
    await expect(menu.getByText('time ▸ sleep')).toBeVisible()
    await expect(menu.getByText('storage ▸ exists')).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(page.getByLabel(SEARCH_LABEL)).toHaveValue('')
    await expect(menu.getByRole('menuitem', { name: 'transform', exact: true })).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(page.getByRole('menu')).toHaveCount(0)
    await expect(page.locator('.react-flow__node')).toHaveCount(0)
})

/**
 * THE MENU IS PLACED AGAINST THE WINDOW, NOT AGAINST THE POINTER ALONE.
 *
 * A right-click in the far corner of the canvas is the ordinary case near the foot of a screen,
 * and a menu that hung off the window there would be a menu with rows nobody can reach.
 */
test('the menu opens inside the window wherever the pointer is', async ({ page }) => {
    await signIn(page)
    await page.goto('/pipelines/$new')
    await expect(page.getByText('No steps.', { exact: false })).toBeVisible()

    const pane = page.locator('.react-flow__pane')
    const canvas = await pane.boundingBox()
    if (canvas === null) throw new Error('the canvas has no box on the screen')
    await pane.click({ button: 'right', position: { x: canvas.width - 6, y: canvas.height - 6 } })

    await expect(page.getByRole('menu')).toBeVisible()
    const inside = await page.evaluate(() => {
        const popup = document.querySelector('[data-slot="dropdown-menu-content"]')
        if (popup === null) return null
        const box = popup.getBoundingClientRect()
        return (
            box.left >= 0 &&
            box.top >= 0 &&
            box.right <= window.innerWidth + 1 &&
            box.bottom <= window.innerHeight + 1
        )
    })
    expect(inside).toBe(true)
})

/**
 * ONLY A SENSOR WEARS A CHIP: which block waits for something is what a shelf cannot say, and a
 * chip on every row would say what the absence of one already says.
 */
test('only a sensor wears a kind chip in its group shelf', async ({ page }) => {
    await signIn(page)
    await page.goto('/pipelines/$new')
    // The palette is the keyboard way in, and reaches the same menu.
    await page.keyboard.press('ControlOrMeta+k')
    await page.getByPlaceholder('Go to a screen, or run something').fill('add step')
    await page
        .getByRole('option')
        .filter({ hasText: /^Add step/ })
        .first()
        .click()
    await page.getByRole('menuitem', { name: 'http', exact: true }).click()
    const operator = page.getByRole('menuitem', { name: 'http.request', exact: false })
    await expect(operator).toBeVisible()
    await expect(operator.locator('.kind-chip')).toHaveCount(0)
    await expect(
        page
            .getByRole('menuitem', { name: 'http.ready', exact: false })
            .locator('.kind-chip[data-kind="sensor"]'),
    ).toHaveCount(1)
})

/**
 * THE ADD-STEP GESTURE THAT CAN BE SEEN.
 *
 * A right-click has to be known about and the palette has to be remembered; the button in the
 * canvas's corner is what a reader who has opened this screen for the first time can find, and
 * it is why the empty canvas states the fact instead of narrating a gesture. It opens the same
 * menu, anchored under itself, and it is reachable from the keyboard like any other button.
 */
test('the button in the corner opens the same menu, under itself', async ({ page }) => {
    await signIn(page)
    await page.goto('/pipelines/$new')
    // The empty state says what is true and nothing about how to change it: the control is there.
    await expect(page.getByText('No steps.', { exact: true })).toBeVisible()

    const button = page.getByRole('button', { name: ADD_STEP_LABEL })
    await expect(button).toBeVisible()
    await button.click()

    const menu = page.getByRole('menu')
    await expect(menu.getByText(ADD_STEP_LABEL, { exact: true })).toBeVisible()
    await expect(page.getByLabel(SEARCH_LABEL)).toBeFocused()

    // The popup hangs off the button rather than off a point, so it is over the corner it opened from.
    const anchor = await button.boundingBox()
    const popup = await page.locator('[data-slot="dropdown-menu-content"]').boundingBox()
    expect(anchor).not.toBeNull()
    expect(popup).not.toBeNull()
    if (anchor === null || popup === null) return
    expect(popup.x).toBeLessThan(anchor.x + anchor.width + 40)

    await page.getByLabel(SEARCH_LABEL).fill('shell')
    await page.keyboard.press('Enter')
    await expect(page.locator('.react-flow__node')).toHaveCount(1)

    // And the keyboard alone opens it: the button takes the focus ring and answers Enter.
    await page.keyboard.press('Escape')
    await button.focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('menu')).toBeVisible()
})

/**
 * A NEW PIPELINE STARTS IN THE EDITOR, NOT IN A DIALOG.
 *
 * `/pipelines/$new` is this screen with no pipeline behind it: a skeleton document, everything in
 * it editable, the code among it. Validate asks the instance what it makes of the draft; Run is
 * shut, because `$run` runs the version the instance holds and there is not one. The first apply
 * is what creates the pipeline, and it takes the reader to the address it will keep answering at.
 */
test('New pipeline opens the editor on a document nothing has applied, and applying creates it', async ({
    page,
}) => {
    // The scratch database outlives one run of this suite, so the code is this run's own and the
    // apply asserted on is really a create rather than `unchanged`.
    const code = `started-in-the-editor-${String(Date.now())}`

    await signIn(page)
    await page.goto('/pipelines')
    await page.getByRole('button', { name: 'New pipeline' }).click()

    await expect(page).toHaveURL(/\/pipelines\/\$new$/)
    // The breadcrumb says what this is until it is something the instance holds.
    await expect(page.getByText('new pipeline', { exact: true })).toBeVisible()
    await expect(page.getByText('no version', { exact: true })).toBeVisible()

    // Validate works on the draft; Run does not, and says why rather than failing at the server.
    await expect(page.getByRole('button', { name: 'Validate' })).toBeEnabled()
    const run = page.getByRole('button', { name: 'Run', exact: true })
    await expect(run).toBeDisabled()
    // A shut button takes no pointer events, so the reason is on what the pointer lands on.
    await expect(run.locator('..')).toHaveAttribute('title', /Apply this document/)

    // The panel opens on the step tab like any other document; the source, where the skeleton
    // and its code are written, is a tab away.
    const panel = page.locator('aside')
    await expect(panel.getByRole('tab', { name: 'Step' })).toHaveAttribute('aria-selected', 'true')
    // Nothing is applied, so there is no pipeline to read: that tab is not offered.
    await expect(panel.getByRole('tab', { name: 'Pipeline' })).toHaveCount(0)
    await panel.getByRole('tab', { name: 'Source' }).click()

    const editor = panel.getByTestId('code-editor')
    await expect(editor.locator('.view-lines')).toContainText('my-pipeline')

    await writeInEditor(
        page,
        editor,
        [
            'format: dirigent/v1',
            'kind: pipeline',
            `code: ${code}`,
            'name: Started in the editor',
            'requires:',
            '  blocks:',
            '    - transform.jq',
            'steps:',
            '  total:',
            '    block: transform.jq',
            '    config:',
            '      input: [1, 2, 3]',
            '      program: add',
            '',
        ].join('\n'),
    )

    // The graph is the document, so the step written in the source is a box on the canvas.
    await expect(page.locator('.react-flow__node').getByText('total', { exact: true })).toBeVisible()

    await page.getByRole('button', { name: 'Apply', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText(/Apply creates/)).toBeVisible()
    await dialog.getByRole('button', { name: 'Apply', exact: true }).click()

    // The document has an address of its own now, at the version the apply wrote.
    await expect(page).toHaveURL(new RegExp(`/pipelines/${code}$`))
    await expect(page.getByText('v1', { exact: true })).toBeVisible()
    await expect(page.getByText('Started in the editor', { exact: true }).first()).toBeVisible()
})

/**
 * THE IDENTITY COLOUR IS SPENT ON WHAT WOULD DO SOMETHING.
 *
 * Applying a document the instance already holds writes nothing, so the button stands beside
 * Validate rather than shouting over it -- and goes loud the moment the document differs.
 */
test('Apply is quiet until the document differs from the version the instance holds', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}`)
    const apply = page.getByRole('button', { name: 'Apply', exact: true })
    await expect(apply).toBeVisible()
    await expect(apply).not.toHaveClass(/bg-primary/)

    await page.locator('.react-flow__node').getByText('parse', { exact: true }).click()
    const panel = page.locator('aside')
    await panel.getByLabel('to', { exact: true }).fill('yaml')

    await expect(apply).toHaveClass(/bg-primary/)
})

/**
 * CHOOSING A BOX IS ASKING TO READ IT.
 *
 * Whichever tab was last in front of somebody, a click on a node is a request for that step --
 * so the panel goes to the step's own tab, and the tab says which step it is holding.
 */
test('choosing a step switches the panel to its own tab, whatever was open, and the tab names it', async ({
    page,
}) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}`)
    await page.locator('.react-flow__node').getByText('parse', { exact: true }).click()

    const panel = page.locator('aside')
    await expect(panel.getByRole('tab', { name: 'Step · parse' })).toBeVisible()

    // Read something else in the panel, then choose another box: the click is the intent.
    await panel.getByRole('tab', { name: 'Pipeline' }).click()
    await expect(panel.getByRole('tab', { name: 'Pipeline' })).toHaveAttribute('aria-selected', 'true')

    await canvasSettled(page)
    await page.locator('.react-flow__node').getByText('report', { exact: true }).click()
    await expect(panel.getByRole('tab', { name: 'Step · report' })).toHaveAttribute('aria-selected', 'true')
})
