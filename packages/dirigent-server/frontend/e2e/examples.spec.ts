import { expect, test, type Locator, type Page } from '@playwright/test'

import { signIn } from './support.ts'

/**
 * The examples corpus on screen, against the instance's own answer rather than a fixture.
 *
 * WHAT THIS SPEC IS FOR is the half a Node test cannot reach: that `GET /examples` on a real
 * instance carries what this screen draws, that the panel's source is the shipped file's own
 * text, and that choosing a starter puts the copy `lib/starters` makes into the editor. The
 * narrowing, the counts and the copy rule are decided in `lib/examples` and `lib/starters` and
 * tested in Node.
 *
 * NOTHING IS APPLIED FIRST. The corpus is what this build installed, not what this suite put in
 * the database, so these assertions hold on an empty instance and on a busy one.
 */

/** A starter with a short header, a real chain of steps, and nothing to configure first. */
const STARTER = 'report-to-file'

/** The title that document gives itself, which is what heads it everywhere the code does not. */
const STARTER_TITLE = 'Render a report and write it to a file'

/** A line of the file's teaching header, which proves the panel shows the shipped text itself. */
const STARTER_COMMENT = 'Render a page of markdown and put it in a file'

/** A document that is deliberately not a starter: one step, and nothing to copy. */
const NOT_A_STARTER = 'hello-world'

/** A block every shipped flow reaches, so the cross-link has rows to show. */
const BLOCK = 'http.request'

function rowOf(page: Page, code: string): Locator {
    return page.getByRole('row').filter({ hasText: code })
}

/**
 * Open a row's panel by its identity cell.
 *
 * A tag on a row is the filter's own door, so the middle of a row is a button that narrows the
 * listing rather than the row itself. What opens a row is its lead cell, which is what somebody
 * reading the title presses.
 */
function openRow(page: Page, code: string): Promise<void> {
    return rowOf(page, code).getByRole('cell').first().click()
}

test('the corpus is listed, and the Starters filter narrows it to what may be copied', async ({ page }) => {
    await signIn(page)
    await page.goto('/examples')

    // Every document the plugins ship, whether or not it opted into being copied.
    await expect(rowOf(page, STARTER)).toBeVisible()
    await expect(rowOf(page, NOT_A_STARTER)).toBeVisible()

    // THE STARTER MARK IS A BADGE AND NOT A CHIP: the row says it once, beside the title.
    await expect(rowOf(page, STARTER).getByText('Starter', { exact: true })).toBeVisible()
    await expect(rowOf(page, NOT_A_STARTER).getByText('Starter', { exact: true })).toHaveCount(0)

    // What the document needs of this instance, counted, from the row's own `requires`.
    await expect(rowOf(page, STARTER)).toContainText('6 blocks')

    // THE SHELF IS ON THE ROW AS THE TAG THE CORPUS GIVES IT, and not as a column of its own:
    // the same word twice on one row is one fact too many.
    await expect(rowOf(page, STARTER).getByRole('button', { name: 'Filter by recipes' })).toBeVisible()

    await page.getByRole('button', { name: 'Starters', exact: true }).click()

    await expect(rowOf(page, STARTER)).toBeVisible()
    await expect(rowOf(page, NOT_A_STARTER)).toHaveCount(0)
    // A NARROWED CATALOGUE IS A LINK: the filters live in the address.
    await expect(page).toHaveURL(/starter=true/)

    // The search box narrows all of it, because all of it was read.
    await page.getByLabel('Search examples by code, name, description or tag').fill('kubernetes')
    await expect(page.getByText('Nothing in the corpus matches that.')).toBeVisible()
})

test('a row opens the shipped document and what it needs of this instance', async ({ page }) => {
    await signIn(page)
    await page.goto('/examples')

    await openRow(page, STARTER)

    const panel = page.getByRole('tabpanel')
    // Titled by its name and addressed by its code, and the code is on screen once.
    await expect(panel.getByRole('heading', { name: STARTER_TITLE })).toBeVisible()
    await expect(panel.getByText(STARTER, { exact: true })).toBeVisible()

    // The facts are the wire's own words, and the path is the file inside the distribution.
    await expect(panel).toContainText('plugin')
    await expect(panel).toContainText('shelf')
    await expect(panel).toContainText(`recipes/${STARTER}.yaml`)

    // THE REQUIREMENTS ARE CHECKED AGAINST THIS INSTANCE, item by item. Every block this
    // document names is in the shipped catalog, so every line reads as held.
    await expect(panel).toContainText('report.render')
    await expect(panel.getByText('here').first()).toBeVisible()

    // THE SOURCE IS THE SHIPPED FILE'S OWN TEXT, comments and all.
    const editor = panel.getByTestId('code-editor').first()
    await expect(editor.locator('.monaco-editor')).toBeVisible({ timeout: 30_000 })
    await expect(editor.locator('.view-lines')).toContainText(STARTER_COMMENT)

    // The verb is offered, because this document opted into being copied.
    await expect(panel.getByRole('button', { name: 'Use as starter' })).toBeVisible()
})

test('a document that is not a starter is offered no way to copy it', async ({ page }) => {
    await signIn(page)
    await page.goto('/examples')

    await openRow(page, NOT_A_STARTER)

    const panel = page.getByRole('tabpanel')
    await expect(panel.getByText(NOT_A_STARTER, { exact: true }).first()).toBeVisible()
    await expect(panel.getByRole('button', { name: 'Use as starter' })).toHaveCount(0)
})

test('From a starter opens the editor on a copy with the starter tag gone', async ({ page }) => {
    await signIn(page)
    await page.goto('/pipelines')

    await page.getByRole('button', { name: 'More ways to start a pipeline' }).click()
    await page.getByRole('menuitem', { name: 'From a starter' }).click()

    // The picker is the palette's own card: a search row over shelved rows.
    await page.getByPlaceholder('Search the starters').fill(STARTER)
    await page.getByRole('option').filter({ hasText: STARTER }).first().click()

    await expect(page).toHaveURL(/\/pipelines\/\$new$/)

    // A DOCUMENT OPENS ON THE SOURCE THAT HOLDS IT, which is where a code is renamed.
    const editor = page.getByTestId('code-editor').first()
    await expect(editor.locator('.monaco-editor')).toBeVisible({ timeout: 30_000 })

    // ONLY THE TWO LINES ARE REWRITTEN. The code is the starter's until somebody changes it,
    // and `starter` is off the tags, so the copy cannot claim to be one. The rest of the
    // document is the starter's, down to the parameter defaults.
    //
    // The editor renders the document it parsed rather than the text it was handed, so what is
    // asserted here is the copy as a document: the comments are `dg pipeline new`'s half.
    const lines = editor.locator('.view-lines')
    await expect(lines).toContainText(`code: ${STARTER}`, { timeout: 30_000 })
    const around = await lines.innerText()
    expect(around).toContain('tags:')
    expect(around).toContain('recipes')
    expect(around).not.toContain('starter')
})

test('the Blocks screen links to the shipped documents that require a block', async ({ page }) => {
    await signIn(page)
    await page.goto('/blocks')

    const link = rowOf(page, BLOCK).getByRole('link', { name: /example/ })
    await expect(link).toBeVisible()
    await link.click()

    await expect(page).toHaveURL(/\/examples\?block=http/)
    // The chip that says what the listing is narrowed to is the chip that takes it off.
    await expect(page.getByRole('button', { name: `Stop narrowing to ${BLOCK}` })).toBeVisible()
    // Every row left requires that block, and one that does not is gone.
    await expect(rowOf(page, NOT_A_STARTER)).toHaveCount(0)
    await expect(page.getByRole('row').filter({ hasText: 'http' }).first()).toBeVisible()
})
