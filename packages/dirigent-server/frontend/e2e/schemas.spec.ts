import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'

import { apiPrefix, signIn, writeInEditor } from './support.ts'

/**
 * The Schemas screen, against a real instance.
 *
 * WHAT THIS SPEC IS FOR is the half a Node test cannot reach: that a schema stored with only
 * a `$id`/`title` shows its identity read from the schema's own keywords, and that opening it
 * draws the schema body. A schema is locally authored, so the row is seeded over the API the
 * way a person would apply one.
 *
 * AND THAT THE BOX KNOWS WHAT IT HOLDS. The dialog edits a schema document rather than a JSON
 * value, so monaco is handed the meta-schema of the draft the server validates with. Only a
 * browser can say whether that arrived: the worker, the completion it answers with and the
 * marker it puts on a wrong value are the real thing here or they are nothing.
 */

const SCHEMA = {
    $id: 'e2e-org-unit',
    title: 'Organisation unit',
    description: 'The shape the org-unit read returns.',
    type: 'object',
    required: ['id'],
    properties: { id: { type: 'string' } },
}

async function seedSchema(request: APIRequestContext): Promise<void> {
    const prefix = await apiPrefix(request)
    await request.delete(`${prefix}/schemas/e2e-org-unit`)
    const created = await request.post(`${prefix}/schemas`, { data: { body: SCHEMA } })
    expect(created.ok(), await created.text()).toBe(true)
}

test('a schema reads as its own identity and shows its body', async ({ page }) => {
    await signIn(page)
    await seedSchema(page.request)

    await page.goto('/schemas')

    // The title is the schema's title, and the code it is addressed by is beside it in mono.
    const row = page.getByRole('row').filter({ hasText: 'Organisation unit' })
    await expect(row).toContainText('e2e-org-unit')

    await row.click()
    const panel = page.locator('aside')
    // The body is on screen -- a property name a reader can see, proving the schema is drawn.
    await expect(panel.getByText('properties', { exact: false })).toBeVisible()
})

test('a link straight to a schema opens that schema', async ({ page }) => {
    await signIn(page)
    await seedSchema(page.request)

    // The address is the selection, so nothing has to be found on the listing first.
    await page.goto('/schemas/e2e-org-unit')

    const panel = page.locator('aside')
    await expect(panel.getByText('properties', { exact: false })).toBeVisible()
    await expect(page.getByRole('row').filter({ hasText: 'Organisation unit' })).toBeVisible()
})

test('choosing a row writes its code into the address', async ({ page }) => {
    await signIn(page)
    await seedSchema(page.request)

    await page.goto('/schemas')
    await page.getByRole('row').filter({ hasText: 'Organisation unit' }).click()

    await expect(page).toHaveURL(/\/schemas\/e2e-org-unit$/)
})

test('the schema box completes against the meta-schema', async ({ page }) => {
    await signIn(page)

    await page.goto('/schemas')
    await page.getByRole('button', { name: 'New schema' }).click()

    const editor = await theSchemaBox(page)
    await editor.locator('.view-lines').click()
    await expect(editor.locator('textarea').first()).toBeFocused()

    // One character: monaco closes the brace itself and leaves the caret between the pair,
    // which is where the draft's own keywords are what may be written next.
    await page.keyboard.type('{')
    await page.keyboard.press('Control+Space')

    // The widget draws the rows it has room for, so what is asserted is a keyword the list
    // opens on and then the one that is typed for, which narrows the same list to it.
    const suggestions = page.locator('.suggest-widget')
    await expect(suggestions).toBeVisible({ timeout: 15_000 })
    await expect(suggestions).toContainText('$id')
    await page.keyboard.type('propert')
    await expect(suggestions).toContainText('properties')
})

test('the schema box marks a value the draft does not take', async ({ page }) => {
    await signIn(page)

    await page.goto('/schemas')
    await page.getByRole('button', { name: 'New schema' }).click()

    const editor = await theSchemaBox(page)
    // An unknown key is not marked -- 2020-12 says nothing about keys it does not know -- so
    // what the meta-schema refuses is a value: `type` takes one of the seven names or a list
    // of them, and never a number.
    await writeInEditor(page, editor, '{ "type": 3 }')

    await expect(editor.locator('.squiggly-warning, .squiggly-error').first()).toBeVisible({
        timeout: 15_000,
    })
})

/** The dialog's one editor, once the chunk monaco lives in has landed. */
async function theSchemaBox(page: Page): Promise<Locator> {
    const editor = page.getByRole('dialog').getByTestId('code-editor')
    await expect(editor.locator('.monaco-editor')).toBeVisible({ timeout: 30_000 })
    return editor
}

/**
 * The rows the fault was reported on: a title that needs most of the column it stands in, and a
 * shorter one beside it.
 *
 * THE CODE IS PART OF THE WIDTH. It is drawn in mono beside the title and the column has to hold
 * both, so `echo-reading` is the code this row carries rather than an `e2e-` one -- what the
 * measurement was short by is a fraction of a pixel, and the glyphs are where that fraction comes
 * from.
 */
const LONG = [
    {
        $id: 'echo-reading',
        title: 'The reading, as Postman Echo answers it',
        description:
            'The shape a reading takes once the echo service has answered it. Every field the ' +
            'pipeline reads downstream is named here.',
        type: 'object',
    },
    {
        $id: 'e2e-field-units',
        title: 'Field units',
        description:
            'One field unit as the tutorial pulls it from the demo database. The identifier is ' +
            'a uid, and the parent is the unit one level above it.',
        type: 'object',
    },
]

async function seedLong(request: APIRequestContext): Promise<void> {
    const prefix = await apiPrefix(request)
    for (const body of LONG) {
        await request.delete(`${prefix}/schemas/${body.$id}`)
        const created = await request.post(`${prefix}/schemas`, { data: { body } })
        expect(created.ok(), await created.text()).toBe(true)
    }
}

/**
 * Wait for the listing to settle at the width it has just been given.
 *
 * Two frames: the listing measures itself in a layout effect, and what it settles on is drawn
 * in the frame after the one the resize arrived in.
 */
async function settled(page: Page): Promise<void> {
    await page.evaluate(
        () =>
            new Promise<void>((done) => {
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        done()
                    })
                })
            }),
    )
}

/**
 * How far the text in this listing's title cells runs past the boxes it was given, in fractions
 * of a pixel.
 *
 * `scrollWidth` answers in whole ones, which is what this fault hid behind: text short of its
 * box by a hundredth of a pixel reads there as text with room to spare, while the browser has
 * already drawn the ellipsis -- and the ellipsis eats the word in front of it as well as the
 * character that did not fit. A range over the text answers in the fractions the layout was
 * done in.
 */
async function titlesPast(page: Page): Promise<number> {
    return page.evaluate(() => {
        const past = (element: Element): number => {
            const range = document.createRange()
            range.selectNodeContents(element)
            const rects = [...range.getClientRects()]
            if (rects.length === 0) return 0
            const reach = Math.max(...rects.map((rect) => rect.right))
            return reach - element.getBoundingClientRect().right
        }
        const cells = [...document.querySelectorAll('[data-list-title] *')]
        return Math.max(0, ...cells.map((element) => past(element)))
    })
}

/**
 * THE TITLE IS WHAT TELLS ONE ROW FROM ANOTHER, so the column it stands in is measured to hold
 * the longest of them whole -- and a title granted a hundredth of a pixel less than it needs is
 * a title with its last word replaced by an ellipsis.
 */
test.describe('a listing whose titles run long', () => {
    test.use({ viewport: { width: 1280, height: 900 } })

    test('every title reads whole, at every width the table is drawn at', async ({ page }) => {
        await signIn(page)
        await seedLong(page.request)

        await page.goto('/schemas')
        await expect(page.getByRole('row').filter({ hasText: LONG[0].$id })).toBeVisible()

        // SWEPT RATHER THAN SAMPLED. Which widths fall short is a matter of where the
        // rounding lands, so the guarantee is read across the range the table is drawn in
        // rather than at the one viewport the fault was reported from.
        const cut: number[] = []
        for (let width = 1024; width <= 1440; width += 4) {
            await page.setViewportSize({ width, height: 900 })
            await settled(page)
            const past = await titlesPast(page)
            if (past > 0) cut.push(width)
        }
        expect(cut).toEqual([])
    })
})
