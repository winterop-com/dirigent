import { expect, test } from '@playwright/test'

import { apiPrefix, applyDocument, signIn } from './support.ts'

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
