/**
 * The block catalog: what this instance can run, and the config each block takes.
 *
 * A BLOCK IS ADDRESSED BY ITS ID AND HAS NO NAME. Every other addressable thing in this API
 * carries the quartet and is titled by its `name`; a catalog entry carries `id` -- `shell.run`
 * -- and one line of `summary`. So the identity rule lands on its simple side here: the title
 * is the id, it wears the mono face, and the summary is the body. Nothing invents a name.
 *
 * THE CATALOG IS ONE ANSWER, NOT A CURSOR WALK. `GET /blocks` is the whole of what a host has
 * merged from its plugins, so the screen reads it once and narrows what it holds. There is no
 * server-side filter to offer, and the foot states how many rows that is.
 *
 * WHAT A FIELD IS, IS `lib/schema-form`'s. A block publishes its config as a JSON Schema and
 * that module is the one place a schema becomes fields -- so the catalog's read-only reference
 * and the step form it mirrors cannot disagree about what a block takes.
 */

import { apiJson, type JsonMap } from '@/lib/api'
import type { FieldDescriptor } from '@/lib/schema-form'

/** Which surface a catalog entry describes. `BlockKind`. */
export type BlockKind = 'operator' | 'sensor'

/** One block in the catalog, with the schemas a form is built from. `BlockEntry`. */
export interface BlockEntry {
    /** The addressable key, such as `shell.run`. A block has no name and is titled by this. */
    id: string
    kind: BlockKind
    /** The one line the block says about itself. */
    summary: string
    /** The shelf the block declares itself onto, which is what a catalog is arranged by. */
    group: string
    /** The plugin that contributed it. */
    plugin: string
    idempotent: boolean
    /** The block executes code on the worker, so an instance must allowlist its id to run it. */
    local_execution: boolean
    default_poll_seconds: number | null
    default_deadline_seconds: number | null
    config_schema: JsonMap
    output_schema: JsonMap
}

/** The host's merged view of every contribution. `Catalog`, of which three members are read here. */
/** One of the catalog's supporting registries: a storage scheme, a notifier, a connection kind. */
export interface CatalogEntry {
    id: string
    plugin: string
    config_schema: JsonMap
}

export interface Catalog {
    api_version: number
    plugins: string[]
    blocks: BlockEntry[]
    storage_schemes: CatalogEntry[]
    notifiers: CatalogEntry[]
    connection_kinds: CatalogEntry[]
}

/** The family a block id files under, which is everything before its first dot. */
export function familyOf(id: string): string {
    const dot = id.indexOf('.')
    return dot === -1 ? id : id.slice(0, dot)
}

/**
 * The shelf a block belongs on, which the catalog answers with rather than the screen deriving.
 *
 * A GROUP IS DECLARED, NOT READ OFF THE ID. `map.jq` and `transform.jq` are two verbs of one
 * `transform` group, and an id's first half would have shelved each of them alone.
 */
export function groupOf(entry: BlockEntry): string {
    return entry.group
}

/** Blocks shelved by group, groups in name order and blocks in id order within one. */
export function byGroup(blocks: readonly BlockEntry[]): [string, BlockEntry[]][] {
    const shelves = new Map<string, BlockEntry[]>()
    for (const entry of blocks.toSorted((a, b) => a.id.localeCompare(b.id))) {
        const group = groupOf(entry)
        const shelf = shelves.get(group)
        if (shelf === undefined) shelves.set(group, [entry])
        else shelf.push(entry)
    }
    return [...shelves.entries()].toSorted(([a], [b]) => a.localeCompare(b))
}

/** The entries whose id carries what was typed. */
export function narrowEntries(entries: readonly CatalogEntry[], needle: string): CatalogEntry[] {
    const wanted = needle.trim().toLowerCase()
    if (wanted === '') return [...entries]
    return entries.filter((entry) => entry.id.toLowerCase().includes(wanted))
}

/** Read the whole catalog, which is what this screen, a block picker and a step form are built from. */
export function readCatalog(): Promise<Catalog> {
    return apiJson<Catalog>('/blocks')
}

/** Read one block's schemas. */
export function readBlock(blockId: string): Promise<BlockEntry> {
    return apiJson<BlockEntry>(`/blocks/${encodeURIComponent(blockId)}`)
}

/**
 * The blocks whose id or summary carries what was typed.
 *
 * The whole catalog is in hand, so this narrows all of it rather than whichever rows a walk had
 * reached -- which is why the screen can say the box finds nothing rather than "nothing yet".
 */
export function narrowBlocks(blocks: readonly BlockEntry[], needle: string): BlockEntry[] {
    const wanted = needle.trim().toLowerCase()
    if (wanted === '') return [...blocks]
    return blocks.filter((entry) => `${entry.id} ${entry.summary}`.toLowerCase().includes(wanted))
}

/** A count and the thing counted, in the singular where there is one of it. */
function count(many: number, thing: string): string {
    return `${String(many)} ${thing}${many === 1 ? '' : 's'}`
}

/** How much config a block takes, for the column that says so at a glance. */
export function configSummary(fields: readonly FieldDescriptor[]): string {
    if (fields.length === 0) return 'none'
    return count(fields.length, 'field')
}

/**
 * The type a field takes, in the words the schema is written in.
 *
 * The step form spends `FieldDescriptor.kind` on choosing a control; a reference has no control
 * to choose and states the shape instead, so `switch` reads as `boolean` and a field the schema
 * also allowed null for says so. A field carrying a program is a string, and the reference names
 * the language it is written in, which is the one thing its shape does not say.
 */
export function typeLabel(field: FieldDescriptor): string {
    const base = field.mediaType === null ? TYPES[field.kind] : `${TYPES[field.kind]} (${field.mediaType})`
    return field.nullable ? `${base} or null` : base
}

const TYPES: Readonly<Record<FieldDescriptor['kind'], string>> = {
    text: 'string',
    code: 'string',
    number: 'number',
    integer: 'integer',
    switch: 'boolean',
    select: 'enum',
    json: 'json',
}

/**
 * What a field falls back to when a document does not carry the key, or null when it has none.
 *
 * A list or a map is written as the JSON it is: `argv` defaults to an empty list, and `String`
 * of one is the empty string, which on screen is indistinguishable from no default at all.
 */
export function defaultLabel(field: FieldDescriptor): string | null {
    const value = field.fallback
    if (value === undefined) return null
    if (value === null) return 'null'
    if (typeof value === 'object') return JSON.stringify(value)
    return String(value)
}

/** One labelled fact about a block, keyed by the name the catalog answers with. */
export interface BlockFact {
    term: string
    detail: string
}

/**
 * What the catalog says about a block besides its schemas, as the rows of a definition list.
 *
 * THE TERM IS THE WIRE'S OWN WORD, the same rule the step form's labels follow: somebody
 * reading this is reading the answer `GET /blocks` gave, and a prettified term would be
 * teaching a name that appears nowhere.
 *
 * `local_execution` IS SAID IN BOTH DIRECTIONS. It is the one fact here that decides whether a
 * pipeline naming this block will run at all, and a row that appeared only when the answer was
 * yes would leave its absence meaning either no or not-read.
 */
export function factsOf(entry: BlockEntry): BlockFact[] {
    const facts: BlockFact[] = [
        { term: 'plugin', detail: entry.plugin },
        { term: 'idempotent', detail: entry.idempotent ? 'yes' : 'no' },
        {
            term: 'local_execution',
            detail: entry.local_execution ? 'requires allowlisting' : 'no allowlist entry',
        },
    ]
    if (entry.default_poll_seconds !== null) {
        facts.push({ term: 'default_poll_seconds', detail: `${String(entry.default_poll_seconds)}s` })
    }
    if (entry.default_deadline_seconds !== null) {
        facts.push({ term: 'default_deadline_seconds', detail: `${String(entry.default_deadline_seconds)}s` })
    }
    return facts
}
