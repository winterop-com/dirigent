/**
 * A description, read as markdown.
 *
 * SANITISED BY CONSTRUCTION, NOT BY FILTERING. `marked` is used for its lexer and nothing else:
 * what comes back here is a tree of the nodes below, and `components/Markdown` turns that tree
 * into React elements. No HTML string is ever produced, so there is nothing for a sanitiser to
 * clean and nothing `dangerouslySetInnerHTML` could be handed. A `<script>` in a description
 * arrives as an `html` token and leaves as text, which React escapes because React escapes every
 * string it renders. The safety here is a property of the shape rather than of a denylist
 * somebody has to keep up to date.
 *
 * A USEFUL SUBSET, AND EVERYTHING ELSE IS TEXT. Paragraphs, headings, emphasis, strong, inline
 * code, code blocks, lists, blockquotes, tables and links are the whole of what a description
 * needs. Anything else -- an image, raw markup -- comes out as the text it was written as, so a
 * description renders as its own source rather than as nothing.
 *
 * A LINK IS http, https OR mailto. Every other scheme is refused and the link is drawn as its
 * own words: `javascript:` is the obvious one, and a scheme this bundle was built before is
 * refused for the same reason -- nothing here can say where it goes.
 */

import { Lexer, marked, type Token, type Tokens } from 'marked'

/** One run inside a paragraph, a heading, a list item or a quote. */
export type Inline =
    | { kind: 'text'; text: string }
    | { kind: 'emphasis'; children: Inline[] }
    | { kind: 'strong'; children: Inline[] }
    | { kind: 'code'; text: string }
    | { kind: 'link'; href: string; children: Inline[] }
    | { kind: 'break' }

/** How a column is set, which the row of dashes under the heading declares. */
export type Align = 'left' | 'center' | 'right' | null

/** One block of a description. */
export type Block =
    | { kind: 'paragraph'; children: Inline[] }
    | { kind: 'heading'; level: number; children: Inline[] }
    | { kind: 'code'; text: string; language: string | null }
    | { kind: 'list'; ordered: boolean; items: Inline[][] }
    | { kind: 'quote'; children: Block[] }
    | { kind: 'table'; align: Align[]; header: Inline[][]; rows: Inline[][][] }
    | { kind: 'rule' }

/** The schemes a link may carry. Everything else is drawn as its own words. */
const SCHEMES = new Set(['http:', 'https:', 'mailto:'])

/** The deepest heading there is, which is markdown's own limit. */
const DEEPEST_HEADING = 6

/** The last code point that is whitespace or a control character. */
const BLANK = 0x20

/** Read one description as the blocks it is made of. Empty text is no blocks at all. */
export function readMarkdown(text: string): Block[] {
    if (text.trim() === '') return []
    return blocksOf(marked.lexer(text))
}

/**
 * Read one line of a description as the runs it is made of, with nothing block-level around it.
 *
 * A field's help is one line under a control, and it comes from a docstring: ``null`` and
 * `output_uri` are code spans and have to be drawn as code rather than as their own backticks.
 * Block markup in such a line is drawn as the text it was written as.
 */
export function readInline(text: string): Inline[] {
    return inlinesOf(Lexer.lexInline(text))
}

/** Whether an href may be followed, which is a question about its scheme and nothing else. */
export function safeHref(href: string): string | null {
    // Blanks inside a scheme are how `java\nscript:` is written, so they go before it is read.
    const bare = [...href].filter((one) => (one.codePointAt(0) ?? 0) > BLANK).join('')
    const scheme = /^[a-zA-Z][a-zA-Z0-9+.-]*:/.exec(bare)
    if (scheme === null) return null
    return SCHEMES.has(scheme[0].toLowerCase()) ? href : null
}

function blocksOf(tokens: readonly Token[]): Block[] {
    return tokens.flatMap(blockOf)
}

function blockOf(token: Token): Block[] {
    switch (token.type) {
        case 'space':
        case 'def':
            return []
        case 'hr':
            return [{ kind: 'rule' }]
        case 'heading': {
            const heading = token as Tokens.Heading
            const level = Math.min(Math.max(heading.depth, 1), DEEPEST_HEADING)
            return [{ kind: 'heading', level, children: inlinesOf(heading.tokens) }]
        }
        case 'code': {
            const code = token as Tokens.Code
            return [{ kind: 'code', text: code.text, language: code.lang ?? null }]
        }
        case 'blockquote':
            return [{ kind: 'quote', children: blocksOf((token as Tokens.Blockquote).tokens) }]
        case 'table': {
            const table = token as Tokens.Table
            return [
                {
                    kind: 'table',
                    align: table.align.map((one) => one ?? null),
                    header: table.header.map((cell) => inlinesOf(cell.tokens)),
                    rows: table.rows.map((row) => row.map((cell) => inlinesOf(cell.tokens))),
                },
            ]
        }
        case 'list': {
            const list = token as Tokens.List
            return [
                {
                    kind: 'list',
                    ordered: list.ordered,
                    items: list.items.map((item) => inlinesOf(item.tokens)),
                },
            ]
        }
        case 'paragraph':
        case 'text': {
            const carried = (token as Tokens.Paragraph).tokens
            return [
                {
                    kind: 'paragraph',
                    children: carried === undefined ? [words(token.raw)] : inlinesOf(carried),
                },
            ]
        }
        default:
            // Raw markup, and anything a later marked learns to lex: its own source, as words.
            return [{ kind: 'paragraph', children: [words(token.raw)] }]
    }
}

function inlinesOf(tokens: readonly Token[]): Inline[] {
    return tokens.flatMap(inlineOf)
}

function inlineOf(token: Token): Inline[] {
    switch (token.type) {
        case 'br':
            return [{ kind: 'break' }]
        case 'codespan':
            return [{ kind: 'code', text: (token as Tokens.Codespan).text }]
        case 'em':
            return [{ kind: 'emphasis', children: inlinesOf((token as Tokens.Em).tokens) }]
        case 'strong':
            return [{ kind: 'strong', children: inlinesOf((token as Tokens.Strong).tokens) }]
        case 'del':
            return inlinesOf((token as Tokens.Del).tokens)
        case 'link': {
            const link = token as Tokens.Link
            const children = inlinesOf(link.tokens)
            const href = safeHref(link.href)
            return href === null ? children : [{ kind: 'link', href, children }]
        }
        case 'escape':
            return [words((token as Tokens.Escape).text)]
        case 'text': {
            const carried = (token as Tokens.Text).tokens
            return carried === undefined ? [words((token as Tokens.Text).text)] : inlinesOf(carried)
        }
        default:
            // An `html` token, an image: whatever it was written as, as words.
            return [words(token.raw)]
    }
}

function words(text: string): Inline {
    return { kind: 'text', text }
}
