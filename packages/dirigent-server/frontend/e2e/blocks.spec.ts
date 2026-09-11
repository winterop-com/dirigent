import { expect, test, type Page } from '@playwright/test'

import { signIn } from './support.ts'

/**
 * The block catalog, against the instance's own answer rather than a fixture.
 *
 * WHAT THIS SPEC IS FOR is the half a Node test cannot reach: that `GET /blocks` on a real
 * instance carries what this screen draws. The narrowing and the labels are decided in
 * `lib/blocks` and tested in Node; what is asserted here is that the shipped catalog actually
 * publishes a block's summary, its plugin, its kind and the docstring on each config key -- so
 * a block author's sentence reaching the screen is a fact about the round trip.
 *
 * NOTHING IS APPLIED FIRST. The catalog is what this build installed, not what this suite put
 * in the database, so this is the one listing screen that says the same thing on an empty
 * instance as on a busy one.
 */

/** The one shipped block that executes code on the worker, and the config key it is read by. */
const SHELL = 'shell.run'

/** A block author's own sentence, published as the JSON Schema `description` of `argv`. */
const ARGV_HELP = 'The command as an argument vector, which does not involve a shell.'

/** A sensor, so the kind column is asserted against both families rather than one. */
const SLEEP = 'time.sleep'

function rowOf(page: Page, id: string) {
    return page.getByRole('row').filter({ hasText: id })
}

test('the catalog lists every installed block in its family, with its kind and plugin', async ({ page }) => {
    await signIn(page)
    await page.goto('/blocks')

    // An operator and a sensor, each headed by the id it is addressed by -- a block has no
    // name, so the id is the title.
    await expect(rowOf(page, SHELL)).toBeVisible()
    await expect(rowOf(page, SLEEP)).toBeVisible()

    // The row carries what the catalog says about the block, not what this spec guessed.
    await expect(rowOf(page, SHELL)).toContainText('Run a command on the worker.')
    // The plugin that contributed it, which for the shipped catalog is the builtin entry point.
    await expect(rowOf(page, SHELL)).toContainText('builtin')

    // A KIND IS NOT A STATUS: the chip is drawn from the kind family, and the two blocks
    // asserted here sit in different ones.
    await expect(rowOf(page, SHELL).locator('.kind-chip[data-kind="operator"]')).toBeVisible()
    await expect(rowOf(page, SLEEP).locator('.kind-chip[data-kind="sensor"]')).toBeVisible()

    // GROUPS SHELVE THE CATALOG, and a block declares its own: `shell.run` is under `execute`
    // with the other two blocks that run something, and there is no `shell` shelf at all.
    await expect(page.getByRole('heading', { name: 'execute', exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'transform', exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'shell', exact: true })).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'map', exact: true })).toHaveCount(0)

    // The supporting registries are on the catalog screen too, so s3 or a notifier is findable.
    await expect(page.getByRole('heading', { name: 'Notifiers' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Connection kinds' })).toBeVisible()
})

test('choosing a block opens its config reference in the panel', async ({ page }) => {
    await signIn(page)
    await page.goto('/blocks')

    await rowOf(page, SHELL).click()

    const panel = page.getByRole('tabpanel')
    await expect(panel.getByRole('heading', { name: SHELL })).toBeVisible()
    await expect(panel).toContainText('Run a command on the worker.')

    // The facts are named with the words the catalog answers with, and the allowlist gate is
    // stated because it decides whether a pipeline naming this block runs at all.
    await expect(panel).toContainText('plugin')
    await expect(panel).toContainText('local_execution')
    await expect(panel).toContainText('requires allowlisting')

    // THE CONFIG REFERENCE IS THE BLOCK AUTHOR'S OWN WORDS. Each key is published with the
    // docstring written beside it in Python, and that sentence is what the panel states.
    await expect(panel).toContainText('argv')
    await expect(panel).toContainText(ARGV_HELP)
    await expect(panel).toContainText('timeout')
    await expect(panel).toContainText('default 5m')

    // A reference states shapes rather than offering controls: there is nothing to edit here.
    await expect(panel.getByRole('textbox')).toHaveCount(0)
})

test('a required config key is marked as one, and a sensor states its timing defaults', async ({ page }) => {
    await signIn(page)
    await page.goto('/blocks')

    await rowOf(page, SLEEP).click()

    // `time.sleep` takes one key and the schema lists it as required, which is the half of the
    // reference `shell.run` cannot show: every key it takes is optional.
    const panel = page.getByRole('tabpanel')
    await expect(panel.getByRole('heading', { name: SLEEP })).toBeVisible()
    await expect(panel).toContainText('for')
    await expect(panel).toContainText('required')

    // A sensor is polled and deadlined, and the catalog answers both; an operator answers
    // neither, so these rows are absent there rather than empty.
    await expect(panel).toContainText('default_poll_seconds')
    await expect(panel).toContainText('default_deadline_seconds')
    await expect(panel).toContainText('no allowlist entry')
})

test('the search box narrows the catalog to what was typed', async ({ page }) => {
    await signIn(page)
    await page.goto('/blocks')

    await expect(rowOf(page, SLEEP)).toBeVisible()

    await page.getByLabel('Search blocks by id or summary').fill('shell')

    await expect(rowOf(page, SHELL)).toBeVisible()
    await expect(rowOf(page, SLEEP)).toHaveCount(0)

    // A search that finds nothing says so, rather than falling back to the whole catalog.
    await page.getByLabel('Search blocks by id or summary').fill('kubernetes')
    await expect(page.getByText('Nothing in the catalog matches that.', { exact: false })).toBeVisible()

    // Clearing the box brings the catalog back.
    await page.getByLabel('Search blocks by id or summary').fill('')
    await expect(rowOf(page, SLEEP)).toBeVisible()
})

// REVERT-PROOF. Leave the zebra stripe in the selected row's class list and this fails:
// `even:` carries a pseudo-class, so the stripe outranks the tint and a selected even row
// looks exactly like an unselected one.
test('a selected row wears the same tint on either side of the stripe', async ({ page }) => {
    await signIn(page)
    await page.goto('/blocks')

    const painted = async (id: string) => {
        await rowOf(page, id).first().click()
        await page.mouse.move(4, 4)
        // The tint arrives over transition-colors, so the read waits for two frames to agree.
        return rowOf(page, id)
            .first()
            .evaluate(async (row) => {
                const paint = () => getComputedStyle(row).backgroundColor
                const settle = () => new Promise((done) => setTimeout(done, 100))
                let seen = paint()
                for (let tries = 0; tries < 20; tries += 1) {
                    await settle()
                    const now = paint()
                    if (now === seen) return now
                    seen = now
                }
                return seen
            })
    }

    // convert.std is transform's first row and transform.jq its fourth, so one sits on
    // each side of the even/odd stripe.
    expect(await painted('transform.jq')).toBe(await painted('convert.std'))
})
