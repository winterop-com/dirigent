import { fileURLToPath } from 'node:url'

import { defineConfig } from 'vitest/config'

/**
 * Unit tests run in plain Node.
 *
 * What is under test is the wire layer -- the fetch choke point, the SSE parser, the palette's
 * filter, the module store -- and none of it needs a DOM. `fetch` is native in Node, so
 * `apiFetch` is exercised for real against a stubbed global rather than through a browser
 * emulation, and a component's rendering is the browser suite's job.
 *
 * Deliberately separate from vite.config.ts so the tests load neither the React plugin nor
 * Tailwind. `include` names `src/**` only, which is what keeps the Playwright specs under
 * `e2e/` out of vitest's reach: they are the other runner's.
 */
export default defineConfig({
    resolve: {
        alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    test: {
        environment: 'node',
        include: ['src/**/*.test.ts'],
    },
})
