import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, test } from 'vitest'

const SRC = fileURLToPath(new URL('..', import.meta.url))
const INDEX_CSS = path.join(SRC, 'index.css')

function sourceFiles(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
        const full = path.join(dir, name)
        if (statSync(full).isDirectory()) return sourceFiles(full)
        return /\.tsx?$/.test(name) ? [full] : []
    })
}

/** The library's component modules the app imports: `@winterop-com/sokkel-ui/<Module>`. */
function importedModules(): Set<string> {
    const found = new Set<string>()
    for (const file of sourceFiles(SRC)) {
        for (const match of readFileSync(file, 'utf8').matchAll(
            /from '@winterop-com\/sokkel-ui\/([A-Z][A-Za-z]+)'/g,
        )) {
            found.add(match[1])
        }
    }
    return found
}

describe('the library styles', () => {
    // The lean entry scans only the modules index.css names, so a module imported without its
    // sources line draws without the classes only it uses.
    test('every library module the app imports has its sources line in index.css', () => {
        const css = readFileSync(INDEX_CSS, 'utf8')
        const missing = [...importedModules()].filter(
            (name) => !css.includes(`@import '@winterop-com/sokkel-ui/sources/${name}.css';`),
        )
        expect(missing).toEqual([])
    })
})
