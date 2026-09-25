import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig, devices } from '@playwright/test'

/**
 * The nine pictures docs/screens.md is built out of, against a SEEDED instance.
 *
 * Not a test suite -- a camera, like `shots.config.ts` beside it, and the same arrangement:
 * the seed script rather than a bare `dg dev`, so the pictures carry weather. What is
 * different is where they land and what they are of. The gallery photographs every screen in
 * both palettes into an untracked directory; this photographs nine screens in the `dirigent`
 * palette in dark mode into `docs/images/screens/`, and those files are committed, because
 * a documentation page cannot render a picture nobody kept.
 *
 * THE PICTURES ARE OF THE SHOWCASE SHELF. `examples/showcase/` is three documents sized like
 * real work, and this camera runs them to the states the page needs: one mid-flight with
 * eight items in the air, one settled `completed_with_errors` with a report to read.
 *
 * ITS OWN PORT AND ITS OWN STATE, so a run of this never touches a developer's instance or
 * the gallery's.
 */

const here = path.dirname(fileURLToPath(import.meta.url))
const repositoryRoot = path.resolve(here, '../../..')

export const DOCS_SHOTS_PORT = Number(process.env.DOCS_SHOTS_PORT ?? 3379)
export const DOCS_SHOTS_BASE_URL = `http://127.0.0.1:${String(DOCS_SHOTS_PORT)}`

/** Every picture is taken at this width, and none of them may scroll sideways in it. */
export const DOCS_SHOTS_WIDTH = 1440
export const DOCS_SHOTS_HEIGHT = 900

const scratchRoot = path.join(here, 'docs-shots-src', '.state')

export default defineConfig({
    testDir: './docs-shots-src',
    fullyParallel: false,
    retries: 0,
    workers: 1,
    reporter: 'list',
    timeout: 300_000,
    use: {
        baseURL: DOCS_SHOTS_BASE_URL,
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
        command: `uv run python scripts/seed_dev.py --root ${scratchRoot} --host 127.0.0.1 --port ${String(DOCS_SHOTS_PORT)}`,
        cwd: repositoryRoot,
        env: {
            ...process.env,
            DIRIGENT_LOGIN_RATE_PER_MINUTE: '600',
            // A worker registers under its hostname unless it is told otherwise, and the
            // dashboard draws it. These pictures are published, so the name is this one's
            // rather than whichever laptop took them.
            DIRIGENT_WORKER_NAME: 'worker-1',
        },
        url: `${DOCS_SHOTS_BASE_URL}/health`,
        reuseExistingServer: false,
        stdout: 'ignore',
        timeout: 300_000,
    },
})
