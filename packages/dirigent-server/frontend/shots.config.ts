import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig, devices } from '@playwright/test'

/**
 * The screenshot gallery: every screen, both palettes, against a SEEDED instance.
 *
 * Not a test suite -- a camera. It reuses the browser machinery because the e2e lane already
 * knows how to stand a real instance up, and it runs against the seed script rather than a
 * bare `dg dev` so the pictures carry weather: failed runs, red health, paused schedules.
 * `make ui-shots` runs it; the gallery lands in `shots/`, regenerated every time and never
 * committed -- one change to the bottom bar would touch every picture.
 */

const here = path.dirname(fileURLToPath(import.meta.url))
const repositoryRoot = path.resolve(here, '../../..')

export const SHOTS_PORT = Number(process.env.SHOTS_PORT ?? 3378)
export const SHOTS_BASE_URL = `http://127.0.0.1:${String(SHOTS_PORT)}`

const scratchRoot = path.join(here, 'shots-src', '.state')

export default defineConfig({
    testDir: './shots-src',
    fullyParallel: false,
    retries: 0,
    workers: 1,
    reporter: 'list',
    timeout: 180_000,
    use: {
        baseURL: SHOTS_BASE_URL,
        viewport: { width: 1440, height: 900 },
    },
    projects: [
        { name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    ],
    webServer: {
        command: `uv run python scripts/seed_dev.py --root ${scratchRoot} --host 127.0.0.1 --port ${String(SHOTS_PORT)}`,
        cwd: repositoryRoot,
        env: {
            ...process.env,
            DIRIGENT_LOGIN_RATE_PER_MINUTE: '600',
        },
        url: `${SHOTS_BASE_URL}/health`,
        reuseExistingServer: false,
        stdout: 'ignore',
        timeout: 180_000,
    },
})
