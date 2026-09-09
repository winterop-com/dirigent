import { expect, test, type Page } from '@playwright/test'

/**
 * The seam between the login's two panes, which is also the handle that moves it.
 *
 * WHAT A UNIT TEST CANNOT SAY. `clampPaneWidth` is a pure function and has its own tests; what
 * this spec is for is the part only a browser has -- a pointer dragging an element that is not
 * where the layout put it until the drag moves it, a choice surviving a reload, and the keys
 * doing what the pointer does.
 */

const MIN = 560
const FORM_COLUMN = 526

/** The seam is a separator, and it is the only one on this screen. */
const seamOf = (page: Page) => page.getByRole('separator', { name: 'Resize the brand pane' })

const paneWidth = async (page: Page) =>
    (await page.locator('aside').boundingBox().then((box) => box?.width)) ?? 0

async function openLogin(page: Page, width: number, height: number): Promise<void> {
    await page.setViewportSize({ width, height })
    await page.goto('/login')
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
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

test('the seam drags, and what it was dragged to comes back with the browser', async ({
    page,
}) => {
    await openLogin(page, 1440, 900)
    const before = await paneWidth(page)

    // 200 is past what a 1440 window has room for, so the drag stops on the bound rather than
    // where the pointer went: the pane's maximum is what the form column leaves of the window.
    await dragSeam(page, 200)
    expect(await paneWidth(page)).toBeCloseTo(1440 - FORM_COLUMN, 0)

    // A drag with room in front of it moves exactly as far as the pointer did.
    await dragSeam(page, -100)
    const narrowed = await paneWidth(page)
    expect(narrowed).toBeCloseTo(1440 - FORM_COLUMN - 100, 0)

    await page.reload()
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
    expect(await paneWidth(page)).toBeCloseTo(narrowed, 0)
    expect(before).toBeLessThan(narrowed)
})

test('the keys move the seam, and Home and End are the bounds', async ({ page }) => {
    await openLogin(page, 1440, 900)
    const seam = seamOf(page)
    await seam.focus()

    await seam.press('End')
    expect(await paneWidth(page)).toBeCloseTo(1440 - FORM_COLUMN, 0)

    await seam.press('Home')
    expect(await paneWidth(page)).toBeCloseTo(MIN, 0)

    // An arrow is sixteen pixels and a shifted one is sixty-four.
    await seam.press('ArrowRight')
    expect(await paneWidth(page)).toBeCloseTo(MIN + 16, 0)
    await seam.press('Shift+ArrowRight')
    expect(await paneWidth(page)).toBeCloseTo(MIN + 80, 0)

    // The separator states where it stands, for a reader who cannot see the seam at all.
    await expect(seam).toHaveAttribute('aria-valuenow', String(MIN + 80))
    await expect(seam).toHaveAttribute('aria-valuemin', String(MIN))
    await expect(seam).toHaveAttribute('aria-valuemax', String(1440 - FORM_COLUMN))
})

test('a double-click gives the pane its own clamp back, and so does Delete', async ({ page }) => {
    await openLogin(page, 1440, 900)
    const clamped = await paneWidth(page)

    await seamOf(page).press('End')
    expect(await paneWidth(page)).not.toBeCloseTo(clamped, 0)

    await seamOf(page).dblclick()
    expect(await paneWidth(page)).toBeCloseTo(clamped, 0)

    await seamOf(page).press('End')
    await seamOf(page).press('Delete')
    expect(await paneWidth(page)).toBeCloseTo(clamped, 0)

    // The clamp is what a fresh browser gets, so nothing was left behind in storage.
    await page.reload()
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
    expect(await paneWidth(page)).toBeCloseTo(clamped, 0)
})

test('there is no seam to drag below lg', async ({ page }) => {
    await openLogin(page, 390, 844)
    await expect(seamOf(page)).toBeHidden()
    await openLogin(page, 1000, 900)
    await expect(seamOf(page)).toBeHidden()
})

test('two columns keep the pane at its floor', async ({ page }) => {
    await openLogin(page, 1024, 900)
    await expect(seamOf(page)).toBeVisible()
    expect(await paneWidth(page)).toBeGreaterThanOrEqual(MIN)
})
