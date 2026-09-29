import { expect, test } from '@playwright/test'

import { LABELS } from '../src/lib/labels.ts'
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
    await expect(page.getByLabel(LABELS.shell.instance.label)).toBeVisible()
})

test('a chord opens it, and escape closes it again', async ({ page }) => {
    await page.keyboard.press('ControlOrMeta+k')
    await expect(page.getByPlaceholder(LABELS.palette.placeholder)).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(page.getByPlaceholder(LABELS.palette.placeholder)).toBeHidden()
})

test('typing narrows it to the rows that answer, and drops the rest', async ({ page }) => {
    await page.keyboard.press('ControlOrMeta+k')
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('option').filter({ hasText: /^Connections/ })).toHaveCount(1)

    await page.getByPlaceholder(LABELS.palette.placeholder).fill('connection')
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
    await expect(headings.first()).toHaveText(LABELS.palette.shelf.list)
    expect(await headings.count()).toBeGreaterThan(1)
})

test('choosing a row runs it, and the palette is gone before the screen changes', async ({ page }) => {
    await page.keyboard.press('ControlOrMeta+k')
    await page.getByPlaceholder(LABELS.palette.placeholder).fill('runs')
    // A row's accessible name is its title and the muted line beside it, so it is filtered on
    // rather than matched exactly.
    await page.getByRole('option').filter({ hasText: /^Runs/ }).first().click()

    await expect(page).toHaveURL(/\/runs$/)
    await expect(page.getByPlaceholder(LABELS.palette.placeholder)).toBeHidden()
})

/**
 * ONE INSET, AND EVERY PART OF THE DIALOG ON IT.
 *
 * The palette lays out its own body rather than taking the generated dialog's padding, so the
 * only thing holding its search glyph, its shelf headings, its rows and its footer on one edge
 * is that they are all spending the same number. Read off the rendered boxes, because that is
 * where the three different insets this replaced were visible and nowhere else.
 */
test('the search glyph, a heading, a row and the footer stand on one left edge', async ({ page }) => {
    await page.goto('/pipelines')
    await page.keyboard.press('ControlOrMeta+k')
    const dialog = page.getByRole('dialog')
    await expect(dialog.locator('[cmdk-group-heading]').first()).toBeVisible()

    const lefts = await dialog.evaluate((box) => {
        const at = (element: Element | null) =>
            element === null
                ? null
                : Math.round(element.getBoundingClientRect().left - box.getBoundingClientRect().left)
        const heading = box.querySelector('[cmdk-group-heading]')
        const headingText =
            heading === null ? null : Number(getComputedStyle(heading).paddingInlineStart.replace('px', ''))
        return {
            glyph: at(box.querySelector('[data-slot="input-group-addon"] svg')),
            heading: (at(heading) ?? 0) + (headingText ?? 0),
            rowTile: at(box.querySelector('[data-slot="command-item"] span')),
            footer: at(box.querySelector('[data-slot="palette-footer"] > *')),
        }
    })

    expect(lefts.glyph).toBe(16)
    expect(lefts.heading).toBe(16)
    expect(lefts.rowTile).toBe(16)
    expect(lefts.footer).toBe(16)
})

/** The search row is the inset above and below a line of its text, not a boxed input. */
test('the search text stands the inset below the top of the dialog', async ({ page }) => {
    await page.keyboard.press('ControlOrMeta+k')
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByPlaceholder(LABELS.palette.placeholder)).toBeVisible()

    const gap = await dialog.evaluate((box) => {
        const field = box.querySelector('[data-slot="command-input"]')
        if (field === null) return null
        return Math.round(field.getBoundingClientRect().top - box.getBoundingClientRect().top)
    })
    expect(gap).toBe(16)
})

test('a query nothing answers says so rather than showing everything', async ({ page }) => {
    await page.keyboard.press('ControlOrMeta+k')
    await page.getByPlaceholder(LABELS.palette.placeholder).fill('stroopwafel')
    await expect(page.getByText(LABELS.palette.empty)).toBeVisible()
})
