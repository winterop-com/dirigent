import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { Disclosure } from '@/components/pipeline/Disclosure'
import { JsonBlock } from '@/components/JsonBlock'
import { Mark } from '@/components/Mark'
import type { JsonMap } from '@/lib/api'
import { healthOf, settingsSummary, type ConnectionOut } from '@/lib/connections'
import { kindGlyph, type Glyph } from '@/lib/glyphs'
import { codeNamed, resolveConnection, resolveSchema } from '@/lib/references'
import type { ReferenceKind } from '@/lib/schema-form'
import type { SchemaOut } from '@/lib/schemas'

/**
 * The thing a field's code names, under the box holding the code.
 *
 * A BOX HOLDING A CODE SAYS NOTHING ABOUT WHAT IT NAMES. `metadata-snapshot-org-units` in a one
 * line box is a string somebody has to go and look up somewhere else, so the row under it says
 * where that code was answered, opens to the definition itself, and links to the screen the
 * thing has of its own.
 *
 * THE CODE IS NEVER DRAWN TWICE. The box above already holds it in mono, so the row is headed by
 * the thing's name where it has one and by where it was found where it has not, and neither the
 * row nor the window over the body repeats the key.
 *
 * A CONNECTION LEADS WITH ITS KIND'S MARK, the one `lib/glyphs` gives that kind everywhere else.
 * A schema has no kind, so its row leads with nothing.
 *
 * `lib/references` DECIDES WHAT WAS FOUND. Which listing answered, and whether one has answered
 * at all, is a pure function with its own test; this draws the answer.
 */
export function ReferenceRow({
    refers,
    value,
    document,
    schemas,
    connections,
}: {
    refers: ReferenceKind
    /** What the field holds, which is a code only when it is text and not a `${...}` reference. */
    value: unknown
    /** The document being edited, which may carry the schema a gate names. */
    document: JsonMap | null
    /** Every schema this instance holds, or null while the listing is being read. */
    schemas: SchemaOut[] | null
    /** Every connection this instance holds, or null while the listing is being read. */
    connections: ConnectionOut[] | null
}) {
    const [open, setOpen] = useState(false)
    const code = codeNamed(value)
    if (code === null) return null

    const found =
        refers === 'schema'
            ? schemaRow(resolveSchema(document, code, schemas), code)
            : connectionRow(resolveConnection(code, connections))
    if (found === null) return null

    // A code nothing holds has nothing under it to open, so it is one muted line and no chevron.
    if (found.body === null) return <p className="py-1.5 text-xs text-muted-foreground">{found.words}</p>

    return (
        <Disclosure
            title={
                <span className="flex items-center gap-1.5 text-xs font-normal">
                    {found.mark !== null && <Mark glyph={found.mark} />}
                    {found.named ?? found.words}
                </span>
            }
            summary={
                found.named === null ? undefined : (
                    <span className="ml-auto text-xs text-muted-foreground">{found.words}</span>
                )
            }
            open={open}
            onToggle={() => {
                setOpen(!open)
            }}
        >
            {found.body}
        </Disclosure>
    )
}

/** One row's parts: what heads it, the words under or beside that, and what it opens to. */
interface Found {
    /** The kind's mark, where the row names a kind. A schema is not a kind and carries none. */
    mark: Glyph | null
    /** The thing's own name, when it has one and it is not the code. */
    named: string | null
    /** Where the code was answered, in the reader's words. */
    words: string
    /** The definition, or null on a row with nothing to open. */
    body: ReactNode | null
}

/** A name a thing carries, or null: a blank one is no name, and a code is not one either. */
function nameOf(thing: { code: string; name: string | null }): string | null {
    const name = thing.name?.trim() ?? ''
    return name === '' || name === thing.code ? null : name
}

function schemaRow(resolution: ReturnType<typeof resolveSchema>, code: string): Found | null {
    switch (resolution.source) {
        case 'unread':
            return null
        case 'missing':
            return { mark: null, named: null, words: 'not stored', body: null }
        case 'carried': {
            const words = 'carried by this document'
            return { mark: null, named: null, words, body: <Body title={words} value={resolution.body} /> }
        }
        case 'instance': {
            const named = nameOf(resolution.schema)
            return {
                mark: null,
                named,
                words: 'instance',
                body: (
                    <div className="space-y-2">
                        <Body title={named ?? 'instance'} value={resolution.schema.body} />
                        <Opens to={`/schemas/${encodeURIComponent(code)}`}>Open in Schemas</Opens>
                    </div>
                ),
            }
        }
    }
}

function connectionRow(resolution: ReturnType<typeof resolveConnection>): Found | null {
    if (resolution.source === 'unread') return null
    if (resolution.source === 'missing')
        return { mark: null, named: null, words: 'not configured', body: null }
    const held = resolution.connection
    return {
        // The kind is spelled in the words as well as marked: the code is in the box above, so
        // the row has none of its own to stand the mark beside.
        mark: kindGlyph(held.kind),
        named: nameOf(held),
        words: `${held.kind} · ${healthOf(held).label}`,
        body: (
            <div className="space-y-2">
                <p className="font-mono text-xs text-muted-foreground">{settingsSummary(held)}</p>
                <Opens to={`/connections/${encodeURIComponent(held.code)}`}>Open in Connections</Opens>
            </div>
        ),
    }
}

/** A definition, in the same coloured box and the same window every piece of JSON here gets. */
function Body({ title, value }: { title: string; value: JsonMap }) {
    return <JsonBlock title={title} text={JSON.stringify(value, null, 2)} className="max-h-64" />
}

/** The way out to the thing's own screen. */
function Opens({ to, children }: { to: string; children: ReactNode }) {
    return (
        <Link className="text-xs text-primary hover:underline" to={to}>
            {children}
        </Link>
    )
}
