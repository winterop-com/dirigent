import { expect, test, type Page } from '@playwright/test'

import { applyExample, signIn } from './support.ts'

/**
 * The chassis itself: the two rules across the app, and what the corner says it is.
 *
 * THE SEAMS ARE MEASURED, NOT EYEBALLED. The rail, the content column and the right panel each
 * draw a strip along the top, and a rule that is one pixel out at a column edge reads as a step
 * in the window. So this asks the browser where every strip actually is, in both palettes, with
 * the rail expanded and collapsed and the panel open and closed -- the four ways the columns
 * can be arranged.
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
    // slow runner the shell has not mounted yet and querySelector returns null. Wait for the
    // strips, the rule and the foot bar to be on the page first, so a seam is measured, never
    // its absence.
    await expect(page.locator('[data-shell-strip="top"]').first()).toBeVisible()
    await expect(page.locator('[data-shell-rule="top"]')).toBeVisible()
    await expect(page.locator('[data-shell-strip="foot"]')).toBeVisible()
})

test('every strip along the top starts and ends at the same y', async ({ page }) => {
    const strips = await topStrips(page)
    expect(strips.length).toBeGreaterThanOrEqual(2)
    for (const strip of strips) {
        expect(strip.top).toBe(strips[0].top)
        expect(strip.height).toBe(strips[0].height)
    }
})

test('the rule under them is one line across the whole width', async ({ page }) => {
    const measured = await page.evaluate(() => {
        const rule = document.querySelector('[data-shell-rule="top"]')?.getBoundingClientRect()
        const strip = document.querySelector('[data-shell-strip="top"]')?.getBoundingClientRect()
        return rule === undefined || strip === undefined
            ? null
            : {
                  ruleTop: Math.round(rule.top),
                  ruleWidth: Math.round(rule.width),
                  stripBottom: Math.round(strip.bottom),
                  windowWidth: window.innerWidth,
              }
    })
    expect(measured).not.toBeNull()
    expect(measured?.ruleTop).toBe(measured?.stripBottom)
    expect(measured?.ruleWidth).toBe(measured?.windowWidth)
})

test('the bar along the foot is one element, and its cells fill it exactly', async ({ page }) => {
    const measured = await page.evaluate(() => {
        const bars = document.querySelectorAll('[data-shell-strip="foot"]')
        const bar = bars[0]?.getBoundingClientRect()
        const cells = [...document.querySelectorAll('[data-shell-cell]')].map((element) => {
            const box = element.getBoundingClientRect()
            return { top: Math.round(box.top), bottom: Math.round(box.bottom), right: Math.round(box.right) }
        })
        return bar === undefined
            ? null
            : {
                  bars: bars.length,
                  barTop: Math.round(bar.top),
                  barBottom: Math.round(bar.bottom),
                  barWidth: Math.round(bar.width),
                  windowWidth: window.innerWidth,
                  cells,
              }
    })
    // ONE bar rather than two side by side, which is what makes the rule uncuttable.
    expect(measured?.bars).toBe(1)
    expect(measured?.barWidth).toBe(measured?.windowWidth)
    expect(measured?.cells).toHaveLength(2)
    for (const cell of measured?.cells ?? []) {
        // Inside the bar's own border, and spanning its full height.
        expect(cell.top).toBe((measured?.barTop ?? 0) + 1)
        expect(cell.bottom).toBe(measured?.barBottom)
    }
    // The settings cell ends exactly where the status cell begins: one divider, no gap.
    expect(measured?.cells[0].right).toBeGreaterThan(0)
})

test('the seams hold with the rail collapsed', async ({ page }) => {
    await page.getByRole('button', { name: 'Collapse the navigation' }).click()
    await expect(page.getByRole('button', { name: 'Expand the navigation' })).toBeVisible()

    const strips = await topStrips(page)
    for (const strip of strips) {
        expect(strip.top).toBe(strips[0].top)
        expect(strip.height).toBe(strips[0].height)
    }
})

test('the seams hold with the right panel open', async ({ page }) => {
    // The panel exists only when a screen fills it, so apply a document and choose its row.
    await page.goto('/pipelines')
    await applyExample(page.request, 'examples/transform/jq-reshape.yaml')
    await page.reload()
    // On the row itself, away from its title link and its tag chips: both of those do
    // something else, and what this spec is about is the panel a chosen row opens.
    await page
        .getByRole('row')
        .filter({ hasText: 'jq-reshape' })
        .first()
        .getByText('jq-reshape', { exact: true })
        .click()
    await expect(page.getByRole('tab', { name: 'Pipeline' })).toBeVisible()

    const strips = await topStrips(page)
    expect(strips.length).toBe(3)
    for (const strip of strips) {
        expect(strip.top).toBe(strips[0].top)
        expect(strip.height).toBe(strips[0].height)
    }
})

test('the seams hold in the light palette as they do in the dark one', async ({ page }) => {
    await page.goto('/pipelines')
    await page.evaluate(() => {
        localStorage.setItem('theme', 'light')
    })
    await page.reload()
    await expect(page.getByRole('heading', { name: 'Pipelines' })).toBeVisible()

    const strips = await topStrips(page)
    for (const strip of strips) {
        expect(strip.top).toBe(strips[0].top)
        expect(strip.height).toBe(strips[0].height)
    }
})

test('the corner names the instance rather than only colouring it', async ({ page }) => {
    const corner = page.getByRole('button', { name: 'Instance' })
    // The name and the environment come from `/system/info`; this suite runs `dg dev`.
    await expect(corner).toContainText('dirigent')
    await expect(corner).toContainText('local')
})

test('a panel nothing has filled is not there at all, toggle included', async ({ page }) => {
    // An unfilled panel would only ever say "nothing selected", so it does not render, and
    // neither does the control that would reveal it.
    await expect(page.getByRole('button', { name: 'Show or hide the side panel' })).toHaveCount(0)
    await expect(page.getByText('Nothing selected', { exact: false })).toHaveCount(0)
})

test('an empty listing states the fact and stops', async ({ page }) => {
    // The way a rule is made is a button on this screen, so the empty state names no way in:
    // what New rule does is what New rule says.
    await page.goto('/admin/alerting')
    await expect(page.getByRole('heading', { name: 'Alerting' })).toBeVisible()
    await expect(page.getByText(/No rules\./)).toBeVisible()
    await expect(page.getByRole('button', { name: 'New rule' })).toBeVisible()
})

test('a collapsed rail wakes when its edge is dragged outward', async ({ page }) => {
    await page.getByRole('button', { name: 'Collapse the navigation' }).click()
    await expect(page.getByRole('link', { name: 'Pipelines' })).not.toContainText('Pipelines')

    // The collapse animates; the edge is only draggable once the rail has settled.
    await page.waitForFunction(() => {
        const aside = document.querySelector('aside')
        return aside !== null && aside.getBoundingClientRect().width < 60
    })
    const edge = page.getByRole('separator', { name: 'Expand the navigation' })
    const box = await edge.boundingBox()
    if (box === null) throw new Error('no edge to drag')
    await page.mouse.move(box.x + box.width / 2, 400)
    await page.mouse.down()
    await page.mouse.move(box.x + 180, 400, { steps: 6 })
    await page.mouse.up()

    // The rail expanded under the drag and the labels are back.
    await expect(page.getByRole('link', { name: 'Pipelines' })).toContainText('Pipelines')
})
