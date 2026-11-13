import { existsSync, readFileSync } from 'node:fs'
import { readdir, readFile, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { promisify } from 'node:util'
import { brotliCompress, constants, gzip } from 'node:zlib'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

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

/** Asset types that shrink under compression; images and fonts arrive compressed already. */
const compressible = /\.(js|mjs|css|html|json|svg|map|txt|wasm)$/

/** Below this a file is served as it is: the encoding's framing would outweigh the saving. */
const minimumBytes = 1024

const brotli = promisify(brotliCompress)
const gzipped = promisify(gzip)

/**
 * Writes a `.br` and a `.gz` copy beside every compressible file in `dist/assets`, which the
 * server answers with when a request accepts that coding. Both at their highest level: the
 * cost is paid once per build, never per request. A worker is bundled in a build of its own,
 * which closes before `dist/assets` is written; that close finds nothing and does nothing.
 */
function precompress(): Plugin {
    return {
        name: 'dirigent-precompress',
        apply: 'build',
        async closeBundle() {
            const assets = path.resolve(import.meta.dirname, 'dist', 'assets')
            if (!existsSync(assets)) return
            const names = await readdir(assets, { recursive: true })
            await Promise.all(
                names
                    .filter((name) => compressible.test(name))
                    .map(async (name) => {
                        const file = path.join(assets, name)
                        const bytes = await readFile(file)
                        if (bytes.length < minimumBytes) return
                        await Promise.all([
                            brotli(bytes, {
                                params: {
                                    [constants.BROTLI_PARAM_QUALITY]: constants.BROTLI_MAX_QUALITY,
                                    [constants.BROTLI_PARAM_SIZE_HINT]: bytes.length,
                                },
                            }).then((out) => writeFile(`${file}.br`, out)),
                            gzipped(bytes, { level: constants.Z_BEST_COMPRESSION }).then((out) =>
                                writeFile(`${file}.gz`, out),
                            ),
                        ])
                    }),
            )
        },
    }
}

/**
 * Serves sokkel-ui's pre-paint script at `/appearance.js`, the fixed address index.html loads it
 * from: emitted beside index.html in a build, answered by the dev server in `vite dev`. The bytes
 * are the library's own built file.
 */
function appearanceScript(): Plugin {
    const fileName = 'appearance.js'
    const source = readFileSync(
        createRequire(import.meta.url).resolve(`@winterop-com/sokkel-ui/${fileName}`),
        'utf8',
    )
    return {
        name: 'dirigent-appearance-script',
        configureServer(server) {
            server.middlewares.use(`/${fileName}`, (_request, response) => {
                response.setHeader('Content-Type', 'text/javascript')
                response.end(source)
            })
        },
        generateBundle() {
            this.emitFile({ type: 'asset', fileName, source })
        },
    }
}

/**
 * sokkel-ui-graph's fallback elk, `elkjs/lib/elk.bundled.js`, resolves to a stub that throws:
 * the app sets its own elk, in a worker, before any graph is laid out.
 */
export default defineConfig({
    base: '/',
    plugins: [react(), tailwindcss(), precompress(), appearanceScript()],
    resolve: {
        alias: [
            { find: '@', replacement: path.resolve(import.meta.dirname, './src') },
            {
                find: /^elkjs\/lib\/elk\.bundled\.js$/,
                replacement: path.resolve(import.meta.dirname, './src/lib/elk-bundled-stub.ts'),
            },
        ],
    },
    server: { proxy },
    build: {
        outDir: 'dist',
        emptyOutDir: true,
        rolldownOptions: {
            output: {
                codeSplitting: {
                    groups: [
                        {
                            name: 'react',
                            test: /[\\/]node_modules[\\/](react|react-dom|react-router|scheduler)[\\/]/,
                        },
                    ],
                },
            },
        },
    },
})
