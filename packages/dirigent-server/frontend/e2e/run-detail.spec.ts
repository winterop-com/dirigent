import { expect, test, type APIRequestContext } from '@playwright/test'

import { LABELS } from '../src/lib/labels.ts'
import {
    applyDocument,
    applyExample,
    canvasSettled,
    dragBy,
    everyNodeIsInView,
    graphZoom,
    ranToCompletion,
    signIn,
    startRun,
} from './support.ts'

/**
 * The run detail screen, against a run this suite really started on a real `dg dev`.
 *
 * THE EXAMPLE IS CHOSEN FOR WHAT IT COSTS. `examples/transform/std-convert-fan-out.yaml` is
 * eight steps, one of them a fan-out over three regions, and every block in it is a transform,
 * a codec or a hop through the run's own scratch space: no network, no allowlisted block, and
 * the whole run settles in under a second. So this spec asserts on a settled run without
 * polling a remote or waiting on a sleep.
 *
 * ONE THING HERE NEEDS A RUN THAT LASTS. A graph redrawn while its stream is still delivering is
 * what `sleep-race` below is for: three waits and a step that joins them, written in this file
 * because no shipped example is both slow enough to watch and cheap enough to run.
 */

const EXAMPLE = 'examples/transform/std-convert-fan-out.yaml'
const PIPELINE = 'std-convert-fan-out'

/** Every step the example declares, which is what the graph has to draw. */
const STEPS = ['source', 'parse', 'rows', 'active', 'per_region', 'report', 'store', 'as_csv']

/** Apply the example and start a run of it, answering with the run's id. */
async function runOfTheExample(request: APIRequestContext): Promise<string> {
    await applyExample(request, EXAMPLE)
    return startRun(request, PIPELINE)
}

test('a run reads as its graph, its steps, and the state it settled in', async ({ page }) => {
    await signIn(page)
    const runId = await runOfTheExample(page.request)

    await page.goto(`/runs/${runId}`)

    // THE GRAPH. Every step of the pinned definition is a node, and the fan-out is one node
    // rather than one per region.
    for (const step of STEPS) {
        // Each assertion waits on the same canvas; running them together would race the retries.
        // oxlint-disable-next-line no-await-in-loop
        await expect(page.locator('.react-flow__node').getByText(step, { exact: true })).toBeVisible()
    }
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)

    // THE STATE IT SETTLED IN, on the chip in the topbar strip.
    await expect(page.locator('.status-chip[data-status="succeeded"]').first()).toBeVisible({
        timeout: 30_000,
    })
})

test('choosing a step on the graph opens it in the panel', async ({ page }) => {
    await signIn(page)
    const runId = await runOfTheExample(page.request)

    await page.goto(`/runs/${runId}`)
    await expect(page.locator('.react-flow__node').getByText('parse', { exact: true })).toBeVisible()

    await page.locator('.react-flow__node').getByText('parse', { exact: true }).click()

    const panel = page.locator('aside')
    await expect(panel.getByRole('tab', { name: LABELS.word.step })).toBeVisible()
    await expect(panel.getByRole('tab', { name: 'Run' })).toBeVisible()
    await expect(panel.getByRole('tab', { name: LABELS.word.output })).toBeVisible()
    // The step's own facts, which only the selected step has.
    await expect(panel.getByText('convert.std', { exact: true })).toBeVisible()
    await expect(panel.getByText('Attempts (1)')).toBeVisible()

    // What the step produced is on its tab, which is where somebody inspecting the data
    // flowing between nodes finds it.
    await expect(panel.getByRole('heading', { name: LABELS.word.output, exact: true })).toBeVisible()
    await expect(panel.locator('pre').filter({ hasText: '"target"' }).first()).toBeVisible()

    // An output opens in a window: the read-only editor, which is a chunk of its own and is
    // fetched when first asked for.
    await panel.getByLabel('Open parse · output in a window').click()
    const window = page.getByRole('dialog')
    await expect(window.locator('.monaco-editor')).toBeVisible({ timeout: 30_000 })
    await page.keyboard.press('Escape')
    await expect(window).toBeHidden()

    // The run tab is the same one stream read a different way, not a second read.
    await panel.getByRole('tab', { name: 'Run' }).click()
    await expect(panel.getByRole('link', { name: PIPELINE })).toBeVisible()
})

test('a run this instance does not have is refused in the server own words', async ({ page }) => {
    await signIn(page)
    await page.goto('/runs/00000000-0000-4000-8000-000000000000')
    await expect(page.getByText(/no run 00000000/)).toBeVisible()
})

test("a run's graph opens with every step in view, at a zoom that does not blow it up", async ({ page }) => {
    await signIn(page)
    const runId = await runOfTheExample(page.request)

    await page.goto(`/runs/${runId}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)
    await everyNodeIsInView(page)
    expect(await graphZoom(page)).toBeLessThanOrEqual(1.25)
})

test("a run's graph offers no port, and nothing on it can be dragged or connected", async ({ page }) => {
    // REVERT-PROOF: this canvas draws what already happened. A port here would offer to edit a
    // pinned definition, and there is no verb that would carry it out.
    await signIn(page)
    const runId = await runOfTheExample(page.request)

    await page.goto(`/runs/${runId}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)

    // The anchors an edge ends at are there, because React Flow routes to them and draws no
    // edge without one. Not one of them is a port: none is visible, and none is connectable.
    await expect(page.locator('.react-flow__handle')).not.toHaveCount(0)
    await expect(page.locator('.react-flow__handle.dg-port')).toHaveCount(0)
    await expect(page.locator('.react-flow__handle.connectable')).toHaveCount(0)
    await expect(page.locator('.react-flow__handle').first()).toBeHidden()
    await expect(page.locator('.react-flow__node.draggable')).toHaveCount(0)
})

/**
 * Three waits that start at once and one step that joins all three.
 *
 * `time.sleep` is a sensor, so the waits park rather than occupy a worker, and the run lasts
 * long enough for the screen to redraw itself several times over. The join is what gives the
 * graph its edges: three of them, into one node.
 */
const SLEEP_RACE = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: 'sleep-race',
    steps: {
        slow: { block: 'time.sleep', config: { for: '4s' } },
        middling: { block: 'time.sleep', config: { for: '2s' } },
        quick: { block: 'time.sleep', config: { for: '1s' } },
        report: {
            block: 'transform.jq',
            depends_on: ['slow', 'middling', 'quick'],
            config: { input: { done: true }, program: '.' },
        },
    },
}

/** The steps of `sleep-race`, in the order the document writes them. */
const RACE_STEPS = ['slow', 'middling', 'quick', 'report']

/** Start a run of the sleep race, which is still going when this returns. */
async function liveRace(page: Parameters<typeof signIn>[0]): Promise<string> {
    await applyDocument(page.request, SLEEP_RACE)
    return startRun(page.request, 'sleep-race')
}

/** The nodes on the canvas, in the order the canvas draws them. */
async function drawnOrder(page: Parameters<typeof signIn>[0]): Promise<string[]> {
    return page.evaluate(() =>
        [...document.querySelectorAll('.react-flow__node')].map((node) => node.getAttribute('data-id') ?? ''),
    )
}

test('a live run keeps every edge, however often the stream redraws it', async ({ page }) => {
    // REVERT-PROOF: the canvas rebuilds its node objects on every frame of the stream and every
    // second a retry counts down. React Flow drops the handle bounds of a node it has not seen
    // before unless the node states its own measurement, and it draws no edge to a node with no
    // bounds -- so a graph that does not say what size it was drawn at loses its edges, one
    // frame at a time, for as long as the run is going.
    await signIn(page)
    const runId = await liveRace(page)

    await page.goto(`/runs/${runId}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(RACE_STEPS.length)
    await expect(page.locator('.react-flow__edge')).toHaveCount(3)

    // Every animation frame until the run settles: an edge dropped and redrawn between two
    // assertions is still an edge that was not on the graph.
    const watch = await page.evaluate(async () => {
        const counts: number[] = []
        const started = performance.now()
        await new Promise<void>((resolve) => {
            const tick = () => {
                counts.push(document.querySelectorAll('.react-flow__edge').length)
                const settled = document.querySelector('.status-chip[data-status="running"]') === null
                const elapsed = performance.now() - started
                if (elapsed > 30_000 || (settled && elapsed > 2_000)) {
                    resolve()
                    return
                }
                requestAnimationFrame(tick)
            }
            requestAnimationFrame(tick)
        })
        return { frames: counts.length, edgeless: counts.filter((count) => count !== 3).length }
    })

    expect(watch.frames).toBeGreaterThan(60)
    expect(watch.edgeless, 'frames the graph was drawn without all three of its edges').toBe(0)
    await expect(page.locator('.status-chip[data-status="succeeded"]').first()).toBeVisible()
    await expect(page.locator('.react-flow__edge')).toHaveCount(3)
})

/**
 * A step that produces at once, feeding two that take their time.
 *
 * WHAT MOTION NEEDS IS A LIVE CONSUMER. The race above has three steps finishing into one that
 * settles instantly, so an edge carrying anything is on screen for a frame; here the source has
 * succeeded while both dependents are still running, which is the state an edge moves in.
 */
const LIVE_FLOW = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: 'live-flow',
    steps: {
        seed: { block: 'transform.jq', config: { input: { rows: [1, 2] }, program: '.' } },
        left: { block: 'time.sleep', depends_on: ['seed'], config: { for: '4s' } },
        right: { block: 'time.sleep', depends_on: ['seed'], config: { for: '4s' } },
    },
}

/** Start a run whose first step hands its output to two steps that are still reading it. */
async function liveFlow(page: Parameters<typeof signIn>[0]): Promise<string> {
    await applyDocument(page.request, LIVE_FLOW)
    return startRun(page.request, 'live-flow')
}

test('an edge moves while its downstream step is reading, and stills when the run settles', async ({
    page,
}) => {
    await signIn(page)
    const runId = await liveFlow(page)

    await page.goto(`/runs/${runId}`)
    await expect(page.locator('.react-flow__edge')).toHaveCount(2)

    // Both edges out of the step that has produced, into the two still reading it.
    await expect(page.locator('.react-flow__edge.dg-edge-flowing')).toHaveCount(2, { timeout: 30_000 })

    // A terminal run has no motion anywhere on it, and neither has one opened again.
    await expect(page.locator('.status-chip[data-status="succeeded"]').first()).toBeVisible({
        timeout: 30_000,
    })
    await expect(page.locator('.react-flow__edge.dg-edge-flowing')).toHaveCount(0)
    await expect(page.locator('.react-flow__edge.dg-edge-handover')).toHaveCount(0)
    await page.reload()
    await expect(page.locator('.react-flow__edge')).toHaveCount(2)
    await expect(page.locator('.react-flow__edge.dg-edge-flowing')).toHaveCount(0)
})

test('the header says the run is running while it still is, without a reload', async ({ page }) => {
    // WHAT THIS PINS. A run claimed between the page load and the first paint would show
    // `running` off the initial read alone, and racing the worker for that window is not a
    // test. So the one read the screen opens with is answered as `queued`, which is what a
    // page opened a moment earlier is really given: the chip can then only move because the
    // stream said the run started, which is the whole of what this asserts.
    await signIn(page)
    const runId = await liveFlow(page)
    await page.route(
        (url) => url.pathname === `/api/v1/runs/${runId}`,
        async (route) => {
            const response = await route.fetch()
            const detail = (await response.json()) as { run: Record<string, unknown> }
            await route.fulfill({
                response,
                json: { ...detail, run: { ...detail.run, status: 'queued', started_at: null } },
            })
        },
    )

    await page.goto(`/runs/${runId}`)

    // THE STREAM'S STATE, said in one word where somebody can read it off the screen. Here
    // rather than on the settled example above, because only a run that lasts has a live
    // moment to be read: that one is over before the graph it drew has finished drawing.
    await expect(page.getByText(LABELS.state.stream.live, { exact: true })).toBeVisible()

    const chip = page.locator('nav[aria-label="Breadcrumb"] + .status-chip')
    await expect(chip).toHaveAttribute('data-status', 'running', { timeout: 15_000 })
    await expect(chip).toHaveAttribute('data-status', 'succeeded', { timeout: 30_000 })
})

test('an edge is lit rather than moving for somebody who asked for less motion', async ({ page }) => {
    await signIn(page)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    const runId = await liveFlow(page)

    await page.goto(`/runs/${runId}`)
    await expect(page.locator('.react-flow__edge.dg-edge-lit')).toHaveCount(2, { timeout: 30_000 })
    await expect(page.locator('.react-flow__edge.dg-edge-flowing')).toHaveCount(0)
})

test('a graph is laid out in the order its steps were written, in flight and once settled', async ({
    page,
}) => {
    // A run read while it is going and the same run read again are one shape, and elk is told to
    // respect the order it is given -- so an order that depended on which step started first
    // would move every box the moment the page was opened again.
    await signIn(page)
    const runId = await liveRace(page)

    await page.goto(`/runs/${runId}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(RACE_STEPS.length)
    expect(await drawnOrder(page)).toEqual(RACE_STEPS)

    await expect(page.locator('.status-chip[data-status="succeeded"]').first()).toBeVisible({
        timeout: 30_000,
    })
    await page.reload()
    await expect(page.locator('.react-flow__node')).toHaveCount(RACE_STEPS.length)
    expect(await drawnOrder(page)).toEqual(RACE_STEPS)
})

/** Three steps in a row, whose last box is the one an opening right panel would cover. */
const IN_A_ROW = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: 'three-in-a-row',
    steps: {
        first: { block: 'transform.jq', config: { input: { at: 1 }, program: '.' } },
        second: { block: 'transform.jq', depends_on: ['first'], config: { input: { at: 2 }, program: '.' } },
        third: { block: 'transform.jq', depends_on: ['second'], config: { input: { at: 3 }, program: '.' } },
    },
}

/** Whether a node's whole box lies inside the canvas. */
async function nodeInView(page: Parameters<typeof signIn>[0], id: string): Promise<boolean> {
    return page.evaluate((step) => {
        const pane = document.querySelector('.react-flow')
        const node = document.querySelector(`.react-flow__node[data-id="${step}"]`)
        if (pane === null || node === null) return false
        const canvas = pane.getBoundingClientRect()
        const box = node.getBoundingClientRect()
        return (
            box.left >= canvas.left - 1 &&
            box.right <= canvas.right + 1 &&
            box.top >= canvas.top - 1 &&
            box.bottom <= canvas.bottom + 1
        )
    }, id)
}

test('choosing the last step keeps it on the canvas the opening panel narrows', async ({ page }) => {
    // REVERT-PROOF: a box on the run's graph cannot be dragged, so pressing one starts a pan that
    // goes nowhere -- and a canvas that counted that as the reader taking the view over stopped
    // re-fitting just as the panel it opened took the right of the canvas, over the chosen step.
    await signIn(page)
    await applyDocument(page.request, IN_A_ROW)
    const runId = await startRun(page.request, 'three-in-a-row')

    await page.goto(`/runs/${runId}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(3)
    // The panel is shut, which is what a first visit opens with, so the fit had the whole width.
    await expect(page.locator('aside[inert]')).toHaveCount(1)
    await everyNodeIsInView(page)
    await canvasSettled(page)

    await page.locator('.react-flow__node[data-id="third"]').click()
    await expect(page.locator('aside[inert]')).toHaveCount(0)
    await canvasSettled(page)
    await expect.poll(async () => nodeInView(page, 'third')).toBe(true)
    await everyNodeIsInView(page)
})

test('a view the reader moved is kept when the panel opens, with the chosen step brought onto it', async ({
    page,
}) => {
    await signIn(page)
    await applyDocument(page.request, IN_A_ROW)
    const runId = await startRun(page.request, 'three-in-a-row')

    await page.goto(`/runs/${runId}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(3)
    await everyNodeIsInView(page)
    await canvasSettled(page)

    // A pan to the right, which leaves the last box nearer the edge the panel opens over.
    await dragBy(page, page.locator('.react-flow__node[data-id="second"]'), 120, 0)
    await canvasSettled(page)
    const zoom = await graphZoom(page)

    await expect(page.locator('aside[inert]')).toHaveCount(1)
    await page.locator('.react-flow__node[data-id="third"]').click()
    await expect(page.locator('aside[inert]')).toHaveCount(0)
    await canvasSettled(page)
    await expect.poll(async () => nodeInView(page, 'third')).toBe(true)
    expect(await graphZoom(page), 'a moved view is not re-fitted').toBe(zoom)
})

/**
 * Two steps whose outputs are wide: one value on a single long line, and a list of long lines
 * tall enough that its box scrolls.
 */
const WIDE_OUTPUTS = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: 'wide-outputs',
    steps: {
        one: { block: 'transform.jq', config: { input: { line: 'x'.repeat(240) }, program: '.line' } },
        many: {
            block: 'transform.jq',
            config: {
                input: { lines: Array.from({ length: 30 }, (_, at) => `${String(at)} ${'y'.repeat(240)}`) },
                program: '.lines',
            },
        },
    },
}

/**
 * How many pieces of the text in a step's output box lie under its window button.
 *
 * Only the part of each line inside the box's scrolled view counts, which is what is drawn.
 */
async function textUnderTheButton(page: Parameters<typeof signIn>[0], step: string): Promise<number> {
    const panel = page.locator('aside')
    const button = panel.getByLabel(`Open ${step} · output in a window`)
    await expect(button).toBeVisible()
    const at = await button.boundingBox()
    if (at === null) throw new Error('the window button has no box')
    return panel
        .locator('pre')
        .first()
        .evaluate((element, b) => {
            const outer = element.getBoundingClientRect()
            const left = outer.left + element.clientLeft
            const top = outer.top + element.clientTop
            const right = left + element.clientWidth
            const bottom = top + element.clientHeight
            const range = document.createRange()
            range.selectNodeContents(element)
            return [...range.getClientRects()].filter((line) => {
                const l = Math.max(line.left, left)
                const r = Math.min(line.right, right)
                const t = Math.max(line.top, top)
                const u = Math.min(line.bottom, bottom)
                if (l >= r || t >= u) return false
                return l < b.x + b.width && r > b.x && t < b.y + b.height && u > b.y
            }).length
        }, at)
}

test("a step output's window button covers none of its text, however long its lines", async ({ page }) => {
    // REVERT-PROOF: the button sat over the foot of the box, and the strip kept clear for it was
    // padding at the end of the text -- so a box scrolled anywhere short of its end drew its
    // bottom line's tail under the button.
    await signIn(page)
    await applyDocument(page.request, WIDE_OUTPUTS)
    const runId = await startRun(page.request, 'wide-outputs')

    await page.goto(`/runs/${runId}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(2)
    await expect(page.locator('.status-chip[data-status="succeeded"]').first()).toBeVisible({
        timeout: 30_000,
    })

    for (const step of ['one', 'many']) {
        // Each step replaces what the one before it put in the panel.
        // oxlint-disable-next-line no-await-in-loop
        await page.locator(`.react-flow__node[data-id="${step}"]`).click()
        // oxlint-disable-next-line no-await-in-loop
        expect(await textUnderTheButton(page, step), `${step}: text under the button`).toBe(0)
    }
})

test('a live wait draws how far it has come as a line on its node and under its attempt', async ({
    page,
}) => {
    // REVERT-PROOF: `playground.arrive` reports a fraction on every poke. Without the foot line
    // there is no progressbar on the node or in the attempt row; a line that took room in the
    // box would make it taller than the height elk was given and than its sibling.
    await signIn(page)
    await applyExample(page.request, 'examples/playground/waiting-for-a-batch.yaml')
    // Twelve pokes at the example's one-second poll: long enough to read the line twice.
    const runId = await startRun(page.request, 'waiting-for-a-batch', { after_pokes: 12 })

    await page.goto(`/runs/${runId}`)
    const waiting = page.locator('.react-flow__node[data-id="wait_for_batch"]')
    const line = waiting.getByRole('progressbar')
    await expect(line).toBeVisible({ timeout: 15_000 })
    await expect(line).toHaveAttribute('aria-valuemin', '0')
    await expect(line).toHaveAttribute('aria-valuemax', '100')
    await expect(waiting.locator('.step-node')).toHaveAttribute('title', /\(\d+%\)$/)

    // The line lies inside the box, so the waiting node is the height its sibling is.
    const heights = await page.evaluate(() =>
        [...document.querySelectorAll<HTMLElement>('.react-flow__node .step-node')].map(
            (node) => node.offsetHeight,
        ),
    )
    expect(heights).toHaveLength(2)
    expect(heights[0]).toBe(heights[1])

    const first = Number(await line.getAttribute('aria-valuenow'))
    await expect
        .poll(async () => Number(await line.getAttribute('aria-valuenow')), { timeout: 10_000 })
        .toBeGreaterThan(first)

    await waiting.click()
    await expect(page.locator('aside').getByRole('progressbar')).toBeVisible()

    // A settled wait draws no line, on the node or in its row.
    await ranToCompletion(page.request, runId)
    await expect(page.getByRole('progressbar')).toHaveCount(0)
})

/**
 * A list that takes its time, and a fan-out over what it listed.
 *
 * THE GRID IS WRITTEN WHILE THE PAGE IS OPEN. `each` reads `list`'s output, so the run is created
 * with one pending gate in its place and the items arrive on the stream once `list` succeeds --
 * the only fan-out whose width a person can watch appear.
 */
const LISTED_LATER = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: 'listed-later',
    steps: {
        list: { block: 'playground.generate', config: { rows: 3, seed: 7, delay: '3s' } },
        each: {
            block: 'playground.generate',
            depends_on: ['list'],
            for_each: '${steps.list.output.records}',
            config: { input: '${item}' },
        },
    },
}

test('a fan-out over a step output waits for it, then draws its items as they arrive', async ({ page }) => {
    await signIn(page)
    await applyDocument(page.request, LISTED_LATER)
    const runId = await startRun(page.request, 'listed-later')

    await page.goto(`/runs/${runId}`)
    const each = page.locator('.react-flow__node[data-id="each"]')
    await expect(each.getByText('waits for list', { exact: true })).toBeVisible()
    const waiting = await each.boundingBox()

    await expect(each.getByText('3 items', { exact: true })).toBeVisible({ timeout: 30_000 })
    await expect(each.getByText('waits for list', { exact: true })).toHaveCount(0)
    await expect(page.locator('.status-chip[data-status="succeeded"]').first()).toBeVisible({
        timeout: 30_000,
    })
    await expect(each.locator('.step-node')).toHaveAttribute('data-outcome', 'succeeded')
    const expanded = await each.boundingBox()
    expect(expanded?.height, 'the box keeps its height when the grid expands into it').toBe(waiting?.height)
})
