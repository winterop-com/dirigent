import { mkdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { parse } from 'yaml'

import { DOCS_BASICS_PORT } from '../docs-basics.config.ts'
import { DOCS_SHOTS_WIDTH } from '../docs-shots.config.ts'

/**
 * The ten pictures docs/basics.md renders, taken by walking the page.
 *
 * THE DOCUMENTS ARE READ OUT OF THE PAGE, not restated here: the first read, the pipeline as
 * the page prints it in full, the schema and the two failures are each lifted from the page's
 * own code blocks. A page whose documents stop applying stops this camera, rather than leaving
 * pictures of documents nobody can write.
 *
 * The page's documents call the playground on 3333, the port a reader's `dg dev` binds and the
 * one this camera binds by default. An instance moved to another port has that one address
 * rewritten on the way in.
 */

const docs = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..', 'docs')
const OUT = path.join(docs, 'images/basics')
const PAGE = readFileSync(path.join(docs, 'basics.md'), 'utf8')

const DEV_USERNAME = 'admin'
const DEV_PASSWORD = 'admin'
const PIPELINE = 'first-reading'
const FAILURES = 'two-failures'
const SCHEMA = 'basics-reading'

type Json = Record<string, unknown>

/** Every fenced block of one language on the page, in page order. */
function blocks(language: string): string[] {
    const fence = new RegExp('^```' + language + '\\n([\\s\\S]*?)^```', 'gm')
    return [...PAGE.matchAll(fence)].map((match) => match[1])
}

/** The one block of a language that holds a line, refused when there is none or several. */
function blockWith(language: string, needle: string): string {
    const found = blocks(language).filter((text) => text.includes(needle))
    expect(found, `docs/basics.md has one ${language} block holding ${needle}`).toHaveLength(1)
    return found[0]
}

function localised(text: string): string {
    return text.replaceAll('127.0.0.1:3333', `127.0.0.1:${String(DOCS_BASICS_PORT)}`)
}

/** Every block of the pipeline's own code, in page order: its first version first, its last last. */
function versions(): string[] {
    const found = blocks('yaml').filter((text) => text.includes(`code: ${PIPELINE}`))
    expect(found.length, `docs/basics.md writes ${PIPELINE} out at least twice`).toBeGreaterThanOrEqual(2)
    return found
}

/** The pipeline as section 3 writes it: one step. */
function firstVersion(): Json {
    return parse(localised(versions()[0])) as Json
}

/** The pipeline as the page prints it in full: the read, the gate and the send. */
function thirdVersion(): Json {
    const document = parse(localised(versions().at(-1) ?? '')) as Json
    const steps = document.steps as Json
    expect(Object.keys(steps), 'the full document is ask, check and send').toEqual(['ask', 'check', 'send'])
    return document
}

/** Section 4's version: the same document before the send was added. */
function secondVersion(): Json {
    const document = thirdVersion()
    delete (document.steps as Json).send
    return document
}

function twoFailures(): Json {
    return parse(localised(blockWith('yaml', `code: ${FAILURES}`))) as Json
}

function schemaBody(): Json {
    return JSON.parse(blockWith('json', `"$id": "${SCHEMA}"`)) as Json
}

async function apiPrefix(request: APIRequestContext): Promise<string> {
    const config = (await (await request.get('/config.json')).json()) as { api_prefix: string }
    return config.api_prefix
}

async function apply(request: APIRequestContext, document: Json): Promise<void> {
    const prefix = await apiPrefix(request)
    const applied = await request.post(`${prefix}/pipelines/$apply`, { data: { document, source: 'api' } })
    expect(applied.ok(), await applied.text()).toBe(true)
    const result = (await applied.json()) as { action: string }
    expect(result.action, JSON.stringify(result)).not.toBe('invalid')
}

async function startRun(request: APIRequestContext, pipeline: string, params: Json = {}): Promise<string> {
    const prefix = await apiPrefix(request)
    const started = await request.post(`${prefix}/pipelines/${pipeline}/$run`, { data: { params } })
    expect(started.ok(), await started.text()).toBe(true)
    const accepted = (await started.json()) as { run_id: string | null }
    expect(accepted.run_id, `${pipeline} was not accepted`).not.toBeNull()
    return accepted.run_id as string
}

/** Wait for a run to stop moving, and answer with where it stopped. */
async function settled(request: APIRequestContext, runId: string): Promise<string> {
    const prefix = await apiPrefix(request)
    let status = 'pending'
    await expect
        .poll(
            async () => {
                const detail = (await (await request.get(`${prefix}/runs/${runId}`)).json()) as {
                    run: { status: string }
                }
                status = detail.run.status
                return ['running', 'queued', 'pending'].includes(status) ? 'moving' : 'settled'
            },
            { timeout: 120_000, intervals: [500] },
        )
        .toBe('settled')
    return status
}

async function signIn(page: Page): Promise<void> {
    await page.goto('/login')
    await page.getByLabel('Username').fill(DEV_USERNAME)
    await page.getByLabel('Password', { exact: true }).fill(DEV_PASSWORD)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await page.waitForURL((url) => url.pathname === '/')
}

/** Wait until the corner has read the instance, and refuse a picture wider than the frame. */
async function shot(page: Page, name: string): Promise<void> {
    await page
        .getByRole('button', { name: /^Instance: (healthy|degraded|unhealthy)/ })
        .waitFor({ timeout: 15_000 })
    await page.waitForTimeout(900)
    const width = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(width, `${name} is ${String(width)}px wide`).toBeLessThanOrEqual(DOCS_SHOTS_WIDTH)
    await page.screenshot({ path: path.join(OUT, `${name}.png`) })
}

/** A run's screen with one step chosen, which is what opens its panel. */
async function runOnStep(page: Page, runId: string, step: string): Promise<void> {
    await page.goto(`/runs/${runId}`)
    const node = page.locator('.react-flow__node').filter({ hasText: step })
    await node.first().waitFor({ timeout: 30_000 })
    await node.getByText(step, { exact: true }).first().click()
    await page.getByRole('tab', { name: 'Step', exact: true }).waitFor({ timeout: 15_000 })
}

/**
 * Scroll a step's output past the headers to the part the page reads: the answer's body, or with
 * `nth` 1 the body of the request the playground reflected, which is what a send sent.
 */
async function outputAtBody(page: Page, nth = 0): Promise<void> {
    const body = page.getByText('"body"', { exact: true }).nth(nth)
    await body.waitFor({ timeout: 15_000 })
    await body.evaluate((line) => {
        line.scrollIntoView({ block: 'start' })
    })
}

test('the pictures docs/basics.md is built out of', async ({ page }) => {
    test.setTimeout(600_000)
    mkdirSync(OUT, { recursive: true })

    // Section 1: the sign-in screen, as a reader first meets it.
    await page.goto('/login')
    await page.getByLabel('Username').fill(DEV_USERNAME)
    await page.getByRole('button', { name: 'Sign in', exact: true }).waitFor()
    await page.waitForTimeout(600)
    await page.screenshot({ path: path.join(OUT, 'login.png') })

    await signIn(page)
    await page.evaluate(() => {
        localStorage.setItem('theme', 'dark')
        localStorage.setItem('dirigent.palette', 'amber')
        localStorage.setItem('dirigent.terminalOpen', 'false')
    })
    const request = page.request

    // Section 3: the first read.
    await apply(request, firstVersion())
    const first = await startRun(request, PIPELINE)
    expect(await settled(request, first)).toBe('succeeded')
    await runOnStep(page, first, 'ask')
    await outputAtBody(page)
    await shot(page, 'run-first')

    // Section 4: the schema handed to the instance, and the gate naming it.
    const prefix = await apiPrefix(request)
    const stored = await request.post(`${prefix}/schemas`, { data: { body: schemaBody() } })
    expect(stored.ok(), await stored.text()).toBe(true)
    await apply(request, secondVersion())
    const gated = await startRun(request, PIPELINE)
    expect(await settled(request, gated)).toBe('succeeded')

    await page.goto(`/schemas/${SCHEMA}`)
    await page.getByRole('heading', { name: 'Schemas' }).waitFor({ timeout: 30_000 })
    await shot(page, 'schemas')

    await page.goto(`/pipelines/${PIPELINE}/edit`)
    await page.locator('.react-flow__node').getByText('check', { exact: true }).click()
    await page.locator('aside').getByRole('heading', { name: 'Config' }).waitFor({ timeout: 30_000 })
    const schemaTitle = schemaBody().title as string
    await page.locator('aside').getByText(schemaTitle, { exact: true }).first().click()
    await page.getByText('Open in Schemas').waitFor({ timeout: 15_000 })
    await page.getByText('Open in Schemas').scrollIntoViewIfNeeded()
    await shot(page, 'step-check')

    // Section 5: the send.
    await apply(request, thirdVersion())
    const sent = await startRun(request, PIPELINE)
    expect(await settled(request, sent)).toBe('succeeded')
    await runOnStep(page, sent, 'send')
    await outputAtBody(page, 1)
    await shot(page, 'run-send')

    // The graph beside the document the instance holds: the editor, on its Source tab.
    await page.goto(`/pipelines/${PIPELINE}/edit`)
    // The panel is shut until a step is chosen, and the tab row it opens carries Source.
    await page.locator('.react-flow__node').getByText('send', { exact: true }).click({ timeout: 30_000 })
    await page.locator('aside').getByRole('tab', { name: 'Source', exact: true }).click()
    await shot(page, 'pipeline')

    // Section 6: a gate refusing, and the two failures.
    const refused = await startRun(request, PIPELINE, { station: '' })
    expect(await settled(request, refused)).toBe('failed')
    await runOnStep(page, refused, 'check')
    await shot(page, 'run-gate-rejected')

    await apply(request, twoFailures())
    const failures = await startRun(request, FAILURES)
    expect(await settled(request, failures)).toBe('failed')
    await runOnStep(page, failures, 'refused')
    await shot(page, 'run-refused')
    await runOnStep(page, failures, 'unlucky')
    await shot(page, 'run-retried')

    // Section 7: what the page leaves behind.
    await page.goto('/')
    await page.getByRole('heading', { name: 'Dashboard' }).waitFor({ timeout: 30_000 })
    await shot(page, 'dashboard')
})
