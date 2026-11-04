import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'

import { LABELS } from '../src/lib/labels.ts'
import { apiPrefix, applyDocument, removeSchema, signIn, writeInEditor } from './support.ts'

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
 *
 * AND THAT A SHAPE SOMEBODY GOT WRONG CAN BE PUT RIGHT. A schema's page is a form over
 * `PATCH /schemas/{code}`, so what these assert is the round trip: what the boxes send, what is
 * then stored, and that the code is not among the things it sends.
 *
 * AND THAT THE TWO HALVES ANSWER DIFFERENTLY UNDER A DEPENDENCY. Removing a shape a stored
 * pipeline names is refused and correcting one is not, so the page draws both at once: a Delete
 * that is shut and says which pipeline shut it, beside a Save that still works.
 *
 * AND THAT A VALUE IS TRIED AGAINST THE TEXT IN THE EDITOR, saved or not, on the page and in the
 * full-screen window over the same two buffers.
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
    // A spec that leaves a pipeline naming this code leaves the code undeletable, which is the
    // rule this screen is about: the dependants go first, as they would for a person.
    await removeSchema(request, 'e2e-org-unit')
    const created = await request.post(`${prefix}/schemas`, { data: { body: SCHEMA } })
    expect(created.ok(), await created.text()).toBe(true)
}

test("a schema row opens the schema's own page", async ({ page }) => {
    await signIn(page)
    await seedSchema(page.request)

    await page.goto('/schemas')

    // The title is the schema's title, and the code it is addressed by is beside it in mono.
    const row = page.getByRole('row').filter({ hasText: 'Organisation unit' })
    await expect(row).toContainText('e2e-org-unit')

    await row.click()
    await expect(page).toHaveURL(/\/schemas\/e2e-org-unit$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Organisation unit' })).toBeVisible()
    await expect(schemaEditor(page).locator('.view-lines')).toContainText('properties')
})

test('a link straight to a schema opens its page', async ({ page }) => {
    await signIn(page)
    await seedSchema(page.request)

    await page.goto('/schemas/e2e-org-unit')
    await expect(schemaEditor(page).locator('.view-lines')).toContainText('properties')
})

test('the schema box completes against the meta-schema', async ({ page }) => {
    await signIn(page)
    await seedSchema(page.request)

    await page.goto('/schemas/e2e-org-unit')
    const editor = schemaEditor(page)
    await writeInEditor(page, editor, '')
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

test('a new schema is named in the dialog and opens on its own page', async ({ page }) => {
    await signIn(page)
    await removeSchema(page.request, 'e2e-created-shape')

    await page.goto('/schemas')
    await page.getByRole('button', { name: LABELS.schemas.new }).click()
    const dialog = page.getByRole('dialog')
    const create = dialog.getByRole('button', { name: LABELS.action.create.verb, exact: true })
    // Create is shut until there is a code, and says why.
    await expect(create).toBeDisabled()
    await dialog.getByLabel(LABELS.word.code).fill('E2E shape')
    await dialog.getByLabel(LABELS.word.name.label).click()
    await expect(dialog.getByText(LABELS.schemas.create.code_shape)).toBeVisible()

    await dialog.getByLabel(LABELS.word.code).fill('e2e-created-shape')
    await dialog.getByLabel(LABELS.word.name.label).fill('Created in the dialog')
    await create.click()

    await expect(page).toHaveURL(/\/schemas\/e2e-created-shape$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Created in the dialog' })).toBeVisible()
    await expect(schemaEditor(page).locator('.view-lines')).toContainText('e2e-created-shape')
    await removeSchema(page.request, 'e2e-created-shape')
})

test('a stored schema is relabelled on its page', async ({ page }) => {
    await signIn(page)
    await seedSchema(page.request)

    await page.goto('/schemas/e2e-org-unit')
    const save = page.getByRole('button', { name: LABELS.action.save.verb, exact: true })
    // Nothing changed is nothing to send, and the shut control says so.
    await expect(save).toBeDisabled()

    // The name is a display title with no identity, so it is a box in Details; the code is the heading.
    const panel = await details(page)
    await panel.getByRole('button', { name: LABELS.schemas.edit_details }).click()
    await panel.getByLabel(LABELS.word.name.label).fill('Org unit, corrected')
    await save.click()
    await expect(page.getByRole('heading', { level: 1, name: 'Org unit, corrected' })).toBeVisible()
    await expect(save).toBeDisabled()

    const prefix = await apiPrefix(page.request)
    const read = await (await page.request.get(`${prefix}/schemas/e2e-org-unit`)).json()
    expect(read.name).toBe('Org unit, corrected')
    expect(read.body.title).toBe('Organisation unit')
})

test('a shape somebody got wrong is corrected on its page', async ({ page }) => {
    await signIn(page)
    await seedSchema(page.request)

    await page.goto('/schemas/e2e-org-unit')
    const editor = schemaEditor(page)
    await expect(editor.locator('.view-lines')).toContainText('properties')
    await writeInEditor(page, editor, JSON.stringify({ ...SCHEMA, required: ['id', 'displayName'] }, null, 2))

    const save = page.getByRole('button', { name: LABELS.action.save.verb, exact: true })
    await save.click()
    await expect(save).toBeDisabled()

    const prefix = await apiPrefix(page.request)
    const read = await (await page.request.get(`${prefix}/schemas/e2e-org-unit`)).json()
    expect(read.body.required).toEqual(['id', 'displayName'])
    expect(read.code).toBe('e2e-org-unit')
})

test('a value is tried against the text in the schema editor, saved or not', async ({ page }) => {
    await signIn(page)
    await seedSchema(page.request)

    await page.goto('/schemas/e2e-org-unit')
    await page.getByRole('button', { name: LABELS.schemas.try_value, exact: true }).click()
    const window = page.getByRole('dialog')

    const [schema, value] = [
        window.getByTestId('code-editor').nth(0),
        window.getByTestId('code-editor').nth(1),
    ]
    const result = window.getByRole('region', { name: LABELS.schemas.tester.result_heading })

    await writeInEditor(page, value, '{"id": 7}')
    await expect(result.getByText(LABELS.schemas.tester.invalid, { exact: true })).toBeVisible()
    await expect(result.getByRole('button', { name: /^\/id type / })).toBeVisible()

    await writeInEditor(page, value, '{"id": "ou-1"}')
    await expect(result.getByText(LABELS.schemas.tester.fits)).toBeVisible()

    // The schema editor's own text is what is checked against, before anything is saved.
    await writeInEditor(page, schema, JSON.stringify({ ...SCHEMA, required: ['id', 'level'] }, null, 2))
    await expect(result.getByText(LABELS.schemas.tester.invalid, { exact: true })).toBeVisible()
    const prefix = await apiPrefix(page.request)
    const read = await (await page.request.get(`${prefix}/schemas/e2e-org-unit`)).json()
    expect(read.body.required).toEqual(['id'])

    await writeInEditor(page, value, '{"id": ')
    await expect(result.getByText(/^The value is not readable JSON/)).toBeVisible()
})

test("the tester's schema is the page's, and its value is kept between openings", async ({ page }) => {
    await signIn(page)
    await seedSchema(page.request)

    await page.goto('/schemas/e2e-org-unit')
    await page.getByRole('button', { name: LABELS.schemas.try_value, exact: true }).click()
    const window = page.getByRole('dialog')
    await writeInEditor(page, window.getByTestId('code-editor').nth(1), '{"id": 7}')
    await writeInEditor(
        page,
        window.getByTestId('code-editor').nth(0),
        JSON.stringify({ ...SCHEMA, required: ['id', 'tried'] }, null, 2),
    )
    // Escape inside an editor is the editor's; the window's own close is what shuts it.
    await window.locator('[data-slot="dialog-close"]').click()
    await expect(window).toBeHidden()
    await expect(schemaEditor(page).locator('.view-lines')).toContainText('tried')

    await page.getByRole('button', { name: LABELS.schemas.try_value, exact: true }).click()
    await expect(window.getByTestId('code-editor').nth(1).locator('.view-lines')).toContainText('"id": 7')
})

/** A pipeline whose gate validates against the seeded schema, so the code is named by a version. */
const NAMING = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: 'e2e-schema-dependant',
    requires: { schemas: ['e2e-org-unit'] },
    steps: {
        gate: {
            block: 'validate.schema',
            config: { input: { id: 'x' }, schema: 'e2e-org-unit' },
        },
    },
}

test('a shape a pipeline names cannot be deleted, and the shut control says which', async ({ page }) => {
    await signIn(page)
    await seedSchema(page.request)
    await applyDocument(page.request, NAMING)

    await page.goto('/schemas/e2e-org-unit')

    // The pipelines that check against it are named in Details, each a link to its pipeline.
    await expect((await details(page)).getByRole('link', { name: 'e2e-schema-dependant' })).toBeVisible()

    // A control that would be refused says so before it is pressed.
    const remove = page.getByRole('button', { name: LABELS.action.delete.verb, exact: true })
    await expect(remove).toBeDisabled()
    await expect(page.locator('[title*="cannot be removed"]').first()).toHaveAttribute(
        'title',
        /e2e-schema-dependant.*cannot be removed/,
    )

    // And the shape is still there, because nothing was sent.
    const prefix = await apiPrefix(page.request)
    expect((await page.request.get(`${prefix}/schemas/e2e-org-unit`)).status()).toBe(200)
})

test('the same shape is still corrected in place while that pipeline names it', async ({ page }) => {
    await signIn(page)
    await seedSchema(page.request)
    await applyDocument(page.request, NAMING)

    await page.goto('/schemas/e2e-org-unit')
    const editor = schemaEditor(page)
    await expect(editor.locator('.view-lines')).toContainText('properties')
    await writeInEditor(page, editor, JSON.stringify({ ...SCHEMA, required: ['id', 'code'] }, null, 2))

    // Save is not shut by the dependency: correcting the shape every pipeline should now
    // validate against is what the page is for.
    const save = page.getByRole('button', { name: LABELS.action.save.verb, exact: true })
    await save.click()
    await expect(save).toBeDisabled()

    const prefix = await apiPrefix(page.request)
    const read = await (await page.request.get(`${prefix}/schemas/e2e-org-unit`)).json()
    expect(read.body.required).toEqual(['id', 'code'])
    expect(read.used_by).toEqual(['e2e-schema-dependant'])
})

test("the page's schema box marks a value the draft does not take", async ({ page }) => {
    await signIn(page)
    await seedSchema(page.request)

    await page.goto('/schemas/e2e-org-unit')
    const editor = schemaEditor(page)
    // `type` takes one of the seven names or a list of them, and never a number: the draft is
    // what says so, and only a browser can say the worker holding it arrived.
    await writeInEditor(page, editor, '{ "type": 3 }')

    await expect(editor.locator('.squiggly-warning, .squiggly-error').first()).toBeVisible({
        timeout: 15_000,
    })
})

/** The right panel's Details, opened where the reader's preference left it shut. */
async function details(page: Page): Promise<Locator> {
    const panel = page.getByRole('tabpanel', { name: LABELS.schemas.details_heading })
    // A shut panel stays in the page, inert, so whether it is open is read off its container.
    const aside = page.locator('aside').filter({ has: panel })
    await expect(aside).toBeAttached()
    if ((await aside.getAttribute('inert')) !== null) {
        await page.getByRole('button', { name: LABELS.shell.toggle_panel }).click()
    }
    await expect(aside).not.toHaveAttribute('inert')
    return panel
}

/** The page's schema editor, its only one. */
function schemaEditor(page: Page): Locator {
    return page.getByRole('main').getByTestId('code-editor').nth(0)
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
        // Nothing to measure is a fault of its own: `Math.max(0)` is 0, which reads as room to
        // spare at every width and would sweep the whole range green having measured no title.
        if (cells.length === 0) return Number.NaN
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
            if (Number.isNaN(past)) throw new Error(`no title to measure at ${String(width)}px`)
            if (past > 0) cut.push(width)
        }
        expect(cut).toEqual([])
    })
})
