import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig, devices } from '@playwright/test'

import { DOCS_SHOTS_HEIGHT, DOCS_SHOTS_WIDTH } from './docs-shots.config.ts'

/**
 * The pictures docs/basics.md is built out of, against a BARE `dg dev`.
 *
 * A camera beside `docs-shots.config.ts`, with one difference that decides everything: the page
 * starts from an empty instance and builds it up, so its pictures are of an instance holding the
 * page's own documents and nothing else. No seed, no corpus -- the dashboard at the end of the
 * page counts the runs the page made.
 *
 * ITS OWN STATE, wiped on every start, ON THE PORT THE PAGE NAMES: the page's documents call
 * the playground on 3333 and its pictures show that address, so the camera binds it too, and
 * refuses to start while a `dg dev` already holds it. `DOCS_BASICS_PORT` moves it, and the
 * documents are rewritten to follow.
 */

const here = path.dirname(fileURLToPath(import.meta.url))
const repositoryRoot = path.resolve(here, '../../..')

export const DOCS_BASICS_PORT = Number(process.env.DOCS_BASICS_PORT ?? 3333)
export const DOCS_BASICS_BASE_URL = `http://127.0.0.1:${String(DOCS_BASICS_PORT)}`

const stateRoot = path.join(here, 'docs-shots-src', '.state', 'basics')

export default defineConfig({
    testDir: './docs-shots-src',
    testMatch: 'basics.spec.ts',
    fullyParallel: false,
    retries: 0,
    workers: 1,
    reporter: 'list',
    timeout: 300_000,
    use: {
        baseURL: DOCS_BASICS_BASE_URL,
        viewport: { width: DOCS_SHOTS_WIDTH, height: DOCS_SHOTS_HEIGHT },
    },
    projects: [
        {
            name: 'chromium',
            use: {
                ...devices['Desktop Chrome'],
                viewport: { width: DOCS_SHOTS_WIDTH, height: DOCS_SHOTS_HEIGHT },
            },
        },
    ],
    webServer: {
        command: `mkdir -p "${stateRoot}" && cd "${stateRoot}" && uv run --project "${repositoryRoot}" dg dev --wipe-state --host 127.0.0.1 --port ${String(DOCS_BASICS_PORT)}`,
        cwd: repositoryRoot,
        env: {
            ...process.env,
            DIRIGENT_LOGIN_RATE_PER_MINUTE: '600',
            DIRIGENT_LOGIN_ADDRESS_RATE_PER_MINUTE: '600',
            DIRIGENT_WORKER_NAME: 'worker-1',
        },
        url: `${DOCS_BASICS_BASE_URL}/health`,
        reuseExistingServer: false,
        stdout: 'ignore',
        timeout: 300_000,
    },
})
