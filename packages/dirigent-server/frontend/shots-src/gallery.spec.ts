import { existsSync, mkdirSync, rmSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { test, type Page } from '@playwright/test'

/** Where the gallery lands. Wiped per run; gitignored. */
const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'shots')

const DEV_USERNAME = 'dev'
const DEV_PASSWORD = 'dirigent-dev'

async function shot(page: Page, mode: string, name: string): Promise<void> {
    // The corner identity fills over its reads after every full load; a picture of the
    // asking state would put the wrong topbar in every frame.
    await page
        .waitForFunction(() => /\d+\.\d+\.\d+/.test(document.querySelector('header')?.textContent ?? ''), undefined, {
            timeout: 8000,
        })
        .catch(() => undefined)
    await page.waitForTimeout(800)
    await page.screenshot({ path: path.join(OUT, `${name}--${mode}.png`) })
}

async function signIn(page: Page): Promise<void> {
    await page.goto('/login')
    await page.getByLabel('Username').fill(DEV_USERNAME)
    await page.getByLabel('Password', { exact: true }).fill(DEV_PASSWORD)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await page.waitForURL((url) => url.pathname === '/')
}

/** The one "test": a camera walking every screen in both palettes. */
test('the gallery', async ({ page }) => {
    test.setTimeout(480_000)
    if (existsSync(OUT)) rmSync(OUT, { recursive: true })
    mkdirSync(OUT, { recursive: true })
    // The login page, before any session exists.
    for (const mode of ['dark', 'light']) {
        await page.goto('/login')
        await page.evaluate((theme) => localStorage.setItem('theme', theme), mode)
        await page.goto('/login')
        await shot(page, mode, 'login')
    }
    await signIn(page)

    // The weather has to settle before the camera walks: the seed applies documents and
    // starts runs while this camera would otherwise already be shooting, and a gallery of a
    // half-seeded instance shows neither the corpus nor the failures.
    let items: { status: string; id: string }[] = []
    let count = 0
    let quiet = 0
    for (let waited = 0; waited < 120_000 && quiet < 3; waited += 1500) {
        const pipelines = (await (await page.request.get('/api/v1/pipelines?limit=50')).json()) as {
            items: unknown[]
        }
        items = ((await (await page.request.get('/api/v1/runs?limit=50')).json()) as {
            items: { status: string; id: string }[]
        }).items
        const settled =
            items.length > 0 && items.every((run) => !['running', 'queued', 'pending'].includes(run.status))
        quiet = settled && pipelines.items.length === count && count > 0 ? quiet + 1 : 0
        count = pipelines.items.length
        await page.waitForTimeout(1500)
    }
    const failed = items.find((run) => run.status === 'failed')
    const succeeded = items.find((run) => run.status === 'succeeded')

    for (const mode of ['dark', 'light']) {
        // The drawer remembers being open, so the pass that opened it would leave every run
        // frame of the next pass with a console under the graph and shoot a shut drawer here.
        await page.evaluate((theme) => {
            localStorage.setItem('theme', theme)
            localStorage.setItem('dirigent.terminalOpen', 'false')
        }, mode)

        for (const [name, route] of [
            ['dashboard', '/'],
            ['pipelines', '/pipelines'],
            ['runs', '/runs'],
            ['run-detail-failed', failed ? `/runs/${failed.id}` : '/runs'],
            ['run-detail-succeeded', succeeded ? `/runs/${succeeded.id}` : '/runs'],
            ['editor', '/pipelines/fan-in'],
            ['triggers', '/triggers'],
            ['connections', '/connections'],
            ['blocks', '/blocks'],
            ['admin-overview', '/admin'],
            ['admin-users', '/admin/users'],
            ['admin-workers', '/admin/workers'],
            ['admin-alerting', '/admin/alerting'],
        ] as const) {
            await page.goto(route)
            await shot(page, mode, name)
        }

        // The overlays: the palette, the settings dialog, and the run terminal.
        await page.goto('/pipelines')
        await page.keyboard.press('ControlOrMeta+k')
        await page.getByPlaceholder(/run, pipeline|go to/i).or(page.locator('[cmdk-input]')).first()
            .waitFor({ timeout: 4000 })
            .catch(() => undefined)
        await shot(page, mode, 'palette')
        await page.keyboard.press('Escape')

        await page.getByRole('button', { name: 'Settings', exact: true }).click()
        await shot(page, mode, 'settings')
        await page.keyboard.press('Escape')

        if (failed) {
            // The graph first: `t` is read off the document, and a press that lands before the
            // shell has mounted is a press nothing answers.
            await page.goto(`/runs/${failed.id}`)
            await page.locator('.react-flow__node').first().waitFor({ timeout: 30_000 })
            await page.locator('body').press('t')
            await page.getByRole('region', { name: 'Run terminal' }).waitFor({ timeout: 10_000 })
            await shot(page, mode, 'run-terminal')
        }
    }
})
