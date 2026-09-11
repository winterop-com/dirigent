import { expect, test, type Page } from '@playwright/test'

import {
    applyDocument,
    applyExample,
    DEV_USERNAME,
    ranToCompletion,
    ranToFailure,
    refusedDocument,
    signIn,
    signInAs,
    signOut,
    startRun,
} from './support.ts'

/**
 * The admin section and the settings dialog, against a real instance.
 *
 * WHAT THESE SPECS ARE FOR is the half a Node test cannot reach: that the dashboard's tiles are
 * composed out of listings a real server answered, that the last-admin guard is the server's and
 * its sentence reaches the screen unchanged, and that a setting written in the dialog moves what
 * is already rendered behind it.
 *
 * THE INSTANCE'S ONLY ADMIN IS `dg dev`'s OWN. Every account this file makes is a viewer, so the
 * development admin stays the only active one and the guard has something to guard.
 */

const EXAMPLE = { file: 'examples/transform/std-convert-fan-out.yaml', code: 'std-convert-fan-out' }

/** A pipeline whose one call this instance answers, with an answer the step does not accept. */
const REFUSED = 'admin-spec-refused'

/** A username no other run of this suite will have used. */
function someone(): string {
    return `spec-${String(Date.now())}`
}

/**
 * The tile whose label is this, on the dashboard.
 *
 * Scoped to the content column: the rail carries a link called Workers too, and a tile is not
 * the navigation entry that happens to share its name.
 */
function tile(page: Page, label: string) {
    return page
        .getByRole('main')
        .locator('a')
        .filter({ has: page.getByText(label, { exact: true }) })
}

/** The accounts table row for one username. */
function rowOf(page: Page, username: string) {
    return page.getByRole('row').filter({ has: page.getByRole('button', { name: username, exact: true }) })
}

/** The tokens table row for one token name. */
function tokenRowOf(page: Page, name: string) {
    return page.getByRole('row').filter({ hasText: name })
}

/** Make an account through the dialog, which is the door this screen offers. */
async function createAccount(page: Page, username: string, email?: string): Promise<void> {
    await page.getByRole('button', { name: 'New account' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Username', { exact: true }).fill(username)
    if (email !== undefined) await dialog.getByLabel('Email', { exact: true }).fill(email)
    await dialog.getByLabel('Password', { exact: true }).fill('a-long-enough-password')
    await dialog.getByRole('button', { name: 'Create', exact: true }).click()
}

test('the dashboard composes its tiles out of the listings behind them', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, EXAMPLE.file)
    const runId = await startRun(page.request, EXAMPLE.code)
    await ranToCompletion(page.request, runId)

    await page.goto('/admin')

    // The window tile counted the run this spec just made, and links to the screen that lists it.
    await expect(tile(page, 'Last 24 hours')).toBeVisible()
    await expect(tile(page, 'Last 24 hours')).toHaveAttribute('href', '/runs')
    await expect(tile(page, 'Last 24 hours')).not.toContainText('Nothing has run')

    // Each of the other four states its own fact and links to the screen that explains it.
    await expect(tile(page, 'Right now')).toBeVisible()
    await expect(tile(page, 'Workers')).toHaveAttribute('href', '/admin/workers')
    await expect(tile(page, 'Connections')).toHaveAttribute('href', '/connections')
    await expect(tile(page, 'Schedules')).toHaveAttribute('href', '/triggers')

    // The workers table is on the dashboard whether or not anything has registered.
    await expect(page.getByRole('heading', { name: 'Workers' })).toBeVisible()

    // The status bar spends no words on whose screen this is: being here is the proof.
    await expect(page.getByText('admin only')).toHaveCount(0)
})

test('a tile counts the states that occurred and spends no clause on the ones that did not', async ({
    page,
    baseURL,
}) => {
    await signIn(page)
    await applyDocument(page.request, refusedDocument(baseURL ?? '', REFUSED))
    const runId = await startRun(page.request, REFUSED)
    await ranToFailure(page.request, runId)

    await page.goto('/admin')

    // The day has a failure in it and nothing that finished with errors, so the tile names the
    // one and says nothing whatever about the other.
    await expect(tile(page, 'Last 24 hours')).toContainText('failed')
    await expect(tile(page, 'Last 24 hours')).not.toContainText('0 finished with errors')

    // Nothing is running or waiting once it has settled, and that is one sentence about an idle
    // instance rather than a pair of zeroes.
    await expect(tile(page, 'Right now')).toContainText('Nothing is running and nothing is waiting.')
    await expect(tile(page, 'Right now')).not.toContainText('0 running')

    // The run that failed is in the table the tiles sit above.
    await expect(page.getByRole('main').getByRole('row').filter({ hasText: 'failed' }).first()).toBeVisible()
})

test('an account is made, and then turned off', async ({ page }) => {
    await signIn(page)
    const username = someone()

    await page.goto('/admin/users')
    await expect(rowOf(page, DEV_USERNAME)).toBeVisible()
    await expect(rowOf(page, DEV_USERNAME)).toContainText('admin')

    await createAccount(page, username)

    await expect(rowOf(page, username)).toBeVisible()
    await expect(rowOf(page, username)).toContainText('viewer')
    await expect(rowOf(page, username)).toContainText('active')

    // The row's actions are in the panel, which selecting it opens.
    await page.getByRole('button', { name: username, exact: true }).click()
    const panel = page.getByRole('tabpanel')

    // The panel heads the account the way every panel in this app heads a thing: with no name
    // on it the title is what it signs in as, and it wears the mono face itself.
    await expect(panel.getByText(username, { exact: true })).toBeVisible()
    await expect(panel).toContainText('viewer')

    // When it was made and whether it has ever been used are read here, not counted.
    await expect(panel).toContainText('Created')
    await expect(panel).toContainText('never signed in')

    await panel.getByRole('button', { name: 'Deactivate' }).click()
    await expect(rowOf(page, username)).toContainText('deactivated')

    // And the panel says so of itself, rather than leaving the button label to imply it.
    await expect(panel).toContainText('deactivated')
})

test('the last admin cannot deactivate itself, and is told so where it asked', async ({ page }) => {
    await signIn(page)
    await page.goto('/admin/users')

    await page.getByRole('button', { name: DEV_USERNAME, exact: true }).click()
    await page.getByRole('button', { name: 'Deactivate' }).click()

    // The refusal is the server's own sentence, rendered beside the button that asked for it
    // rather than as a toast that outlives the screen. Its status phrase is not a heading: it
    // would say "Conflict" of every refusal this screen can make.
    await expect(page.getByText('the only active admin')).toBeVisible()

    // And nothing changed: the account is still active and still an admin.
    await expect(rowOf(page, DEV_USERNAME)).toContainText('active')
    await expect(rowOf(page, DEV_USERNAME)).toContainText('admin')
})

test('the settings dialog switches the appearance and the clock behind it', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, EXAMPLE.file)
    const runId = await startRun(page.request, EXAMPLE.code)
    await ranToCompletion(page.request, runId)

    await page.goto('/runs')
    const started = page.getByRole('row').filter({ hasText: EXAMPLE.code }).locator('[title]').last()
    await expect(started).not.toHaveAttribute('title', /UTC/)

    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    // Appearance lives under Theme, the same axis the header's own menu writes.
    await dialog.getByRole('button', { name: 'Theme', exact: true }).click()
    await dialog.getByRole('button', { name: 'Dark', exact: true }).click()
    await expect(page.locator('html')).toHaveClass(/dark/)
    await dialog.getByRole('button', { name: 'Light', exact: true }).click()
    await expect(page.locator('html')).not.toHaveClass(/dark/)

    // The clock lives under General; the formatters read it, so a timestamp behind moves.
    await dialog.getByRole('button', { name: 'General', exact: true }).click()
    await dialog.getByRole('button', { name: 'UTC', exact: true }).click()
    await page.keyboard.press('Escape')
    await expect(started).toHaveAttribute('title', /UTC/)
})

test('the settings search reaches across every category', async ({ page }) => {
    await signIn(page)
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    const dialog = page.getByRole('dialog')

    await dialog.getByLabel('Search the settings').fill('password')
    await expect(dialog.getByRole('button', { name: 'Account', exact: true })).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'General', exact: true })).toHaveCount(0)

    // One box across the renamed groups: a palette is a Theme row and a chord is a Shortcuts one.
    await dialog.getByLabel('Search the settings').fill('palette')
    await expect(dialog.getByRole('button', { name: 'Theme', exact: true })).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Shortcuts', exact: true })).toBeVisible()

    await dialog.getByLabel('Search the settings').fill('stroopwafel')
    await expect(dialog.getByText('Nothing matches that.')).toBeVisible()
})

test('the nav is three groups and About is not one of them', async ({ page }) => {
    await signIn(page)
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    const dialog = page.getByRole('dialog')

    for (const group of ['Preferences', 'You', 'This instance']) {
        await expect(dialog.getByText(group, { exact: true })).toBeVisible()
    }
    await expect(dialog.getByRole('button', { name: 'About', exact: true })).toHaveCount(0)

    // The version lives on Server, and the two links are at that pane's foot.
    await dialog.getByRole('button', { name: 'Server', exact: true }).click()
    await expect(dialog.getByText('Version', { exact: true })).toBeVisible()
    await expect(dialog.getByRole('link', { name: 'Documentation' })).toBeVisible()
    await expect(dialog.getByRole('link', { name: 'API reference' })).toHaveAttribute('href', '/docs')
})

test('a palette is chosen from its swatch, by pointer and by the arrows', async ({ page }) => {
    await signIn(page)
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('button', { name: 'Theme', exact: true }).click()

    const paper = dialog.getByRole('radio', { name: 'Paper' })
    await paper.click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'paper')
    await expect(paper).toHaveAttribute('aria-checked', 'true')

    // The card is the radio, so the arrows move and choose, and the ends wrap.
    await paper.focus()
    await page.keyboard.press('ArrowRight')
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'contrast')
    await page.keyboard.press('ArrowRight')
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dirigent')
})

test('the password form expands under its row and states the refusal there', async ({ page }) => {
    await signIn(page)
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('button', { name: 'Account', exact: true }).click()

    // Nothing is over the dialog: the form is in the row, and the button that opened it is gone.
    await dialog.getByRole('button', { name: 'Change', exact: true }).click()
    await expect(dialog.getByLabel('Current password')).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Change', exact: true })).toHaveCount(0)

    // The server's own sentence, beside the fields, and the section stays open on a refusal.
    await dialog.getByLabel('Current password').fill('not-the-password')
    await dialog.getByLabel('New password').fill('a-long-enough-password')
    await dialog.getByRole('button', { name: 'Change password' }).click()
    await expect(dialog.getByRole('alert')).toBeVisible()
    await expect(dialog.getByLabel('Current password')).toBeVisible()

    await dialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(dialog.getByLabel('Current password')).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: 'Change', exact: true })).toBeVisible()
})

test('an email is carried into the panel, changed there, and is unique across accounts', async ({ page }) => {
    await signIn(page)
    const username = someone()
    const email = `${username}@example.test`

    await page.goto('/admin/users')
    await createAccount(page, username, email)
    await expect(rowOf(page, username)).toBeVisible()

    // The panel's Email box is where the account's address is, so the input carries it.
    await page.getByRole('button', { name: username, exact: true }).click()
    const panel = page.getByRole('tabpanel')
    await expect(panel.getByLabel('Email')).toHaveValue(email)

    // Saving a changed one writes it, and reading the panel again answers the new address.
    const moved = `${username}-moved@example.test`
    await panel.getByLabel('Email').fill(moved)
    await panel.getByRole('button', { name: 'Save' }).click()
    await expect(panel.getByRole('button', { name: 'Save' })).toBeDisabled()
    await page.reload()
    await page.getByRole('button', { name: username, exact: true }).click()
    await expect(page.getByRole('tabpanel').getByLabel('Email')).toHaveValue(moved)

    // A second account asking for that address is refused, in the server's own sentence, in
    // the dialog that asked for it.
    await createAccount(page, `${username}-two`, moved)
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('alert')).toContainText('already exists')
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Cancel' }).click()
})

test('a password is reset from the panel, and the account signs in with the new one', async ({ page }) => {
    await signIn(page)
    const username = someone()

    await page.goto('/admin/users')
    await createAccount(page, username)
    await expect(rowOf(page, username)).toBeVisible()
    await page.getByRole('button', { name: username, exact: true }).click()

    await page.getByRole('tabpanel').getByRole('button', { name: 'Reset password' }).click()
    const dialog = page.getByRole('dialog')

    // A password too short is refused where it was typed, and the dialog stays where it is.
    await dialog.getByLabel('New password').fill('short')
    await dialog.getByRole('button', { name: 'Reset', exact: true }).click()
    await expect(dialog.getByRole('alert')).toBeVisible()
    await expect(dialog).toBeVisible()

    const changed = 'another-long-password'
    await dialog.getByLabel('New password').fill(changed)
    await dialog.getByRole('button', { name: 'Reset', exact: true }).click()
    await expect(dialog).toHaveCount(0)

    // The password the reset set is the one that account signs in with from then on.
    await signOut(page)
    await signInAs(page, username, changed)
})

test('a token is minted for another account, and the tokens table says whose it is', async ({ page }) => {
    await signIn(page)
    const username = someone()
    const token = `tok-${username}`

    await page.goto('/admin/users')
    await createAccount(page, username)
    await expect(rowOf(page, username)).toBeVisible()
    await page.getByRole('button', { name: username, exact: true }).click()

    await page.getByRole('tabpanel').getByRole('button', { name: 'New token' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText(`It holds whatever ${username} holds.`)
    await dialog.getByLabel('Name').fill(token)
    await dialog.getByRole('button', { name: 'Create', exact: true }).click()

    // The secret is shown once, beside the account it authenticates as.
    await expect(dialog).toContainText(username)
    await dialog.getByRole('button', { name: 'Done' }).click()

    // The row in the tokens table carries the account, which is what makes revoking one honest.
    await expect(tokenRowOf(page, token)).toContainText(username)

    // Revoking reaches that account's token: the row stays, says so, and offers no second press.
    await tokenRowOf(page, token)
        .getByRole('button', { name: `Revoke ${token}` })
        .click()
    await expect(page.getByRole('main').getByRole('alert')).toHaveCount(0)
    await expect(tokenRowOf(page, token)).toContainText('revoked')
    await expect(tokenRowOf(page, token).getByRole('button', { name: `Revoke ${token}` })).toHaveCount(0)
})
