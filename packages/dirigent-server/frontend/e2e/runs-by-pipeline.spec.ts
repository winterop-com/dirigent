import { expect, test, type APIRequestContext } from '@playwright/test'

import { LABELS } from '../src/lib/labels.ts'
import { apiPrefix, applyDocument, signIn, startRun, statusChip } from './support.ts'

/**
 * The Runs screen grouped by pipeline: one row per pipeline that ran in the window, its states
 * counted with none at zero, a strip of its recent runs each a link, and the view in the address.
 *
 * The code is this file's own, so no other spec's runs land in its row.
 */

const CODE = 'e2e-grouped-runs'

/** One step that fails, refused rather than retried, when `fail` is 1 and succeeds when it is 0. */
const DOCUMENT = {
    format: 'dirigent/v1',
    code: CODE,
    params: {
        type: 'object',
        properties: { fail: { type: 'integer', default: 0, minimum: 0, maximum: 1 } },
    },
    steps: {
        only: {
            block: 'playground.generate',
            config: { rows: 1, fail_until: '${params.fail}', fail_as: 'rejected' },
        },
    },
}

/** Wait for a run to settle, whichever way it settles. */
async function settled(request: APIRequestContext, runId: string): Promise<string> {
    const prefix = await apiPrefix(request)
    let status = ''
    await expect
        .poll(
            async () => {
                const response = await request.get(`${prefix}/runs/${runId}`)
                status = ((await response.json()) as { run: { status: string } }).run.status
                return ['succeeded', 'failed'].includes(status)
            },
            { timeout: 30_000 },
        )
        .toBe(true)
    return status
}

test('a pipeline that ran many times is one row, counted by state, with a strip of its runs', async ({
    page,
}) => {
    // Six runs settle one after another before the screen is opened.
    test.setTimeout(120_000)
    await signIn(page)
    await applyDocument(page.request, DOCUMENT)
    const fails = [0, 1, 0, 0, 1, 0]
    const runs: string[] = []
    for (const fail of fails) {
        const run = await startRun(page.request, CODE, { fail })
        expect(await settled(page.request, run)).toBe(fail === 1 ? 'failed' : 'succeeded')
        runs.push(run)
    }

    await page.goto('/runs')
    await page
        .getByRole('group', { name: LABELS.runs.view.label })
        .getByRole('button', { name: LABELS.runs.view.by_pipeline })
        .click()
    await expect(page).toHaveURL(/\/runs\?group=pipeline&window=24h$/)

    const row = page.getByRole('row').filter({ hasText: CODE })
    await expect(row).toHaveCount(1)
    // A scratch database a local run reuses holds this pipeline's runs from before, so the counts
    // are at least what this run added, and a state it never reached is not drawn at all.
    await expect(row.getByLabel(/^\d+ succeeded$/)).toBeVisible()
    await expect(row.getByLabel(/^\d+ failed$/)).toBeVisible()
    await expect(row.getByLabel(/cancelled$/)).toHaveCount(0)
    await expect(row.getByLabel(/^0 /)).toHaveCount(0)
    await expect(statusChip(row, 'succeeded')).toBeVisible()

    // The strip reads oldest to newest from left to right; it is laid out from its right end, so
    // the newest is first in the document and this run's six are the first six, each a link.
    const strip = row.getByTestId('recent-runs').getByRole('link')
    const hrefs = await strip.evaluateAll((links) => links.map((link) => link.getAttribute('href')))
    expect(hrefs.slice(0, runs.length)).toEqual(runs.map((run) => `/runs/${run}`).toReversed())
    const boxes = await strip.evaluateAll((links) => links.map((link) => link.getBoundingClientRect().x))
    expect(boxes[0]).toBeGreaterThan(boxes[1])
    await expect(strip.first()).toHaveAttribute('data-status', 'succeeded')
    await expect(strip.nth(1)).toHaveAttribute('data-status', 'failed')
    await expect(strip.first()).toHaveAttribute('title', /^succeeded, /)

    // The window is in the address, and a reload opens on it.
    await page
        .getByRole('group', { name: LABELS.word.window.label })
        .getByRole('button', { name: LABELS.runs.window_option('7d') })
        .click()
    await expect(page).toHaveURL(/\/runs\?group=pipeline&window=7d$/)
    await page.reload()
    await expect(
        page
            .getByRole('group', { name: LABELS.word.window.label })
            .getByRole('button', { name: LABELS.runs.window_option('7d') }),
    ).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByRole('row').filter({ hasText: CODE })).toHaveCount(1)

    // A dot opens its own run.
    await page
        .getByRole('row')
        .filter({ hasText: CODE })
        .getByTestId('recent-runs')
        .getByRole('link')
        .first()
        .click()
    await expect(page).toHaveURL(new RegExp(`/runs/${runs[runs.length - 1]}$`))
    await page.goBack()

    // A row opens the flat list of that pipeline over the same window.
    await page.getByRole('row').filter({ hasText: CODE }).getByRole('gridcell').nth(1).click()
    await expect(page).toHaveURL(new RegExp(`/runs\\?pipeline=${CODE}&since=7d$`))
    await expect(
        page
            .getByRole('group', { name: LABELS.runs.view.label })
            .getByRole('button', { name: LABELS.runs.view.list }),
    ).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByRole('row').filter({ hasText: CODE }).first()).toBeVisible()
    await expect(page.getByRole('searchbox', { name: LABELS.runs.filter_pipeline })).toHaveValue(CODE)

    // And back to the grouped view, keeping the window.
    await page
        .getByRole('group', { name: LABELS.runs.view.label })
        .getByRole('button', { name: LABELS.runs.view.by_pipeline })
        .click()
    await expect(page).toHaveURL(new RegExp(`/runs\\?group=pipeline&window=7d&pipeline=${CODE}$`))
    await expect(page.getByRole('row').filter({ hasText: CODE })).toHaveCount(1)
})

/** A pipeline whose code is as long as a real one runs to, with a name over it. */
const LONG = { code: 'e2e-grouped-under-a-long-code', name: 'Grouped under a code as long as a real one' }

test.describe('in the column a 1024 window leaves', () => {
    test.use({ viewport: { width: 1024, height: 768 } })

    test('the grouped runs are a table, and a long code reads whole under its name', async ({ page }) => {
        await signIn(page)
        await applyDocument(page.request, { ...DOCUMENT, code: LONG.code, name: LONG.name })
        await settled(page.request, await startRun(page.request, LONG.code, { fail: 0 }))

        await page.goto(`/runs?group=pipeline&window=24h&pipeline=${LONG.code}`)
        const row = page.getByRole('row').filter({ hasText: LONG.code })
        await expect(row).toHaveCount(1)
        await expect(page.getByRole('columnheader').first()).toBeVisible()

        const code = row.getByTitle(LONG.code, { exact: true })
        await expect(code).toBeVisible()
        expect(await code.evaluate((node) => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(0)

        await expect
            .poll(async () => page.getByRole('grid').evaluate((box) => box.scrollWidth - box.clientWidth))
            .toBe(0)
    })
})
