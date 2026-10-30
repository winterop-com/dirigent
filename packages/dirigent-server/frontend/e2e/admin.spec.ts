import { expect, test, type Page } from '@playwright/test'

import { LABELS } from '../src/lib/labels.ts'
import {
    applyExample,
    DEV_USERNAME,
    ranToCompletion,
    signIn,
    signInAs,
    signOut,
    startRun,
    apiPrefix,
    openSettings,
} from './support.ts'

/**
 * The admin section and the settings dialog, against a real instance.
 *
 * WHAT THESE SPECS ARE FOR is the half a Node test cannot reach: that the last-admin guard is the
 * server's and its sentence reaches the screen unchanged, and that a setting written in the dialog
 * moves what is already rendered behind it.
 *
 * THE INSTANCE'S ONLY ADMIN IS `dg dev`'s OWN. Every account this file makes is a viewer, so the
 * development admin stays the only active one and the guard has something to guard.
 */

const EXAMPLE = { file: 'examples/transform/std-convert-fan-out.yaml', code: 'std-convert-fan-out' }

/** A username no other run of this suite will have used. */
function someone(): string {
    return `spec-${String(Date.now())}`
}

/** The accounts table row for one username. */
function rowOf(page: Page, username: string) {
    return page
        .getByRole('row')
        .or(page.getByRole('listitem'))
        .filter({
            has: page.getByRole('button', { name: LABELS.users.new_token_for(username), exact: true }),
        })
}

/**
 * The tokens row for one token name, in whichever form the listing is drawing.
 *
 * A listing beside an open panel has half the width it had and draws its rows as cards, so a
 * test that opens one is asserting about a `listitem` from that moment on.
 */
function tokenRowOf(page: Page, name: string) {
    const tokens = page.locator('[data-account-tokens]')
    return tokens.getByRole('row').or(tokens.getByRole('listitem')).filter({ hasText: name })
}

/** Make an account through the dialog, which is the door this screen offers. */
async function createAccount(page: Page, username: string, email?: string): Promise<void> {
    await page.getByRole('button', { name: LABELS.users.new_account }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel(LABELS.word.username, { exact: true }).fill(username)
    if (email !== undefined) await dialog.getByLabel(LABELS.word.email, { exact: true }).fill(email)
    await dialog.getByLabel(LABELS.word.password, { exact: true }).fill('a-long-enough-password')
    await dialog.getByRole('button', { name: LABELS.action.create.verb, exact: true }).click()
}

test('there is no admin overview: the heading is a word, and the bare address is nowhere', async ({
    page,
}) => {
    await signIn(page)
    await page.goto('/admin/users')
    await expect(page.getByRole('link', { name: LABELS.screen.admin, exact: true })).toHaveCount(0)
    await expect(
        page.getByRole('complementary').getByText(LABELS.screen.admin, { exact: true }),
    ).toBeVisible()

    await page.goto('/admin')
    await expect(page.getByRole('main')).toContainText(LABELS.screen.nowhere)
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

    // A column saying `active` of every row is no column: only what is not active says so.
    await expect(rowOf(page, username)).not.toContainText(LABELS.state.armed.deactivated)

    // The row's actions are in the panel, which selecting it opens.
    await rowOf(page, username).click()
    const panel = page.getByRole('tabpanel')

    // The panel heads the account the way every panel in this app heads a thing: with no name
    // on it the title is what it signs in as, and it wears the mono face itself.
    await expect(panel.getByText(username, { exact: true })).toBeVisible()
    await expect(panel).toContainText('viewer')

    // When it was made and whether it has ever been used are read here, not counted.
    await expect(panel).toContainText(LABELS.word.created.label)
    await expect(panel).toContainText(LABELS.users.never_signed_in)

    await panel.getByRole('button', { name: LABELS.action.deactivate }).click()
    await expect(rowOf(page, username)).toContainText('deactivated')

    // And the panel says so of itself, rather than leaving the button label to imply it.
    await expect(panel).toContainText('deactivated')
})

test('the last admin cannot deactivate itself, and is told so where it asked', async ({ page }) => {
    await signIn(page)
    await page.goto('/admin/users')

    await rowOf(page, DEV_USERNAME).click()
    await page.getByRole('button', { name: LABELS.action.deactivate }).click()

    // The refusal is the server's own sentence, rendered beside the button that asked for it
    // rather than as a toast that outlives the screen. Its status phrase is not a heading: it
    // would say "Conflict" of every refusal this screen can make.
    await expect(page.getByText('the only active admin')).toBeVisible()

    // And nothing changed: the account is still active and still an admin.
    await expect(rowOf(page, DEV_USERNAME)).not.toContainText(LABELS.state.armed.deactivated)
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

    await openSettings(page)
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    // Appearance lives under Theme, the same axis the header's own menu writes.
    await dialog.getByRole('button', { name: LABELS.settings.category.theme, exact: true }).click()
    await dialog.getByRole('button', { name: LABELS.shell.mode.dark, exact: true }).click()
    await expect(page.locator('html')).toHaveClass(/dark/)
    await dialog.getByRole('button', { name: LABELS.shell.mode.light, exact: true }).click()
    await expect(page.locator('html')).not.toHaveClass(/dark/)

    // The clock lives under General; the formatters read it, so a timestamp behind moves.
    await dialog.getByRole('button', { name: LABELS.settings.category.general, exact: true }).click()
    await dialog.getByRole('button', { name: LABELS.measure.utc, exact: true }).click()
    await page.keyboard.press('Escape')
    await expect(started).toHaveAttribute('title', /UTC/)
})

test('the settings search reaches across every category', async ({ page }) => {
    await signIn(page)
    await openSettings(page)
    const dialog = page.getByRole('dialog')

    await dialog.getByLabel(LABELS.settings.search).fill('password')
    await expect(dialog.getByRole('button', { name: LABELS.word.account.label, exact: true })).toBeVisible()
    await expect(
        dialog.getByRole('button', { name: LABELS.settings.category.general, exact: true }),
    ).toHaveCount(0)

    // One box across the renamed groups: a palette is a Theme row and a chord is a Shortcuts one.
    await dialog.getByLabel(LABELS.settings.search).fill('palette')
    await expect(
        dialog.getByRole('button', { name: LABELS.settings.category.theme, exact: true }),
    ).toBeVisible()
    await expect(
        dialog.getByRole('button', { name: LABELS.settings.category.shortcuts, exact: true }),
    ).toBeVisible()

    await dialog.getByLabel(LABELS.settings.search).fill('stroopwafel')
    await expect(dialog.getByText(LABELS.settings.no_match)).toBeVisible()
})

test('the nav is three groups and About is not one of them', async ({ page }) => {
    await signIn(page)
    await openSettings(page)
    const dialog = page.getByRole('dialog')

    for (const group of ['Preferences', 'You', 'This instance']) {
        await expect(dialog.getByText(group, { exact: true })).toBeVisible()
    }
    await expect(dialog.getByRole('button', { name: 'About', exact: true })).toHaveCount(0)

    // The version lives on Server, and the two links are at that pane's foot.
    await dialog.getByRole('button', { name: LABELS.settings.category.server, exact: true }).click()
    await expect(dialog.getByText(LABELS.word.version.label, { exact: true })).toBeVisible()
    await expect(dialog.getByRole('link', { name: LABELS.settings.documentation })).toBeVisible()
    await expect(dialog.getByRole('link', { name: LABELS.settings.api_reference })).toHaveAttribute(
        'href',
        '/docs',
    )
})

test('a palette is chosen from its swatch, by pointer and by the arrows', async ({ page }) => {
    await signIn(page)
    await openSettings(page)
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('button', { name: LABELS.settings.category.theme, exact: true }).click()

    const paper = dialog.getByRole('radio', { name: LABELS.shell.colours.paper })
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
    await openSettings(page)
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('button', { name: LABELS.word.account.label, exact: true }).click()

    // Nothing is over the dialog: the form is in the row, and the button that opened it is gone.
    await dialog.getByRole('button', { name: LABELS.action.change, exact: true }).click()
    await expect(dialog.getByLabel(LABELS.settings.current_password)).toBeVisible()
    await expect(dialog.getByRole('button', { name: LABELS.action.change, exact: true })).toHaveCount(0)

    // The server's own sentence, beside the fields, and the section stays open on a refusal.
    await dialog.getByLabel(LABELS.settings.current_password).fill('not-the-password')
    await dialog.getByLabel('New password').fill('a-long-enough-password')
    await dialog.getByRole('button', { name: LABELS.settings.change_password }).click()
    await expect(dialog.getByRole('alert')).toBeVisible()
    await expect(dialog.getByLabel(LABELS.settings.current_password)).toBeVisible()

    await dialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(dialog.getByLabel(LABELS.settings.current_password)).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: LABELS.action.change, exact: true })).toBeVisible()
})

test('an email is carried into the panel, changed there, and is unique across accounts', async ({ page }) => {
    await signIn(page)
    const username = someone()
    const email = `${username}@example.test`

    await page.goto('/admin/users')
    await createAccount(page, username, email)
    await expect(rowOf(page, username)).toBeVisible()

    // The panel's Email box is where the account's address is, so the input carries it.
    await rowOf(page, username).click()
    const panel = page.getByRole('tabpanel')
    await expect(panel.getByLabel(LABELS.word.email)).toHaveValue(email)

    // Saving a changed one writes it, and reading the panel again answers the new address.
    const moved = `${username}-moved@example.test`
    await panel.getByLabel(LABELS.word.email).fill(moved)
    await panel.getByRole('button', { name: LABELS.action.save.verb }).click()
    await expect(panel.getByRole('button', { name: LABELS.action.save.verb })).toBeDisabled()
    await page.reload()
    await rowOf(page, username).click()
    await expect(page.getByRole('tabpanel').getByLabel(LABELS.word.email)).toHaveValue(moved)

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
    await rowOf(page, username).click()

    await page.getByRole('tabpanel').getByRole('button', { name: LABELS.users.reset_password }).click()
    const dialog = page.getByRole('dialog')

    // A password too short is refused where it was typed, and the dialog stays where it is.
    await dialog.getByLabel('New password').fill('short')
    await dialog.getByRole('button', { name: LABELS.action.reset, exact: true }).click()
    await expect(dialog.getByRole('alert')).toBeVisible()
    await expect(dialog).toBeVisible()

    const changed = 'another-long-password'
    await dialog.getByLabel('New password').fill(changed)
    await dialog.getByRole('button', { name: LABELS.action.reset, exact: true }).click()
    await expect(dialog).toHaveCount(0)

    // The password the reset set is the one that account signs in with from then on.
    await signOut(page)
    await signInAs(page, username, changed)
})

test('a token is made on its account, listed under it, and revoked after a question', async ({ page }) => {
    await signIn(page)
    const username = someone()
    const token = `tok-${username}`

    await page.goto('/admin/users')
    await expect(page.getByRole('heading', { name: LABELS.screen.users.name, exact: true })).toBeVisible()
    await createAccount(page, username)
    await expect(rowOf(page, username)).toBeVisible()

    // An account with none says so when it is opened.
    await page.getByRole('button', { name: LABELS.users.show_tokens(username) }).click()
    await expect(page.getByText(LABELS.users.tokens_empty, { exact: true })).toBeVisible()

    await page.getByRole('button', { name: LABELS.users.new_token_for(username) }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText(LABELS.users.token_scope_for(username))
    await dialog.getByLabel(LABELS.word.name.label).fill(token)
    await dialog.getByRole('button', { name: LABELS.action.create.verb, exact: true }).click()

    // The secret is shown once, beside the account it authenticates as.
    await expect(dialog).toContainText(username)
    await dialog.getByRole('button', { name: LABELS.action.done }).click()

    // It stands under its account, its row says how many, and there is no Prefix anywhere.
    await expect(tokenRowOf(page, token)).toBeVisible()
    await expect(rowOf(page, username)).toContainText('1 token')
    await expect(page.getByRole('main')).not.toContainText('Prefix')

    // Revoking asks first, and the row stays, says so, and offers no second press.
    await tokenRowOf(page, token)
        .getByRole('button', { name: `Revoke ${token}` })
        .click()
    const asking = page.getByRole('dialog', { name: `Revoke ${token}?` })
    await expect(asking.locator('p')).toHaveCount(0)
    await asking.getByRole('button', { name: LABELS.action.revoke, exact: true }).click()
    await expect(asking).toHaveCount(0)
    await expect(tokenRowOf(page, token)).toContainText(LABELS.state.armed.revoked)
    await expect(tokenRowOf(page, token).getByRole('button', { name: `Revoke ${token}` })).toHaveCount(0)
})

test('two live tokens sharing a name show their prefix, and revoking says it takes both', async ({
    page,
}) => {
    await signIn(page)
    const username = someone()
    const prefix = await apiPrefix(page.request)
    const name = 'shared-name'

    await page.goto('/admin/users')
    await createAccount(page, username)
    await expect(rowOf(page, username)).toBeVisible()
    const first = await page.request.post(`${prefix}/users/${username}/tokens`, { data: { name } })
    const second = await page.request.post(`${prefix}/users/${username}/tokens`, { data: { name } })
    expect(first.ok() && second.ok()).toBe(true)
    const heads = [(await first.json()) as { prefix: string }, (await second.json()) as { prefix: string }]

    await page.getByRole('button', { name: LABELS.users.show_tokens(username) }).click()
    for (const head of heads) {
        await expect(page.getByText(LABELS.users.token_prefix(head.prefix), { exact: true })).toBeVisible()
    }

    await tokenRowOf(page, name)
        .first()
        .getByRole('button', { name: `Revoke ${name}` })
        .click()
    const asking = page.getByRole('dialog', { name: `Revoke ${name}?` })
    await expect(asking).toContainText(LABELS.users.revoke_shared('2'))
})

test('an account holding many tokens walks them in a box of its own', async ({ page }) => {
    await signIn(page)
    const username = someone()
    const prefix = await apiPrefix(page.request)

    await page.goto('/admin/users')
    await createAccount(page, username)
    await expect(rowOf(page, username)).toBeVisible()
    for (let at = 0; at < 60; at += 1) {
        const made = await page.request.post(`${prefix}/users/${username}/tokens`, {
            data: { name: `many-${String(at).padStart(2, '0')}` },
        })
        expect(made.ok()).toBe(true)
    }

    await page.getByRole('button', { name: LABELS.users.show_tokens(username) }).click()
    await expect(tokenRowOf(page, 'many-00')).toBeVisible()

    // The list holds its height, so the accounts around it stay where they were.
    const box = page.locator('[data-account-tokens]')
    const height = (await box.boundingBox())?.height ?? 0
    expect(height).toBeLessThanOrEqual(384)

    // Reaching the foot of the box reads the next page.
    await box.getByRole('button', { name: LABELS.shell.load_more('50') }).scrollIntoViewIfNeeded()
    await expect(box).toContainText('60 tokens')
})
