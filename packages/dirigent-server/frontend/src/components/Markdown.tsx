import type { ReactNode } from 'react'

import { readInline, readMarkdown, type Align, type Block, type Inline } from '@/lib/markdown'
import { cn } from '@/lib/utils'

/**
 * A description, drawn.
 *
 * THERE IS NO HTML STRING ANYWHERE IN THIS FILE, and there must never be one. `lib/markdown`
 * answers with a tree of nodes and this walks it into React elements, so every string a
 * description carries reaches the DOM as a text child -- which React escapes. A `<script>` in a
 * description is drawn as the characters somebody typed. One `dangerouslySetInnerHTML` would
 * undo the whole of that, which is why a test refuses those words anywhere this app ships.
 *
 * EVERY LINK LEAVES. A description is written by whoever applied a document, so an anchor here
 * carries `rel="noopener noreferrer"` and opens in a new tab, and `lib/markdown` has already
 * refused every scheme but http, https and mailto.
 */
export function Markdown({ text }: { text: string }) {
    const blocks = readMarkdown(text)
    if (blocks.length === 0) return null
    return <div className="space-y-2 text-sm">{blocks.map((block, index) => draw(block, index))}</div>
}

/**
 * One line of a description, drawn as runs with no block around it.
 *
 * A field's help, a summary in a listing: text that sits inside a paragraph somebody else set,
 * and carries code spans because it was written as a docstring.
 */
export function MarkdownLine({ text }: { text: string }) {
    const inlines = readInline(text)
    if (inlines.length === 0) return null
    return <>{runs(inlines)}</>
}

/** The three sizes are the whole scale, so every heading is the body size and carries its weight. */
const HEADING = 'text-sm font-semibold'

/** What a cell of each column is set to. A column that declared nothing is set the way prose is. */
const SET: Record<'left' | 'center' | 'right', string> = {
    left: 'text-left',
    center: 'text-center',
    right: 'text-right',
}

/** Every cell of a table is padded the way a listing's cells are, and a heading is quieter. */
const CELL = 'px-3 py-2 align-top'
const HEAD = `text-muted-foreground font-medium ${CELL}`
const ROW = 'border-border even:bg-secondary/30 border-t'

function setting(align: Align | undefined): string | undefined {
    return align === undefined || align === null ? undefined : SET[align]
}

function draw(block: Block, index: number): ReactNode {
    switch (block.kind) {
        case 'paragraph':
            return <p key={index}>{runs(block.children)}</p>
        case 'heading':
            return (
                <p key={index} className={HEADING} role="heading" aria-level={block.level}>
                    {runs(block.children)}
                </p>
            )
        case 'code':
            return (
                <pre
                    key={index}
                    className="bg-secondary/50 overflow-x-auto rounded-md p-2 font-mono text-xs"
                    data-language={block.language ?? undefined}
                >
                    {block.text}
                </pre>
            )
        case 'list':
            return block.ordered ? (
                <ol key={index} className="list-decimal space-y-0.5 pl-5">
                    {items(block.items)}
                </ol>
            ) : (
                <ul key={index} className="list-disc space-y-0.5 pl-5">
                    {items(block.items)}
                </ul>
            )
        case 'quote':
            return (
                <blockquote key={index} className="border-border text-muted-foreground space-y-2 border-l-2 pl-3">
                    {block.children.map((one, at) => draw(one, at))}
                </blockquote>
            )
        case 'table':
            // A table is as wide as its columns need, and a description is drawn in a panel that
            // is often narrower than that: it scrolls inside its own box rather than the page.
            return (
                <div key={index} className="border-border overflow-x-auto rounded-md border">
                    <table className="w-full border-collapse text-xs">
                        <thead>
                            <tr className="border-border bg-secondary/40 border-b">
                                {headCells(block.header, block.align)}
                            </tr>
                        </thead>
                        <tbody>{bodyRows(block.rows, block.align)}</tbody>
                    </table>
                </div>
            )
        case 'rule':
            return <hr key={index} className="border-border" />
    }
}

/**
 * The rows of a list.
 *
 * A markdown tree carries no ids and is rebuilt whole whenever the text changes, so a node's
 * position is the only thing there is to key on.
 */
function items(rows: readonly Inline[][]): ReactNode {
    // oxlint-disable-next-line react/no-array-index-key
    return rows.map((row, index) => <li key={index}>{runs(row)}</li>)
}

/**
 * A table, keyed by position for the same reason a list's rows are: a markdown tree carries no
 * ids and is rebuilt whole whenever the text changes.
 */
function bodyRows(body: readonly Inline[][][], align: readonly Align[]): ReactNode {
    // oxlint-disable-next-line react/no-array-index-key
    return body.map((row, at) => <tr key={at} className={ROW}>{bodyCells(row, align)}</tr>)
}

function headCells(row: readonly Inline[][], align: readonly Align[]): ReactNode {
    // oxlint-disable-next-line react/no-array-index-key
    return row.map((cell, at) => <th key={at} className={cn(HEAD, setting(align[at]))}>{runs(cell)}</th>)
}

function bodyCells(row: readonly Inline[][], align: readonly Align[]): ReactNode {
    // oxlint-disable-next-line react/no-array-index-key
    return row.map((cell, at) => <td key={at} className={cn(CELL, setting(align[at]))}>{runs(cell)}</td>)
}

function runs(inlines: readonly Inline[]): ReactNode {
    return inlines.map((inline, index) => run(inline, index))
}

function run(inline: Inline, index: number): ReactNode {
    switch (inline.kind) {
        case 'text':
            return <span key={index}>{inline.text}</span>
        case 'emphasis':
            return <em key={index}>{runs(inline.children)}</em>
        case 'strong':
            return <strong key={index}>{runs(inline.children)}</strong>
        case 'code':
            return (
                <code key={index} className="bg-secondary/50 rounded-sm px-1 font-mono text-[0.85em]">
                    {inline.text}
                </code>
            )
        case 'link':
            return (
                <a
                    key={index}
                    className="text-primary hover:underline"
                    href={inline.href}
                    target="_blank"
                    rel="noopener noreferrer"
                >
                    {runs(inline.children)}
                </a>
            )
        case 'break':
            return <br key={index} />
    }
}
