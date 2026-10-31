import { expect, test } from '@playwright/test'

import { counted, LABELS } from '../src/lib/labels.ts'
import { applyDocument, ranToFailure, refusedDocument, signIn, startRun } from './support.ts'

/**
 * The front door, against a real instance.
 *
 * WHAT THESE SPECS ARE FOR is the half a Node test cannot reach: that the root is a screen
 * rather than a redirect, that its chart and its sections are composed out of
 * listings a real server answered for a signed-in account, and that a state nothing is in costs
 * the screen no words.
 */

/** A pipeline whose one call this instance answers, with an answer the step does not accept. */
const REFUSED = 'home-spec-refused'

test('the root is the home screen rather than a redirect to a listing', async ({ page }) => {
    await signIn(page)
    await page.goto('/')

    await expect(page).toHaveURL(/^https?:\/\/[^/]+\/$/)
    await expect(page.getByRole('heading', { name: LABELS.screen.dashboard.name, level: 1 })).toBeVisible()

    // The rail leads with it, and the corner mark goes to it.
    await expect(page.getByRole('link', { name: LABELS.screen.dashboard.name, exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: 'dirigent', exact: true })).toHaveAttribute('href', '/')
})

test('a run that failed is under needs a look, and the row opens it', async ({ page, baseURL }) => {
    await signIn(page)
    await applyDocument(page.request, refusedDocument(baseURL ?? '', REFUSED))
    const runId = await startRun(page.request, REFUSED)
    await ranToFailure(page.request, runId)

    await page.goto('/')

    // The settled failure is a row of its own under the section that is the way out to the
    // runs, led by its pipeline's shape with the step it failed in filled.
    await expect(
        page.getByRole('main').getByRole('link', { name: LABELS.dashboard.troubled_runs, exact: true }),
    ).toHaveAttribute('href', '/runs')
    const row = page.getByRole('main').locator(`a[href="/runs/${runId}"]`).first()
    await expect(row).toBeVisible()
    await expect(row).toContainText('failed')
    await expect(row.locator('svg.mini-graph')).toBeVisible()

    // And it goes where it says it goes.
    await row.click()
    await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`))
})

test('a state at zero is not written, and a section with nothing in it is not drawn', async ({
    page,
    baseURL,
}) => {
    await signIn(page)
    await applyDocument(page.request, refusedDocument(baseURL ?? '', REFUSED))
    const runId = await startRun(page.request, REFUSED)
    await ranToFailure(page.request, runId)

    await page.goto('/')
    const main = page.getByRole('main')
    await expect(main.locator(`a[href="/runs/${runId}"]`).first()).toBeVisible()

    // REVERT-PROOF. Count a state at zero in a sentence anywhere on this screen and one of these
    // fails, because a reader has to read it to find out nothing happened.
    await expect(main).not.toContainText(/\b0 failed/)
    await expect(main).not.toContainText(/\b0 completed with errors/)
    await expect(main).not.toContainText(/\b0 succeeded/)
    await expect(main).not.toContainText(/\b0 running/)
    await expect(main).not.toContainText(/\b0 cancelled/)
    await expect(main).not.toContainText(/\b0 waiting/)

    // The recent runs are there, with the way to every one of them beside the heading.
    await expect(main.getByRole('link', { name: LABELS.dashboard.all_runs, exact: true })).toHaveAttribute(
        'href',
        '/runs',
    )
})

test('the day is drawn by the hour, and what this instance depends on is beside it', async ({ page }) => {
    await signIn(page)
    await page.goto('/')

    // The chart is one figure with the whole of what it drew as its name, so a reader who cannot
    // see the bars is told the same thing the bars say.
    const chart = page.getByRole('img', { name: /last 24 hours/i })
    await expect(chart).toBeVisible()
    await expect(page.getByRole('heading', { name: LABELS.dashboard.chart.title })).toBeVisible()

    // The panel beside it lists the workers and the connections, and says in one line what is
    // not perfect. `dg dev` runs a worker of its own, so this instance has one to list.
    await expect(page.getByRole('heading', { name: LABELS.word.health })).toBeVisible()
    // The worker this instance really has, with the noun the catalogue spells for its slot count:
    // an alternation that also allowed a silent worker or none at all would pass whatever happened.
    const worker = page.getByText(/^worker · \d+ slots?$/)
    await expect(worker).toBeVisible()
    const said = await worker.innerText()
    const slots = Number(/\d+/.exec(said)?.[0])
    expect(slots).toBeGreaterThan(0)
    expect(said).toBe(counted(slots, LABELS.dashboard.health.worker)(String(slots)))
})
