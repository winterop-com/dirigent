import { expect, test } from '@playwright/test'

import { signIn } from './support.ts'

/**
 * The command palette, driven the way it is actually used: a chord, a few letters, a row.
 *
 * WHAT IS WORTH A BROWSER HERE is the part `lib/palette`'s own tests cannot reach -- that the
 * chord is bound at all, that the registry's filter is what narrows the list rather than cmdk's,
 * and that the shelf the screen registered leads the ones the shell did.
 */

test.beforeEach(async ({ page }) => {
    await signIn(page)
    // The chord is a keydown the shell has to be listening for: on a slow runner a press
    // fired before the shell mounts is simply lost, so the chip standing in the topbar is
    // the precondition every chord below relies on.
    await expect(page.getByLabel('Instance')).toBeVisible()
})

test('a chord opens it, and escape closes it again', async ({ page }) => {
    await page.keyboard.press('ControlOrMeta+k')
    await expect(page.getByPlaceholder('Go to a screen, or run something')).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(page.getByPlaceholder('Go to a screen, or run something')).toBeHidden()
})

test('typing narrows it to the rows that answer, and drops the rest', async ({ page }) => {
    await page.keyboard.press('ControlOrMeta+k')
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('option').filter({ hasText: /^Connections/ })).toHaveCount(1)

    await page.getByPlaceholder('Go to a screen, or run something').fill('connection')
    await expect(dialog.getByRole('option').filter({ hasText: /^Connections/ })).toHaveCount(1)
    await expect(dialog.getByRole('option').filter({ hasText: /^Runs/ })).toHaveCount(0)
    await expect(dialog.getByRole('option').filter({ hasText: /^Workers/ })).toHaveCount(0)
})

test('the shelf the screen registered is laid out first', async ({ page }) => {
    // The pipelines listing registers its own rows: new, new from a file, re-read. The front
    // door a session begins on registers a shelf of its own, so this asks the question on the
    // screen whose shelf it names.
    await page.goto('/pipelines')
    await page.keyboard.press('ControlOrMeta+k')
    // The screen registers its rows from an effect, so the first shelf is asserted with a
    // retrying expectation rather than read once out of the markup.
    const headings = page.getByRole('dialog').locator('[cmdk-group-heading]')
    await expect(headings.first()).toHaveText('This listing')
    expect(await headings.count()).toBeGreaterThan(1)
})

test('choosing a row runs it, and the palette is gone before the screen changes', async ({ page }) => {
    await page.keyboard.press('ControlOrMeta+k')
    await page.getByPlaceholder('Go to a screen, or run something').fill('runs')
    // A row's accessible name is its title and the muted line beside it, so it is filtered on
    // rather than matched exactly.
    await page.getByRole('option').filter({ hasText: /^Runs/ }).first().click()

    await expect(page).toHaveURL(/\/runs$/)
    await expect(page.getByPlaceholder('Go to a screen, or run something')).toBeHidden()
})

test('a query nothing answers says so rather than showing everything', async ({ page }) => {
    await page.keyboard.press('ControlOrMeta+k')
    await page.getByPlaceholder('Go to a screen, or run something').fill('stroopwafel')
    await expect(page.getByText('Nothing here answers to that')).toBeVisible()
})
