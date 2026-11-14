import { expect, test, type ElementHandle, type Locator } from '@playwright/test'

import { apiPrefix, applyDocument, signIn, startRun } from './support.ts'

/**
 * Back to a long screen is back where the reader left it, though the rows it scrolls arrive after
 * the screen is drawn: the shell's scroller holds the place while the listing's read lands.
 */

/** Enough pipelines that the listing runs several screens past the fold. */
const CODES = Array.from({ length: 40 }, (_, index) => `scroll-place-${String(index + 1).padStart(2, '0')}`)

/** The row opened, far enough down that the place cannot be the top. */
const OPENED = 'scroll-place-30'

/** How long the listing's read is held on the way back, so the rows land after the screen is drawn. */
const LATE_MS = 1_000

test('back from a pipeline lands the listing where it was left', async ({ page }) => {
    await signIn(page)
    for (const code of CODES) {
        await applyDocument(page.request, {
            format: 'dirigent/v1',
            kind: 'pipeline',
            code,
            requires: { blocks: ['transform.jq'] },
            steps: { total: { block: 'transform.jq', config: { input: [1, 2, 3], program: 'add' } } },
        })
    }
    const prefix = await apiPrefix(page.request)
    try {
        await page.goto('/pipelines')
        const scroller = page.locator('main')
        const row = page.locator(`a[href="/pipelines/${OPENED}"]`)
        await row.scrollIntoViewIfNeeded()
        await expect(row).toBeInViewport()
        const left = await scroller.evaluate((element) => element.scrollTop)
        expect(left).toBeGreaterThan(500)

        await row.click()
        await expect(page).toHaveURL(new RegExp(`/pipelines/${OPENED}$`))

        await page.route(
            (url) => url.pathname === `${prefix}/pipelines`,
            async (route) => {
                await new Promise((resolve) => setTimeout(resolve, LATE_MS))
                await route.continue()
            },
        )
        await page.goBack()
        await expect(page).toHaveURL(/\/pipelines$/)

        await expect.poll(() => scroller.evaluate((element) => element.scrollTop)).toBeCloseTo(left, -1)
        await expect(row).toBeInViewport()
    } finally {
        await page.unrouteAll({ behavior: 'ignoreErrors' })
        for (const code of CODES) await page.request.delete(`${prefix}/pipelines/${code}`)
    }
})

/** A pipeline of its own, so the listing narrowed to it holds only this spec's runs. */
const RUNS_CODE = 'scroll-place-runs'

/** More runs than one page holds, so the place kept lies on the second page. */
const RUN_COUNT = 70

/** The row opened, counting the heading as row 1: a run on the second page, read only once the reader nears the first's end. */
const RUN_ROW = 60

/** The element a listing's rows scroll in: the nearest ancestor of a row that scrolls itself. */
function scrollerOf(row: Locator): Promise<ElementHandle<HTMLElement>> {
    return row
        .evaluateHandle((element) => {
            let node = element.parentElement
            while (node !== null && !['auto', 'scroll'].includes(getComputedStyle(node).overflowY)) {
                node = node.parentElement
            }
            return node as HTMLElement
        })
        .then((handle) => handle as ElementHandle<HTMLElement>)
}

test('back from a run on a later page lands the runs listing where it was left', async ({ page }) => {
    test.setTimeout(120_000)
    await signIn(page)
    await applyDocument(page.request, {
        format: 'dirigent/v1',
        kind: 'pipeline',
        code: RUNS_CODE,
        requires: { blocks: ['transform.jq'] },
        steps: { total: { block: 'transform.jq', config: { input: [1, 2, 3], program: 'add' } } },
    })
    const prefix = await apiPrefix(page.request)
    for (let index = 0; index < RUN_COUNT; index++) await startRun(page.request, RUNS_CODE)

    try {
        // Every read of the listing, and the ones that carry on from a cursor.
        const reads: URL[] = []
        page.on('request', (request) => {
            const url = new URL(request.url())
            if (url.pathname === `${prefix}/runs`) reads.push(url)
        })
        const later = () => reads.filter((url) => url.searchParams.has('after')).length

        await page.goto(`/runs?pipeline=${RUNS_CODE}`)
        // The heading row is row 1, so the first run is row 2; rows out of view are not drawn.
        const first = page.locator('[role="row"][aria-rowindex="2"]')
        const drawn = page.locator('[role="row"][aria-rowindex]:not([aria-rowindex="1"])').first()
        await expect(first).toBeVisible()
        // Opening the listing reads one page and stops there, however fast the answer came.
        await page.waitForTimeout(1_500)
        expect(reads).toHaveLength(1)

        const scroller = await scrollerOf(first)
        await expect
            .poll(async () => {
                await scroller.evaluate((element) => {
                    element.scrollTop = element.scrollHeight
                })
                return later()
            })
            .toBeGreaterThan(0)

        const row = page.locator(`[role="row"][aria-rowindex="${String(RUN_ROW)}"]`)
        await expect
            .poll(async () => {
                await scroller.evaluate((element) => {
                    element.scrollTop = element.scrollHeight
                })
                return row.count()
            })
            .toBe(1)
        await row.scrollIntoViewIfNeeded()
        await expect(row).toBeInViewport()
        const left = await scroller.evaluate((element) => element.scrollTop)
        expect(left).toBeGreaterThan(500)

        await row.click()
        await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+$/)
        const opened = page.url()

        await page.goBack()
        await expect(page).toHaveURL(new RegExp(`/runs\\?pipeline=${RUNS_CODE}$`))
        await expect
            .poll(async () => (await scrollerOf(drawn)).evaluate((element) => element.scrollTop))
            .toBeCloseTo(left, -1)
        await expect(row).toBeInViewport()

        await row.click()
        await expect(page).toHaveURL(opened)
    } finally {
        await page.request.delete(`${prefix}/pipelines/${RUNS_CODE}`)
    }
})
