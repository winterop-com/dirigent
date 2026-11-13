import { expect, test, type Page } from '@playwright/test'

import { LABELS } from '../src/lib/labels.ts'

import { applyExample, signIn, startRun } from './support.ts'

/**
 * The chassis itself: the top row across the app, the foot line, the rail that narrows and hides,
 * and what the corner says it is.
 *
 * THE TOP ROW IS MEASURED, NOT EYEBALLED. The rail's head, the top bar and the right panel's tab
 * strip are three elements in three columns, and the mark, the crumb and the tabs sit on one line
 * only when the three are exactly as tall and start at the same y.
 */

/** The rail's head, the top bar and the panel's tab strip, in the order they appear across the width. */
const TOP_STRIPS = '.h-shell-top'

/** Every top strip's box, in the order they appear across the width. */
async function topStrips(page: Page): Promise<{ top: number; height: number }[]> {
    return page.evaluate(
        (selector) =>
            [...document.querySelectorAll(selector)].map((element) => {
                const box = element.getBoundingClientRect()
                return { top: Math.round(box.top), height: Math.round(box.height) }
            }),
        TOP_STRIPS,
    )
}

test.beforeEach(async ({ page }) => {
    await signIn(page)
    // The measurements below read the chrome's geometry the instant the test body runs; on a
    // slow runner the shell has not mounted yet and querySelector returns null.
    await expect(page.locator('header.h-shell-top')).toBeVisible()
})

test('every strip along the top starts and ends at the same y', async ({ page }) => {
    const strips = await topStrips(page)
    expect(strips.length).toBeGreaterThanOrEqual(2)
    for (const strip of strips) {
        expect(strip.top).toBe(strips[0].top)
        expect(strip.height).toBe(strips[0].height)
    }
})

test('the foot is one line across the window, the account in its corner and the version at its end', async ({
    page,
}) => {
    const foot = await page.locator('footer').boundingBox()
    const account = await page.getByRole('button', { name: /^Account: / }).boundingBox()
    if (foot === null || account === null) throw new Error('no foot or no account')
    expect(Math.abs(foot.y + foot.height - (account.y + account.height))).toBeLessThan(8)
    expect(account.x).toBeLessThan(foot.x)
    await expect(page.locator('footer')).toContainText(LABELS.word.version.term)
})

test('the rail hides whole, and the menu button opens it as a drawer meanwhile', async ({ page }) => {
    const rail = page.locator('[data-shell-rail]')
    // The rail's chord is the platform's modifier, which the library reads off the machine.
    await page.keyboard.press('ControlOrMeta+b')
    await expect(rail).toHaveCount(0)
    await page.getByRole('button', { name: LABELS.shell.open_nav }).click()
    await expect(
        page.locator('[data-overlay]').getByRole('link', { name: LABELS.screen.pipelines.name }),
    ).toBeVisible()
    await page.keyboard.press('Escape')
    await page.keyboard.press('ControlOrMeta+b')
    await expect(rail.getByRole('link', { name: LABELS.screen.pipelines.name })).toBeVisible()

    const strips = await topStrips(page)
    expect(strips.length).toBeGreaterThanOrEqual(2)
    for (const strip of strips) {
        expect(strip.top).toBe(strips[0].top)
        expect(strip.height).toBe(strips[0].height)
    }
})

test('the rail narrows to its marks and widens again, and keeps how it was left', async ({ page }) => {
    const rail = page.locator('[data-shell-rail] aside')
    await page.getByRole('button', { name: LABELS.shell.collapse_nav }).click()
    await expect(rail).toHaveAttribute('data-collapsed')
    await page.reload()
    await expect(rail).toHaveAttribute('data-collapsed')
    await page.getByRole('button', { name: LABELS.shell.expand_nav }).first().click()
    await expect(rail).not.toHaveAttribute('data-collapsed')
})

test('a narrowed rail names every mark, and says the word on hover', async ({ page }) => {
    const rail = page.locator('[data-shell-rail] aside')
    await page.getByRole('button', { name: LABELS.shell.collapse_nav }).click()
    await expect(rail).toHaveAttribute('data-collapsed')
    for (const link of await rail.getByRole('link').all()) {
        expect((await link.getAttribute('aria-label')) ?? (await link.innerText()).trim()).not.toBe('')
    }
    const runs = rail.getByRole('link', { name: LABELS.screen.runs.name, exact: true })
    await expect(runs).toBeVisible()
    await runs.hover()
    await expect(
        page.locator('[data-side="right"]').getByText(LABELS.screen.runs.name, { exact: true }),
    ).toBeVisible()
})

test('the trail is the screens above, every crumb a link and none of them the page', async ({ page }) => {
    await applyExample(page.request, 'examples/transform/jq-reshape.yaml')
    const run = await startRun(page.request, 'jq-reshape')
    await page.goto(`/runs/${run}`)
    const trail = page.getByRole('navigation', { name: LABELS.shell.breadcrumb })
    await expect(trail.getByRole('link')).toHaveText([LABELS.screen.runs.name, 'Reshape with jq'])
    await expect(trail.locator('[aria-current]')).toHaveCount(0)
    await trail.getByRole('link', { name: LABELS.screen.runs.name }).click()
    await expect(page).toHaveURL(/\/runs$/)
    // A listing states no trail.
    await expect(trail).toHaveCount(0)
})

/** The rail's width before anything was dragged, and the widest it goes. */
const RAIL_WIDTH = 168
const RAIL_MAX_WIDTH = 320

test('the rail is dragged by its edge, moved by the keys, kept, and reset by a double-click', async ({
    page,
}) => {
    const rail = page.locator('[data-shell-rail] aside')
    const edge = page.getByRole('separator', { name: LABELS.shell.resize_nav })
    const width = async () => Math.round((await rail.boundingBox())?.width ?? 0)
    expect(await width()).toBe(RAIL_WIDTH)

    const box = await edge.boundingBox()
    if (box === null) throw new Error('no rail edge')
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width / 2 + 60, box.y + box.height / 2, { steps: 4 })
    await page.mouse.up()
    await expect.poll(width).toBe(RAIL_WIDTH + 60)

    await edge.focus()
    await page.keyboard.press('ArrowLeft')
    await expect.poll(width).toBe(RAIL_WIDTH + 44)
    await page.keyboard.press('End')
    await expect.poll(width).toBe(RAIL_MAX_WIDTH)

    await page.reload()
    await expect.poll(width).toBe(RAIL_MAX_WIDTH)

    await page.getByRole('separator', { name: LABELS.shell.resize_nav }).dblclick()
    await expect.poll(width).toBe(RAIL_WIDTH)
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
        localStorage.setItem('sokkel-ui-scheme', 'light')
    })
    await page.reload()
    await expect(page.getByRole('heading', { name: LABELS.screen.pipelines.name, exact: true })).toBeVisible()
    // The palette this test is named for is really the one on the page.
    await expect(page.locator('html')).not.toHaveClass(/dark/)

    const strips = await topStrips(page)
    expect(strips.length).toBeGreaterThanOrEqual(2)
    for (const strip of strips) {
        expect(strip.top).toBe(strips[0].top)
        expect(strip.height).toBe(strips[0].height)
    }
})

test('the top bar is one dot, named for the instance, and its checks are the tooltip', async ({ page }) => {
    const dot = page.getByRole('button', { name: LABELS.shell.instance.label })
    await expect(dot).toHaveAccessibleName(/^Instance: dirigent \S+, healthy$/)
    await expect(dot).toHaveText('')
    await dot.hover()
    const tip = page.locator('[data-slot="tooltip-content"]')
    // The name and the environment come from `/system/info`; this suite runs `dg dev`.
    const head = tip.locator('p').first()
    await expect(head).toContainText('dirigent')
    await expect(head).toContainText('local')
    await expect(head.locator('.font-mono')).toHaveText(/^\S+$/)
    await expect(tip.locator('time')).toHaveText(
        new RegExp(`^${LABELS.shell.instance.checked_at(`(${LABELS.measure.just_now}|\\d+m ago)`)}$`),
    )
    await expect(tip).toContainText('database')
    await expect(tip).toContainText(LABELS.state.server.healthy)

    // Once the first ask has settled, opening the tooltip again asks again.
    await page.mouse.move(0, 0)
    await expect(tip).toHaveCount(0)
    const asked = page.waitForRequest('**/health/ready')
    await dot.hover()
    await asked
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
    await expect(page.getByRole('button', { name: /side panel$/ })).toHaveCount(0)
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

test('the account menu holds the account, the settings, the shortcuts, the mode, the way out and the instance', async ({
    page,
}) => {
    const row = page.getByRole('button', { name: /^Account: / })
    // The development admin is `admin` as username and role. At the rail's own width the row
    // keeps the username whole and leaves the role to the menu's head.
    const said = row.getByText('admin', { exact: true })
    await expect(said.first()).toBeVisible()
    expect(await said.first().evaluate((name) => name.scrollWidth <= name.clientWidth)).toBe(true)
    await expect(said.nth(1)).toBeHidden()
    await row.click()
    const menu = page.getByRole('menu')
    await expect(menu.getByText('admin', { exact: true })).toHaveCount(2)
    for (const word of await menu.getByText('admin', { exact: true }).all()) await expect(word).toBeVisible()
    // The instance is said once, in the head.
    await expect(menu.getByText('local', { exact: false })).toHaveCount(1)
    await expect(page.getByRole('menuitem', { name: LABELS.shell.settings })).toBeVisible()
    await expect(page.getByRole('menuitemradio', { name: LABELS.shell.mode.system })).toBeChecked()
    await expect(page.getByRole('menuitem', { name: LABELS.action.sign_out })).toBeVisible()

    await page.getByRole('menuitem', { name: LABELS.shell.account.shortcuts }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
})

test('the account menu is walked by keyboard, the mode included', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' })
    const row = page.getByRole('button', { name: /^Account: / })
    await row.focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('menu')).toBeVisible()

    const light = page.getByRole('menuitemradio', { name: LABELS.shell.mode.light })
    await light.focus()
    await page.keyboard.press('Enter')
    await expect(page.locator('html')).not.toHaveClass(/dark/)
    expect(await page.evaluate(() => localStorage.getItem('sokkel-ui-scheme'))).toBe('light')

    await page.keyboard.press('Escape')
    await expect(page.getByRole('menu')).toHaveCount(0)
    await expect(row).toBeFocused()

    // The mode is said in the menu, so the top bar carries no flip of its own.
    await expect(page.getByRole('button', { name: /^Switch to / })).toHaveCount(0)
})

test('signing out from the account menu goes to the door', async ({ page }) => {
    await page.getByRole('button', { name: /^Account: / }).click()
    await page.getByRole('menuitem', { name: LABELS.action.sign_out }).click()
    await expect(page).toHaveURL(/\/login/)
})
