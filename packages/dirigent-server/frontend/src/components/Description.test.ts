import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { PlainMarkdown, type PlainMarkdownProps } from '@winterop-com/sokkel-ui/PlainMarkdown'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test } from 'vitest'

import { DESCRIPTION_MARKDOWN } from '@/lib/design-system'

/** The app's own source, which one test below reads to assert what is not in it. */
const SOURCE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

/** The library module a description is drawn by, as the bundle resolves it. */
const RENDERER = fileURLToPath(import.meta.resolve('@winterop-com/sokkel-ui/PlainMarkdown'))

/** A description as the DOM would receive it, read the way `Description` reads every one. */
function drawn(text: string, set: Partial<PlainMarkdownProps> = {}): string {
    return renderToStaticMarkup(
        createElement(PlainMarkdown, { content: text, ...DESCRIPTION_MARKDOWN, ...set }),
    )
}

/**
 * Every file this app ships, which is not a spec.
 *
 * A `.test.ts` reaches no browser -- this one names the thing it is looking for, which is why it
 * cannot be looking at itself.
 */
function shippedFiles(root: string): string[] {
    return readdirSync(root).flatMap((entry) => {
        const full = path.join(root, entry)
        if (statSync(full).isDirectory()) return shippedFiles(full)
        if (entry.endsWith('.test.ts') || entry.endsWith('.test.tsx')) return []
        return entry.endsWith('.ts') || entry.endsWith('.tsx') ? [full] : []
    })
}

/** Every library file the renderer reaches through its own relative imports, static and lazy. */
function reachedFrom(entry: string): string[] {
    const seen = new Set<string>()
    const walk = (file: string) => {
        if (seen.has(file)) return
        seen.add(file)
        const source = readFileSync(file, 'utf8')
        for (const match of source.matchAll(/(?:from|import\()\s*["'](\.{1,2}\/[^"']+)["']/g)) {
            walk(path.resolve(path.dirname(file), match[1]))
        }
    }
    walk(entry)
    return [...seen]
}

/** The two ways React is handed an HTML string: a JSX prop, and a member of a props object. */
const INJECTIONS = ['dangerouslySetInnerHTML=', 'dangerouslySetInnerHTML:']

/** The same two, as a bundler writes them into the library's built modules. */
const BUILT_INJECTIONS = ['dangerouslySetInnerHTML']

/**
 * DO NOT DELETE THIS BLOCK, AND DO NOT LOOSEN IT.
 *
 * A description is written by whoever applied the document and rendered to whoever opens the
 * pipeline, so it is somebody else's text on this reader's screen. The defence is that no HTML
 * string is ever handed to the DOM: `PlainMarkdown` builds React elements from a syntax tree and
 * drops raw markup, so what a description says can only arrive as text React escapes.
 *
 * The last two tests are the ones that keep it true: `dangerouslySetInnerHTML` in this app's own
 * source, or in a library module the renderer reaches, would undo everything above them in one
 * line, whatever the rendered output of these few strings then said.
 */
describe('a description cannot put markup on the screen', () => {
    test('a script tag survives as the characters somebody typed and as no element', () => {
        const html = drawn('<script>alert(1)</script>')

        expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;')
        expect(html).not.toContain('<script')
    })

    test('an event handler attribute is text, not an attribute', () => {
        const html = drawn('<img src=x onerror="alert(1)">')

        expect(html).toContain('&lt;img src=x onerror=&quot;alert(1)&quot;&gt;')
        expect(html).not.toContain('<img')
    })

    test('markup inside a sentence stays inside the sentence as text', () => {
        const html = drawn('before <script>alert(1)</script> after')

        expect(html).toContain('before &lt;script&gt;alert(1)&lt;/script&gt; after')
        expect(html).not.toContain('<script')
    })

    test('a script link keeps its words and carries no script', () => {
        for (const text of [
            '[click me](javascript:alert(1))',
            '[click me](JavaScript:alert(1))',
            '[click me](vbscript:msgbox(1))',
            '[click me](data:text/html;base64,PHNjcmlwdD4=)',
        ]) {
            const html = drawn(text)
            expect(html).toContain('click me')
            expect(html).not.toContain('<a')
            expect(html).not.toContain('href=')
        }
    })

    test('a link that is not to the web or a mailbox is its words and goes nowhere', () => {
        for (const text of [
            '[here](/pipelines/other)',
            '[up](../secrets)',
            '[chat](irc://irc.example.test/room)',
            '[same scheme](//example.test/x)',
        ]) {
            const html = drawn(text)
            expect(html).not.toContain('<a')
            expect(html).not.toContain('href=')
        }
    })

    test('an image is its alt text and address, never an element that fetches', () => {
        for (const text of [
            '![a chart](/api/runs/1/chart.png)',
            '![tracker](https://example.test/pixel.gif)',
        ]) {
            const html = drawn(text)
            expect(html).not.toContain('<img')
            expect(html).not.toContain('src=')
        }
        expect(drawn('![a chart](/api/runs/1/chart.png)')).toContain('a chart')
    })

    test('a link to the web or to a mailbox keeps its address and leaves in a new tab', () => {
        const web = drawn('[the docs](https://example.test/docs)')
        expect(web).toContain('href="https://example.test/docs"')
        expect(web).toContain('target="_blank"')
        expect(web).toContain('noopener')
        expect(drawn('[plain](http://example.test/)')).toContain('href="http://example.test/"')
        expect(drawn('[write](mailto:someone@example.test)')).toContain('href="mailto:someone@example.test"')
    })

    test('nothing this app ships injects an HTML string', () => {
        const offenders = shippedFiles(SOURCE).filter((file) => {
            const source = readFileSync(file, 'utf8')
            return INJECTIONS.some((injection) => source.includes(injection))
        })
        expect(offenders).toEqual([])
    })

    test('nothing the renderer reaches in the library injects an HTML string', () => {
        const reached = reachedFrom(RENDERER)
        expect(reached.length).toBeGreaterThan(1)
        const offenders = reached.filter((file) => {
            const source = readFileSync(file, 'utf8')
            return BUILT_INJECTIONS.some((injection) => source.includes(injection))
        })
        expect(offenders).toEqual([])
    })
})

describe('the subset a description is read as', () => {
    test('a heading sits under the heading the description is set beneath', () => {
        expect(drawn('# Overview', { headingOffset: 1 })).toMatch(/<h2[^>]*>Overview<\/h2>/)
        expect(drawn('# Overview', { headingOffset: 2 })).toMatch(/<h3[^>]*>Overview<\/h3>/)
        expect(drawn('# Overview', { headingOffset: 2 })).not.toMatch(/<h[12]/)
    })

    test("a field's help is one line, with no block of its own", () => {
        const html = drawn('Written when the value is ``null``.\n\nA second paragraph.', { inline: true })

        expect(html).toContain('<code>null</code>')
        expect(html).not.toMatch(/<(p|div)[\s>]/)
    })

    test('a heading, emphasis, strong and inline code are drawn as themselves', () => {
        const html = drawn('### What this does\n\nA **bold** and _quiet_ and `literal`.')

        expect(html).toMatch(/<h3[^>]*>What this does<\/h3>/)
        expect(html).toContain('<strong>bold</strong>')
        expect(html).toContain('<em>quiet</em>')
        expect(html).toContain('<code>literal</code>')
    })

    test("a docstring's double backticks are code rather than their own characters", () => {
        expect(drawn('Written when the value is ``null``.')).toContain('<code>null</code>')
    })

    test('a nested list is a list inside its item', () => {
        expect(drawn('- reshape\n  - `transform.jq`\n- load')).toMatch(
            /<li>reshape\s*<ul>\s*<li><code>transform\.jq<\/code><\/li>/,
        )
    })

    test('a table is its heading row, its body rows and how each column is set', () => {
        const html = drawn('| left | middle | right |\n| :--- | :----: | ----: |\n| a | `b` | **c** |')

        expect(html).toContain('<table')
        expect(html).toContain('text-align:center')
        expect(html).toContain('text-align:right')
        expect(html).toContain('<strong>c</strong>')
    })

    test("a key/value table's empty heading row is not drawn", () => {
        const html = drawn('| | |\n| --- | --- |\n| Status | ok |')

        expect(html).toContain('<table')
        expect(html).not.toContain('<thead')
        expect(html).toContain('Status')
    })

    test('a description of nothing draws no words', () => {
        expect(drawn('')).not.toMatch(/<(p|h\d|li)/)
    })
})
