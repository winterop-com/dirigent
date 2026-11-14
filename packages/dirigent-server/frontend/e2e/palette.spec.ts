import { expect, test } from '@playwright/test'

import { LABELS } from '../src/lib/labels.ts'
import { signIn } from './support.ts'

/**
 * The command palette, driven the way it is actually used: a chord, a few letters, a row.
 *
 * WHAT IS WORTH A BROWSER HERE is the part `lib/palette`'s own tests cannot reach -- that the
 * chord is bound at all, that what a row is found by narrows the list, that the shelf the screen
 * registered leads the ones the shell did, and that a pasted id opens its run.
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

test('a query nothing answers says so rather than showing everything', async ({ page }) => {
    await page.keyboard.press('ControlOrMeta+k')
    await page.getByPlaceholder(LABELS.palette.placeholder).fill('stroopwafel')
    await expect(page.getByText(LABELS.palette.empty)).toBeVisible()
})

test('a pasted run id is one row, and Enter opens the run', async ({ page }) => {
    const id = '01a1a11a-0000-7000-8000-00000000abcd'
    await page.keyboard.press('ControlOrMeta+k')
    await page.getByPlaceholder(LABELS.palette.placeholder).fill(id)
    await expect(page.getByRole('option', { name: LABELS.palette.open_id(id) })).toBeVisible()
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(new RegExp(`/runs/${id}`))
})

test('an id typed key by key is answered at once, and never says Reading on the way', async ({ page }) => {
    const id = '01a1a11a-0000-7000-8000-00000000abcd'
    await page.keyboard.press('ControlOrMeta+k')
    const box = page.getByPlaceholder(LABELS.palette.placeholder)
    await expect(box).toBeVisible()
    // Every frame is read while the keys go in, so a searching line drawn for one frame counts.
    await page.evaluate((reading) => {
        const seen = { frames: 0, running: true }
        Object.assign(window, { readingFrames: seen })
        const look = () => {
            const lines = document.querySelectorAll('[role="dialog"] [role="status"]')
            if (Array.from(lines).some((line) => line.textContent?.includes(reading))) seen.frames += 1
            if (seen.running) requestAnimationFrame(look)
        }
        requestAnimationFrame(look)
    }, LABELS.shell.reading)
    await box.pressSequentially(id, { delay: 120 })
    await expect(page.getByRole('option', { name: LABELS.palette.open_id(id) })).toBeVisible()
    const frames = await page.evaluate(() => {
        const seen = (window as unknown as { readingFrames: { frames: number; running: boolean } })
            .readingFrames
        seen.running = false
        return seen.frames
    })
    expect(frames).toBe(0)
})

test.describe('on a Mac', () => {
    test.use({
        userAgent:
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    })

    test('Ctrl+K opens it as Cmd+K does', async ({ page }) => {
        await page.addInitScript(() => {
            Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' })
        })
        await page.reload()
        await expect(page.getByLabel(LABELS.shell.instance.label)).toBeVisible()
        await page.keyboard.press('Control+k')
        await expect(page.getByPlaceholder(LABELS.palette.placeholder)).toBeVisible()
        await page.keyboard.press('Escape')
        await page.keyboard.press('Meta+k')
        await expect(page.getByPlaceholder(LABELS.palette.placeholder)).toBeVisible()
    })
})
