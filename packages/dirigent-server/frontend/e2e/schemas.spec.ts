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
