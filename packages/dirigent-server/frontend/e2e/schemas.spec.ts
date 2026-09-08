import { expect, test, type APIRequestContext } from '@playwright/test'

import { apiPrefix, signIn } from './support.ts'

/**
 * The Schemas screen, against a real instance.
 *
 * WHAT THIS SPEC IS FOR is the half a Node test cannot reach: that a schema stored with only
 * a `$id`/`title` shows its identity read from the schema's own keywords, and that opening it
 * draws the schema body. A schema is locally authored, so the row is seeded over the API the
 * way a person would apply one.
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
