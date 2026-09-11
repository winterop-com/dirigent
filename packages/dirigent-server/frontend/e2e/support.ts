import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, type APIRequestContext, type Locator, type Page } from '@playwright/test'

/**
 * What every spec in this suite needs before it can say anything: a session, this instance's
 * API prefix, and a way to put one of this repository's own examples into it.
 *
 * THE CREDENTIALS ARE `dg dev`'s OWN. An empty instance gets a development admin made for it
 * when the process starts -- `dirigent_cli.main.DEV_ADMIN` and `DEV_PASSWORD` -- and this suite
 * points that process at a scratch database, so the account exists because this run created it.
 *
 * THE DOCUMENTS ARE THE SHIPPED ONES, NOT COPIES. The API takes a document as JSON and an
 * example is YAML, so a file is read through the interpreter this suite already depends on
 * rather than transcribed into a spec, where it would drift the moment either changed.
 */

export const DEV_USERNAME = 'dev'
export const DEV_PASSWORD = 'dirigent-dev'

const here = path.dirname(fileURLToPath(import.meta.url))

/** The workspace root, which every example reference is relative to. */
export const repositoryRoot = path.resolve(here, '../../../..')

/** Read one of this repository's YAML examples as the JSON document the API applies. */
export function documentOf(reference: string): Record<string, unknown> {
    const read = 'import json,sys,yaml; print(json.dumps(yaml.safe_load(open(sys.argv[1]))))'
    const text = execFileSync('uv', ['run', 'python', '-c', read, reference], {
        cwd: repositoryRoot,
        encoding: 'utf8',
    })
    return JSON.parse(text) as Record<string, unknown>
}

/**
 * Sign in through the form, which is what puts the session cookie on this context.
 *
 * The password label is matched exactly, because the field's own reveal toggle is labelled
 * "Show password" and a substring match takes both.
 */
export async function signIn(page: Page): Promise<void> {
    await signInAs(page, DEV_USERNAME, DEV_PASSWORD)
}

/** Sign in as an account this run made, which is how a spec reads the app as another role. */
export async function signInAs(page: Page, username: string, password: string): Promise<void> {
    await page.goto('/login')
    await page.getByLabel('Username').fill(username)
    await page.getByLabel('Password', { exact: true }).fill(password)
    await page.getByRole('button', { name: 'Sign in' }).click()
    // The front door is the root, so a session that has just begun is at the root.
    await expect(page).toHaveURL(/^https?:\/\/[^/]+\/$/)
}

/**
 * Put one account of a given role on the instance, whatever an earlier run left behind.
 *
 * An account is never deleted on this API, only deactivated, so a run that finds its own
 * account already there sets the role and activates it rather than minting a second one. The
 * password is this suite's own constant, so the account an earlier run made signs in the same.
 *
 * The caller's context must already hold an admin session: making an account is an admin's.
 */
export async function seedUser(
    request: APIRequestContext,
    username: string,
    password: string,
    role: 'admin' | 'operator' | 'viewer',
): Promise<void> {
    const prefix = await apiPrefix(request)
    const created = await request.post(`${prefix}/users`, { data: { username, password, role } })
    if (created.ok()) return
    expect(created.status(), await created.text()).toBe(409)
    const changed = await request.patch(`${prefix}/users/${username}`, { data: { role } })
    expect(changed.ok(), await changed.text()).toBe(true)
    const active = await request.post(`${prefix}/users/${username}/$activate`)
    expect(active.ok(), await active.text()).toBe(true)
}

/** End the session this context holds, so the next sign-in is read as another account. */
export async function signOut(page: Page): Promise<void> {
    const prefix = await apiPrefix(page.request)
    const ended = await page.request.post(`${prefix}/auth/logout`)
    expect(ended.ok(), await ended.text()).toBe(true)
}

/** Where this instance mounted its versioned API, which the bundle reads and so does this. */
export async function apiPrefix(request: APIRequestContext): Promise<string> {
    const response = await request.get('/config.json')
    const config = (await response.json()) as { api_prefix: string }
    return config.api_prefix
}

/** Apply one of this repository's examples to the instance under test. */
export async function applyExample(request: APIRequestContext, reference: string): Promise<void> {
    const prefix = await apiPrefix(request)
    const applied = await request.post(`${prefix}/pipelines/$apply`, {
        data: { document: documentOf(reference), source: 'file', source_ref: reference },
    })
    expect(applied.ok(), await applied.text()).toBe(true)
}

/**
 * Apply a document written in the spec itself.
 *
 * For a shape no shipped example has -- two steps with nothing between them is not a pipeline
 * anybody would ship, and it is exactly what a spec about drawing an edge needs.
 */
export async function applyDocument(
    request: APIRequestContext,
    document: Record<string, unknown>,
): Promise<void> {
    const prefix = await apiPrefix(request)
    const applied = await request.post(`${prefix}/pipelines/$apply`, { data: { document } })
    expect(applied.ok(), await applied.text()).toBe(true)
}

/** Start an ad hoc run of a pipeline, answering with the run's id. */
export async function startRun(request: APIRequestContext, pipeline: string): Promise<string> {
    const prefix = await apiPrefix(request)
    const started = await request.post(`${prefix}/pipelines/${pipeline}/$run`, { data: { params: {} } })
    expect(started.ok(), await started.text()).toBe(true)
    const accepted = (await started.json()) as { run_id: string | null }
    expect(accepted.run_id).not.toBeNull()
    return accepted.run_id as string
}

/** Wait for a run to reach the state it settles in, which for these examples is under a second. */
export async function ranToCompletion(request: APIRequestContext, runId: string): Promise<void> {
    const prefix = await apiPrefix(request)
    await expect
        .poll(
            async () => {
                const response = await request.get(`${prefix}/runs/${runId}`)
                const detail = (await response.json()) as { run: { status: string } }
                return detail.run.status
            },
            { timeout: 30_000 },
        )
        .toBe('succeeded')
}

/**
 * One step that fails against this very instance, so a day with a failure in it is real.
 *
 * `/health` answers 200 and the step accepts only 418, so the call is made, the answer arrives,
 * and the step refuses it: a failure with no external network and nothing to be flaky about.
 * The code is the caller's, because two specs applying one pipeline would be two specs sharing
 * a history.
 */
export function refusedDocument(baseURL: string, code: string): Record<string, unknown> {
    return {
        format: 'dirigent/v1',
        kind: 'pipeline',
        code,
        description: 'One call whose answer is not one this step accepts.',
        requires: { blocks: ['http.request'] },
        steps: {
            call: { block: 'http.request', config: { url: `${baseURL}/health`, success_status: [418] } },
        },
    }
}

/** Wait for a run to settle where a refused call settles, which is badly. */
export async function ranToFailure(request: APIRequestContext, runId: string): Promise<void> {
    const prefix = await apiPrefix(request)
    await expect
        .poll(
            async () => {
                const response = await request.get(`${prefix}/runs/${runId}`)
                const detail = (await response.json()) as { run: { status: string } }
                return detail.run.status
            },
            { timeout: 30_000 },
        )
        .toBe('failed')
}

/**
 * Write a whole document into a Monaco editor, the way somebody puts one there.
 *
 * IT IS NOT A CONTROL WITH A VALUE. Monaco draws its own lines and reads a hidden textarea for
 * input, so `fill` writes into a box nothing reads and asserts a value nothing holds.
 *
 * IT REPLACES WHAT IS THERE. A pane opened on a document already holds one, and text pasted
 * into the middle of it is not the document the spec wrote.
 *
 * IT IS A PASTE, NOT KEYSTROKES. Typing a document in character by character is typing, and
 * Monaco indents what is typed: every line after the first arrives under the last one's indent,
 * and the YAML that lands is not the YAML the spec wrote. A paste is inserted as it stands,
 * which is what somebody pasting a document gets.
 *
 * The chunk is fetched when the pane first mounts, so this waits for the editor to arrive.
 */
export async function writeInEditor(page: Page, editor: Locator, text: string): Promise<void> {
    await expect(editor.locator('.monaco-editor')).toBeVisible({ timeout: 30_000 })
    const input = editor.locator('textarea').first()
    await editor.locator('.view-lines').click()
    await expect(input).toBeFocused()
    await page.keyboard.press('ControlOrMeta+a')
    // A real paste replaces the selection; a synthetic one is inserted at the caret, so a pane
    // that already holds a document is emptied rather than left for the new text to land inside.
    if ((await editor.locator('.view-lines').innerText()).trim() !== '') {
        await expect(editor.locator('.selected-text').first()).toBeVisible()
        await page.keyboard.press('Backspace')
    }
    await input.evaluate((node, written) => {
        const carried = new DataTransfer()
        carried.setData('text/plain', written)
        node.dispatchEvent(
            new ClipboardEvent('paste', { clipboardData: carried, bubbles: true, cancelable: true }),
        )
    }, text)
}

/**
 * Assert that every node of the graph on this page is inside the canvas that draws it.
 *
 * A GRAPH IS A SHAPE, and somebody opening one is asking what shape it is. A view that opened
 * zoomed into one corner answers a question nobody asked and hides the rest of the pipeline
 * under the panel beside it, so what is asserted is the whole of it being on screen at once.
 */
export async function everyNodeIsInView(page: Page): Promise<void> {
    await expect(page.locator('.react-flow__node').first()).toBeVisible()
    await expect
        .poll(
            async () =>
                page.evaluate(() => {
                    const pane = document.querySelector('.react-flow')
                    const nodes = [...document.querySelectorAll('.react-flow__node')]
                    if (pane === null || nodes.length === 0) return -1
                    const canvas = pane.getBoundingClientRect()
                    return nodes.filter((node) => {
                        const box = node.getBoundingClientRect()
                        return (
                            box.left >= canvas.left - 1 &&
                            box.right <= canvas.right + 1 &&
                            box.top >= canvas.top - 1 &&
                            box.bottom <= canvas.bottom + 1
                        )
                    }).length
                }),
            { timeout: 15_000 },
        )
        .toBe(await page.locator('.react-flow__node').count())
}

/**
 * Wait until the canvas has stopped moving.
 *
 * A graph re-fits on its own -- when elk answers, and whenever the canvas is resized, which is
 * what opening the right panel or the run's drawer does. A gesture aimed at a point read before
 * that settles lands somewhere else, so anything that presses on the canvas waits here first.
 */
export async function canvasSettled(page: Page): Promise<void> {
    let last = ''
    await expect
        .poll(
            async () => {
                const now = await viewportTransform(page)
                const steady = now !== '' && now === last
                last = now
                return steady
            },
            { intervals: [120, 120, 120, 120, 120, 250, 250, 500], timeout: 15_000 },
        )
        .toBe(true)
}

/** The pan and zoom the canvas is drawn at, as React Flow writes it. */
async function viewportTransform(page: Page): Promise<string> {
    return page.evaluate(() => {
        const viewport = document.querySelector('.react-flow__viewport')
        return viewport instanceof HTMLElement ? viewport.style.transform : ''
    })
}

/** How far the canvas is zoomed in, which a fit is capped at so a small graph is not blown up. */
export async function graphZoom(page: Page): Promise<number> {
    return page.evaluate(() => {
        const viewport = document.querySelector('.react-flow__viewport')
        const transform = viewport instanceof HTMLElement ? viewport.style.transform : ''
        return Number(/scale\(([\d.]+)\)/.exec(transform)?.[1] ?? 0)
    })
}

/**
 * Drag from one element to another the way a pointer does.
 *
 * In steps rather than in one jump: a canvas follows pointer moves, and a gesture that teleports
 * is one it never sees the middle of.
 */
export async function dragFromTo(page: Page, from: Locator, to: Locator): Promise<void> {
    const start = await from.boundingBox()
    const end = await to.boundingBox()
    expect(start, 'nothing to drag from').not.toBeNull()
    expect(end, 'nothing to drag to').not.toBeNull()
    await dragBetween(page, centreOf(start), centreOf(end))
}

/** Drag one element by an offset, which is how a box is moved on the canvas. */
export async function dragBy(page: Page, element: Locator, dx: number, dy: number): Promise<void> {
    const box = await element.boundingBox()
    expect(box, 'nothing to drag').not.toBeNull()
    const from = centreOf(box)
    await dragBetween(page, from, { x: from.x + dx, y: from.y + dy })
}

async function dragBetween(page: Page, from: Point, to: Point): Promise<void> {
    await page.mouse.move(from.x, from.y)
    await page.mouse.down()
    await page.mouse.move(to.x, to.y, { steps: 16 })
    await page.mouse.move(to.x, to.y)
    await page.mouse.up()
}

interface Point {
    x: number
    y: number
}

function centreOf(box: { x: number; y: number; width: number; height: number } | null): Point {
    if (box === null) throw new Error('the element has no box on the screen')
    return { x: box.x + box.width / 2, y: box.y + box.height / 2 }
}

/**
 * Where one node sits on the canvas, in the graph's own coordinates.
 *
 * React Flow writes a node's position as the element's own transform and the pan and zoom as the
 * viewport's, so this is where the box is in the graph rather than where it is on the screen.
 */
export async function nodeAt(page: Page, id: string): Promise<Point> {
    const transform = await page
        .locator(`.react-flow__node[data-id="${id}"]`)
        .evaluate((element) => (element instanceof HTMLElement ? element.style.transform : ''))
    const read = /translate\((-?[\d.]+)px,\s*(-?[\d.]+)px\)/.exec(transform)
    if (read === null) throw new Error(`node ${id} is not placed: ${transform}`)
    return { x: Number(read[1]), y: Number(read[2]) }
}

/**
 * Click the middle of an edge.
 *
 * An edge is a line: its bounding box has no area, so the centre of the box is not a point on
 * the line and a click aimed there lands on the canvas. What is aimed at instead is the middle
 * of the path itself, in the screen coordinates a pointer is moved in.
 */
export async function clickEdge(page: Page, edge: Locator): Promise<void> {
    const at = await edge.locator('.react-flow__edge-interaction').evaluate((element) => {
        const line = element as SVGPathElement
        const middle = line.getPointAtLength(line.getTotalLength() / 2)
        const screen = middle.matrixTransform(line.getScreenCTM() ?? undefined)
        return { x: screen.x, y: screen.y }
    })
    await page.mouse.click(at.x, at.y)
}
