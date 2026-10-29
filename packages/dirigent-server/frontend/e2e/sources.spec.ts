import { expect, test, type APIRequestContext } from '@playwright/test'

import { LABELS } from '../src/lib/labels.ts'
import { apiPrefix, applyDocument, signIn } from './support.ts'

/**
 * The sources section of the triggers screen, against a real instance taking real calls.
 *
 * WHAT THIS SPEC IS FOR is what a Node test cannot reach: that a call made to an endpoint shows
 * up as a row with its route and its state, and that the panel's journal reads what the intake
 * wrote, the reply that answered and the refusal alike.
 */

/** An endpoint answered by a reply, under a path no shipped example claims. */
const ECHO = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: 'e2e-source-echo',
    steps: {
        ask: { source: { kind: 'endpoint', path: '/e2e-source-echo' } },
        answer: { depends_on: ['ask'], reply: { status: 200, body: '${steps.ask.output.body}' } },
    },
}

/** Give the source a token this spec knows, then call it once well and once with a body it refuses. */
async function callTwice(request: APIRequestContext): Promise<void> {
    const prefix = await apiPrefix(request)
    const rotated = await request.post(`${prefix}/pipelines/${ECHO.code}/sources/ask/$rotate-token`)
    expect(rotated.ok(), await rotated.text()).toBe(true)
    const { token } = (await rotated.json()) as { token: string }
    const headers = { Authorization: `Bearer ${token}` }
    const replied = await request.post('/endpoints/e2e-source-echo', { headers, data: { said: 'hi' } })
    expect(replied.status()).toBe(200)
    const refused = await request.post('/endpoints/e2e-source-echo', {
        headers: { ...headers, 'Content-Type': 'image/png' },
        data: Buffer.from('not json'),
    })
    expect(refused.status()).toBe(415)
}

test('a source called over the wire is listed with its route, and its panel reads its journal', async ({
    page,
}) => {
    await signIn(page)
    await applyDocument(page.request, ECHO)
    await callTwice(page.request)

    await page.goto('/triggers')
    const row = page.getByRole('row').filter({ hasText: ECHO.code })
    await expect(row).toContainText('POST /endpoints/e2e-source-echo')
    await expect(row).toContainText(LABELS.state.source.listening)

    // The route cell, rather than the row's middle: one of its cells is a link to the pipeline.
    await row.getByText('POST /endpoints/e2e-source-echo', { exact: true }).click()
    const panel = page.getByRole('tabpanel')
    await expect(panel).toContainText(LABELS.triggers.source.route)
    await expect(panel).toContainText(LABELS.triggers.source.outcome.replied)
    await expect(panel).toContainText(LABELS.triggers.source.outcome.refused)
    await expect(panel).toContainText('415')

    // Pausing is the instance's verb, and the row behind says so at once.
    await panel.getByRole('button', { name: LABELS.action.pause }).click()
    await expect(panel.getByRole('button', { name: LABELS.action.resume })).toBeVisible()
    await expect(row).toContainText(LABELS.state.source.paused)
    await panel.getByRole('button', { name: LABELS.action.resume }).click()
    await expect(row).toContainText(LABELS.state.source.listening)
})
