import { expect, test, type Page } from '@playwright/test'

import { WHEEL_ZOOM_LIMIT } from '../src/lib/dag-layout.ts'

import { LABELS } from '../src/lib/labels.ts'
import {
    applyDocument,
    canvasSettled,
    everyNodeIsInView,
    ranToCompletion,
    signIn,
    startRun,
} from './support.ts'

/**
 * A graph on a page, read the way somebody reads the run of a wide pipeline: every step code
 * whole, the chosen step in the address, the layout changeable for the visit, a canvas that fills
 * the run screen and zooms on its wheel, and a pipeline page whose wheel scrolls and whose pinch
 * zooms.
 *
 * THE SHAPE IS A FAN-IN WITH LONG CODES: a chain of three, three fan-outs and two plain steps
 * all into `health`, and one more after it. Every block is `transform.jq`, so it settles at once.
 */

const PIPELINE = 'e2e-graph-fan-in'

const STEPS = [
    'levels',
    'level_filters',
    'org_units_by_level',
    'system_info',
    'counts',
    'data_elements_by_domain',
    'jobs',
    'health',
    'publish_health_summary',
]

function fanIn(): Record<string, unknown> {
    const jq = (extra: Record<string, unknown> = {}) => ({
        block: 'transform.jq',
        config: { input: '${item}', program: '.' },
        ...extra,
    })
    return {
        format: 'dirigent/v1',
        code: PIPELINE,
        steps: {
            levels: { block: 'transform.jq', config: { input: [1, 2, 3], program: '.' } },
            level_filters: {
                block: 'transform.jq',
                depends_on: ['levels'],
                config: { input: 1, program: '.' },
            },
            org_units_by_level: jq({
                depends_on: ['levels', 'level_filters'],
                for_each: ['national', 'district'],
            }),
            system_info: { block: 'transform.jq', config: { input: 1, program: '.' } },
            counts: jq({
                for_each: [
                    'organisationUnits',
                    'dataElements',
                    'indicators',
                    'programs',
                    'dataSets',
                    'categoryOptions',
                ],
            }),
            data_elements_by_domain: jq({ for_each: ['aggregate', 'tracker'] }),
            jobs: { block: 'transform.jq', config: { input: 1, program: '.' } },
            health: {
                block: 'transform.jq',
                depends_on: [
                    'org_units_by_level',
                    'system_info',
                    'counts',
                    'data_elements_by_domain',
                    'jobs',
                ],
                config: { input: 1, program: '.' },
            },
            publish_health_summary: {
                block: 'transform.jq',
                depends_on: ['health'],
                config: { input: 1, program: '.' },
            },
        },
    }
}

/** A settled run of the fan-in, answering with its id. */
async function settledRun(page: Page): Promise<string> {
    await applyDocument(page.request, fanIn())
    const run = await startRun(page.request, PIPELINE)
    await ranToCompletion(page.request, run)
    return run
}

/** The pan and zoom the page's canvas is drawn at. */
async function transformOf(page: Page): Promise<string> {
    return page.evaluate(() => {
        const viewport = document.querySelector('.react-flow__viewport')
        return viewport instanceof HTMLElement ? viewport.style.transform : ''
    })
}

/** The pan and zoom in a transform React Flow wrote. */
function viewOf(transform: string): { x: number; y: number; zoom: number } {
    const match = /translate\((-?[\d.]+)px,\s*(-?[\d.]+)px\)\s*scale\(([\d.]+)\)/.exec(transform)
    if (match === null) throw new Error(`no view in ${transform}`)
    return { x: Number(match[1]), y: Number(match[2]), zoom: Number(match[3]) }
}

/** How far the page has scrolled. */
async function pageScroll(page: Page): Promise<number> {
    return page.evaluate(() => document.querySelector('[data-page-scroller]')?.scrollTop ?? 0)
}

/** Where each box stands on the page, by its step. */
async function boxes(page: Page): Promise<Record<string, { x: number; y: number }>> {
    return page.evaluate(() =>
        Object.fromEntries(
            [...document.querySelectorAll('.react-flow__node')].map((node) => {
                const box = node.getBoundingClientRect()
                return [node.getAttribute('data-id') ?? '', { x: Math.round(box.x), y: Math.round(box.y) }]
            }),
        ),
    )
}

test('no step code, block or fan-out element is cut on a box', async ({ page }) => {
    await signIn(page)
    const run = await settledRun(page)
    await page.goto(`/runs/${run}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)
    await canvasSettled(page)

    const cut = await page.evaluate(() =>
        [
            ...document.querySelectorAll(
                '.react-flow__node [data-testid="step-title"], .react-flow__node [data-testid="step-line"], .react-flow__node [data-testid="step-strip"] span.font-mono',
            ),
        ]
            .filter((element) => element.scrollWidth > element.clientWidth + 1)
            .map((element) => element.textContent),
    )
    expect(cut).toEqual([])
    for (const step of STEPS) {
        await expect(page.locator('.react-flow__node').getByText(step, { exact: true })).toBeVisible()
    }
    await expect(
        page.locator('.react-flow__node').getByText('organisationUnits', { exact: true }),
    ).toBeVisible()
})

test('every box is on the canvas on the first fit, and the canvas fills the room above the terminal', async ({
    page,
}) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await signIn(page)
    const run = await settledRun(page)
    await page.goto(`/runs/${run}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)
    if (!(await page.getByRole('separator', { name: /terminal/i }).isVisible()))
        await page.keyboard.press('t')
    await canvasSettled(page)
    await everyNodeIsInView(page)

    // NO DEAD GAP. The panel's foot is within the page's own bottom padding of the terminal's top.
    const panel = await page.getByRole('region', { name: LABELS.pipelines.page.graph }).boundingBox()
    const seam = await page.getByRole('separator', { name: /terminal/i }).boundingBox()
    expect(panel).not.toBeNull()
    expect(seam).not.toBeNull()
    expect((seam?.y ?? 0) - ((panel?.y ?? 0) + (panel?.height ?? 0))).toBeLessThan(48)

    // THE SEAM DRAGGED IS A RESIZE: the canvas refits once, then holds still.
    const before = await transformOf(page)
    const from = seam ?? { x: 0, y: 0, width: 0, height: 0 }
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
    await page.mouse.down()
    await page.mouse.move(from.x + from.width / 2, from.y + 120, { steps: 8 })
    await page.mouse.up()
    await canvasSettled(page)
    const after = await transformOf(page)
    expect(after).not.toBe(before)
    await page.waitForTimeout(600)
    expect(await transformOf(page)).toBe(after)
    await everyNodeIsInView(page)
})

test('a plain wheel over the run canvas zooms it one step about the pointer, and the page stays', async ({
    page,
}) => {
    // A short window with the terminal docked, so the page would have something to scroll.
    await page.setViewportSize({ width: 1440, height: 620 })
    await signIn(page)
    const run = await settledRun(page)
    await page.goto(`/runs/${run}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)
    if (!(await page.getByRole('separator', { name: /terminal/i }).isVisible()))
        await page.keyboard.press('t')
    await expect(page.getByRole('separator', { name: /terminal/i })).toBeVisible()
    await canvasSettled(page)

    const canvas = await page.locator('.react-flow').first().boundingBox()
    if (canvas === null) throw new Error('no canvas')
    // Near the canvas's top, which is on screen however short the window.
    const at = { x: canvas.width / 3, y: 40 }
    await page.mouse.move(canvas.x + at.x, canvas.y + at.y)
    const drawn = await transformOf(page)
    const before = viewOf(drawn)
    await page.mouse.wheel(0, -100)
    await expect.poll(() => transformOf(page)).not.toBe(drawn)
    const after = viewOf(await transformOf(page))

    // One notch is one step, and the point under the pointer stays under it.
    expect(after.zoom / before.zoom).toBeCloseTo(WHEEL_ZOOM_LIMIT, 3)
    expect((at.x - after.x) / after.zoom).toBeCloseTo((at.x - before.x) / before.zoom, 1)
    expect((at.y - after.y) / after.zoom).toBeCloseTo((at.y - before.y) / before.zoom, 1)
    expect(await pageScroll(page)).toBe(0)

    // A notch the other way steps back out, and the page still stands where it was.
    await page.mouse.wheel(0, 100)
    await expect.poll(async () => viewOf(await transformOf(page)).zoom).toBeCloseTo(before.zoom, 3)
    await page.waitForTimeout(300)
    expect(await pageScroll(page)).toBe(0)
})

test("a plain wheel over a pipeline's canvas scrolls the page; a modified one zooms it", async ({ page }) => {
    // A short window, so the page has something to scroll.
    await page.setViewportSize({ width: 1440, height: 520 })
    await signIn(page)
    await applyDocument(page.request, fanIn())
    await page.goto(`/pipelines/${PIPELINE}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)
    await canvasSettled(page)

    const canvas = await page.locator('.react-flow').first().boundingBox()
    if (canvas === null) throw new Error('no canvas')
    await page.mouse.move(canvas.x + canvas.width / 2, canvas.y + 30)
    const before = await transformOf(page)
    await page.mouse.wheel(0, 200)
    await expect.poll(() => pageScroll(page)).toBeGreaterThan(0)
    await page.waitForTimeout(400)
    expect(await transformOf(page)).toBe(before)

    // A pinch is a wheel with Ctrl held, and so is Ctrl and a mouse wheel: one notch is one step.
    // Back up the page first: the head stands still over what the body scrolls under it.
    await page.mouse.wheel(0, -400)
    await expect.poll(() => pageScroll(page)).toBe(0)
    await page.mouse.move(canvas.x + canvas.width / 2, canvas.y + 30)
    await page.keyboard.down('Control')
    await page.mouse.wheel(0, -100)
    await page.keyboard.up('Control')
    await expect.poll(() => transformOf(page)).not.toBe(before)
    const zoomed = await transformOf(page)
    expect(viewOf(zoomed).zoom / viewOf(before).zoom).toBeCloseTo(WHEEL_ZOOM_LIMIT, 3)

    // The view is the reader's now: a page scroll does not take it back.
    await page.mouse.wheel(0, 200)
    await page.waitForTimeout(400)
    expect(await transformOf(page)).toBe(zoomed)
})

test('a chosen step is the address, survives a reload, and is put down with the panel', async ({ page }) => {
    await signIn(page)
    const run = await settledRun(page)
    await page.goto(`/runs/${run}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)
    await canvasSettled(page)

    await page.locator('.react-flow__node').getByText('data_elements_by_domain', { exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/runs/${run}/data_elements_by_domain$`))
    const panel = page.locator('aside')
    await expect(panel.getByText('Attempts (2)')).toBeVisible()

    // Each try carries its id, and a fan-out element its own.
    await expect(panel.getByRole('button', { name: LABELS.runs.copy_attempt_id }).first()).toBeVisible()
    await panel.getByRole('button', { name: /^aggregate/ }).click()
    await expect(page).toHaveURL(/\?item=/)
    await expect(panel.getByRole('button', { name: LABELS.runs.copy_item_id })).toBeVisible()

    await page.reload()
    await expect(
        page.locator('.react-flow__node[data-id="data_elements_by_domain"] .step-node'),
    ).toHaveAttribute('data-selected', 'true')
    await expect(panel.getByRole('button', { name: LABELS.runs.copy_item_id })).toBeVisible()

    // Another step replaces the address, and its element goes with the step before.
    await page.locator('.react-flow__node').getByText('jobs', { exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/runs/${run}/jobs$`))

    // The ground puts the step down.
    const canvas = await page.locator('.react-flow__pane').first().boundingBox()
    await page.mouse.click((canvas?.x ?? 0) + 4, (canvas?.y ?? 0) + 4)
    await expect(page).toHaveURL(new RegExp(`/runs/${run}$`))

    // Back leaves the run rather than walking the steps chosen on it.
    await page.goto('/runs')
    await page.goto(`/runs/${run}/health`)
    await page.locator('.react-flow__node').getByText('jobs', { exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/runs/${run}/jobs$`))
    await page.goBack()
    await expect(page).toHaveURL(/\/runs$/)

    // A code the run does not hold opens the run, saying so.
    await page.goto(`/runs/${run}/no_such_step`)
    await expect(page.getByText(LABELS.runs.no_such_step('no_such_step'))).toBeVisible()
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)
})

test("a pipeline's page puts its chosen step in the address too", async ({ page }) => {
    await signIn(page)
    await applyDocument(page.request, fanIn())
    await page.goto(`/pipelines/${PIPELINE}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)
    await canvasSettled(page)
    await page.locator('.react-flow__node').getByText('counts', { exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/pipelines/${PIPELINE}/counts$`))
    await page.reload()
    await expect(page.locator('.react-flow__node[data-id="counts"] .step-node')).toHaveAttribute(
        'data-selected',
        'true',
    )
    await page.goto(`/pipelines/${PIPELINE}/nope`)
    await expect(page.getByText(LABELS.pipelines.page.no_such_step('nope'))).toBeVisible()
})

test('a layout chosen for the view redraws the graph, and the next visit opens on the default', async ({
    page,
}) => {
    await signIn(page)
    const run = await settledRun(page)
    await page.goto(`/runs/${run}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)
    await canvasSettled(page)
    const opened = await boxes(page)

    await page.getByRole('button', { name: LABELS.shell.layout.menu }).first().click()
    await page.getByRole('menuitemradio', { name: LABELS.shell.layout.down }).click()
    await expect.poll(async () => JSON.stringify(await boxes(page))).not.toBe(JSON.stringify(opened))
    await canvasSettled(page)
    const down = await boxes(page)
    expect(down.health?.y ?? 0).toBeGreaterThan(down.levels?.y ?? 0)

    await page.getByRole('button', { name: LABELS.shell.layout.menu }).first().click()
    await page.getByRole('menuitemradio', { name: LABELS.shell.layout.orthogonal }).click()
    await expect(page.locator('.react-flow__edge-path').first()).toHaveAttribute('d', /Q/)

    // Kept nowhere: the address says nothing about it, and the screen opens on the default again.
    expect(page.url()).not.toContain('layout')
    await page.goto('/runs')
    await page.goto(`/runs/${run}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)
    await canvasSettled(page)
    expect(await boxes(page)).toEqual(opened)
})

test('the graph opens in a window, where the wheel zooms and a box chosen is chosen on the page', async ({
    page,
}) => {
    await signIn(page)
    const run = await settledRun(page)
    await page.goto(`/runs/${run}`)
    await expect(page.locator('.react-flow__node')).toHaveCount(STEPS.length)
    await page
        .getByRole('button', { name: LABELS.shell.open_in_window(LABELS.shell.graph_window(PIPELINE)) })
        .click()
    const window = page.getByRole('dialog')
    await expect(window.locator('.react-flow__node')).toHaveCount(STEPS.length)
    await expect(window.getByRole('button', { name: LABELS.shell.layout.menu })).toBeVisible()

    const viewport = window.locator('.react-flow__viewport')
    await expect
        .poll(async () => viewport.evaluate((element) => (element as HTMLElement).style.transform))
        .not.toBe('')
    const before = await viewport.evaluate((element) => (element as HTMLElement).style.transform)
    const box = await window.locator('.react-flow').boundingBox()
    await page.mouse.move((box?.x ?? 0) + (box?.width ?? 0) / 2, (box?.y ?? 0) + (box?.height ?? 0) / 2)
    await page.mouse.wheel(0, -200)
    await expect
        .poll(async () => viewport.evaluate((element) => (element as HTMLElement).style.transform))
        .not.toBe(before)

    await window.locator('.react-flow__node').getByText('jobs', { exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/runs/${run}/jobs$`))
    await page.keyboard.press('Escape')
    await expect(window).toBeHidden()
    await expect(page.locator('.react-flow__node[data-id="jobs"] .step-node')).toHaveAttribute(
        'data-selected',
        'true',
    )
})
