import { expect, test, type APIRequestContext } from '@playwright/test'

import { applyDocument, applyExample, everyNodeIsInView, graphZoom, signIn, startRun } from './support.ts'

/**
 * The run detail screen, against a run this suite really started on a real `dg dev`.
 *
 * THE EXAMPLE IS CHOSEN FOR WHAT IT COSTS. `examples/transform/std-convert-fan-out.yaml` is
 * five steps, one of them a fan-out over three regions, and every block in it is a pure
 * transform: no network, no allowlisted block, and the whole run settles in under a second. So
 * this spec asserts on a settled run without polling a remote or waiting on a sleep.
 *
 * ONE THING HERE NEEDS A RUN THAT LASTS. A graph redrawn while its stream is still delivering is
 * what `sleep-race` below is for: three waits and a step that joins them, written in this file
 * because no shipped example is both slow enough to watch and cheap enough to run.
 */

const EXAMPLE = 'examples/transform/std-convert-fan-out.yaml'
const PIPELINE = 'std-convert-fan-out'

/** Every step the example declares, which is what the graph has to draw. */
const STEPS = ['parse', 'active', 'per_region', 'report', 'as_csv']

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
    await expect(panel.getByRole('tab', { name: 'Step' })).toBeVisible()
    await expect(panel.getByRole('tab', { name: 'Run' })).toBeVisible()
    await expect(panel.getByRole('tab', { name: 'Output' })).toBeVisible()
    // The step's own facts, which only the selected step has.
    await expect(panel.getByText('convert.std', { exact: true })).toBeVisible()
    await expect(panel.getByText('Attempts (1)')).toBeVisible()

    // What the step produced is on its tab, which is where somebody inspecting the data
    // flowing between nodes finds it.
    await expect(panel.getByRole('heading', { name: 'Output', exact: true })).toBeVisible()
    await expect(panel.locator('pre').filter({ hasText: '"text"' }).first()).toBeVisible()

    // A large output opens in a window: the read-only editor, which is a chunk of its own
    // and is fetched when first asked for.
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
    await expect(page.getByText('live', { exact: true })).toBeVisible()

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
