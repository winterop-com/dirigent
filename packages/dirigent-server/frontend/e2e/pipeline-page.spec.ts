import { expect, test } from '@playwright/test'

import { LABELS } from '../src/lib/labels.ts'
import { applyDocument, belowTheFold, ranToCompletion, signIn, startRun } from './support.ts'

/**
 * A pipeline's page says what the pipeline did: its newest runs, and the latest settled run's
 * report where the document declares one.
 *
 * The codes are this file's own, so no other spec's runs land in these panels.
 */

const REPORTED = 'e2e-page-reported'
const QUIET = 'e2e-page-quiet'
const LONG = 'e2e-page-long'

/** One step that settles at once, with a report whose table is the key/value idiom. */
function documentOf(code: string, report: boolean): Record<string, unknown> {
    return {
        format: 'dirigent/v1',
        code,
        steps: { sum: { block: 'transform.jq', config: { input: [4, 5], program: 'add' } } },
        ...(report
            ? {
                  report: {
                      template:
                          '# Digest of {{ pipeline.code }}\n\n| | |\n| --- | --- |\n| Status | {{ run.status }} |\n',
                  },
              }
            : {}),
    }
}

test('a pipeline with runs and a report shows both, each leading to its run', async ({ page }) => {
    await signIn(page)
    await applyDocument(page.request, documentOf(REPORTED, true))
    const first = await startRun(page.request, REPORTED)
    await ranToCompletion(page.request, first)
    const latest = await startRun(page.request, REPORTED)
    await ranToCompletion(page.request, latest)

    await page.goto(`/pipelines/${REPORTED}`)

    const runs = page.getByRole('region', { name: LABELS.pipelines.page.recent_runs })
    await expect(runs.getByRole('link', { name: LABELS.pipelines.page.all_runs })).toHaveAttribute(
        'href',
        `/runs?pipeline=${REPORTED}`,
    )
    // A scratch database a local run reuses holds this pipeline's runs from before, newest first.
    const lines = runs.getByTestId('pipeline-runs').getByRole('link')
    await expect(lines.first()).toHaveAttribute('href', `/runs/${latest}`)
    await expect(lines.nth(1)).toHaveAttribute('href', `/runs/${first}`)
    await expect(lines.first().locator('.status-chip[data-status="succeeded"]')).toBeVisible()

    const report = page.getByRole('region', { name: LABELS.pipelines.page.report })
    await expect(report.getByRole('heading', { name: `Digest of ${REPORTED}` })).toBeVisible()
    // The key/value idiom's empty heading row is not drawn.
    await expect(report.locator('table')).toBeVisible()
    await expect(report.locator('thead')).toHaveCount(0)
    await expect(report.getByRole('cell', { name: 'Status' })).toBeVisible()

    const from = report.getByRole('link', { name: /^from the run / })
    await expect(from).toHaveAttribute('href', `/runs/${latest}?tab=report`)
    await expect(report.getByRole('link', { name: /ago|just now/ }).nth(1)).toHaveAttribute(
        'href',
        `/runs/${first}?tab=report`,
    )

    // The run's screen opens on its report.
    await from.click()
    await expect(page).toHaveURL(new RegExp(`/runs/${latest}\\?tab=report$`))
    const panel = page.locator('aside')
    await expect(panel.getByRole('tab', { name: LABELS.word.report })).toHaveAttribute(
        'aria-selected',
        'true',
    )
    await expect(panel.getByRole('heading', { name: `Digest of ${REPORTED}` })).toBeVisible()
})

test('a pipeline with neither says it has no runs and draws no report', async ({ page }) => {
    await signIn(page)
    await applyDocument(page.request, documentOf(QUIET, false))

    await page.goto(`/pipelines/${QUIET}`)

    const runs = page.getByRole('region', { name: LABELS.pipelines.page.recent_runs })
    await expect(runs.getByText(LABELS.pipelines.page.no_runs, { exact: true })).toBeVisible()
    await expect(page.getByRole('region', { name: LABELS.pipelines.page.report })).toHaveCount(0)
    await expect(page.getByRole('region', { name: LABELS.pipelines.page.blocks })).toBeVisible()
})

test("a long report's window button is on screen at the top of the document", async ({ page }) => {
    await signIn(page)
    const paragraphs = Array.from({ length: 60 }, (_, at) => `Paragraph ${String(at)} of a long digest.`)
    await applyDocument(page.request, {
        ...documentOf(LONG, false),
        report: { template: `# Long digest\n\n${paragraphs.join('\n\n')}\n` },
    })
    const runId = await startRun(page.request, LONG)
    await ranToCompletion(page.request, runId)
    const button = LABELS.shell.open_in_window('report.md')

    await page.goto(`/pipelines/${LONG}`)
    const report = page.getByRole('region', { name: LABELS.pipelines.page.report })
    await expect(report.getByRole('heading', { name: 'Long digest' })).toBeVisible()
    expect(await belowTheFold(report, button)).toBeLessThanOrEqual(0)

    await page.goto(`/runs/${runId}?tab=report`)
    const panel = page.getByRole('tabpanel')
    await expect(panel.getByRole('heading', { name: 'Long digest' })).toBeVisible()
    expect(await belowTheFold(panel, button)).toBeLessThanOrEqual(0)
})
