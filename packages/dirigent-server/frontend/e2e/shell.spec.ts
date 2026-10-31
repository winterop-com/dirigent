import { expect, test, type Page } from '@playwright/test'

import { LABELS } from '../src/lib/labels.ts'
import { applyExample, signIn } from './support.ts'

/**
 * The chassis itself: the top row across the app, the rail that hides whole, and what the corner
 * says it is.
 *
 * THE TOP ROW IS MEASURED, NOT EYEBALLED. The rail's head, the top strip and the right panel's tab
 * strip are three elements in three columns, and the mark, the crumb and the tabs sit on one line
 * only when the three are exactly as tall and start at the same y.
 */

/** Every top strip's box, in the order they appear across the width. */
async function topStrips(page: Page): Promise<{ top: number; height: number }[]> {
    return page.evaluate(() =>
        [...document.querySelectorAll('[data-shell-strip="top"]')].map((element) => {
            const box = element.getBoundingClientRect()
            return { top: Math.round(box.top), height: Math.round(box.height) }
        }),
    )
}

test.beforeEach(async ({ page }) => {
    await signIn(page)
    // The measurements below read the chrome's geometry the instant the test body runs; on a
    // slow runner the shell has not mounted yet and querySelector returns null.
    await expect(page.locator('[data-shell-strip="top"]').first()).toBeVisible()
})

test('every strip along the top starts and ends at the same y', async ({ page }) => {
    const strips = await topStrips(page)
    expect(strips.length).toBeGreaterThanOrEqual(2)
    for (const strip of strips) {
        expect(strip.top).toBe(strips[0].top)
        expect(strip.height).toBe(strips[0].height)
    }
})

test('there is no bar along the foot and no rule across the top', async ({ page }) => {
    await expect(page.locator('footer')).toHaveCount(0)
    await expect(page.locator('[data-shell-rule]')).toHaveCount(0)
})

test('the account stands at the foot of the rail', async ({ page }) => {
    const rail = await page.locator('aside').first().boundingBox()
    const account = await page.getByRole('button', { name: /^Account: / }).boundingBox()
    if (rail === null || account === null) throw new Error('no rail or no account')
    expect(rail.y + rail.height - (account.y + account.height)).toBeLessThan(32)
    expect(account.x + account.width).toBeLessThanOrEqual(rail.x + rail.width)
})

test('the rail hides whole and the strip brings it back', async ({ page }) => {
    await page.keyboard.press('ControlOrMeta+b')
    await expect(page.getByRole('link', { name: LABELS.screen.pipelines.name })).toHaveCount(0)
    await page.getByRole('button', { name: LABELS.shell.show_nav }).click()
    await expect(page.getByRole('link', { name: LABELS.screen.pipelines.name })).toBeVisible()

    const strips = await topStrips(page)
    expect(strips.length).toBeGreaterThanOrEqual(2)
    for (const strip of strips) {
        expect(strip.top).toBe(strips[0].top)
        expect(strip.height).toBe(strips[0].height)
    }
})

test('the seams hold with the right panel open', async ({ page }) => {
    // The panel exists only when a screen fills it, so open a document and choose a box on it.
    await applyExample(page.request, 'examples/transform/jq-reshape.yaml')
    await page.goto('/pipelines/jq-reshape/edit')
    await page.locator('.react-flow__node').first().click()
    await expect(page.getByRole('tab', { name: LABELS.word.step.label })).toBeVisible()

    const strips = await topStrips(page)
    expect(strips.length).toBe(3)
    for (const strip of strips) {
        expect(strip.top).toBe(strips[0].top)
        expect(strip.height).toBe(strips[0].height)
    }
})

test('the seams hold in the light palette as they do in the dark one', async ({ page }) => {
    await page.goto('/pipelines')
    // The system palette is the dark one here, so the light one below is the stored choice's
    // doing: without this the default would answer light and the choice would go untested.
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.evaluate(() => {
        localStorage.setItem('theme', 'light')
    })
    await page.reload()
    await expect(page.getByRole('heading', { name: LABELS.screen.pipelines.name })).toBeVisible()
    // The palette this test is named for is really the one on the page.
    await expect(page.locator('html')).toHaveClass(/light/)
    await expect(page.locator('html')).not.toHaveClass(/dark/)

    const strips = await topStrips(page)
    expect(strips.length).toBeGreaterThanOrEqual(2)
    for (const strip of strips) {
        expect(strip.top).toBe(strips[0].top)
        expect(strip.height).toBe(strips[0].height)
    }
})

test('the top bar is one dot, and its details are the tooltip', async ({ page }) => {
    const dot = page.getByRole('button', { name: LABELS.shell.instance.label })
    await expect(dot).not.toContainText('dirigent')
    await dot.hover()
    // The name and the environment come from `/system/info`; this suite runs `dg dev`.
    const tip = page.locator('[data-slot="tooltip-content"]')
    await expect(tip).toContainText('dirigent')
    await expect(tip).toContainText('local')
    await expect(tip).toContainText(LABELS.word.version.term)
})

test('pressing the dot opens the settings on the server pane', async ({ page }) => {
    await page.getByRole('button', { name: LABELS.shell.instance.label }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('button', { name: LABELS.action.recheck })).toBeVisible()
})

test('the top bar has words only when something is wrong', async ({ page }) => {
    await page.route('**/health/ready', (route) => route.abort())
    await page.reload()
    const dot = page.getByRole('button', { name: LABELS.shell.instance.label })
    await expect(dot).toContainText(LABELS.shell.instance.wrong.offline)
})

test('a panel nothing has filled is not there at all, toggle included', async ({ page }) => {
    // An unfilled panel would only ever say "nothing selected", so it does not render, and
    // neither does the control that would reveal it.
    await expect(page.getByRole('button', { name: LABELS.shell.toggle_panel })).toHaveCount(0)
    await expect(page.getByText('Nothing selected', { exact: false })).toHaveCount(0)
})

test('an empty listing states the fact and stops', async ({ page }) => {
    // The way a rule is made is a button on this screen, so the empty state names no way in:
    // what New rule does is what New rule says.
    await page.goto('/admin/alerting')
    await expect(page.getByRole('heading', { name: LABELS.screen.alerting.name })).toBeVisible()
    await expect(page.getByText(/No rules\./)).toBeVisible()
    await expect(page.getByRole('button', { name: LABELS.alerting.new_rule.button })).toBeVisible()
})

test('the account menu holds the account, the settings, the shortcuts, the way out and the instance', async ({
    page,
}) => {
    await page.getByRole('button', { name: /^Account: / }).click()
    const menu = page.getByRole('menu')
    await expect(menu).toContainText('admin')
    await expect(menu).toContainText('local')
    await expect(page.getByRole('menuitem', { name: LABELS.shell.settings })).toBeVisible()
    await expect(page.getByRole('menuitem', { name: LABELS.action.sign_out })).toBeVisible()

    // The one key the menu draws is the one `lib/shortcuts` binds.
    await page.getByRole('menuitem', { name: LABELS.settings.category.shortcuts }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
})

test('signing out from the account menu goes to the door', async ({ page }) => {
    await page.getByRole('button', { name: /^Account: / }).click()
    await page.getByRole('menuitem', { name: LABELS.action.sign_out }).click()
    await expect(page).toHaveURL(/\/login/)
})
