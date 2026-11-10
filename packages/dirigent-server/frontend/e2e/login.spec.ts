import { expect, test, type Page } from '@playwright/test'
import { LABELS } from '../src/lib/labels.ts'

/**
 * The login screen in a browser: the seam between its two panes, where the stacked form stands on
 * a phone, and the keyboard's way through the form.
 */

/** sokkel-ui's `SignIn`: the brand pane is at least 320px, and the form keeps 480px beside it. */
const BRAND_MIN = 320
const FORM_ROOM = 480

const seamOf = (page: Page) => page.getByRole('separator', { name: LABELS.login.seam })

const paneWidth = async (page: Page) =>
    (await page
        .locator('aside')
        .boundingBox()
        .then((box) => box?.width)) ?? 0

async function openLogin(page: Page, width: number, height: number): Promise<void> {
    await page.setViewportSize({ width, height })
    await page.goto('/login')
    await expect(page.getByRole('heading', { name: LABELS.action.sign_in.verb })).toBeVisible()
}

/** Drag the seam by `by` pixels, from wherever it is standing. */
async function dragSeam(page: Page, by: number): Promise<void> {
    const box = await seamOf(page).boundingBox()
    if (box === null) throw new Error('no seam')
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width / 2 + by, box.y + box.height / 2, { steps: 10 })
    await page.mouse.up()
}

test('the seam drags the brand pane', async ({ page }) => {
    await openLogin(page, 1440, 900)
    const before = await paneWidth(page)

    await dragSeam(page, -100)
    expect(await paneWidth(page)).toBeCloseTo(before - 100, 0)
})

test('a double-click on the seam puts the pane back', async ({ page }) => {
    await openLogin(page, 1440, 900)
    const before = await paneWidth(page)

    await seamOf(page).press('Home')
    expect(await paneWidth(page)).toBeCloseTo(BRAND_MIN, 0)

    await seamOf(page).dblclick()
    expect(await paneWidth(page)).toBeCloseTo(before, 0)
})

test('the keys move the seam, and Home and End are the bounds', async ({ page }) => {
    await openLogin(page, 1440, 900)
    const seam = seamOf(page)
    await seam.focus()

    await seam.press('End')
    expect(await paneWidth(page)).toBeCloseTo(1440 - FORM_ROOM, 0)

    await seam.press('Home')
    expect(await paneWidth(page)).toBeCloseTo(BRAND_MIN, 0)

    await seam.press('ArrowRight')
    expect(await paneWidth(page)).toBeCloseTo(BRAND_MIN + 16, 0)

    await expect(seam).toHaveAttribute('aria-valuenow', String(BRAND_MIN + 16))
    await expect(seam).toHaveAttribute('aria-valuemin', String(BRAND_MIN))
    await expect(seam).toHaveAttribute('aria-valuemax', String(1440 - FORM_ROOM))
})

test('there is no seam to drag on a phone', async ({ page }) => {
    await openLogin(page, 390, 844)
    await expect(seamOf(page)).toBeHidden()
})

test('the stacked form stands under the brand bar', async ({ page }) => {
    await openLogin(page, 390, 844)
    const bar = await page.locator('header').boundingBox()
    const eyebrow = await page.getByText(LABELS.login.eyebrow).boundingBox()
    if (bar === null || eyebrow === null) throw new Error('no stacked login')

    const under = eyebrow.y - (bar.y + bar.height)
    expect(under).toBeGreaterThanOrEqual(0)
    expect(under).toBeLessThanOrEqual(80)
})

test('the brand pane names the instance this door answers for', async ({ page }) => {
    await openLogin(page, 1440, 900)
    const pane = page.locator('aside')
    await expect(pane.getByText(LABELS.login.wordmark, { exact: true })).toBeVisible()
    await expect(pane.getByText(new URL(page.url()).host, { exact: true })).toBeVisible()
})

test('the keyboard reaches the fields in order, and the toggle shows the password', async ({ page }) => {
    await openLogin(page, 1440, 900)
    const username = page.getByLabel(LABELS.word.username)
    const password = page.getByLabel(LABELS.word.password, { exact: true })
    await expect(username).toHaveAttribute('autocomplete', 'username')
    await expect(password).toHaveAttribute('autocomplete', 'current-password')
    await expect(username).not.toHaveAttribute('placeholder', /./)
    await expect(password).not.toHaveAttribute('placeholder', /./)

    // The button is held until both fields are filled, and a held button takes no focus.
    await username.fill('admin')
    await page.keyboard.press('Tab')
    await expect(password).toBeFocused()
    await page.keyboard.type('secret')
    await page.keyboard.press('Tab')
    const toggle = page.getByRole('button', { name: LABELS.login.show_password })
    await expect(toggle).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(password).toHaveAttribute('type', 'text')
    await page.keyboard.press('Tab')
    await expect(page.getByRole('button', { name: LABELS.action.sign_in.verb })).toBeFocused()
})
