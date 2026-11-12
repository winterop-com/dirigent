import { readFileSync } from 'node:fs'
import path from 'node:path'

import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'

import { FIT_MIN_ZOOM } from '../src/lib/graph-view.ts'
import { LABELS } from '../src/lib/labels.ts'
import {
    apiPrefix,
    applyDocument,
    applyExample,
    belowTheFold,
    canvasSettled,
    clickEdge,
    DEV_USERNAME,
    dragBy,
    dragFromTo,
    everyNodeIsInView,
    graphZoom,
    nodeAt,
    removeConnection,
    removeSchema,
    repositoryRoot,
    saysShut,
    signIn,
    statusChip,
    writeInEditor,
} from './support.ts'

/**
 * The pipeline editor, against documents this suite really applied to a real `dg dev`.
 *
 * TWO EXAMPLES, EACH FOR WHAT IT HAS. `transform/std-convert-fan-out.yaml` is eight steps with a
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
const STEPS = ['source', 'parse', 'rows', 'active', 'per_region', 'report', 'store', 'as_csv']

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

/** The picker's heading, and the name its search box answers to. */
const ADD_STEP_LABEL = 'Add step'
const SEARCH_LABEL = LABELS.editor.canvas.search_blocks

/** The block picker, wherever it was opened from. */
function picker(page: Page): Locator {
    return page.locator('[data-slot="block-picker"]')
}

/** The picker's search box. */
function searchBox(page: Page): Locator {
    return picker(page).getByRole('combobox', { name: SEARCH_LABEL })
}

/** The picker's row for one block, by its id, in the picker or in one of its groups. */
function blockOption(within: Page | Locator, block: string): Locator {
    const scope = 'goto' in within ? picker(within) : within
    return scope.getByRole('option').filter({ hasText: block })
}

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

/** Where an element sits down the screen, which is how the order of a panel is asserted. */
async function topOf(locator: Locator): Promise<number> {
    const box = await locator.boundingBox()
    return box?.y ?? Number.NaN
}

/** One step's port, which is what an edge is dragged from and to. */
function port(page: Page, step: string, end: 'source' | 'target') {
    return page.locator(`.react-flow__handle.${end}[data-nodeid="${step}"]`)
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

    await page.goto(`/pipelines/${APART_PIPELINE}/edit`)
    await canvasSettled(page)

    const named = page.locator(`.react-flow__node[data-id="${NAMED_STEP}"]`)
    await expect(named.locator('[data-slot="graph-node-title"]')).toHaveText(STEP_NAME)
    await expect(named.locator('[data-slot="graph-node-line"]')).toContainText(NAMED_STEP)

    const plain = page.locator('.react-flow__node[data-id="report"]')
    await expect(plain.locator('[data-slot="graph-node-title"]')).toHaveText('report')
    await expect(plain.locator('[data-slot="graph-node-line"]')).not.toContainText('report')
})

test("a pipeline row on the listing opens that pipeline's page, led by its graph", async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto('/pipelines?examples=all')
    await page
        .getByTestId('pipeline-row')
        .filter({ has: page.getByTitle(DOCUMENT_TITLE, { exact: true }) })
        .click()

    await expect(page).toHaveURL(new RegExp(`/pipelines/${DOCUMENT_PIPELINE}$`))
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)
})

test('the stored document reads as its graph, and a step reads as its own config form', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}/edit`)

    // THE GRAPH IS THE DOCUMENT: every step it declares is a node.
    for (const step of STEPS) {
        // Each assertion waits on the same canvas; running them together would race the retries.
        await expect(page.locator('.react-flow__node').getByText(step, { exact: true })).toBeVisible()
    }
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)

    // THE STEP IN FRONT OF SOMEBODY, with the form generated from its block's own schema.
    await page.locator('.react-flow__node').getByText('parse', { exact: true }).click()

    const panel = page.locator('aside')
    await expect(panel.getByRole('tab', { name: LABELS.word.step.label })).toBeVisible()
    await expect(panel.getByRole('tab', { name: LABELS.word.pipeline.label })).toBeVisible()
    await expect(panel.getByRole('tab', { name: LABELS.word.source })).toBeVisible()
    await expect(panel.getByText('convert.std', { exact: true })).toBeVisible()

    // convert.std's four fields: the pair of formats, and the two uris it reads and writes.
    await expect(panel.getByLabel('from', { exact: true })).toHaveValue('csv')
    await expect(panel.getByLabel('to', { exact: true })).toHaveValue('json')
    await expect(panel.getByLabel('source', { exact: true })).toBeVisible()
    await expect(panel.getByLabel('target', { exact: true })).toBeVisible()
})

test('a step opens on what it needs, and the keys it leaves unset are behind one disclosure', async ({
    page,
}) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}/edit`)

    // rows runs storage.read, which requires a source and offers a content_type and a max_size.
    // The document sets only the source, so the two it says nothing about are folded.
    await page.locator('.react-flow__node').getByText('rows', { exact: true }).click()

    const panel = page.locator('aside')
    await expect(panel.getByText('storage.read', { exact: true })).toBeVisible()
    await expect(panel.getByLabel('source', { exact: true })).toBeVisible()
    await expect(panel.getByLabel('content_type', { exact: true })).toBeHidden()
    await expect(panel.getByText('max_size', { exact: true })).toBeHidden()

    const more = panel.getByRole('button', { name: '2 more fields' })
    await expect(more).toHaveAttribute('aria-expanded', 'false')
    await more.click()

    // THEY OPEN IN PLACE, and the disclosure turns to fold them again.
    await expect(panel.getByLabel('content_type', { exact: true })).toBeVisible()
    await expect(panel.getByText('max_size', { exact: true })).toBeVisible()
    await expect(panel.getByRole('button', { name: 'Fewer fields' })).toHaveAttribute('aria-expanded', 'true')

    // ANOTHER STEP IS ANOTHER FORM, and it opens folded again.
    await page.locator('.react-flow__node').getByText('parse', { exact: true }).click()
    await expect(panel.getByText('convert.std', { exact: true })).toBeVisible()
    await page.locator('.react-flow__node').getByText('rows', { exact: true }).click()
    await expect(panel.getByRole('button', { name: '2 more fields' })).toBeVisible()
})

/** An http step with a header set, and every other key its block takes left to its default. */
const HTTP_FORM_PIPELINE = 'e2e-http-step-form'

/**
 * EVERY SHAPE A REQUEST TAKES HAS ITS OWN CONTROL. Headers are key/value rows, a size is one box
 * that takes `16KB` as well as a count of bytes, a choice left to its default says the default
 * without writing it, and only a value of no type at all, the body, is a JSON buffer.
 */
test("an http step's headers are rows, its sizes text, and its defaults stay unwritten", async ({ page }) => {
    await signIn(page)
    await applyDocument(page.request, {
        format: 'dirigent/v1',
        kind: 'pipeline',
        code: HTTP_FORM_PIPELINE,
        steps: {
            fetch: {
                block: 'http.request',
                config: { url: 'http://127.0.0.1:9/', headers: { Accept: 'text/csv' } },
            },
        },
    })

    await page.goto(`/pipelines/${HTTP_FORM_PIPELINE}/edit`)
    await page.locator('.react-flow__node').getByText('fetch', { exact: true }).click()
    const panel = page.locator('aside')
    await expect(panel.getByText('http.request', { exact: true })).toBeVisible()
    await panel.getByRole('button', { name: /^\d+ more fields?$/ }).click()

    // A map's field: the innermost box holding both its name and the control looked for.
    const field = (name: string, holding: Locator) =>
        panel
            .locator('div')
            .filter({ has: page.getByText(name, { exact: true }) })
            .filter({ has: holding })
            .last()

    // THE HEADER IS A ROW: its name in the key box, its value beside it, both named by the map.
    const headers = field('headers', page.getByRole('button', { name: 'Remove headers Accept', exact: true }))
    await expect(headers.getByLabel('headers key 1', { exact: true })).toHaveValue('Accept')
    await expect(headers.getByLabel('headers value 1', { exact: true })).toHaveValue('text/csv')
    await headers.getByLabel('headers value 1', { exact: true }).fill('application/json')

    // A query value is read as the narrowest thing it parses as: 5 is a number, not the text "5".
    await field('query', page.getByRole('button', { name: 'Add', exact: true }))
        .getByRole('button', { name: 'Add', exact: true })
        .click()
    const query = page.getByLabel('query key 1', { exact: true })
    await query.fill('page')
    await page.getByLabel('query value 1', { exact: true }).fill('5')

    // A SIZE IS ONE BOX. Unset, it shows the default as what applies; 16KB is a size it takes.
    const size = panel.getByLabel('max_response', { exact: true })
    await expect(size).toHaveValue('')
    await expect(size).toHaveAttribute('placeholder', '32mb (default)')
    await size.fill('16KB')
    await size.blur()
    await expect(size).toHaveValue('16KB')
    await expect(size).not.toHaveAttribute('aria-invalid', 'true')

    // A CHOICE LEFT TO ITS DEFAULT SAYS IT, and nothing is written for it.
    await expect(panel.getByLabel('method', { exact: true })).toContainText('GET (default)')

    // The body takes any JSON value, which no control but a JSON buffer can hold.
    await expect(panel.getByRole('textbox', { name: 'body', exact: true })).toBeVisible({ timeout: 30_000 })

    // WHAT WAS TYPED IS THE DOCUMENT, and what was left to its default is not in it.
    await panel.getByRole('tab', { name: LABELS.word.source }).click()
    const source = panel.locator('.cm-content')
    await expect(source).toContainText('Accept: application/json', { timeout: 30_000 })
    await expect(source).toContainText('page: 5')
    await expect(source).toContainText('max_response: 16KB')
    await expect(source).not.toContainText('method:')
    await expect(source).not.toContainText("'5'")

    // A CHOICE IS WRITTEN ONCE CHOSEN, and its default chosen again takes the key out.
    await panel.getByRole('tab', { name: LABELS.word.step.label }).click()
    await panel.getByRole('button', { name: /^\d+ more fields?$/ }).click()
    await panel.getByLabel('method', { exact: true }).click()
    await page.getByRole('option', { name: 'POST', exact: true }).click()
    await panel.getByRole('tab', { name: LABELS.word.source }).click()
    await expect(source).toContainText('method: POST', { timeout: 30_000 })
    await panel.getByRole('tab', { name: LABELS.word.step.label }).click()
    await panel.getByLabel('method', { exact: true }).click()
    await page.getByRole('option', { name: 'Default (GET)', exact: true }).click()
    await expect(panel.getByLabel('method', { exact: true })).toContainText('GET (default)')
    await panel.getByRole('tab', { name: LABELS.word.source }).click()
    await expect(source).toContainText('max_response: 16KB', { timeout: 30_000 })
    await expect(source).not.toContainText('method:')
})

/**
 * THE CONFIG IS THE QUESTION AND THE ENGINE IS THE SETTING.
 *
 * The panel opens on the block's own form; `for_each`, the timings, the retry policy and the rule
 * sit under it as groups that say what would run without being opened, and the display name is
 * last. A group opens under its own row rather than in a second pane.
 */
test('the engine half of a step is groups that say their state, and one opens in place', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}/edit`)
    // per_region is mapped over the parameter, and waits for the step that reshaped the rows.
    await page.locator('.react-flow__node').getByText('per_region', { exact: true }).click()

    const panel = page.locator('aside')
    const config = panel.getByRole('heading', { name: LABELS.word.config })
    const waits = panel.getByRole('button', { name: /Waits for/ })
    const displayName = panel.getByLabel(LABELS.word.name.label, { exact: true })
    await expect(config).toBeVisible()
    await expect(waits).toBeVisible()

    // CONFIG FIRST, THEN THE ENGINE, THEN THE NAME.
    expect(await topOf(config)).toBeLessThan(await topOf(waits))
    expect(await topOf(waits)).toBeLessThan(await topOf(displayName))

    // EVERY GROUP SAYS WHERE IT STANDS WITH NOTHING OPENED: what the step sets, and what it
    // would fall back to.
    await expect(waits).toContainText(LABELS.state.armed.active)
    const fanOut = panel.getByRole('button', { name: /Fan-out/ })
    await expect(fanOut).toContainText('${params.regions}')
    await expect(fanOut).toContainText('fail_fast')
    await expect(panel.getByRole('button', { name: /Timing/ })).toContainText('on_timeout fail')
    await expect(panel.getByRole('button', { name: /Rule/ })).toContainText('all_success')

    const retry = panel.getByRole('button', { name: /Retry/ })
    await expect(retry).toContainText('off')
    await expect(panel.getByLabel('max_attempts', { exact: true })).toBeHidden()

    // A ROW OPENS UNDER ITSELF, and what is edited there is the document.
    await retry.click()
    const attempts = panel.getByLabel('max_attempts', { exact: true })
    await expect(attempts).toBeVisible()
    expect(await topOf(retry)).toBeLessThan(await topOf(attempts))
    await attempts.fill('3')

    // An open row says nothing its fields do not: the line comes back when it shuts, and THEN
    // SAYS THE POLICY THAT WOULD RUN NOW, defaults and all.
    await expect(retry).not.toContainText('attempts')
    await retry.click()
    await expect(attempts).toBeHidden()
    await expect(retry).toContainText('3 attempts')
    await expect(retry).toContainText('30s backoff')

    // The group beside it was never opened by any of this.
    await expect(panel.getByLabel('for_each', { exact: true })).toBeHidden()
    await fanOut.click()
    await expect(panel.getByLabel('for_each', { exact: true })).toHaveValue('${params.regions}')
})

test('a config field the schema calls a program is edited as one, and every other string is not', async ({
    page,
}) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}/edit`)

    // per_region's program is five lines of jq, which is what one input cannot hold.
    await page.locator('.react-flow__node').getByText('per_region', { exact: true }).click()

    const panel = page.locator('aside')
    await expect(panel.getByText('transform.jq', { exact: true })).toBeVisible()

    // The editor is a chunk of its own, fetched when the first structured field of a session
    // opens. per_region carries two buffers: its JSON input, and its program.
    const program = panel.getByRole('textbox', { name: 'program', exact: true })
    await expect(program).toBeVisible({ timeout: 30_000 })

    // THE PROGRAM IS ON THE LINES IT WAS WRITTEN ON, and the label is still the key.
    await expect(program).toContainText('select(.region == $region)')
    await expect(program.locator('.cm-line').nth(3)).toBeVisible()

    // The JSON input is a buffer too, coloured where it stands rather than a bare box.
    const input = panel.getByRole('textbox', { name: 'input', exact: true })
    await expect(input).toBeVisible()

    // The window is a second reader of the same buffer, and closing it leaves the buffer
    // standing: the inline pane still holds the text, and no control keeps a focus ring.
    await panel.getByLabel('Open input in a window').click()
    await expect(page.getByRole('dialog').locator('.cm-editor')).toBeVisible({ timeout: 30_000 })
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toBeHidden()
    await expect(input).toContainText('region')

    // A BLOCK WITH NEITHER A PROGRAM NOR A STRUCTURED FIELD GETS NO EDITOR. convert.std has
    // a from, a to, a source and a target, and the schema says every one is a plain string.
    await page.locator('.react-flow__node').getByText('parse', { exact: true }).click()
    await expect(panel.getByLabel('from', { exact: true })).toHaveValue('csv')
    await expect(panel.locator('[data-slot="code-editor"]')).toHaveCount(0)
})

test('editing a config field is unapplied until it is applied, and the topbar counts it', async ({
    page,
}) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}/edit`)
    await page.locator('.react-flow__node').getByText('parse', { exact: true }).click()

    const panel = page.locator('aside')
    await expect(panel.getByLabel('to', { exact: true })).toHaveValue('json')

    // Nothing is unapplied before anything is edited.
    await expect(page.getByText(/unapplied edit/)).toHaveCount(0)

    await panel.getByLabel('to', { exact: true }).fill('yaml')

    // One step differs from the stored version, and the node on the canvas says which.
    await expect(page.getByRole('button', { name: LABELS.action.apply, exact: true })).toHaveClass(
        /bg-primary/,
    )
    await expect(
        page.locator('.react-flow__node').getByText(LABELS.editor.canvas.edited, { exact: true }),
    ).toBeVisible()
})

test('the source tab holds the same document, in the editor the schema is checked in', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}/edit`)
    await page.locator('.react-flow__node').getByText('parse', { exact: true }).click()

    const panel = page.locator('aside')
    await panel.getByRole('tab', { name: LABELS.word.source }).click()

    // The editor is a chunk of its own and is fetched when this tab is opened, so the assertion
    // is that it arrived and is holding this document rather than an empty buffer.
    await expect(panel.locator('.cm-editor')).toBeVisible({ timeout: 30_000 })
    await expect(panel.locator('.cm-content')).toContainText(DOCUMENT_PIPELINE)
})

/**
 * THE SCHEMA IS CHECKED AS THE DOCUMENT IS WRITTEN. A key no pipeline takes is marked on its
 * own line, before any apply is asked for. Only a browser can say the checker loaded: a buffer
 * whose checker never arrives still draws, highlights and edits, and says nothing.
 */
test('the source tab marks a key the schema does not take, on its line', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}/edit`)
    await page.locator('.react-flow__node').getByText('parse', { exact: true }).click()

    const panel = page.locator('aside')
    await panel.getByRole('tab', { name: LABELS.word.source }).click()
    const editor = panel.locator('[data-slot="code-editor"]')
    const shipped = readFileSync(path.join(repositoryRoot, DOCUMENT_EXAMPLE), 'utf8')
    await writeInEditor(page, editor, `${shipped.trimEnd()}\nnot_a_key: true\n`)

    await expect.poll(() => markedLines(editor), { timeout: 15_000 }).toContain('not_a_key: true')
})

/**
 * A STEP'S CONFIG IS THE BLOCK'S. The schema decides each step's `config` by the block it names,
 * so completion offers that block's keys and a check refuses what that block does not take --
 * and a `${...}` reference, which the run fills in, is never refused. Only the two keys at fault
 * are marked: not `format`, `kind`, `params` or the step that holds them.
 */
test("the source tab completes and checks a step's config from the block it names", async ({ page }) => {
    await signIn(page)
    await page.goto('/pipelines/$new')
    const panel = page.locator('aside')
    await panel.getByRole('tab', { name: LABELS.word.source }).click()
    const editor = panel.locator('[data-slot="code-editor"]')
    const head = ['format: dirigent/v1', 'kind: pipeline', 'code: e2e-config-checked', 'steps:', '  one:']

    for (const [block, keys] of [
        ['http.request', ['url', 'method', 'follow_redirects']],
        ['transform.jq', ['program']],
        ['convert.std', ['from', 'to']],
    ] as const) {
        await writeInEditor(
            page,
            editor,
            [...head, `    block: ${block}`, '    config:', '      '].join('\n'),
        )
        await page.keyboard.press('Control+Space')
        const offered = page.locator('.cm-tooltip-autocomplete')
        await expect(offered).toBeVisible({ timeout: 15_000 })
        for (const key of keys) await expect(offered).toContainText(key)
        await page.keyboard.press('Escape')
    }

    await writeInEditor(
        page,
        editor,
        [
            'format: dirigent/v1',
            'kind: pipeline',
            'code: e2e-config-checked',
            'params:',
            '  type: object',
            '  properties:',
            '    verb:',
            '      type: string',
            'steps:',
            '  one:',
            '    block: http.request',
            '    config:',
            '      url: http://127.0.0.1:9/checked',
            '      method: ${params.verb}',
            '      follow_redirects: 3',
            '      not_a_config_key: 1',
            '',
        ].join('\n'),
    )
    await expect
        .poll(async () => (await markedLines(editor)).toSorted(), { timeout: 15_000 })
        .toEqual(['follow_redirects: 3', 'not_a_config_key: 1'])
})

/** The text of every drawn line the editor's check marked, trimmed. */
async function markedLines(editor: Locator): Promise<string[]> {
    return editor.evaluate((node) => [
        ...new Set(
            [...node.querySelectorAll('.cm-lintRange, .cm-lintPoint')].map((mark) =>
                (mark.closest('.cm-line')?.textContent ?? '').trim(),
            ),
        ),
    ])
}

/** Hold a document on the instance, then ask what replacing it with one plain step would take away. */
async function planWithoutIt(page: Page, pipeline: string, held: Record<string, unknown>): Promise<Locator> {
    const prefix = await apiPrefix(page.request)
    await page.request.delete(`${prefix}/pipelines/${pipeline}`)
    await applyDocument(page.request, {
        format: 'dirigent/v1',
        kind: 'pipeline',
        code: pipeline,
        ...held,
    })
    await page.goto(`/pipelines/${pipeline}/edit`)
    await page.locator('.react-flow__node').first().click()
    const panel = page.locator('aside')
    await panel.getByRole('tab', { name: LABELS.word.source }).click()
    await writeInEditor(
        page,
        panel.locator('[data-slot="code-editor"]'),
        [
            'format: dirigent/v1',
            'kind: pipeline',
            `code: ${pipeline}`,
            'steps:',
            '  plain:',
            '    block: http.request',
            '    config: { url: "http://127.0.0.1:9/after" }',
            '',
        ].join('\n'),
    )
    await page.getByRole('button', { name: LABELS.action.validate }).click()
    return page.getByRole('dialog')
}

test('a plan says when applying would take a source away', async ({ page }) => {
    await signIn(page)
    const dialog = await planWithoutIt(page, 'e2e-plan-retires-source', {
        steps: {
            ask: { source: { kind: 'endpoint', path: '/e2e-plan-retires-source' } },
            answer: { depends_on: ['ask'], reply: { status: 200, body: 'done' } },
        },
    })
    const removes = consequences(dialog, LABELS.editor.plan.retiring.heading)
    await expect(removes).toHaveCount(1)
    await expect(removes.first()).toContainText(LABELS.editor.plan.retiring.sources.one)
    await expect(removes.first()).toContainText('ask')
})

test('a plan says when applying would take a schedule away', async ({ page }) => {
    await signIn(page)
    const dialog = await planWithoutIt(page, 'e2e-plan-retires-schedule', {
        triggers: { schedules: [{ code: 'nightly', cron: '0 3 * * *' }] },
        steps: { plain: { block: 'http.request', config: { url: 'http://127.0.0.1:9/before' } } },
    })
    // What changes is one list and what goes is another, each a row per kind with its codes.
    const changes = consequences(dialog, LABELS.editor.plan.changes_heading)
    await expect(changes.filter({ hasText: LABELS.editor.plan.steps_changed.one })).toContainText('plain')
    await expect(changes.filter({ hasText: LABELS.editor.plan.triggers_changed })).toHaveCount(1)
    const removes = consequences(dialog, LABELS.editor.plan.retiring.heading)
    await expect(removes).toHaveCount(1)
    await expect(removes.first()).toContainText(LABELS.editor.plan.retiring.schedules.one)
    await expect(removes.first()).toContainText('nightly')

    // And the stored document stands against this one, the dropped schedule among the removed lines.
    const diff = dialog.locator('[data-slot="code-block"]').filter({
        hasText: LABELS.editor.plan.diff_title('1', '2'),
    })
    await expect(diff.locator('[data-variant="removed"]').filter({ hasText: 'nightly' })).toHaveCount(1)
    await expect(diff.locator('[data-variant="added"]').filter({ hasText: '127.0.0.1:9/after' })).toHaveCount(
        1,
    )
    // Its window is opened from the diff's own header.
    await expect(
        diff.locator('[data-slot="code-block-header"]').getByRole('button', {
            name: LABELS.shell.open_in_window(LABELS.editor.plan.diff_title('1', '2')),
        }),
    ).toBeVisible()
})

test('a plan that rewrites nothing in the document draws no diff', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)
    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}/edit`)
    await page.getByRole('button', { name: LABELS.action.validate }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText(/Apply writes nothing/)).toBeVisible()
    await expect(dialog.locator('[data-slot="code-block"]')).toHaveCount(0)
})

/** The rows of the plan's list named by its heading. */
function consequences(dialog: Locator, heading: string): Locator {
    return dialog.getByRole('list', { name: heading, exact: true }).getByRole('listitem')
}

test('a canvas with nothing on it offers nothing to zoom', async ({ page }) => {
    await signIn(page)
    await page.goto('/pipelines/$new')
    await expect(page.getByText(LABELS.editor.canvas.no_steps)).toBeVisible()
    await expect(page.getByRole('button', { name: LABELS.shell.fit_view })).toHaveCount(0)
})

test('a token an apply creates is shown once, before the editor moves on', async ({ page }) => {
    await signIn(page)
    const prefix = await apiPrefix(page.request)
    const pipeline = 'e2e-apply-mints'
    await page.request.delete(`${prefix}/pipelines/${pipeline}`)
    await page.goto('/pipelines/$new')
    const panel = page.locator('aside')
    await panel.getByRole('tab', { name: LABELS.word.source }).click()
    await writeInEditor(
        page,
        panel.locator('[data-slot="code-editor"]'),
        [
            'format: dirigent/v1',
            'kind: pipeline',
            `code: ${pipeline}`,
            'steps:',
            '  ask:',
            '    source: { kind: endpoint, path: /e2e-apply-mints }',
            '  answer:',
            '    depends_on: [ask]',
            '    reply: { status: 200, body: done }',
            '',
        ].join('\n'),
    )
    await page.getByRole('button', { name: LABELS.action.apply, exact: true }).click()
    const asking = page.getByRole('dialog').filter({ hasText: LABELS.editor.apply.title })
    await asking.getByRole('button', { name: LABELS.action.apply, exact: true }).click()

    const shown = page.getByRole('dialog').filter({ hasText: LABELS.triggers.token.title('ask') })
    await expect(shown.locator('code').first()).not.toBeEmpty()
    await expect(page).toHaveURL(/\/pipelines\/\$new$/)
    await shown.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/pipelines/${pipeline}/edit$`))
    await page.request.delete(`${prefix}/pipelines/${pipeline}`)
})

test('validating an intact document reports no issues', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}/edit`)
    await page.getByRole('button', { name: LABELS.action.validate }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText(LABELS.editor.apply.validate_title)).toBeVisible()
    // The digest matches what was applied a moment ago, so applying would write nothing --
    // and, either way, the instance refuses nothing about it.
    await expect(dialog.getByText(/Apply writes nothing/)).toBeVisible()
    await expect(dialog.getByText(LABELS.editor.plan.refuse(DOCUMENT_PIPELINE))).toHaveCount(0)
    // Validate asks nothing, so it has no footer and the corner's close is the way out.
    await expect(dialog.getByRole('button', { name: LABELS.action.cancel })).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: 'Close', exact: true })).toBeVisible()
    await expect(dialog.getByRole('button', { name: LABELS.action.apply, exact: true })).toHaveCount(0)
})

/**
 * A DIALOG IS A DECISION, AND THIS ONE WOULD HAVE NONE. The document on screen is the version
 * the instance holds, so applying writes nothing: the verb is shut where it is offered, says
 * why to a pointer and to a reader, and no dialog opens.
 */
test('apply is shut on a document the instance already holds, and says why', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}/edit`)
    const apply = page.getByRole('button', { name: LABELS.action.apply, exact: true })
    await saysShut(page, apply, LABELS.editor.apply.nothing_to_apply)
    // A shut verb stays reachable, so the sentence can be read without a pointer.
    await apply.focus()
    await expect(apply).toBeFocused()

    // The two verbs beside it act on a document that has not changed, so both stay live.
    await expect(page.getByRole('button', { name: LABELS.action.validate })).toBeEnabled()
    await expect(
        page.getByRole('button', { name: LABELS.action.asks(LABELS.action.run), exact: true }),
    ).toBeEnabled()

    await apply.click({ force: true })
    await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('the run dialog is built from the pipeline own parameter schema', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, PARAMS_EXAMPLE)

    await page.goto(`/pipelines/${PARAMS_PIPELINE}/edit`)
    await page.getByRole('button', { name: 'Run…', exact: true }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: 'Run', exact: true })).toBeVisible()
    await expect(dialog.getByText('Every parameter shape')).toBeVisible()
    // Every parameter the document declares, each as the control its schema asks for.
    await expect(dialog.getByLabel('day', { exact: true })).toBeVisible()
    await expect(dialog.getByLabel('batch_size', { exact: true })).toBeVisible()
    await expect(dialog.getByText('required').first()).toBeVisible()
    // It says who the run would be attributed to, which is what the run's own screen shows.
    await expect(dialog.getByText(`runs as ${DEV_USERNAME}`)).toBeVisible()

    // The run decides what its log keeps: info and up unless this control asks for debug.
    await expect(dialog.getByLabel(LABELS.editor.run.log_level)).toBeVisible()
})

test('a document that reads a window is not run until it is given one', async ({ page }) => {
    await signIn(page)
    await applyDocument(page.request, WINDOWED)

    await page.goto(`/pipelines/${WINDOWED_PIPELINE}/edit`)
    await page.getByRole('button', { name: 'Run…', exact: true }).click()

    const dialog = page.getByRole('dialog')
    const start = dialog.getByLabel(LABELS.word.start, { exact: true })
    const end = dialog.getByLabel(LABELS.word.end, { exact: true })
    // The section is open on this document rather than behind the link, because its steps
    // read a window and a run carrying none would stop at the first of them.
    await expect(start).toBeVisible()
    await expect(end).toBeVisible()
    await expect(dialog.getByRole('button', { name: LABELS.editor.run.add_window })).toHaveCount(0)

    const runNow = dialog.getByRole('button', { name: LABELS.editor.run.confirm })
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
    await expect(statusChip(page, 'succeeded').first()).toBeVisible({
        timeout: 30_000,
    })
    await expect((await runFacts(page)).getByText(LABELS.word.window.term, { exact: true })).toBeVisible()
})

test('a document that reads no window keeps its window behind a link and runs without one', async ({
    page,
}) => {
    await signIn(page)
    await applyDocument(page.request, PLAIN)

    await page.goto(`/pipelines/${PLAIN_PIPELINE}/edit`)
    await page.getByRole('button', { name: 'Run…', exact: true }).click()

    const dialog = page.getByRole('dialog')
    const add = dialog.getByRole('button', { name: LABELS.editor.run.add_window })
    await expect(add).toBeVisible()
    await expect(dialog.getByLabel(LABELS.word.start, { exact: true })).toHaveCount(0)

    const runNow = dialog.getByRole('button', { name: LABELS.editor.run.confirm })
    await expect(runNow).toBeEnabled()

    // The link opens the same two boxes, and leaving them empty leaves the run without a window.
    await add.click()
    await expect(dialog.getByLabel(LABELS.word.start, { exact: true })).toBeVisible()
    await expect(runNow).toBeEnabled()
    await runNow.click()

    await expect(page).toHaveURL(/\/runs\//)
    await expect(statusChip(page, 'succeeded').first()).toBeVisible({
        timeout: 30_000,
    })
    const panel = await runFacts(page)
    await expect(panel.getByText(LABELS.word.created.term, { exact: true })).toBeVisible()
    await expect(panel.getByText(LABELS.word.window.term, { exact: true })).toHaveCount(0)
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

test("a pipeline this instance does not have is refused in this interface's own words", async ({ page }) => {
    await signIn(page)
    await page.goto('/pipelines/no-such-pipeline/edit')
    // `pipeline.unknown` off the wire, drawn from the catalogue rather than from its `detail`.
    await expect(
        page.getByText(LABELS.refused.pipeline.unknown.replace('{code}', "'no-such-pipeline'")),
    ).toBeVisible()
})

test('the editor opens with the whole graph in view, at a zoom that does not blow it up', async ({
    page,
}) => {
    await signIn(page)
    await applyExample(page.request, DOCUMENT_EXAMPLE)

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}/edit`)
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)
    await everyNodeIsInView(page)
    // A fit never zooms past a box's own size: a graph of a few boxes sits at a size worth
    // reading rather than blown up to fill the canvas.
    expect(await graphZoom(page)).toBeLessThanOrEqual(1)
})

test('a graph too big for the floor opens readable, from its start, and is panned to', async ({ page }) => {
    await signIn(page)
    const prefix = await apiPrefix(page.request)
    const pipeline = 'e2e-past-the-floor'
    await page.request.delete(`${prefix}/pipelines/${pipeline}`)
    const count = 60
    const steps = Object.fromEntries(
        Array.from({ length: count }, (_, at) => [
            `step_${String(at).padStart(2, '0')}`,
            {
                block: 'http.request',
                config: { url: `http://127.0.0.1:9/${String(at)}` },
                ...(at === 0 ? {} : { depends_on: [`step_${String(at - 1).padStart(2, '0')}`] }),
            },
        ]),
    )
    await applyDocument(page.request, { format: 'dirigent/v1', kind: 'pipeline', code: pipeline, steps })

    await page.goto(`/pipelines/${pipeline}/edit`)
    await expect(page.locator('.react-flow__node')).toHaveCount(count)
    await canvasSettled(page)

    expect(await graphZoom(page)).toBeCloseTo(FIT_MIN_ZOOM)
    const first = page.locator('.react-flow__node[data-id="step_00"]')
    const canvas = page.locator('.react-flow')
    const inside = async () => {
        const [box, frame] = await Promise.all([first.boundingBox(), canvas.boundingBox()])
        return box !== null && frame !== null && box.x >= frame.x && box.y >= frame.y
    }
    await expect.poll(inside).toBe(true)
    await page.request.delete(`${prefix}/pipelines/${pipeline}`)
})

test('a graph of two steps is fully visible rather than filling the canvas', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, PARAMS_EXAMPLE)

    await page.goto(`/pipelines/${PARAMS_PIPELINE}/edit`)
    await everyNodeIsInView(page)
    expect(await graphZoom(page)).toBeLessThanOrEqual(1)
})

test('the editor draws a port on every step, and a run graph draws none', async ({ page }) => {
    await signIn(page)
    await applyDocument(page.request, APART)

    await page.goto(`/pipelines/${APART_PIPELINE}/edit`)
    await expect(page.locator('.react-flow__node')).toHaveCount(2)

    // Two per box, both visible and both connectable: this is the canvas that edits.
    await expect(page.locator('.react-flow__handle')).toHaveCount(4)
    await expect(port(page, 'fetch', 'source')).toBeVisible()
    await expect(port(page, 'report', 'target')).toBeVisible()
    await expect(page.locator('.react-flow__handle.connectable')).toHaveCount(4)
})

test('an edge dragged between two ports is the dependency, and Delete takes it away', async ({ page }) => {
    await signIn(page)
    await applyDocument(page.request, APART)

    await page.goto(`/pipelines/${APART_PIPELINE}/edit`)
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
    await expect(page.getByRole('button', { name: LABELS.action.apply, exact: true })).toHaveClass(
        /bg-primary/,
    )
    await page.locator('.react-flow__node').getByText('report', { exact: true }).click()
    // The panel says it in the shut Waits for row, and opening the row is where it is taken back.
    const waits = page.locator('aside').getByRole('button', { name: /Waits for/ })
    await expect(waits).toContainText('fetch')
    await waits.click()
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

    await page.goto(`/pipelines/${APART_PIPELINE}/edit`)
    await expect(page.locator('.react-flow__node')).toHaveCount(2)
    await canvasSettled(page)

    await dragFromTo(page, port(page, 'fetch', 'source'), port(page, 'report', 'target'))
    await expect(page.locator('.react-flow__edge')).toHaveCount(1)
    await canvasSettled(page)

    await dragFromTo(page, port(page, 'report', 'source'), port(page, 'fetch', 'target'))

    await expect(page.getByText('fetch → report → fetch', { exact: false })).toBeVisible()
    await expect(page.locator('.react-flow__edge')).toHaveCount(1)
    await expect(page.getByRole('button', { name: LABELS.action.apply, exact: true })).toHaveClass(
        /bg-primary/,
    )
})

test('a box stays where it was dragged, across a reload, until laying out again gives it back', async ({
    page,
}) => {
    await signIn(page)
    await applyDocument(page.request, APART)

    await page.goto(`/pipelines/${APART_PIPELINE}/edit`)
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

    // Laying out again is how it is given back: elk decides again, and storage holds nothing.
    await page.keyboard.press('ControlOrMeta+k')
    await page.getByPlaceholder(LABELS.palette.placeholder).fill(LABELS.editor.topbar.relayout)
    await page.getByRole('option').filter({ hasText: LABELS.editor.topbar.relayout }).first().click()
    await expect.poll(async () => (await nodeAt(page, 'fetch')).x).toBeCloseTo(placed.x, 0)
    expect(await page.evaluate((key) => localStorage.getItem(key), APART_LAYOUT_KEY)).toBeNull()
    await everyNodeIsInView(page)
})

test('a connection dropped on empty ground adds a step already waiting for the one it came from', async ({
    page,
}) => {
    await signIn(page)
    await applyDocument(page.request, APART)

    await page.goto(`/pipelines/${APART_PIPELINE}/edit`)
    await expect(page.locator('.react-flow__node')).toHaveCount(2)
    await canvasSettled(page)

    // Let go over the ground rather than over a port: the picker opens where it was dropped, and
    // says which step the one it is about to add will wait for.
    await dragBy(page, port(page, 'fetch', 'source'), 220, 140)

    await expect(picker(page).getByText(`${ADD_STEP_LABEL} after fetch`, { exact: true })).toBeVisible()
    // The four transform verbs declare one group, so the block is listed under it.
    await blockOption(
        picker(page).getByRole('group', { name: 'transform', exact: true }),
        'transform.jq',
    ).click()

    await expect(page.locator('.react-flow__node')).toHaveCount(3)
    await expect(page.locator('.react-flow__edge')).toHaveCount(1)
    // The key is the block's own name, made unique against the two the document already has.
    await expect(
        page.locator('.react-flow__node').getByText(LABELS.reference.jq.title, { exact: true }),
    ).toBeVisible()
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
    await expect(page.getByText(LABELS.editor.canvas.no_steps, { exact: false })).toBeVisible()

    await page.locator('.react-flow__pane').click({ button: 'right', position: { x: 80, y: 80 } })

    await expect(picker(page).getByText(ADD_STEP_LABEL, { exact: true })).toBeVisible()
    await expect(searchBox(page)).toBeFocused()
    // Every group the catalog declares, and nothing else: a group of one -- webhook -- is
    // still a group, so the list is one uniform arrangement of groups.
    await expect(picker(page).getByRole('group', { name: 'transform', exact: true })).toBeVisible()
    await expect(picker(page).getByRole('group', { name: 'execute', exact: true })).toBeVisible()
    await expect(picker(page).getByRole('group', { name: 'webhook', exact: true })).toBeVisible()
    await expect(picker(page).getByRole('group', { name: 'sensors', exact: true })).toHaveCount(0)

    await blockOption(page, 'webhook.post').click()

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

    await page.goto(`/pipelines/${CHAIN_PIPELINE}/edit`)
    await expect(page.locator('.react-flow__node')).toHaveCount(2)
    await expect(page.locator('.react-flow__edge')).toHaveCount(1)
    await canvasSettled(page)

    await page.locator('.react-flow__node[data-id="fetch"]').click({ button: 'right' })
    const menu = page.getByRole('menu')
    await expect(menu.getByRole('menuitem', { name: LABELS.editor.canvas.add_after })).toBeVisible()

    // The step goes, and the edge that named it goes with it: a `depends_on` naming a step
    // the document no longer declares is what an apply refuses.
    await menu.getByRole('menuitem', { name: LABELS.editor.canvas.delete_step }).click()
    await expect(page.locator('.react-flow__node')).toHaveCount(1)
    await expect(page.locator('.react-flow__edge')).toHaveCount(0)
    // The topbar counts it with every other unapplied edit, and nothing has been written.
    await expect(page.getByRole('button', { name: LABELS.action.apply, exact: true })).toHaveClass(
        /bg-primary/,
    )

    // Nothing was written: the document the instance holds still has both steps.
    await page.reload()
    await expect(page.locator('.react-flow__node')).toHaveCount(2)
})

/** A chosen step and the key: the same gesture a chosen edge answers. */
test('a chosen step is deleted by the key, and never while a text box has the focus', async ({ page }) => {
    await signIn(page)
    await applyDocument(page.request, CHAIN)

    await page.goto(`/pipelines/${CHAIN_PIPELINE}/edit`)
    await expect(page.locator('.react-flow__node')).toHaveCount(2)
    await canvasSettled(page)

    // The step's own pane opens on the choice, and typing a name into it is not a deletion.
    await page.locator('.react-flow__node[data-id="report"]').click()
    const name = page.locator('aside').getByLabel(LABELS.word.name.label, { exact: true })
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
 * The groups are for somebody who knows where a block lives; the box is for somebody who knows
 * what it is called. It narrows the list to the blocks it matches, each titled by its whole id,
 * the arrows move through them, and the return key places the one they are on.
 */
test('the search box narrows the picker, and the return key places one', async ({ page }) => {
    // A document with no steps is `/pipelines/$new`: the instance refuses to store one, and it
    // is where an add-step gesture matters most.
    await signIn(page)
    await page.goto('/pipelines/$new')
    await expect(page.getByText(LABELS.editor.canvas.no_steps, { exact: false })).toBeVisible()

    await page.locator('.react-flow__pane').click({ button: 'right', position: { x: 120, y: 120 } })
    await searchBox(page).fill('ru')

    await expect(blockOption(page, 'docker.run')).toBeVisible()
    await expect(blockOption(page, 'shell.run')).toBeVisible()
    // Only the groups holding a match are left while there is something in the box.
    await expect(picker(page).getByRole('group', { name: 'webhook', exact: true })).toHaveCount(0)

    // The arrows walk the results from the first, and the return key places the one they are on.
    const results = await picker(page).getByRole('option').allTextContents()
    const at = results.findIndex((text) => text.includes('shell.run'))
    expect(at).toBeGreaterThan(0)
    for (let step = 0; step < at; step += 1) await page.keyboard.press('ArrowDown')
    await expect(picker(page).locator('[role="option"][aria-selected="true"]')).toContainText('shell.run')
    await page.keyboard.press('Enter')

    await expect(page.locator('.react-flow__node')).toHaveCount(1)
    await expect(page.locator('.react-flow__node').getByText('run', { exact: true })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Step · run' })).toHaveAttribute('aria-selected', 'true')
})

/**
 * AN UNREAD CATALOG IS NOT AN EMPTY ONE.
 *
 * The menu opens on whatever the screen has in hand, and the catalog is a read that may not have
 * landed. A search over nothing would answer that no block matches -- the one thing it does not
 * know -- and a sentence that is wrong for the half second before the answer arrives teaches a
 * reader to stop believing it. So the menu says which of the two it is in, and the row is there
 * to place once the read comes back.
 */
test('the menu says it is reading the catalog rather than that nothing matches', async ({ page }) => {
    await signIn(page)

    // The catalog is held until this spec lets it go, so the two states are asserted on in turn
    // rather than raced for.
    let release = () => {}
    const held = new Promise<void>((resolve) => {
        release = resolve
    })
    await page.route(/\/api\/v\d+\/blocks$/, async (route) => {
        await held
        await route.fallback()
    })

    await page.goto('/pipelines/$new')
    await page.getByRole('button', { name: ADD_STEP_LABEL }).click()
    await expect(searchBox(page)).toBeFocused()

    // Before a search: no groups to draw, and it says why rather than drawing an empty popup.
    await expect(picker(page).getByText(LABELS.shell.reading, { exact: true })).toBeVisible()

    // And during one: still reading, rather than the flat denial the same box used to answer with.
    await searchBox(page).fill('shell')
    await expect(picker(page).getByText(LABELS.shell.reading, { exact: true })).toBeVisible()
    await expect(picker(page).getByText(LABELS.editor.canvas.no_block_matches, { exact: true })).toHaveCount(
        0,
    )

    release()
    // The read lands under the search already typed, and the row it found is there to place.
    const found = blockOption(page, 'shell.run')
    await expect(found).toHaveCount(1)
    await expect(picker(page).getByText(LABELS.shell.reading, { exact: true })).toHaveCount(0)
    await found.click()
    await expect(page.locator('.react-flow__node')).toHaveCount(1)
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
    await searchBox(page).fill('sensor')

    // The words a kind is named by find every block of that kind, whatever group it is listed under.
    await expect(blockOption(page, 'time.sleep')).toBeVisible()
    await expect(blockOption(page, 'storage.exists')).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(searchBox(page)).toHaveValue('')
    await expect(picker(page).getByRole('group', { name: 'transform', exact: true })).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(picker(page)).toHaveCount(0)
    await expect(page.locator('.react-flow__node')).toHaveCount(0)
})

/**
 * THE PICKER IS PLACED AGAINST THE CANVAS, NOT AGAINST THE POINTER ALONE.
 *
 * A right-click in the far corner of the canvas is the ordinary case near the foot of a screen,
 * and a picker that hung off the canvas there would be a list with rows nobody can reach.
 */
test('the picker opens inside the canvas wherever the pointer is', async ({ page }) => {
    await signIn(page)
    await page.goto('/pipelines/$new')
    await expect(page.getByText(LABELS.editor.canvas.no_steps, { exact: false })).toBeVisible()

    const pane = page.locator('.react-flow__pane')
    const canvas = await pane.boundingBox()
    if (canvas === null) throw new Error('the canvas has no box on the screen')
    await pane.click({ button: 'right', position: { x: canvas.width - 6, y: canvas.height - 6 } })

    await expect(picker(page)).toBeVisible()
    const inside = await page.evaluate(() => {
        const popup = document.querySelector('[data-slot="block-picker"]')
        const frame = document.querySelector('[data-graph-view]')
        if (popup === null || frame === null) return null
        const box = popup.getBoundingClientRect()
        const room = frame.getBoundingClientRect()
        return (
            box.left >= room.left - 1 &&
            box.top >= room.top - 1 &&
            box.right <= room.right + 1 &&
            box.bottom <= room.bottom + 1
        )
    })
    expect(inside).toBe(true)
})

/**
 * ONLY A SENSOR WEARS A CHIP: which block waits for something is what a group cannot say, and a
 * chip on every row would say what the absence of one already says.
 */
test('only a sensor wears a kind chip in its group', async ({ page }) => {
    await signIn(page)
    await page.goto('/pipelines/$new')
    // The palette is the keyboard way in, and reaches the same menu.
    await page.keyboard.press('ControlOrMeta+k')
    await page.getByPlaceholder(LABELS.palette.placeholder).fill('add step')
    await page
        .getByRole('option')
        .filter({ hasText: /^Add step/ })
        .first()
        .click()
    const http = picker(page).getByRole('group', { name: 'http', exact: true })
    const operator = blockOption(http, 'http.request')
    await expect(operator).toBeVisible()
    await expect(operator.locator('[data-slot="chip"]')).toHaveCount(0)
    await expect(blockOption(http, 'http.ready').locator('[data-slot="chip"]')).toHaveText('sensor')
})

/**
 * THE ADD-STEP GESTURE THAT CAN BE SEEN.
 *
 * A right-click has to be known about and the palette has to be remembered; the button on the
 * canvas is what a reader who has opened this screen for the first time can find: under the
 * empty canvas's words, then beside the zoom. It opens the same picker beside itself, and it is
 * reachable from the keyboard like any other button.
 */
test('the add button opens the same picker, beside itself', async ({ page }) => {
    await signIn(page)
    await page.goto('/pipelines/$new')
    // The empty state says what is true and nothing about how to change it: the control is there.
    await expect(page.getByText(LABELS.editor.canvas.no_steps, { exact: true })).toBeVisible()

    const button = page.getByRole('button', { name: ADD_STEP_LABEL })
    await expect(button).toBeVisible()
    await button.click()

    await expect(picker(page).getByText(ADD_STEP_LABEL, { exact: true })).toBeVisible()
    const search = searchBox(page)
    await expect(search).toBeFocused()
    await page.keyboard.type('shell')
    await expect(search).toHaveValue('shell')

    // The picker opens beside the button rather than at a point elsewhere on the canvas.
    const anchor = await button.boundingBox()
    const popup = await picker(page).boundingBox()
    expect(anchor).not.toBeNull()
    expect(popup).not.toBeNull()
    if (anchor === null || popup === null) return
    expect(popup.x).toBeLessThan(anchor.x + anchor.width + 40)
    expect(popup.y).toBeLessThan(anchor.y + anchor.height + 40)

    // The catalog is a read that may not have landed when the picker opens, so the row is waited
    // for rather than a keystroke sent at whatever is there.
    const found = blockOption(page, 'shell.run')
    await expect(found).toHaveCount(1)
    await found.click()
    await expect(page.locator('.react-flow__node')).toHaveCount(1)

    // And the keyboard alone opens it: the button beside the zoom takes the focus ring and answers Enter.
    await page.keyboard.press('Escape')
    await button.focus()
    await page.keyboard.press('Enter')
    await expect(picker(page)).toBeVisible()
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
    await page.getByRole('button', { name: LABELS.pipelines.new }).click()

    await expect(page).toHaveURL(/\/pipelines\/\$new$/)
    // The breadcrumb says what this is until it is something the instance holds.
    await expect(page.getByText(LABELS.editor.topbar.new_pipeline, { exact: true })).toBeVisible()
    await expect(page.getByText(LABELS.editor.version.none, { exact: true })).toBeVisible()

    // Validate works on the draft; Run does not, and says why rather than failing at the server.
    await expect(page.getByRole('button', { name: LABELS.action.validate })).toBeEnabled()
    const run = page.getByRole('button', { name: 'Run…', exact: true })
    await saysShut(page, run, /Apply this document/)

    // The panel opens on the step tab like any other document; the source, where the skeleton
    // and its code are written, is a tab away.
    const panel = page.locator('aside')
    await expect(panel.getByRole('tab', { name: LABELS.word.step.label })).toHaveAttribute(
        'aria-selected',
        'true',
    )
    // Nothing is applied, so there is no pipeline to read: that tab is not offered.
    await expect(panel.getByRole('tab', { name: LABELS.word.pipeline.label })).toHaveCount(0)
    await panel.getByRole('tab', { name: LABELS.word.source }).click()

    const editor = panel.locator('[data-slot="code-editor"]')
    await expect(editor.locator('.cm-content')).toContainText('my-pipeline')

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

    await page.getByRole('button', { name: LABELS.action.apply, exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText(/Apply creates/)).toBeVisible()
    await dialog.getByRole('button', { name: LABELS.action.apply, exact: true }).click()

    // The document has an address of its own now, at the version the apply wrote.
    await expect(page).toHaveURL(new RegExp(`/pipelines/${code}/edit$`))
    // The status line states the version the instance holds, once.
    await expect(page.locator('footer')).toContainText(LABELS.editor.version.short('1'))
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

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}/edit`)
    const apply = page.getByRole('button', { name: LABELS.action.apply, exact: true })
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

    await page.goto(`/pipelines/${DOCUMENT_PIPELINE}/edit`)
    await page.locator('.react-flow__node').getByText('parse', { exact: true }).click()

    const panel = page.locator('aside')
    await expect(panel.getByRole('tab', { name: 'Step · parse' })).toBeVisible()

    // Read something else in the panel, then choose another box: the click is the intent.
    await panel.getByRole('tab', { name: LABELS.word.pipeline.label }).click()
    await expect(panel.getByRole('tab', { name: LABELS.word.pipeline.label })).toHaveAttribute(
        'aria-selected',
        'true',
    )

    await canvasSettled(page)
    await page.locator('.react-flow__node').getByText('report', { exact: true }).click()
    await expect(panel.getByRole('tab', { name: 'Step · report' })).toHaveAttribute('aria-selected', 'true')
})

/**
 * A FIELD THAT NAMES A THING SHOWS THE THING.
 *
 * `validate.schema`'s `schema` and every block's `connection` hold a code, and a code in a one
 * line box says nothing about what it addresses. What these assert is the row under the box: what
 * answered the code, the definition it opens to, and the way out to that thing's own screen --
 * against a schema and a connection this run really put on the instance.
 *
 * AN APPLIED DOCUMENT NAMES NOTHING THE INSTANCE HAS NOT GOT: the server refuses one that does.
 * So the unheld code and the carried shape are read where they are reachable, which is a document
 * being edited.
 */
const REFERENCE_SCHEMA = 'e2e-ou-record'

const REFERENCE_SCHEMA_TITLE = 'Org unit record'

const REFERENCE_CONNECTION = 'e2e-reference-http'

/** A code the instance holds nothing under, which is what a row has to say so about. */
const UNHELD_SCHEMA = 'e2e-nothing-holds-this'

const NAMING_PIPELINE = 'names-things'

const NAMING = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: NAMING_PIPELINE,
    description: 'Two steps, each naming something this instance holds by code.',
    requires: { blocks: ['validate.schema', 'http.request'] },
    steps: {
        check: { block: 'validate.schema', config: { input: { id: 'OU1' }, schema: REFERENCE_SCHEMA } },
        call: { block: 'http.request', config: { connection: REFERENCE_CONNECTION, path: '/health' } },
    },
}

/** The document carrying its own shape, under the very code the instance holds one under. */
const CARRYING = [
    'format: dirigent/v1',
    'kind: pipeline',
    'code: carries-its-shape',
    'schemas:',
    `  ${REFERENCE_SCHEMA}:`,
    '    type: object',
    '    required: [carried_here]',
    '    properties:',
    '      carried_here: { type: string }',
    'steps:',
    '  check:',
    '    block: validate.schema',
    '    config:',
    '      input: { carried_here: a value }',
    `      schema: ${REFERENCE_SCHEMA}`,
    '',
].join('\n')

/** Put the schema and the connection these specs name onto the instance. */
async function seedNamed(request: APIRequestContext, baseURL: string): Promise<void> {
    const prefix = await apiPrefix(request)
    // A stored schema a pipeline names cannot be removed, so the dependants go with it.
    await removeSchema(request, REFERENCE_SCHEMA)
    const stored = await request.post(`${prefix}/schemas`, {
        data: {
            body: {
                $id: REFERENCE_SCHEMA,
                title: REFERENCE_SCHEMA_TITLE,
                type: 'object',
                required: ['id'],
                properties: { id: { type: 'string' } },
            },
        },
    })
    expect(stored.ok(), await stored.text()).toBe(true)
    await removeConnection(request, REFERENCE_CONNECTION)
    const minted = await request.post(`${prefix}/connections`, {
        data: {
            code: REFERENCE_CONNECTION,
            kind: 'http',
            config: { base_url: baseURL, health_path: '/health' },
        },
    })
    expect(minted.ok(), await minted.text()).toBe(true)
}

test('a field naming a schema the instance holds opens it, and links to its screen', async ({
    page,
    baseURL,
}) => {
    await signIn(page)
    await seedNamed(page.request, baseURL ?? '')
    await applyDocument(page.request, NAMING)

    await page.goto(`/pipelines/${NAMING_PIPELINE}/edit`)
    await page.locator('.react-flow__node').getByText('check', { exact: true }).click()

    const panel = page.locator('aside')
    // The box holds the code and the row under it says what answered it, headed by the schema's
    // own title so the code is not on screen twice.
    await expect(panel.getByLabel('schema', { exact: true })).toHaveValue(REFERENCE_SCHEMA)
    const row = panel.getByRole('button', { name: /instance/ })
    await expect(row).toContainText(REFERENCE_SCHEMA_TITLE)
    await expect(row).toContainText('instance')

    // IT OPENS UNDER ITSELF, on the schema itself.
    await row.click()
    await expect(panel.getByText('properties', { exact: false }).first()).toBeVisible()

    // AND THE THING HAS A SCREEN OF ITS OWN, at an address that can be sent.
    await panel.getByRole('link', { name: LABELS.editor.reference_row.open_schema }).click()
    await expect(page).toHaveURL(new RegExp(`/schemas/${REFERENCE_SCHEMA}$`))
    await expect(
        page.getByRole('main').locator('[data-slot="code-editor"]').first().locator('.cm-content'),
    ).toContainText('properties')
})

test('a field naming a connection reads its kind and where its last check left it', async ({
    page,
    baseURL,
}) => {
    await signIn(page)
    await seedNamed(page.request, baseURL ?? '')
    await applyDocument(page.request, NAMING)

    await page.goto(`/pipelines/${NAMING_PIPELINE}/edit`)
    await page.locator('.react-flow__node').getByText('call', { exact: true }).click()

    const panel = page.locator('aside')
    await expect(panel.getByLabel('connection', { exact: true })).toHaveValue(REFERENCE_CONNECTION)
    const row = panel.getByRole('button', { name: /never checked/ })
    await expect(row).toContainText('http')
    await expect(row).toContainText('never checked')
    // And it leads with the mark that kind wears everywhere else.
    await expect(row.locator('[data-slot="mark"]')).toHaveCount(1)

    // Open, and it says what the credential is pointed at, and where it is edited.
    await row.click()
    await expect(panel.getByText('base_url=', { exact: false })).toBeVisible()
    await panel.getByRole('link', { name: LABELS.editor.reference_row.open_connection }).click()
    await expect(page).toHaveURL(new RegExp(`/connections/${REFERENCE_CONNECTION}$`))
})

test('a code nothing holds says so, and is not something to press', async ({ page, baseURL }) => {
    await signIn(page)
    await seedNamed(page.request, baseURL ?? '')
    await applyDocument(page.request, NAMING)

    await page.goto(`/pipelines/${NAMING_PIPELINE}/edit`)
    await page.locator('.react-flow__node').getByText('check', { exact: true }).click()

    // The row follows the box: typing a code nothing holds is what makes it a missing one.
    const panel = page.locator('aside')
    await panel.getByLabel('schema', { exact: true }).fill(UNHELD_SCHEMA)

    await expect(panel.getByText(LABELS.editor.reference_row.not_stored, { exact: true })).toBeVisible()
    // NOTHING WEARS INTERACTIVE CHROME UNLESS IT DOES SOMETHING: there is nothing to open.
    await expect(panel.getByRole('button', { name: /not stored/ })).toHaveCount(0)
})

test('a schema the document carries answers the gate before anything the instance holds', async ({
    page,
    baseURL,
}) => {
    await signIn(page)
    await seedNamed(page.request, baseURL ?? '')

    await page.goto('/pipelines')
    await page.getByRole('button', { name: LABELS.pipelines.new }).click()
    const panel = page.locator('aside')
    await panel.getByRole('tab', { name: LABELS.word.source }).click()
    const editor = panel.locator('[data-slot="code-editor"]')
    await expect(editor.locator('.cm-content')).toContainText('my-pipeline')
    await writeInEditor(page, editor, CARRYING)

    await page.locator('.react-flow__node').getByText('check', { exact: true }).click()

    // The instance holds a schema under this very code, and the carried one is what would run.
    const row = panel.getByRole('button', { name: /carried by this document/ })
    await expect(row).toBeVisible()
    await expect(panel.getByText(REFERENCE_SCHEMA_TITLE)).toHaveCount(0)

    await row.click()
    await expect(panel.getByText('carried_here', { exact: false }).first()).toBeVisible()
})

/**
 * THE WAY OUT OF A MISSING CONNECTION DOES NOT COST THE DOCUMENT.
 *
 * A document carrying a `connections:` section is refused by the apply, and the row that says
 * this instance has not got the connection it names is where a credential is minted. That row
 * used to carry a link to the Connections screen, and a document nothing has applied is held
 * nowhere but this screen -- so taking the way forward threw away everything somebody had typed
 * and came back to an empty skeleton. The form opens under the row instead: nothing navigates,
 * the code and the kind the document declares are not asked for again, and the row turns
 * `already here` the moment the credential exists.
 *
 * WHAT IS ASSERTED IS THE DOCUMENT SURVIVING, not the gesture. The address never leaves
 * `/pipelines/$new` while the credential is minted, and the apply after it writes the steps that
 * were typed before it -- which is the whole of what the old door lost.
 */
const CARRIED_CONNECTION = 'e2e-minted-in-the-row'

const CARRYING_CONNECTION_PIPELINE = 'carries-a-connection'

/** The step this document declares, which is what has to still be there at the end. */
const CARRIED_STEP = 'call_out'

const CARRYING_CONNECTION = [
    'format: dirigent/v1',
    'kind: pipeline',
    `code: ${CARRYING_CONNECTION_PIPELINE}`,
    'connections:',
    `  ${CARRIED_CONNECTION}:`,
    '    kind: http',
    '    config:',
    '      base_url: http://127.0.0.1:1',
    'steps:',
    `  ${CARRIED_STEP}:`,
    '    block: http.request',
    '    config:',
    `      connection: ${CARRIED_CONNECTION}`,
    '      path: /health',
    '',
].join('\n')

test('a carried connection is minted in its own row, and the document is never left', async ({ page }) => {
    await signIn(page)
    const prefix = await apiPrefix(page.request)
    // Whatever an earlier run left behind: this spec is about a code the instance has not got.
    await page.request.delete(`${prefix}/pipelines/${CARRYING_CONNECTION_PIPELINE}`)
    await removeConnection(page.request, CARRIED_CONNECTION)

    await page.goto('/pipelines')
    await page.getByRole('button', { name: LABELS.pipelines.new }).click()
    await expect(page).toHaveURL(/\/pipelines\/\$new$/)

    const panel = page.locator('aside')
    await panel.getByRole('tab', { name: LABELS.word.source }).click()
    const editor = panel.locator('[data-slot="code-editor"]')
    await writeInEditor(page, editor, CARRYING_CONNECTION)
    await expect(page.locator('.react-flow__node').getByText(CARRIED_STEP, { exact: true })).toBeVisible()

    // The apply refuses a carried section, and the offer under the refusal is what answers it.
    await page.getByRole('button', { name: LABELS.action.apply, exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: LABELS.editor.apply.title })).toBeVisible()

    // THE ROW SAYS THE INSTANCE HAS NOT GOT IT, and the confirm is not drawn while that holds.
    const row = dialog.locator('li').filter({ hasText: CARRIED_CONNECTION })
    await expect(row).toContainText(LABELS.editor.carried.state.missing)
    await expect(dialog.getByText(LABELS.editor.carried.no_connection.one(CARRIED_CONNECTION))).toBeVisible()

    // THE FORM OPENS UNDER THE ROW. The code and the kind are the document's, so neither is
    // asked for again -- what the form asks for is the credential this instance will hold.
    await row.getByRole('button', { name: LABELS.editor.carried.create_row(CARRIED_CONNECTION) }).click()
    await expect(dialog.getByLabel('base_url', { exact: true })).toBeVisible()
    await expect(dialog.getByLabel(LABELS.word.code, { exact: true })).toHaveCount(0)
    await expect(dialog.getByLabel(LABELS.word.kind.label, { exact: true })).toHaveCount(0)

    await dialog.getByLabel('base_url', { exact: true }).fill('http://127.0.0.1:1')
    await row.getByRole('button', { name: LABELS.action.create.verb, exact: true }).click()

    // THE ROW ANSWERS ITSELF, and nothing said it twice: what was missing is now the
    // instance's own, which is what was in the way of the confirm being drawn at all.
    await expect(row).toContainText(LABELS.editor.carried.state.held)
    const confirm = dialog.getByRole('button', { name: LABELS.action.apply, exact: true })
    await expect(confirm).toBeVisible()

    // AND NOTHING NAVIGATED. The document is still the one that was typed, at the address it
    // was typed at -- which is exactly what the link out of this row used to cost.
    await expect(page).toHaveURL(/\/pipelines\/\$new$/)

    await confirm.click()
    // The first apply creates the pipeline and the screen goes to the address it answers at.
    await expect(page).toHaveURL(new RegExp(`/pipelines/${CARRYING_CONNECTION_PIPELINE}/edit$`))
    await expect(page.locator('.react-flow__node').getByText(CARRIED_STEP, { exact: true })).toBeVisible()

    // The document that was stored names the connection by code and carries no section of its own.
    const stored = await page.request.get(`${prefix}/pipelines/${CARRYING_CONNECTION_PIPELINE}`)
    expect(stored.ok(), await stored.text()).toBe(true)
    const detail = (await stored.json()) as { document: Record<string, unknown> }
    expect(detail.document.connections).toBeUndefined()
    expect(detail.document.requires).toEqual({ connections: [CARRIED_CONNECTION] })
})

/**
 * THE THIRD OPTION, WHICH THE BROWSER COULD NOT TAKE. A document carrying a shape under a code
 * the instance already holds a different shape under is a collision, and the two answers beside
 * it were both the document author's: change what the document carries, or carry it under
 * another code. The third is to update the stored schema, and it is the right one often enough
 * that leaving it out made this dialog a dead end.
 *
 * IT IS PRESSED IN THE ROW AND NOT BY THE APPLY. Applying stores what the document carries and
 * names the codes; replacing what another pipeline validates against is a second decision, so
 * the confirm is drawn only once the collision has gone -- and nothing navigates, for the same
 * reason the connection above opens where it does.
 */
test('a carried schema that collides with a stored one is updated in its own row', async ({
    page,
    baseURL,
}) => {
    await signIn(page)
    await seedNamed(page.request, baseURL ?? '')
    const prefix = await apiPrefix(page.request)
    await page.request.delete(`${prefix}/pipelines/carries-its-shape`)

    await page.goto('/pipelines')
    await page.getByRole('button', { name: LABELS.pipelines.new }).click()
    const panel = page.locator('aside')
    await panel.getByRole('tab', { name: LABELS.word.source }).click()
    await writeInEditor(page, panel.locator('[data-slot="code-editor"]'), CARRYING)

    await page.getByRole('button', { name: LABELS.action.apply, exact: true }).click()
    const dialog = page.getByRole('dialog')
    const row = dialog.locator('li').filter({ hasText: REFERENCE_SCHEMA })
    await expect(row).toContainText(LABELS.editor.carried.state.differs)

    // A CONFIRM IS DRAWN ONLY WHERE PRESSING IT WOULD DO SOMETHING: the collision shuts it, and
    // the sentence beside the rows says which code collided.
    await expect(dialog.getByRole('alert')).toContainText(REFERENCE_SCHEMA)
    await expect(dialog.getByRole('button', { name: LABELS.action.apply, exact: true })).toHaveCount(0)

    // THE DECISION OPENS UNDER THE ROW, over the shape the reader cannot otherwise see without
    // leaving a document nothing has applied.
    await row.getByRole('button', { name: LABELS.editor.carried.update_row(REFERENCE_SCHEMA) }).click()
    await expect(row.getByText(LABELS.editor.carried.held_heading)).toBeVisible()
    await expect(row.getByText(REFERENCE_SCHEMA_TITLE, { exact: false }).first()).toBeVisible()

    await row.getByRole('button', { name: LABELS.editor.carried.update_confirm }).click()

    // THE ROW IS THE REPORT: it turns `already here`, which is what was in the way of the
    // confirm being drawn at all.
    await expect(row).toContainText(LABELS.editor.carried.state.held)
    const confirm = dialog.getByRole('button', { name: LABELS.action.apply, exact: true })
    await expect(confirm).toBeVisible()
    await expect(page).toHaveURL(/\/pipelines\/\$new$/)

    await confirm.click()
    await expect(page).toHaveURL(/\/pipelines\/carries-its-shape\/edit$/)

    // The instance holds what the document carried, identity and all: a store reads a schema's
    // own title and this one declares none, so the name the seed gave it is cleared with it.
    const read = await (await page.request.get(`${prefix}/schemas/${REFERENCE_SCHEMA}`)).json()
    expect(read.body.required).toEqual(['carried_here'])
    expect(read.name).toBeNull()
})

/** A stored shape long enough to have put this row's own controls off the screen: 200+ lines. */
function longShape(): Record<string, unknown> {
    const properties: Record<string, unknown> = {}
    for (let at = 0; at < 68; at += 1) {
        properties[`field_${String(at).padStart(2, '0')}`] = {
            type: 'string',
            description: `What field ${String(at)} of the record carries.`,
        }
    }
    return {
        $id: REFERENCE_SCHEMA,
        title: REFERENCE_SCHEMA_TITLE,
        type: 'object',
        required: ['id'],
        properties,
    }
}

/**
 * A DECISION'S CONTROLS ARE NEVER THE PART THAT SCROLLS AWAY. The shape the instance holds is
 * reference material for the decision above it and has no length of its own, so drawn at its own
 * height it put this row's Cancel and confirm thousands of pixels below the foot of the dialog's
 * scroller: a reader had to go looking for the control the dialog was asking them to press. The
 * pane takes a pane's height instead and the window carries the whole shape.
 *
 * THE SHORT DESKTOP IS THE BINDING ONE, because the dialog's own cap leaves least room there --
 * a phone is narrower, which costs wrapped lines, but it is also taller.
 */
test("a long stored shape leaves the row's own controls on screen", async ({ page, baseURL }) => {
    await signIn(page)
    await seedNamed(page.request, baseURL ?? '')
    const prefix = await apiPrefix(page.request)
    const lengthened = await page.request.patch(`${prefix}/schemas/${REFERENCE_SCHEMA}`, {
        data: { body: longShape() },
    })
    expect(lengthened.ok(), await lengthened.text()).toBe(true)

    await page.goto('/pipelines')
    await page.getByRole('button', { name: LABELS.pipelines.new }).click()
    const panel = page.locator('aside')
    await panel.getByRole('tab', { name: LABELS.word.source }).click()
    await writeInEditor(page, panel.locator('[data-slot="code-editor"]'), CARRYING)

    await page.getByRole('button', { name: LABELS.action.apply, exact: true }).click()
    const dialog = page.getByRole('dialog')
    const row = dialog.locator('li').filter({ hasText: REFERENCE_SCHEMA })
    await expect(row).toContainText(LABELS.editor.carried.state.differs)
    await row.getByRole('button', { name: LABELS.editor.carried.update_row(REFERENCE_SCHEMA) }).click()
    await expect(row.getByRole('button', { name: LABELS.editor.carried.update_confirm })).toBeVisible()

    for (const size of [
        { width: 1024, height: 768 },
        { width: 390, height: 844 },
    ]) {
        await page.setViewportSize(size)
        const where = `${String(size.width)}x${String(size.height)}`
        for (const control of [LABELS.action.cancel, LABELS.editor.carried.update_confirm]) {
            // Polled rather than read once: a viewport that has just changed is a layout still
            // settling, and a measurement taken mid-reflow is a different layout's.
            await expect
                .poll(async () => belowTheFold(row, control), {
                    message: `${control} at ${where}`,
                    timeout: 10_000,
                })
                .toBeLessThanOrEqual(0)
        }
    }
})
