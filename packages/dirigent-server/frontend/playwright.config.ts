import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig, devices } from '@playwright/test'

/**
 * The browser suite runs against a real `dg dev`, not a mock.
 *
 * WHY. What this suite is for is the seam a unit test cannot reach: a bundle served by the very
 * FastAPI app that answers its requests, behind a SPA fallback that has to tell a navigation
 * from a fetch. A mocked API cannot fail the way that arrangement fails -- the interesting bug
 * is `/assets/index-<hash>.js` coming back as a problem document, or a deep link landing on the
 * shell with the wrong status. Everything a mock could cover is already covered by vitest.
 *
 * ITS OWN PORT AND ITS OWN STATE. 3377 rather than the 3333 `dg dev` defaults to: a run that
 * fought a developer's own instance, or worse quietly talked to it, would be a bad afternoon.
 * `DIRIGENT_DATABASE_URL` points it at a scratch database, so the empty listing this suite
 * asserts on is empty because this run created it, and the development admin it signs in as
 * exists because this run's own startup made it.
 *
 * TWO PREREQUISITES, NEITHER RUN AUTOMATICALLY:
 *
 *   bun run build                     # the bundle the server serves
 *   bunx playwright install chromium
 *
 * `make ui-e2e` documents the pair. It is deliberately not part of `make check`.
 */

const here = path.dirname(fileURLToPath(import.meta.url))

/** The workspace root, from which `uv run` resolves the environment. */
const repositoryRoot = path.resolve(here, '../../..')

/** The port this suite's own server binds. See the note above on why it is not 3333. */
export const E2E_PORT = Number(process.env.E2E_PORT ?? 3377)

export const E2E_BASE_URL = `http://127.0.0.1:${String(E2E_PORT)}`

/** Where `dg dev` writes the accounts and runs this suite creates. Gitignored. */
const scratchDatabase = path.join(here, 'e2e', '.state', 'e2e.db')

export default defineConfig({
    testDir: './e2e',
    // ONE SERVER, ONE DATABASE, ONE WORKER. Several specs assert on what the instance holds --
    // "the pipelines listing was empty before this run applied anything" -- and none of that is
    // true if another file is writing at the same moment.
    fullyParallel: false,
    forbidOnly: Boolean(process.env.CI),
    retries: process.env.CI ? 1 : 0,
    workers: 1,
    reporter: process.env.CI ? 'github' : 'list',
    use: {
        baseURL: E2E_BASE_URL,
        trace: 'retain-on-failure',
    },
    projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
    webServer: {
        command: `uv run dg dev --host 127.0.0.1 --port ${String(E2E_PORT)}`,
        cwd: repositoryRoot,
        env: {
            DIRIGENT_DATABASE_URL: `sqlite+aiosqlite:///${scratchDatabase}`,
            DIRIGENT_ENVIRONMENT: 'local',
            // An envelope key, because a connection with a secret cannot be stored without
            // one. It seals rows in the scratch database this run creates and deletes, so it
            // is a fixture rather than a credential -- the same standing as the dev password.
            DIRIGENT_SECRET_KEY: 'dirigent-e2e-envelope-key',
            // Every spec signs in through the form, because that is the round trip worth
            // exercising, and each one gets its own browser context to do it in. An instance
            // accepts ten logins a minute by default -- a bound on Argon2id, for a login route
            // anyone can reach -- and this suite is one machine signing in as its own admin,
            // so the limit here is only counting the suite against itself.
            DIRIGENT_LOGIN_RATE_PER_MINUTE: '600',
        },
        // `/health` rather than `/`: it is the one path that proves the app is up without
        // depending on whether a bundle was built, so a missing bundle fails a spec with a
        // sentence rather than the suite with a timeout.
        url: `${E2E_BASE_URL}/health`,
        reuseExistingServer: !process.env.CI,
        stdout: 'pipe',
        stderr: 'pipe',
        timeout: 120_000,
    },
})
