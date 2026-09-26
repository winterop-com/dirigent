import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

import { DOCS_SHOTS_WIDTH } from '../docs-shots.config.ts'

/** Where the nine pictures land. Committed, because docs/screens.md renders them. */
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..', 'docs/images/screens')

const DEV_USERNAME = 'dev'
const DEV_PASSWORD = 'dirigent-dev'

/** The showcase documents the seeded instance already holds, which every picture is of. */
const BIG = 'nightly-regional-load'
const DEGRADED = 'one-region-refuses'
const BRIEFING = 'morning-briefing'

/** How long each region's export takes on the run photographed mid-flight, a humane duration. */
const PACE = '10s'

/** The step that picture is of: the readiness probe, one per submitted export. */
const WATCHED = 'await'

/**
 * The grid that run fans out over: wider than the worker has slots, so half of it is in
 * progress while the other half waits its turn, which is what a fan-out looks like from the
 * inside and what the picture is there to show.
 */
const WIDE = [
    'east',
    'west',
    'north',
    'south',
    'central',
    'coastal',
    'highland',
    'lakeside',
    'delta',
    'plateau',
    'riverine',
    'savannah',
    'lowland',
    'upland',
    'island',
    'frontier',
]

/**
 * The tag the pipelines picture is filtered to.
 *
 * THE UNFILTERED LISTING IS THE WRONG PICTURE. It sorts by name, so the first screen of a
 * hundred and sixty documents is whatever begins with A, every row reads "never run", and the
 * screen looks like a directory rather than like somewhere work happens. `fan-out` is a tag
 * the three showcase documents share with ten patterns, so filtering to it is one screen of
 * rows that are all about the same thing, carry the vocabulary in their tags column, and --
 * once the cast below has run -- have real last runs with a failure among them.
 */
const TAG = 'fan-out'

/**
 * The documents run so the filtered listing has history in it, all of them already on the
 * instance and all of them cheap: inline data, Postman Echo, or the run's own scratch space.
 * Two settle badly on purpose, which is the point of showing them.
 *
 * `pipeline-run-with-params` wears the tag and is deliberately not here: it starts child runs,
 * and a child's trigger cell carries the parent run's uuid, which widens the runs listing past
 * the frame. The assertion below refuses that picture, so the cast leaves it out rather than
 * the picture leaving out a scrollbar.
 */
const CAST: { pipeline: string; body?: Record<string, unknown>; ends: string }[] = [
    { pipeline: 'fan-out-literal-list', ends: 'succeeded' },
    { pipeline: 'fan-out-from-params', ends: 'succeeded' },
    { pipeline: 'fan-out-then-join', ends: 'succeeded' },
    { pipeline: 'fan-out-item-wise', ends: 'succeeded' },
    { pipeline: 'fan-out-nested-objects', ends: 'succeeded' },
    // run.window.* is a property of the run, so this one is refused without an interval.
    {
        pipeline: 'references-cheat-sheet',
        body: { window_start: '2026-06-01T00:00:00Z', window_end: '2026-06-02T00:00:00Z' },
        ends: 'succeeded',
    },
    { pipeline: 'fan-out-continue', ends: 'completed_with_errors' },
    { pipeline: 'fan-out-fail-fast', ends: 'failed' },
]

/** The rule the alerting picture is of, declared here because a fresh instance has none. */
const RULE = {
    code: 'nightly-page-ops',
    name: 'Page whoever is on for the night',
    description: 'Every run that ends short, through the process log.',
    event: 'run_completed_with_errors',
    scope: 'global',
    throttle: '15m',
}

async function apiPrefix(request: APIRequestContext): Promise<string> {
    const config = (await (await request.get('/config.json')).json()) as { api_prefix: string }
    return config.api_prefix
}

async function signIn(page: Page): Promise<void> {
    await page.goto('/login')
    await page.getByLabel('Username').fill(DEV_USERNAME)
    await page.getByLabel('Password', { exact: true }).fill(DEV_PASSWORD)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await page.waitForURL((url) => url.pathname === '/')
}

/**
 * Refuse a picture that is wider than the frame.
 *
 * A screenshot of a screen with a sideways scrollbar is a screenshot of half a table, and a
 * reader of the page has no way to scroll it. Two measurements say it: the document itself,
 * which must fit the viewport, and every listing's own scroll box, whose content must fit the
 * box it is drawn in.
 */
async function nothingScrollsSideways(page: Page, name: string): Promise<void> {
    const measured = await page.evaluate(() => ({
        document: document.documentElement.scrollWidth,
        lists: [...document.querySelectorAll('.list-scroll')].map((box) => ({
            scroll: box.scrollWidth,
            client: box.clientWidth,
        })),
    }))
    expect(measured.document, `${name} is ${String(measured.document)}px wide`).toBeLessThanOrEqual(
        DOCS_SHOTS_WIDTH,
    )
    for (const [index, list] of measured.lists.entries()) {
        expect(list.scroll, `${name}: listing ${String(index)} overflows its box`).toBe(list.client)
    }
}

/**
 * Wait until the screen has stopped changing under the camera.
 *
 * The corner identity fills over its reads after every full load, so a shot taken while it is
 * asking would put the wrong topbar in the frame.
 */
async function readyForShot(page: Page, name: string): Promise<void> {
    await page
        .waitForFunction(
            () => /\d+\.\d+\.\d+/.test(document.querySelector('header')?.textContent ?? ''),
            undefined,
            { timeout: 15_000 },
        )
        .catch(() => undefined)
    await page.waitForTimeout(900)
    await nothingScrollsSideways(page, name)
}

/** Write one picture. Separate from the wait, so a timed shot can check its subject last. */
async function capture(page: Page, name: string): Promise<void> {
    await page.screenshot({ path: path.join(OUT, `${name}.png`) })
}

async function shot(page: Page, name: string): Promise<void> {
    await readyForShot(page, name)
    await capture(page, name)
}

/** Start a run, answering with its id. The body is the run request, params and all. */
async function startRun(
    request: APIRequestContext,
    pipeline: string,
    body: Record<string, unknown> = {},
): Promise<string> {
    const prefix = await apiPrefix(request)
    const started = await request.post(`${prefix}/pipelines/${pipeline}/$run`, { data: body })
    expect(started.ok(), await started.text()).toBe(true)
    const accepted = (await started.json()) as { run_id: string | null }
    expect(accepted.run_id, `${pipeline} was not accepted`).not.toBeNull()
    return accepted.run_id as string
}

/** What status a run is in right now. */
async function statusOf(request: APIRequestContext, runId: string): Promise<string> {
    const prefix = await apiPrefix(request)
    const detail = (await (await request.get(`${prefix}/runs/${runId}`)).json()) as {
        run: { status: string }
    }
    return detail.run.status
}

/** What one step of a run is doing right now, as the graph reports it. */
async function stepOutcome(request: APIRequestContext, runId: string, step: string): Promise<string | null> {
    const prefix = await apiPrefix(request)
    const detail = (await (await request.get(`${prefix}/runs/${runId}`)).json()) as {
        dag: { nodes: { code: string; outcome: string }[] }
    }
    return detail.dag.nodes.find((node) => node.code === step)?.outcome ?? null
}

/** Wait for a run to stop moving, and answer with where it stopped. */
async function settled(request: APIRequestContext, runId: string): Promise<string> {
    let status = 'pending'
    await expect
        .poll(
            async () => {
                status = await statusOf(request, runId)
                return ['running', 'queued', 'pending'].includes(status) ? 'moving' : 'settled'
            },
            { timeout: 180_000, intervals: [1000] },
        )
        .toBe('settled')
    return status
}

/** Put the one alert rule the alerting picture needs on the instance, whatever was there. */
async function declareRule(request: APIRequestContext): Promise<void> {
    const prefix = await apiPrefix(request)
    await request.delete(`${prefix}/alert-rules/${RULE.code}`)
    const created = await request.post(`${prefix}/alert-rules`, { data: RULE })
    expect(created.ok(), await created.text()).toBe(true)
}

/**
 * Wait until the seeding has stopped putting things into the instance.
 *
 * The seed applies a hundred and sixty documents and starts six runs while this camera would
 * otherwise already be shooting, and a page built on a half-seeded instance shows neither the
 * corpus nor the failures.
 */
async function seedingSettled(page: Page): Promise<void> {
    let stored = 0
    let quiet = 0
    for (let waited = 0; waited < 240_000 && quiet < 3; waited += 1500) {
        const pipelines = (await (await page.request.get('/api/v1/pipelines?limit=1')).json()) as {
            total?: number
            items: unknown[]
        }
        const runs = (await (await page.request.get('/api/v1/runs?limit=50')).json()) as {
            items: { status: string }[]
        }
        const moving = runs.items.some((run) => ['running', 'queued', 'pending'].includes(run.status))
        const count = pipelines.total ?? pipelines.items.length
        quiet = !moving && runs.items.length > 0 && count === stored && count > 0 ? quiet + 1 : 0
        stored = count
        await page.waitForTimeout(1500)
    }
}

test('the nine pictures docs/screens.md is built out of', async ({ page }) => {
    test.setTimeout(900_000)
    mkdirSync(OUT, { recursive: true })

    await signIn(page)
    await seedingSettled(page)

    // Dark, and the dirigent palette: the page is one palette throughout, and the contrast and
    // paper palettes are somebody's accessibility choice rather than the product's face.
    await page.evaluate(() => {
        localStorage.setItem('theme', 'dark')
        localStorage.setItem('dirigent.palette', 'dirigent')
        // The drawer remembers being open, and a console under the graph is not what the run
        // pictures are of.
        localStorage.setItem('dirigent.terminalOpen', 'false')
    })

    await declareRule(page.request)

    // THE CAST FIRST, THE SHOWCASE LAST, so the newest runs in every listing are the ones this
    // page is about. They are started together -- the worker has eight slots and these are a
    // second's work each -- and waited on afterwards.
    const cast = await Promise.all(
        CAST.map(async (wanted) => ({
            wanted,
            id: await startRun(page.request, wanted.pipeline, wanted.body ?? {}),
        })),
    )
    for (const { wanted, id } of cast) {
        expect(await settled(page.request, id), `${wanted.pipeline} settled elsewhere`).toBe(wanted.ends)
    }

    // A day of history for the dashboard to draw, out of the shelf the page is about.
    const degraded = await startRun(page.request, DEGRADED)
    const briefing = await startRun(page.request, BRIEFING)
    const nightly = await startRun(page.request, BIG)
    expect(await settled(page.request, degraded)).toBe('completed_with_errors')
    expect(await settled(page.request, briefing)).toBe('succeeded')
    expect(await settled(page.request, nightly)).toBe('succeeded')

    await page.goto('/')
    await shot(page, 'dashboard')

    // The listing filtered to one tag, which is what the screen is for and what makes every
    // visible row carry a run rather than the word "never".
    await page.goto(`/pipelines?tag=${TAG}`)
    await page.getByRole('heading', { name: 'Pipelines' }).waitFor({ timeout: 30_000 })
    await page.getByRole('row').filter({ hasText: BIG }).waitFor({ timeout: 30_000 })
    await shot(page, 'pipelines')

    // THE EDITOR, with a step open: the panel is half the screen, and a bare canvas is half a
    // picture. `submit` is the step worth opening -- it is the fanned one, and its config
    // carries the item policy and the retry budget.
    await page.goto(`/pipelines/${BIG}`)
    await page.locator('.react-flow__node').getByText('submit', { exact: true }).click()
    await page.locator('aside').getByRole('heading', { name: 'Config' }).waitFor({ timeout: 30_000 })
    await shot(page, 'editor')

    // THE RUN THAT ENDED SHORT, on its report: the page the engine wrote when the run settled.
    await page.goto(`/runs/${degraded}`)
    await page.locator('.react-flow__node').first().waitFor({ timeout: 30_000 })
    await page.getByRole('tab', { name: 'Report' }).click()
    await page.waitForTimeout(1200)
    await shot(page, 'run-failed')

    await page.goto('/runs')
    await page.getByRole('heading', { name: 'Runs' }).waitFor({ timeout: 30_000 })
    await shot(page, 'runs')

    await page.goto('/connections')
    await page.getByRole('heading', { name: 'Connections' }).waitFor({ timeout: 30_000 })
    await shot(page, 'connections')

    await page.goto('/admin/alerting')
    await page.getByRole('heading', { name: 'Alerting' }).waitFor({ timeout: 30_000 })
    await page.getByText(RULE.code, { exact: true }).first().waitFor({ timeout: 30_000 })
    await shot(page, 'alerting')

    await page.goto('/blocks')
    await page.getByRole('heading', { name: 'Blocks' }).waitFor({ timeout: 30_000 })
    await shot(page, 'blocks')

    // THE RUN IN FLIGHT, LAST, because it is the only picture with a clock on it. Each region's
    // readiness probe answers after PACE, so the screen is navigated to before the run
    // reaches the sensor and the camera waits there rather than spending the window arriving.
    await midFlight(page)
})

/**
 * Photograph a run while its fan-out is still in the air.
 *
 * THE WINDOW IS THE PACE THE PROBES ARE GIVEN, so nothing here navigates inside it: the run is
 * started, the screen is opened on it at once, and the camera waits there for the sensor to go
 * into progress. Sixteen regions against a worker with eight slots is what makes the window
 * wide enough to work in, and what puts half a grid in progress and half of it waiting.
 *
 * THE SUBJECT IS CHECKED LAST, immediately before the shutter, because a run that settled while
 * the screen was being waited on is a failed attempt rather than a picture. Then it is started
 * again.
 */
async function midFlight(page: Page): Promise<void> {
    for (let attempt = 1; attempt <= 3; attempt += 1) {
        const runId = await startRun(page.request, BIG, { params: { pace: PACE, regions: WIDE } })
        await page.goto(`/runs/${runId}`)
        await page.locator('.react-flow__node').first().waitFor({ timeout: 60_000 })

        let caught = false
        for (let waited = 0; waited < 120_000 && !caught; waited += 400) {
            const outcome = await stepOutcome(page.request, runId, WATCHED)
            caught = outcome === 'running'
            if (!caught && outcome !== null && !['pending', 'queued'].includes(outcome)) break
            if (!caught) await page.waitForTimeout(400)
        }
        if (!caught) continue

        // The sensor's own items are what the picture is of, so the step is opened on them.
        await page.locator('.react-flow__node').getByText(WATCHED, { exact: true }).click()
        await page.getByRole('tab', { name: 'Step', exact: true }).waitFor({ timeout: 15_000 })
        await readyForShot(page, 'run-in-flight')
        if ((await stepOutcome(page.request, runId, WATCHED)) !== 'running') continue

        await capture(page, 'run-in-flight')
        return
    }
    throw new Error('three runs settled before the camera caught one in flight')
}
