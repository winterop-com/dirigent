import { readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, test } from 'vitest'

/**
 * A surface caps and its body scrolls; nothing between a dialog's header and its footer has a
 * height of its own.
 *
 * A BLOCK THAT CAPS ITSELF HIDES WHAT IS IN IT. A settings group capped at `40vh` hid the last
 * password box under a fold nothing drew, and the same fault came back twice: a run dialog
 * capped the parameter form it wrapped at `50vh`, and both trigger dialogs capped a payload
 * mapping and a pinned-parameters form at `32vh` -- each inside a surface that declared no
 * height at all, so the verbs at the foot went off the bottom of the screen with nothing to
 * scroll.
 *
 * NOTHING IN A BUILD FAILS WHEN THIS COMES BACK. It is a layout, and the only other thing that
 * reads it is a pair of eyes at one window size, so the two tells the convention names are
 * asserted here against the source: a share of the viewport named anywhere but on the surface,
 * and a body that scrolls inside a surface with no cap to scroll under.
 *
 * A FILE RATHER THAN A DIALOG'S OWN SUBTREE IS WHAT IS READ for the first of the two. A block
 * a dialog holds is often a function beside it -- `ParamsBox` is the schedule dialog's pinned
 * parameters -- so a scan that read only what stands between `<DialogContent>` and its close
 * would pass a file whose every fold was one function further down.
 *
 * `docs/ui-conventions.md`, "A surface is inset once, and 16px is the inset". A read-only
 * preview is the one exception, and it takes a pane's height -- `max-h-40`, `max-h-72` -- never
 * a share of the viewport, which is what keeps the exception out of this scan.
 */

const SOURCE = fileURLToPath(new URL('..', import.meta.url))

/** How a surface is told it may take a share of the viewport: its own tag, and nothing below. */
const SURFACE = '<DialogContent'

/** What the surface's cap is spelled as, either as a ceiling or as a height it simply takes. */
const CAP = /\b(?:max-h-|h-)\[/

/** A share of the viewport, however it is written: `50vh`, `32dvh`, `calc(100vh-4rem)`. */
const VIEWPORT_SHARE = /\d*\.?\d*d?vh\b/

/** A body that scrolls under the surface's cap rather than the page. */
const SCROLLS = /\boverflow-y-(?:auto|scroll)\b/

/** Every `.tsx` under `src`, which is every file that could draw a dialog. */
function everyComponent(): string[] {
    const found: string[] = []
    const walk = (directory: string): void => {
        for (const entry of readdirSync(directory, { withFileTypes: true })) {
            const at = path.join(directory, entry.name)
            if (entry.isDirectory()) walk(at)
            else if (entry.name.endsWith('.tsx')) found.push(at)
        }
    }
    walk(SOURCE)
    return found.toSorted()
}

/** One dialog surface: its own tag, and everything it holds. */
interface Surface {
    /** Which one this is, since a reader of a failure has to be told. */
    where: string
    /** The classes and props the surface itself declares. */
    tag: string
    /** The header, the body and the footer, as one piece of source. */
    body: string
}

/** A file that draws at least one dialog, with every surface in it read apart from the rest. */
interface Drawn {
    named: string
    source: string
    surfaces: Surface[]
}

/**
 * Where a surface's own opening tag ends.
 *
 * At the first `>` outside a brace, because a prop's value holds both -- an arrow function is
 * `=>` and a merged class list is `{cn(...)}` -- and a scan stopping at the first `>` would read
 * half a prop as the body.
 */
function tagEnds(source: string, at: number): number {
    let depth = 0
    let cursor = at + SURFACE.length
    while (cursor < source.length) {
        const here = source[cursor]
        if (here === '{') depth += 1
        else if (here === '}') depth -= 1
        else if (here === '>' && depth === 0) break
        cursor += 1
    }
    return cursor
}

/** Every dialog surface in a file, each with its tag and what it holds kept apart. */
function read(file: string): Drawn | null {
    const source = readFileSync(file, 'utf8')
    if (!source.includes(SURFACE)) return null
    const named = path.relative(SOURCE, file)
    const surfaces: Surface[] = []
    let at = source.indexOf(SURFACE)
    while (at !== -1) {
        const cursor = tagEnds(source, at)
        const shut = source.indexOf('</DialogContent>', cursor)
        if (shut === -1) throw new Error(`${named} opens a dialog surface it never closes`)
        surfaces.push({
            where: `${named}:${String(source.slice(0, at).split('\n').length)}`,
            tag: source.slice(at, cursor),
            body: source.slice(cursor, shut),
        })
        at = source.indexOf(SURFACE, shut)
    }
    return { named, source, surfaces }
}

/** Every line of a file naming a share of the viewport outside a surface's own opening tag. */
function sharesOutsideTheSurface(file: Drawn): string[] {
    const tags = file.surfaces.map((surface) => surface.tag)
    let left = file.source
    for (const tag of tags) left = left.replace(tag, '')
    return left.split('\n').filter((line) => VIEWPORT_SHARE.test(line))
}

const DRAWN = everyComponent()
    .map(read)
    .filter((file): file is Drawn => file !== null)

describe('a surface caps and its body scrolls', () => {
    test('there are dialogs to read', () => {
        expect(DRAWN.flatMap((file) => file.surfaces).length).toBeGreaterThan(8)
    })

    for (const file of DRAWN) {
        test(`only the surface takes a share of the viewport in ${file.named}`, () => {
            expect(sharesOutsideTheSurface(file), `${file.named} caps a block inside a dialog`).toEqual([])
        })

        for (const surface of file.surfaces) {
            test(`the dialog at ${surface.where} caps itself where its body scrolls`, () => {
                if (!SCROLLS.test(surface.body)) return
                expect(CAP.test(surface.tag), `${surface.where} scrolls a body under no cap`).toBe(true)
            })
        }
    }
})
