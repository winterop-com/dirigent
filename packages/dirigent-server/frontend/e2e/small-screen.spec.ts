import { expect, test } from '@playwright/test'

import { applyExample, signIn } from './support.ts'

/**
 * Every screen at the size of a phone.
 *
 * ONE VIEWPORT, THE WHOLE SHELL. What is asserted here is what the small-screen rules say the
 * app becomes below `md`: navigation behind a drawer, a listing as cards, a document read
 * rather than written, and a dialog as a sheet. The desktop suite covers the same screens the
 * other way round, so nothing here is a second copy of what shell.spec.ts already measures.
 */

const EXAMPLE = 'examples/transform/std-convert-fan-out.yaml'
const PIPELINE = 'std-convert-fan-out'
const TITLE = 'Convert and fan out'

test.use({ viewport: { width: 390, height: 844 } })

test.beforeEach(async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, EXAMPLE)
})

test('the navigation is a drawer that opens, and closes on arriving somewhere', async ({ page }) => {
    const drawer = page.locator('[data-nav-drawer]')
    const runs = drawer.getByRole('link', { name: 'Runs' })
    await expect(runs).toBeHidden()

    await page.getByRole('button', { name: 'Open navigation' }).click()
    await expect(runs).toBeVisible()
    await expect(page.getByRole('button', { name: 'Close navigation' })).toBeFocused()

    await runs.click()
    await expect(page).toHaveURL(/\/runs$/)
    await expect(runs).toBeHidden()
})

test('the drawer closes on Escape and on the scrim', async ({ page }) => {
    const drawer = page.locator('[data-nav-drawer]')
    const open = page.getByRole('button', { name: 'Open navigation' })

    await open.click()
    await expect(drawer.getByRole('link', { name: 'Runs' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(drawer.getByRole('link', { name: 'Runs' })).toBeHidden()

    await open.click()
    await page.locator('[data-nav-scrim]').click({ position: { x: 380, y: 700 } })
    await expect(drawer.getByRole('link', { name: 'Runs' })).toBeHidden()
})

test('the pipelines listing is cards, and the page does not scroll sideways', async ({ page }) => {
    await page.goto('/pipelines')
    const card = page.getByRole('listitem').filter({ hasText: PIPELINE })
    await expect(card.getByRole('link', { name: TITLE })).toBeVisible()
    await expect(card.getByText(PIPELINE, { exact: true })).toBeVisible()
    // The columns are gone and their headers with them: what is drawn is a list, not a table.
    await expect(page.getByRole('table')).toHaveCount(0)

    const sideways = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(sideways).toBeLessThanOrEqual(0)
})

test.describe('a tablet', () => {
    // The shell is itself here -- the rail is drawn, there is no drawer -- and the content
    // column beside that rail is still too narrow for a table.
    test.use({ viewport: { width: 900, height: 1024 } })

    test('a listing is still cards while the shell is not small', async ({ page }) => {
        await page.goto('/pipelines')
        await expect(page.getByRole('link', { name: 'Pipelines' })).toBeVisible()
        await expect(page.getByRole('button', { name: 'Open navigation' })).toHaveCount(0)
        await expect(page.getByRole('table')).toHaveCount(0)
        await expect(page.getByRole('listitem').filter({ hasText: PIPELINE }).getByRole('link', { name: TITLE })).toBeVisible()
    })
})

test('the editor reads the document and offers nothing that would write one', async ({ page }) => {
    await page.goto(`/pipelines/${PIPELINE}`)
    await expect(page.getByText('Read only on a small screen')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Apply' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Run', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Validate' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Add step' })).toHaveCount(0)
    // The panel is under the screen rather than beside it, and its tabs are along the foot.
    await expect(page.locator('[data-panel-bar]').getByRole('button', { name: 'Source' })).toBeVisible()
})

test('the panel is a sheet raised from the tab bar', async ({ page }) => {
    await page.goto(`/pipelines/${PIPELINE}`)
    const sheet = page.locator('[data-panel-sheet]')
    await expect(sheet).toBeHidden()

    await page.locator('[data-panel-bar]').getByRole('button', { name: 'Source' }).click()
    await expect(sheet).toBeVisible()
    await sheet.getByRole('button', { name: 'Close the panel' }).click()
    await expect(sheet).toBeHidden()
})

test('a dialog fills the screen, with its verbs at the foot', async ({ page }) => {
    await page.getByRole('button', { name: 'Open navigation' }).click()
    await page.getByRole('button', { name: 'Settings' }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    // The dialog scales in, so its box is read once every animation on it has finished.
    const window = page.viewportSize()
    await expect
        .poll(async () => {
            const box = await dialog.boundingBox()
            return box === null ? null : [Math.round(box.width), Math.round(box.height), Math.round(box.x), Math.round(box.y)]
        })
        .toEqual([window?.width, window?.height, 0, 0])
})
