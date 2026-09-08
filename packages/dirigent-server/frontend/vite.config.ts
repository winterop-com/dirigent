import path from 'node:path'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

/**
 * The bundle is served by the dirigent API server itself, same-origin.
 *
 * `build.outDir` is `dist/`, which is where `dirigent_server.ui.CHECKOUT_STATIC` looks in a
 * checkout; the wheel carries a copy at `src/dirigent_server/static/`. Both are gitignored,
 * because a committed bundle is a second copy of the same bytes going stale between rebuilds.
 *
 * `base: '/'` rather than './': the server mounts the asset tree at `/assets`, so an asset URL
 * has to resolve the same however deep the route in the address bar goes.
 */

/** Where `vite dev` sends everything the server claims. `dg dev` binds this by default. */
const target = process.env.DIRIGENT_DEV_API || 'http://127.0.0.1:3333'

/**
 * Every path the server answers ahead of the bundle, proxied so the dev loop talks to the
 * real routes it will talk to in production.
 *
 * The list is `dirigent_server.ui.RESERVED_PREFIXES` plus the configured API prefix, written
 * down: production needs no such list, because the server owns each of these ahead of the
 * static mount. `/assets` and `/favicon.ico` are deliberately absent -- in dev those are
 * vite's own, and proxying them would fetch the last build instead of the current source.
 */
const proxiedPaths = ['/api', '/health', '/hooks', '/config.json', '/docs', '/redoc', '/openapi.json']

const proxy = Object.fromEntries(proxiedPaths.map((prefix) => [prefix, { target, changeOrigin: true }]))

export default defineConfig({
    base: '/',
    plugins: [react(), tailwindcss()],
    resolve: {
        alias: { '@': path.resolve(import.meta.dirname, './src') },
    },
    server: { proxy },
    build: {
        outDir: 'dist',
        emptyOutDir: true,
    },
})
