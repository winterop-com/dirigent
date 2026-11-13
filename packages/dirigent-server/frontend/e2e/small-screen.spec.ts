import { expect, test, type Locator } from '@playwright/test'

import { LABELS } from '../src/lib/labels.ts'
import { apiPrefix, applyExample, DEV_USERNAME, signIn, startRun } from './support.ts'

/**
 * Every screen at the size of a phone.
 *
 * ONE VIEWPORT, THE WHOLE SHELL. What is asserted here is what the small-screen rules say the
 * app becomes below `md`: navigation behind a drawer, a listing as cards, a document read
 * rather than written, a form dialog as a sheet and a confirm sized to its question. The desktop
 * suite covers the same screens the other way round, so nothing here is a second copy of what
 * shell.spec.ts already measures.
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
    const runs = page.getByRole('link', { name: LABELS.screen.runs.name, exact: true })
    await expect(runs).toBeHidden()

    const open = page.getByRole('button', { name: LABELS.shell.open_nav })
    await open.click()
    await expect(runs).toBeVisible()

    await runs.click()
    await expect(page).toHaveURL(/\/runs$/)
    await expect(runs).toBeHidden()
})

test('the drawer closes on Escape, on its own close, and on the scrim', async ({ page }) => {
    const runs = page.getByRole('link', { name: LABELS.screen.runs.name, exact: true })
    const open = page.getByRole('button', { name: LABELS.shell.open_nav })

    await open.click()
    await expect(runs).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(runs).toBeHidden()
    await expect(open).toBeFocused()

    await open.click()
    await page.locator('[data-overlay]').getByRole('button', { name: LABELS.shell.close_nav }).click()
    await expect(runs).toBeHidden()

    await open.click()
    await page.mouse.click(380, 700)
    await expect(runs).toBeHidden()
})

test('a pipeline row wraps on a phone, and the page does not scroll sideways', async ({ page }) => {
    await page.goto('/pipelines?examples=all')
    const row = page.getByTestId('pipeline-row').filter({ has: page.getByTitle(TITLE, { exact: true }) })
    await expect(row).toBeVisible()
    await expect(row.getByText(PIPELINE, { exact: true })).toBeVisible()
    await expect(page.getByRole('table')).toHaveCount(0)

    const sideways = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(sideways).toBeLessThanOrEqual(0)
})

test.describe('a tablet', () => {
    // The shell is itself here -- the rail is drawn, there is no drawer -- and the content
    // column beside that rail is still too narrow for a table.
    test.use({ viewport: { width: 900, height: 1024 } })

    test('a listing is still cards while the shell is not small', async ({ page }) => {
        await page.goto('/runs')
        await expect(page.getByRole('link', { name: LABELS.screen.pipelines.name })).toBeVisible()
        await expect(page.getByRole('button', { name: LABELS.shell.open_nav })).toHaveCount(0)
        await expect(page.getByRole('columnheader')).toHaveCount(0)
        await expect(page.getByRole('row').first()).toBeVisible()
    })
})

test('the editor reads the document and offers nothing that would write one', async ({ page }) => {
    await page.goto(`/pipelines/${PIPELINE}/edit`)
    await expect(page.getByText(LABELS.editor.topbar.read_only)).toBeVisible()
    await expect(page.getByRole('button', { name: LABELS.action.apply })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Run…', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: LABELS.action.validate })).toHaveCount(0)
    await expect(page.getByRole('button', { name: LABELS.editor.canvas.add_step })).toHaveCount(0)
    // The panel is under the screen rather than beside it, and its tabs are along the foot.
    await expect(
        page
            .getByRole('tablist', { name: LABELS.shell.panel_tabs })
            .getByRole('tab', { name: LABELS.word.source }),
    ).toBeVisible()
})

test('the panel is a sheet raised from the tab strip', async ({ page }) => {
    await page.goto(`/pipelines/${PIPELINE}/edit`)
    const sheet = page.getByRole('tabpanel', { name: LABELS.word.source })
    await expect(sheet).toBeHidden()

    const tab = page
        .getByRole('tablist', { name: LABELS.shell.panel_tabs })
        .getByRole('tab', { name: LABELS.word.source })
    await tab.click()
    await expect(sheet).toBeVisible()
    await expect(tab).toHaveAttribute('aria-selected', 'true')
    await page.keyboard.press('Escape')
    await expect(sheet).toBeHidden()
})

test('what a finger lands on is at least 44px tall', async ({ page }) => {
    // The token every control below the breakpoint takes its minimum from.
    const FINGER = 44

    await page.goto('/schemas')
    await page.getByRole('button', { name: LABELS.schemas.new }).click()
    const footer = page.getByRole('dialog').locator('[data-slot="dialog-footer"]')
    await expect(footer.getByRole('button', { name: LABELS.action.create.verb })).toBeVisible()

    // The dialog scales in, so the boxes are read once every animation on it has finished.
    await expect
        .poll(async () => {
            const boxes = await footer.getByRole('button').all()
            const heights = await Promise.all(
                boxes.map(async (button) => (await button.boundingBox())?.height ?? 0),
            )
            return heights.length > 0 && heights.every((height) => height >= FINGER)
        })
        .toBe(true)

    await page.keyboard.press('Escape')

    await page.goto(`/pipelines/${PIPELINE}/edit`)
    const tabs = page.getByRole('tablist', { name: LABELS.shell.panel_tabs }).getByRole('tab')
    await expect(tabs.first()).toBeVisible()
    for (const tab of await tabs.all()) {
        expect((await tab.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(FINGER)
    }

    // A LINK DRAWN AS A CONTROL IS A CONTROL. The `API` chip is a chip of the control size.
    await page.goto('/pipelines')

    // The listing's bar is a finger tall throughout: the search box and every filter chip.
    for (const control of [
        page.locator('[data-slot="search-field"]'),
        page.locator('[data-slot="filter-chip"]'),
    ]) {
        await expect(control).toBeVisible()
        expect((await control.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(FINGER)
    }

    const api = page.locator('[data-slot="chip"]').filter({ has: page.getByRole('link', { name: 'API' }) })
    await expect(api).toBeVisible()
    expect((await api.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(FINGER)
})

test('the trail is the way back: the last screen above alone', async ({ page }) => {
    const run = await startRun(page.request, PIPELINE)
    await page.goto(`/runs/${run}`)
    const trail = page.getByRole('navigation', { name: LABELS.shell.breadcrumb })
    await expect(trail.getByRole('link', { name: TITLE })).toBeVisible()
    await expect(trail.getByRole('link', { name: LABELS.screen.runs.name })).toBeHidden()
    await trail.getByRole('link', { name: TITLE }).click()
    await expect(page).toHaveURL(new RegExp(`/pipelines/${PIPELINE}$`))
})

test('the drawer entries are at least 44px tall', async ({ page }) => {
    await page.goto('/pipelines')
    await page.getByRole('button', { name: LABELS.shell.open_nav }).click()
    const drawer = page.locator('[data-overlay]')
    await expect(drawer.getByRole('link', { name: LABELS.screen.runs.name, exact: true })).toBeVisible()
    const entries = await drawer.getByRole('navigation').getByRole('link').all()
    expect(entries.length).toBeGreaterThan(0)
    for (const entry of entries) {
        expect((await entry.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
    }
})

test('a bare status dot stays a dot, and is not grown to a finger', async ({ page }) => {
    // REVERT-PROOF: a bare dot is its own tooltip's trigger, and a finger rule for triggers drew
    // it 44px tall, which a graph node's 15px row cannot hold. Neither its box nor its disc grows.
    await page.goto('/design')
    const dots = page.locator('[data-gallery="dots"] [data-slot="dot"][role="img"]')
    await expect(dots.first()).toBeVisible()
    // The mark is a box one line tall with the disc in its middle: the disc stays a dot, and the
    // box stays a line rather than a finger.
    for (const dot of await dots.all()) {
        expect((await dot.boundingBox())?.height ?? 0).toBeLessThanOrEqual(24)
        const disc = await dot.locator('> [aria-hidden]').boundingBox()
        expect(disc?.height ?? 0).toBeLessThanOrEqual(10)
        expect(disc?.width ?? 0).toBeLessThanOrEqual(10)
    }
})

test('the palette button is a glyph, and the chord it would have drawn is not', async ({ page }) => {
    const palette = page.getByRole('button', { name: LABELS.shell.palette_button })
    await expect(palette.locator('svg')).toBeVisible()
    await expect(palette.locator('span')).toBeHidden()
    await expect(palette.locator('kbd')).toBeHidden()

    await palette.click()
    await expect(page.getByRole('dialog')).toBeVisible()
})

test('the palette button is a finger square', async ({ page }) => {
    const palette = page.getByRole('button', { name: LABELS.shell.palette_button })
    const box = await palette.boundingBox()
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(44)
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44)
})

/** A box rounded to whole pixels as `[x, y, width, height]`, or null while there is none. */
async function boxOf(locator: Locator): Promise<number[] | null> {
    const box = await locator.boundingBox()
    return box === null ? null : [box.x, box.y, box.width, box.height].map(Math.round)
}

test('a form dialog fills the screen, with its verbs at the foot', async ({ page }) => {
    await page.goto('/schemas')
    await page.getByRole('button', { name: LABELS.schemas.new }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    // The dialog scales in, so its box is read once every animation on it has finished.
    const window = page.viewportSize()
    const width = window?.width ?? 0
    const height = window?.height ?? 0
    await expect.poll(() => boxOf(dialog)).toEqual([0, 0, width, height])

    const footer = await boxOf(dialog.locator('[data-slot="dialog-footer"]'))
    expect((footer?.[1] ?? 0) + (footer?.[3] ?? 0)).toBeGreaterThanOrEqual(height - 1)
})

test('a confirm is sized to its question, with its verbs under it', async ({ page }) => {
    const prefix = await apiPrefix(page.request)
    const name = `phone-confirm-${String(Date.now())}`
    const minted = await page.request.post(`${prefix}/users/${DEV_USERNAME}/tokens`, { data: { name } })
    expect(minted.ok(), await minted.text()).toBe(true)

    await page.goto('/admin/users')
    await page.getByRole('button', { name: LABELS.users.show_tokens(DEV_USERNAME), exact: true }).click()
    await page.getByRole('button', { name: LABELS.users.revoke_row(name), exact: true }).click()

    const dialog = page.getByRole('dialog', { name: `Revoke ${name}?` })
    await expect(dialog).toBeVisible()
    const window = page.viewportSize()
    const width = window?.width ?? 0
    const height = window?.height ?? 0
    await expect
        .poll(async () => {
            const box = await boxOf(dialog)
            return box !== null && box[0] > 0 && box[2] < width && box[3] < height / 2
        })
        .toBe(true)

    // The verbs sit directly under the question, not at the foot of the screen.
    const box = await boxOf(dialog)
    const footer = await boxOf(dialog.locator('[data-slot="dialog-footer"]'))
    expect((footer?.[1] ?? 0) + (footer?.[3] ?? 0)).toBeLessThanOrEqual((box?.[1] ?? 0) + (box?.[3] ?? 0))
    expect((footer?.[1] ?? height) + (footer?.[3] ?? 0)).toBeLessThan(height - 100)

    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
})

test('the channels are folded behind their own heading, and open as a table', async ({ page }) => {
    await page.goto('/admin/alerting')
    const fold = page.getByRole('button', { name: LABELS.alerting.channels_heading })
    await expect(fold).toHaveAttribute('aria-expanded', 'false')
    expect((await fold.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
    // Folded, the dots are the whole of what the strip says; the way in is not drawn at all.
    const door = page.getByRole('link', { name: 'Set up webhook' })
    await expect(door).toBeHidden()

    await fold.click()
    await expect(fold).toHaveAttribute('aria-expanded', 'true')
    await expect(page.getByRole('table')).toBeVisible()
    await expect(door).toBeVisible()
})

test('an account card labels its facts, and New token stands on a line of its own at their edge', async ({
    page,
}) => {
    await page.goto('/admin/users')
    const control = page.getByRole('button', { name: LABELS.users.new_token_for(DEV_USERNAME), exact: true })
    const card = page.getByRole('row').filter({ has: control })
    await expect(control).toBeVisible()

    // Its line holds the control and nothing else: no label beside it.
    await expect(control.locator('xpath=..')).toHaveText(LABELS.users.new_token)

    // The control starts where the labelled facts do.
    const left = (await control.boundingBox())?.x ?? -1
    const edge = (await card.getByText(LABELS.word.role, { exact: true }).boundingBox())?.x ?? -2
    expect(Math.abs(left - edge)).toBeLessThanOrEqual(1)
})
