import { expect, test, type Page } from '@playwright/test'

import { applyDocument, ranToFailure, refusedDocument, signIn, startRun } from './support.ts'

/**
 * The front door, against a real instance.
 *
 * WHAT THESE SPECS ARE FOR is the half a Node test cannot reach: that the root is a screen
 * rather than a redirect, that its tiles, its chart and its sections are composed out of
 * listings a real server answered for a signed-in account, and that a state nothing is in costs
 * the screen no words.
 */

/** A pipeline whose one call this instance answers, with an answer the step does not accept. */
const REFUSED = 'home-spec-refused'

/** The six numbers the screen opens with, in the order the row draws them. */
const TILES = ['Runs', 'Succeeded', 'Failed', 'With errors', 'Running', 'Queued']

/**
 * The stat tile whose label is this.
 *
 * Scoped to the content column: the rail carries an entry called Runs too, and a tile is not
 * the navigation entry that happens to share its name.
 */
function tile(page: Page, label: string) {
    return page
        .getByRole('main')
        .locator('a')
        .filter({ has: page.getByText(label, { exact: true }) })
}

test('the root is the home screen rather than a redirect to a listing', async ({ page }) => {
    await signIn(page)
    await page.goto('/')

    await expect(page).toHaveURL(/^https?:\/\/[^/]+\/$/)
    await expect(page.getByRole('heading', { name: 'Dashboard', level: 1 })).toBeVisible()

    // Each section is here whatever the instance holds, and each is the way out to the screen
    // that owns what it lists.
    const main = page.getByRole('main')
    await expect(main.getByRole('link', { name: 'Right now', exact: true })).toHaveAttribute('href', '/runs')
    await expect(main.getByRole('link', { name: 'Needs a look', exact: true })).toHaveAttribute(
        'href',
        '/runs',
    )
    await expect(main.getByRole('link', { name: 'Next fires', exact: true })).toHaveAttribute(
        'href',
        '/triggers',
    )

    // The rail leads with it, and the corner mark goes to it.
    await expect(page.getByRole('link', { name: 'Dashboard', exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: 'dirigent', exact: true })).toHaveAttribute('href', '/')
})

test('a run that failed is under needs a look, and the row opens it', async ({ page, baseURL }) => {
    await signIn(page)
    await applyDocument(page.request, refusedDocument(baseURL ?? '', REFUSED))
    const runId = await startRun(page.request, REFUSED)
    await ranToFailure(page.request, runId)

    await page.goto('/')

    // The settled failure is a row of its own, under headers that name its columns.
    const row = page.getByRole('main').getByRole('row').filter({ hasText: REFUSED }).first()
    await expect(row).toBeVisible()
    await expect(row).toContainText('failed')
    await expect(page.getByRole('columnheader', { name: 'Failed at' })).toBeVisible()

    // And it goes where it says it goes.
    await row.click()
    await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`))
})

test('the last day is counted by what settled, and a state at zero is not written', async ({
    page,
    baseURL,
}) => {
    await signIn(page)
    await applyDocument(page.request, refusedDocument(baseURL ?? '', REFUSED))
    const runId = await startRun(page.request, REFUSED)
    await ranToFailure(page.request, runId)

    await page.goto('/')
    const main = page.getByRole('main')

    // Every one of the six is on screen, whatever this instance has been doing.
    await Promise.all(TILES.map((label) => expect(tile(page, label)).toBeVisible()))

    // The day has a failure in it, and the tile counting them says so.
    await expect(tile(page, 'Failed')).not.toContainText(/\b0\b/)
    await expect(tile(page, 'Runs')).toContainText('Last 24 hours.')

    // REVERT-PROOF. Count a state at zero in a sentence anywhere on this screen and one of these
    // fails. A tile is a fixed slot and states its own zero; a clause in prose is the thing that
    // may not, because a reader has to read it to find out nothing happened.
    await expect(main).not.toContainText(/\b0 failed/)
    await expect(main).not.toContainText(/\b0 finished with errors/)
    await expect(main).not.toContainText(/\b0 succeeded/)
    await expect(main).not.toContainText(/\b0 running/)
    await expect(main).not.toContainText(/\b0 cancelled/)
    await expect(main).not.toContainText(/\b0 waiting/)

    // Nothing is going once it has settled, and that is one sentence rather than a pair of
    // zeroes above an empty list.
    await expect(main).toContainText('Nothing is running and nothing is waiting.')
})

test('a tile opens the listing narrowed the way the tile counted it', async ({ page, baseURL }) => {
    await signIn(page)
    await applyDocument(page.request, refusedDocument(baseURL ?? '', REFUSED))
    const runId = await startRun(page.request, REFUSED)
    await ranToFailure(page.request, runId)

    await page.goto('/')

    // The window the number was counted under travels with the click.
    await expect(tile(page, 'Failed')).toHaveAttribute('href', '/runs?status=failed&since=24h')
    await expect(tile(page, 'Running')).toHaveAttribute('href', '/runs?status=running')

    await tile(page, 'Failed').click()
    await expect(page).toHaveURL(/\/runs\?status=failed&since=24h$/)

    // And the listing opened on those filters rather than on every run: the bar reads them back,
    // and the run this spec just failed is what the rows hold.
    await expect(page.getByRole('button', { name: 'Status: failed' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Window: Last 24h' })).toBeVisible()
    await expect(page.getByRole('main').getByRole('row').filter({ hasText: REFUSED }).first()).toBeVisible()
})

test('the day is drawn by the hour, and what this instance depends on is beside it', async ({ page }) => {
    await signIn(page)
    await page.goto('/')

    // The chart is one figure with the whole of what it drew as its name, so a reader who cannot
    // see the bars is told the same thing the bars say.
    const chart = page.getByRole('img', { name: /last 24 hours/i })
    await expect(chart).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Runs over time' })).toBeVisible()

    // The panel beside it lists the workers and the connections, and says in one line what is
    // not perfect. `dg dev` runs a worker of its own, so this instance has one to list.
    await expect(page.getByRole('heading', { name: 'Health' })).toBeVisible()
    await expect(page.getByRole('main')).toContainText(
        /worker · \d+ slots?|has gone quiet|No worker has registered/i,
    )
})
