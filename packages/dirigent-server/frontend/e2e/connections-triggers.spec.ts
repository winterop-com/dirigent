import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

import { counted, LABELS } from '../src/lib/labels.ts'
import { apiPrefix, applyDocument, applyExample, removeConnection, signIn } from './support.ts'

/**
 * The two screens that show what an instance is wired to, against a real one.
 *
 * WHAT THESE SPECS ARE FOR is the half a Node test cannot reach: that a credential's row says
 * what it is and never a word of what it holds, and that pressing Check really opens the
 * credential and really moves the row.
 *
 * THE CHECK REACHES THIS INSTANCE. The connection points at the server this suite already
 * runs, so a health check is a real request over a real credential with no external network
 * and nothing to be flaky about.
 */

/** The example documents that carry a trigger each. */
const CRON = {
    file: 'examples/triggers/cron-nightly.yaml',
    pipeline: 'cron-nightly',
    schedule: 'nightly',
    // The document names this clock, so the row is headed by the name and carries the code.
    title: 'Nightly, Oslo time',
    // What the pipeline itself is called, which is how the picker heads its row.
    pipelineTitle: 'Nightly load',
}

/** What a secret is drawn as. `DOTS` in lib/connections. */
const DOTS = '●●●'

const CONNECTION = 'e2e-http'

/** The credential the dialog spec types, which must be nowhere on any screen afterwards. */
const MINTED = 'a credential the dialog must never show'

/**
 * Put one connection on the instance, with a secret set and a health path that answers.
 *
 * Minted fresh every time: whether it has been checked is what two of these specs are about,
 * and a row left behind by an earlier run has been.
 */
async function seedConnection(request: APIRequestContext, baseURL: string): Promise<void> {
    const prefix = await apiPrefix(request)
    await request.delete(`${prefix}/connections/${CONNECTION}`)
    const created = await request.post(`${prefix}/connections`, {
        data: {
            code: CONNECTION,
            kind: 'http',
            description: 'This very instance, so a check is a real request.',
            config: {
                base_url: baseURL,
                basic_username: 'dev',
                basic_password: 'a credential nothing may ever show',
                health_path: '/health',
            },
        },
    })
    expect(created.ok(), await created.text()).toBe(true)
}

/**
 * Pick one row of a combobox by typing at it, the way somebody finds a pipeline.
 *
 * The list is portalled out of the dialog, so the option is reached on the page rather than
 * inside it.
 */
async function pick(page: Page, field: string, query: string, option: string): Promise<void> {
    const box = page.getByRole('dialog').getByLabel(field, { exact: true })
    // Emptied first: a box already holding what is about to be typed into it is a box nothing
    // changed, and the list opens on the change.
    await box.fill('')
    await box.fill(query)
    await page.getByRole('option', { name: option }).click()
}

/** The table row one code is in. */
function rowOf(page: Page, code: string) {
    return page.getByRole('row').filter({ hasText: code })
}

test('a connection row is its code, its kind and its health, and nothing else', async ({ page, baseURL }) => {
    await signIn(page)
    await seedConnection(page.request, baseURL ?? '')

    await page.goto('/connections')

    const row = rowOf(page, CONNECTION)
    await expect(row).toContainText('http')

    // The kind is marked as well as named, the way it is on every other screen.
    await expect(row.locator('[data-slot="mark"]')).toHaveCount(1)

    // One line: what the credential is pointed at, what it says about itself and whether a
    // secret is set are read on its own page, beside the boxes that change them.
    await expect(row).not.toContainText('base_url')
    await expect(row).not.toContainText(DOTS)
    await expect(row).not.toContainText('This very instance, so a check is a real request.')

    // The credential itself is nowhere on the screen, in any form.
    await expect(page.locator('body')).not.toContainText('a credential nothing may ever show')

    // It has never been checked until something checks it.
    await expect(row).toContainText(LABELS.state.health.unchecked)

    // And the dialog behind the row is where all of that is, with the address naming it.
    await row.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('This very instance, so a check is a real request.')
    await expect(dialog).toContainText(baseURL ?? '')
    await expect(page).toHaveURL(new RegExp(`/connections/${CONNECTION}$`))

    // It heads the credential the way the row does, mark and all, and no panel opened.
    await expect(dialog.locator('[data-slot="mark"]')).toHaveCount(1)
    await expect(page.getByRole('tabpanel')).toHaveCount(0)
    await expect(page.getByRole('button', { name: LABELS.shell.toggle_panel })).toHaveCount(0)

    // Closing it takes the address back to the listing.
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await expect(page).toHaveURL(/\/connections$/)
})

test('an address naming a connection opens its dialog', async ({ page, baseURL }) => {
    await signIn(page)
    await seedConnection(page.request, baseURL ?? '')
    await page.goto(`/connections/${CONNECTION}`)
    await expect(page.getByRole('dialog')).toContainText(CONNECTION)
    await expect(page.getByRole('button', { name: LABELS.action.edit, exact: true })).toBeFocused()
})

test('checking a connection moves its own row, and the sentence is on the tooltip', async ({
    page,
    baseURL,
}) => {
    await signIn(page)
    await seedConnection(page.request, baseURL ?? '')

    await page.goto('/connections')
    const row = rowOf(page, CONNECTION)
    await row.click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('button', { name: LABELS.action.check }).click()

    // The dialog says the check's sentence in full, where there is room for it.
    await expect(dialog).toContainText('HTTP 200')
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)

    // A healthy row is a bare dot: no word, and no sentence.
    await expect(row).not.toContainText(LABELS.state.health.unchecked)
    await expect(row).not.toContainText(LABELS.state.health.healthy)
    await expect(row).not.toContainText('HTTP 200')

    // Reaching the dot is what says both. The tooltip primitive describes its trigger rather
    // than carrying a role, so it is found by the slot it is drawn in.
    await row.getByRole('img', { name: LABELS.state.health.healthy }).hover()
    const tip = page.locator('[data-slot="tooltip-content"]')
    await expect(tip).toContainText(LABELS.state.health.healthy)
    await expect(tip).toContainText('HTTP 200')
})

test('a connection edits in the same dialog, and cancelling goes back to the reading', async ({
    page,
    baseURL,
}) => {
    await signIn(page)
    await seedConnection(page.request, baseURL ?? '')

    await page.goto(`/connections/${CONNECTION}`)
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('button', { name: LABELS.action.edit, exact: true }).click()
    const name = dialog.getByLabel(LABELS.word.name.label, { exact: true })
    await expect(name).toBeVisible()

    // Cancel is the way back to the reading, and what was typed goes with it.
    await name.fill('Typed, then thought better of')
    await dialog.getByRole('button', { name: LABELS.action.cancel, exact: true }).click()
    await expect(dialog.getByRole('button', { name: LABELS.action.edit, exact: true })).toBeVisible()
    await expect(page).toHaveURL(new RegExp(`/connections/${CONNECTION}$`))
    await expect(dialog).not.toContainText('Typed, then thought better of')

    // A save writes it, and the dialog reads it back.
    const title = `Saved ${String(Date.now())}`
    await dialog.getByRole('button', { name: LABELS.action.edit, exact: true }).click()
    await name.fill(title)
    await dialog.getByRole('button', { name: LABELS.action.save.verb, exact: true }).click()
    await expect(dialog.getByRole('button', { name: LABELS.action.edit, exact: true })).toBeVisible()
    await expect(dialog).toContainText(title)
    await page.keyboard.press('Escape')
    await expect(rowOf(page, CONNECTION)).toContainText(title)
})

test('deleting a connection asks first, and a refusal stays in the question', async ({ page, baseURL }) => {
    await signIn(page)
    await seedConnection(page.request, baseURL ?? '')

    await page.goto(`/connections/${CONNECTION}`)
    await page.getByRole('button', { name: LABELS.action.delete.verb, exact: true }).click()
    const asking = page.getByRole('dialog', { name: `Delete ${CONNECTION}?` })

    // The question is the title, and it holds nothing else: the verb says what is lost.
    await expect(asking.locator('p')).toHaveCount(0)

    // Cancel leaves it where it was.
    await asking.getByRole('button', { name: LABELS.action.cancel, exact: true }).click()
    await expect(asking).toHaveCount(0)
    await expect(page.getByRole('dialog')).toContainText(CONNECTION)

    // A refusal is said in the question, and the question stays.
    await page.route(`**/connections/${CONNECTION}`, (route) =>
        route.request().method() === 'DELETE'
            ? route.fulfill({
                  status: 409,
                  contentType: 'application/problem+json',
                  body: JSON.stringify({
                      status: 409,
                      title: 'Conflict',
                      detail: 'the server said no',
                      code: 'server.connection_referenced',
                      params: { code: CONNECTION },
                  }),
              })
            : route.continue(),
    )
    await page.getByRole('button', { name: LABELS.action.delete.verb, exact: true }).click()
    await asking.getByRole('button', { name: LABELS.action.delete.verb, exact: true }).click()
    await expect(asking).toContainText(LABELS.refused.server.connection_referenced)
    await page.unrouteAll()

    // And with nothing in the way the connection goes, and the address with it.
    await asking.getByRole('button', { name: LABELS.action.delete.verb, exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page).toHaveURL(/\/connections$/)
    await expect(rowOf(page, CONNECTION)).toHaveCount(0)
})

test('the connections listing fits 1024 without scrolling sideways', async ({ page, baseURL }) => {
    await signIn(page)
    await seedConnection(page.request, baseURL ?? '')

    await page.setViewportSize({ width: 1024, height: 768 })
    await page.goto('/connections')
    await expect(rowOf(page, CONNECTION)).toBeVisible()

    // The table's own scroll box rather than the window: a listing wider than the box it is
    // drawn in is the sideways scroll, whether or not the page itself moves.
    const listing = page.locator('.list-scroll')
    expect(await listing.evaluate((box) => box.scrollWidth - box.clientWidth)).toBeLessThanOrEqual(0)

    const sideways = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(sideways).toBeLessThanOrEqual(0)
})

test('a connection opens a form whose secret box is empty and whose kind is fixed', async ({
    page,
    baseURL,
}) => {
    await signIn(page)
    await seedConnection(page.request, baseURL ?? '')

    await page.goto('/connections')
    await rowOf(page, CONNECTION).click()
    const dialog = page.getByRole('dialog')

    // The reading says a secret is set, and never what it is.
    await expect(dialog).toContainText(DOTS)
    await expect(dialog).not.toContainText('a credential nothing may ever show')
    await dialog.getByRole('button', { name: LABELS.action.edit, exact: true }).click()

    // The form holds the connection's own settings, and the password box starts empty --
    // there is nothing to put in it, because no read anywhere returns a credential.
    const secret = dialog.getByLabel('basic_password')
    await expect(secret).toHaveValue('')
    await expect(secret).toHaveAttribute('type', 'password')
    await expect(dialog.getByLabel('base_url')).toHaveValue(baseURL ?? '')
})

test('a column heading is a label, whatever face its cells are in', async ({ page }) => {
    await signIn(page)
    await page.goto('/blocks')
    const heading = page.getByRole('columnheader', { name: LABELS.word.plugin.label }).first()
    await expect(heading).toBeVisible()
    await expect(heading).toHaveCSS('font-family', /Plex Sans/)
})

test('a small button is on the type scale', async ({ page }) => {
    await signIn(page)
    await page.goto('/pipelines')
    const small = page.locator('[data-slot="button"].text-\\[0\\.8rem\\]').first()
    await expect(small).toBeVisible()
    await expect(small).toHaveCSS('font-size', '12px')
})

test('a new connection has one way out, and it says Cancel', async ({ page }) => {
    await signIn(page)
    await page.goto('/connections')
    await page.getByRole('button', { name: LABELS.connections.new }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('button', { name: LABELS.action.cancel, exact: true })).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Close', exact: true })).toHaveCount(0)
})

test('a connection a rule delivers through says so, and its delete is shut', async ({ page }) => {
    await signIn(page)
    const prefix = await apiPrefix(page.request)
    const code = 'e2e-used-hook'
    const rule = 'e2e-used-by-rule'
    await page.request.delete(`${prefix}/alert-rules/${rule}`)
    await page.request.delete(`${prefix}/connections/${code}`)
    const hook = await page.request.post(`${prefix}/connections`, {
        data: { code, kind: 'webhook', config: { url: 'http://127.0.0.1:9/none' } },
    })
    expect(hook.ok(), await hook.text()).toBe(true)
    const made = await page.request.post(`${prefix}/alert-rules`, {
        data: { code: rule, event: 'run_failed', connection: code },
    })
    expect(made.ok(), await made.text()).toBe(true)

    await page.goto(`/connections/${code}`)
    await page.getByRole('button', { name: LABELS.action.delete.verb, exact: true }).click()
    const asking = page.getByRole('dialog', { name: `Delete ${code}?` })
    await expect(asking).toContainText(LABELS.connections.used_by(`alert rule ${rule}`))
    const verb = asking.getByRole('button', { name: LABELS.action.delete.verb, exact: true })
    await expect(verb).toHaveAttribute('aria-disabled', 'true')
    await expect(verb).toHaveAttribute('title', LABELS.connections.in_use)

    await page.request.delete(`${prefix}/alert-rules/${rule}`)
    await page.request.delete(`${prefix}/connections/${code}`)
})

test('a connection a pipeline names says so in its reading, and its delete is shut', async ({ page }) => {
    await signIn(page)
    const prefix = await apiPrefix(page.request)
    const code = 'e2e-used-http'
    const pipeline = 'e2e-names-a-connection'
    await removeConnection(page.request, code)
    const made = await page.request.post(`${prefix}/connections`, {
        data: { code, kind: 'http', config: { base_url: 'http://127.0.0.1:9' } },
    })
    expect(made.ok(), await made.text()).toBe(true)
    const applied = await page.request.post(`${prefix}/pipelines/$apply`, {
        data: {
            document: {
                format: 'dirigent/v1',
                kind: 'pipeline',
                code: pipeline,
                steps: { fetch: { block: 'http.request', config: { connection: code, path: '/' } } },
            },
        },
    })
    expect(applied.ok(), await applied.text()).toBe(true)

    await page.goto(`/connections/${code}`)
    const reading = page.getByRole('dialog').filter({ hasText: code })
    await expect(reading.getByRole('link', { name: pipeline })).toHaveAttribute(
        'href',
        `/pipelines/${pipeline}`,
    )
    await expect(reading).toContainText('fetch')

    await page.getByRole('button', { name: LABELS.action.delete.verb, exact: true }).click()
    const asking = page.getByRole('dialog', { name: `Delete ${code}?` })
    await expect(asking).toContainText(LABELS.connections.used_by(`pipeline ${pipeline}`))
    const verb = asking.getByRole('button', { name: LABELS.action.delete.verb, exact: true })
    await expect(verb).toHaveAttribute('aria-disabled', 'true')
    await expect(verb).toHaveAttribute('title', LABELS.connections.in_use)

    // THE SERVER REFUSES THE SAME, whatever the read in front of it said.
    const refused = await page.request.delete(`${prefix}/connections/${code}`)
    expect(refused.status()).toBe(409)

    await removeConnection(page.request, code)
})

test('a connection is minted through the form its own kind publishes', async ({ page, baseURL }) => {
    await signIn(page)
    await page.goto('/connections')

    const code = `minted-${String(Date.now())}`
    await page.getByRole('button', { name: LABELS.connections.new }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel(LABELS.word.code, { exact: true }).fill(code)

    // The kind is a choice over what this instance has installed, and choosing one is what
    // draws the config: every box below is the kind's own schema, its secrets excepted.
    await dialog.getByLabel(LABELS.word.kind.label).click()
    // Every kind the dialog offers is marked as well as named.
    const kindRow = page.getByRole('option', { name: 'http', exact: true })
    await expect(kindRow.locator('[data-slot="mark"]')).toHaveCount(1)
    await kindRow.click()
    await dialog.getByLabel('base_url').fill(baseURL ?? '')
    await dialog.getByLabel('basic_password').fill(MINTED)

    // A secret is written and never read, here as much as in the connection's own dialog.
    await expect(dialog.getByLabel('basic_password')).toHaveAttribute('type', 'password')

    await dialog.getByRole('button', { name: LABELS.action.create.verb }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)

    // The row is on the listing, saying which kind it is and never a word of the credential.
    const row = rowOf(page, code)
    await expect(row).toContainText('http')
    await expect(page.locator('body')).not.toContainText(MINTED)

    // And its own dialog says the same: a stored credential, and an empty box to replace it with.
    await row.click()
    const opened = page.getByRole('dialog')
    await opened.getByRole('button', { name: LABELS.action.edit, exact: true }).click()
    const secret = opened.getByLabel('basic_password')
    await expect(secret).toHaveValue('')
    await expect(secret).toHaveAttribute('placeholder', /stored/)
    await expect(opened.getByLabel('base_url')).toHaveValue(baseURL ?? '')
})

test('a schedule shows its clock and its zone', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, CRON.file)

    await page.goto('/triggers')

    const schedule = rowOf(page, CRON.title)
    await expect(schedule).toContainText(CRON.schedule)
    await expect(schedule).toContainText(LABELS.triggers.schedule.dialog.clock.cron.hint)
    await expect(schedule).toContainText('Europe/Oslo')
    await expect(schedule).toContainText(CRON.pipeline)
    await expect(schedule).toContainText(LABELS.triggers.managed)

    // The next firing is an instant like any other: read relatively, and ahead of now.
    await expect(schedule.getByTestId('next-fire')).toHaveText(/^in \d+[mhd]$/)

    // The foot counts what has been read, and there is no page number anywhere on the screen. How
    // many rows this instance holds is not this spec's business, but the sentence beside that
    // number is: it has to be the one the catalogue spells for the number actually on screen.
    for (const noun of [LABELS.word.schedule.count]) {
        const foot = page.getByText(new RegExp(`^\\d+ (${noun.one}|${noun.many})$`))
        await expect(foot).toBeVisible()
        const said = await foot.innerText()
        const read = Number(said.split(' ')[0])
        expect(said).toBe(LABELS.shell.rows_read(String(read), counted(read, noun)))
    }
})

test('a schedule opens its own facts and its firing history beside the listing', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, CRON.file)

    await page.goto('/triggers')
    // The row's own heading, rather than its middle: the middle of a row is whichever
    // cell happens to be there, and one of them is a link to the pipeline.
    await rowOf(page, CRON.title).getByText(CRON.title, { exact: true }).click()

    // The panel's own tab, rather than the aside: the navigation rail is an aside too.
    const panel = page.getByRole('tabpanel')
    await expect(panel).toContainText('Europe/Oslo')
    await expect(panel).toContainText(LABELS.word.firing.heading)
    await expect(panel).toContainText(LABELS.triggers.schedule.no_firings)

    // A paused schedule fires at no instant. The row keeps the one the scheduler computed, so
    // that it has somewhere to resume from, and the screen says it is paused once: the chip.
    await expect(panel.getByTestId('next-fire')).toHaveText(/^in \d+[mhd]$/)
    await panel.getByRole('button', { name: 'Pause' }).click()
    await expect(panel.getByRole('button', { name: 'Resume' })).toBeVisible()
    await expect(panel.getByTestId('next-fire')).toHaveCount(0)
    await expect(panel.getByText(LABELS.state.armed.paused, { exact: true })).toHaveCount(1)
    // The listing behind says it the same way: its chip, and no Next beside it.
    await expect(page.getByTestId('next-fire')).toHaveCount(0)
    await expect(page.getByText(LABELS.state.armed.paused, { exact: true })).toHaveCount(2)

    await panel.getByRole('button', { name: 'Resume' }).click()
    await expect(panel.getByTestId('next-fire')).toHaveText(/^in \d+[mhd]$/)
})

/** A pipeline with no name of its own, carrying a named schedule that fires once a year. */
const UNNAMED = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: 'e2e-unnamed',
    steps: { only: { block: 'transform.jq', config: { input: { at: 1 }, program: '.' } } },
    triggers: {
        schedules: [{ code: 'yearly', name: 'Once a year', cron: '0 0 1 1 *', timezone: 'UTC' }],
    },
}

test('a trigger names the pipeline it fires the way every listing heads one', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, CRON.file)
    await applyDocument(page.request, UNNAMED)

    await page.goto('/triggers')
    // A pipeline with a name is headed by it, with its code under it in mono.
    for (const [row, title, code] of [
        [rowOf(page, CRON.title), CRON.pipelineTitle, CRON.pipeline],
    ] as const) {
        const ref = row.getByTestId('pipeline-ref')
        await expect(ref.getByRole('link')).toHaveText(title)
        await expect(ref.getByText(code, { exact: true })).toHaveCSS('font-family', /Mono/)
    }
    // One without a name is headed by its code, in mono, and the code is not drawn twice.
    const bare = rowOf(page, 'Once a year').getByTestId('pipeline-ref')
    await expect(bare.getByRole('link')).toHaveText(UNNAMED.code)
    await expect(bare.getByRole('link')).toHaveCSS('font-family', /Mono/)
    await expect(bare.getByText(UNNAMED.code, { exact: true })).toHaveCount(1)

    // The panel names it the same way.
    await rowOf(page, CRON.title).getByText(CRON.title, { exact: true }).click()
    const panel = page.getByRole('tabpanel').getByTestId('pipeline-ref')
    await expect(panel.getByRole('link')).toHaveText(CRON.pipelineTitle)
    await expect(panel.getByText(CRON.pipeline, { exact: true })).toHaveCSS('font-family', /Mono/)
})

test('the heading keeps its width at 1024 beside an open panel, and its verb stays in reach', async ({
    page,
}) => {
    await signIn(page)
    await applyExample(page.request, CRON.file)
    await page.setViewportSize({ width: 1024, height: 768 })

    await page.goto('/triggers')
    await rowOf(page, CRON.title).getByText(CRON.title, { exact: true }).click()
    await expect(page.getByRole('tabpanel')).toContainText('Europe/Oslo')

    const heading = page.getByRole('heading', { name: 'Triggers', level: 1 })
    const measured = await heading.evaluate((element) => {
        const range = document.createRange()
        range.selectNodeContents(element)
        return { box: element.getBoundingClientRect().width, natural: range.getBoundingClientRect().width }
    })
    expect(measured.box).toBeGreaterThanOrEqual(measured.natural)
    // The create verb sits beside it, or behind the one menu when it no longer fits.
    await expect(
        page
            .getByRole('button', { name: LABELS.triggers.schedule.new, exact: true })
            .or(page.getByRole('button', { name: LABELS.shell.more_actions })),
    ).toBeVisible()
    expect(
        await page.evaluate(
            () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        ),
    ).toBeLessThanOrEqual(0)
})

test('a pinned parameters block stands off the light panel it is drawn on', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, CRON.file)
    await page.evaluate(() => {
        localStorage.setItem('theme', 'light')
    })

    await page.goto('/triggers')
    await rowOf(page, CRON.title).getByText(CRON.title, { exact: true }).click()
    const panel = page.getByRole('tabpanel')
    const block = panel.locator('pre').filter({ hasText: 'production' })
    await expect(block).toBeVisible()

    // The ground and the block's edge, each painted to one pixel and read back as RGB.
    const apart = await block.evaluate((element) => {
        const paint = (colours: string[]): number[] => {
            const canvas = document.createElement('canvas')
            canvas.width = 1
            canvas.height = 1
            const context = canvas.getContext('2d')
            if (context === null) return [0, 0, 0]
            for (const colour of colours) {
                context.fillStyle = colour
                context.fillRect(0, 0, 1, 1)
            }
            return Array.from(context.getImageData(0, 0, 1, 1).data.slice(0, 3))
        }
        // The block's box is the nearest element inside the panel that draws an edge.
        const tab = element.closest('[role="tabpanel"]')
        let box: Element = element
        while (
            box !== tab &&
            box.parentElement !== null &&
            Number.parseFloat(getComputedStyle(box).borderTopWidth) < 1
        ) {
            box = box.parentElement
        }
        let ground = box.parentElement
        while (ground !== null && getComputedStyle(ground).backgroundColor === 'rgba(0, 0, 0, 0)') {
            ground = ground.parentElement
        }
        const under = ground === null ? 'white' : getComputedStyle(ground).backgroundColor
        const style = getComputedStyle(box)
        const base = paint([under])
        const edge = paint([under, style.backgroundColor, style.borderTopColor])
        const width = Number.parseFloat(style.borderTopWidth)
        return { width, distance: base.reduce((sum, part, at) => sum + Math.abs(part - (edge[at] ?? 0)), 0) }
    })
    expect(apart.width).toBeGreaterThanOrEqual(1)
    expect(apart.distance).toBeGreaterThanOrEqual(24)
})

test('a schedule is created by picking its pipeline and reading its clock back', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, CRON.file)

    await page.goto('/triggers')
    await page.getByRole('button', { name: LABELS.triggers.schedule.new, exact: true }).click()

    const code = `picked-${String(Date.now())}`
    const dialog = page.getByRole('dialog')
    await pick(page, 'Pipeline', CRON.pipeline, CRON.pipelineTitle)
    await dialog.getByLabel(LABELS.word.code, { exact: true }).fill(code)
    await pick(page, 'Timezone', 'Europe/Oslo', 'Europe/Oslo')
    await dialog
        .getByLabel(LABELS.triggers.schedule.dialog.clock.cron.name, { exact: true })
        .fill('0 5 * * *')

    // The clock is read back by the instance: three firings, in the zone that was chosen.
    const reading = dialog.getByTestId('clock-reading')
    await expect(reading).toContainText('05:00')
    expect(((await reading.textContent()) ?? '').split(' · ')).toHaveLength(3)

    // Choosing the pipeline drew its own parameter form, and a pinned value is sent with it.
    await dialog.getByLabel('day', { exact: true }).fill('2026-02-02')

    await dialog.getByRole('button', { name: LABELS.action.create.verb }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)

    const row = rowOf(page, code)
    await expect(row).toContainText(LABELS.triggers.schedule.dialog.clock.cron.hint)
    await expect(row).toContainText('Europe/Oslo')

    const prefix = await apiPrefix(page.request)
    const read = await page.request.get(`${prefix}/pipelines/${CRON.pipeline}/triggers/schedules/${code}`)
    expect((await read.json()).params).toEqual({ day: '2026-02-02' })
})

test('a clock nothing can read says so where its firings would be, and shuts Create', async ({ page }) => {
    await signIn(page)
    await applyExample(page.request, CRON.file)

    await page.goto('/triggers')
    await page.getByRole('button', { name: LABELS.triggers.schedule.new, exact: true }).click()

    const dialog = page.getByRole('dialog')
    await pick(page, 'Pipeline', CRON.pipeline, CRON.pipelineTitle)
    await dialog.getByLabel(LABELS.word.code, { exact: true }).fill('never')
    await dialog
        .getByLabel(LABELS.triggers.schedule.dialog.clock.cron.name, { exact: true })
        .fill('not a cron expression')

    await expect(dialog.getByTestId('clock-reading')).toContainText('is not a cron expression')
    await expect(dialog.getByRole('button', { name: LABELS.action.create.verb })).toBeDisabled()
})
