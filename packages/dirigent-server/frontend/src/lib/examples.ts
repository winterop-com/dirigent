/**
 * The example corpus: every document this build's plugins ship, and the starters among them.
 *
 * THE FIELD NAMES ARE THE WIRE'S. Every interface here mirrors a pydantic model in
 * `dirigent_client.schemas.examples` member for member.
 *
 * THE CATALOGUE IS WHAT THIS BUILD SHIPS, NOT WHAT ANYBODY APPLIED. `GET /examples` reads the
 * plugin host rather than the database, so the answer is the same on an empty instance as on a
 * busy one and it does not change while a tab is open. It is read whole, once, and narrowed in
 * the browser -- the same standing the block catalog has, and the reason a client-side filter
 * here is not a squint at a partial read: there is no page nobody has loaded.
 *
 * ONE READ PER TAB. The screen and the Blocks page's cross-link both want the whole corpus, so
 * the walk is a cached promise: two screens asking is one request.
 *
 * WHAT A DOCUMENT NEEDS IS CHECKED AGAINST THE INSTANCE, not asserted. `requires` says what has
 * to be there before an apply will take; the catalog, the connections listing and the schemas
 * listing say what is. A read that has not landed is `null` and nothing is reported missing on
 * the strength of it.
 */

import { apiJson, type Page } from '@/lib/api'
import { readCatalog } from '@/lib/blocks'
import { readConnections } from '@/lib/connections'
import { readSchemas } from '@/lib/schemas'

/** What a shared document needs of an instance. `Requirements`. */
export interface Requirements {
    blocks: string[]
    connections: string[]
    pipelines: string[]
    storage: string[]
    schemas: string[]
    workers: string[]
}

/** One document of the installed corpus, as a listing shows it. `ExampleOut`. */
export interface ExampleOut {
    /** The key it is addressed by, and what `dg pipeline new` is given. */
    code: string
    name: string | null
    description: string | null
    tags: string[]
    requires: Requirements
    /** The distribution whose shelves it came from. */
    plugin: string
    /** The directory it sits in under that distribution's shelves root; empty at the root. */
    shelf: string
    /** Whether it opted into being copied into a project as a starting point. */
    starter: boolean
    /** The top-level sections it carries rather than requires, which an instance refuses. */
    carries: string[]
}

/** One example plus the text a copy of it copies. `ExampleDetail`. */
export interface ExampleDetail extends ExampleOut {
    source: string
    path: string
}

/** What an empty `requires` is, for a row the server answered without one. */
const NOTHING_REQUIRED: Requirements = {
    blocks: [],
    connections: [],
    pipelines: [],
    storage: [],
    schemas: [],
    workers: [],
}

/** How many rows one request asks for, which is the whole corpus in one answer. */
const CORPUS_PAGE = 500

/** How many pages the walk asks for before it stops, so a bug cannot spin here. */
const PAGE_LIMIT = 10

/** Read one page of the corpus, in plugin, shelf, code order. */
export function readExamples(
    after: string | null = null,
    limit: number = CORPUS_PAGE,
): Promise<Page<ExampleOut>> {
    const query = new URLSearchParams({ limit: String(limit) })
    if (after !== null) query.set('after', after)
    return apiJson<Page<ExampleOut>>(`/examples?${query.toString()}`)
}

let corpus: Promise<ExampleOut[]> | null = null

/**
 * The whole corpus, read once for the life of the tab.
 *
 * A failed read clears the cached promise, so a reader that retries reaches the network again
 * rather than being handed the same rejection forever.
 */
export function readAllExamples(): Promise<ExampleOut[]> {
    corpus ??= walk().catch((error: unknown) => {
        corpus = null
        throw error
    })
    return corpus
}

/** Forget the cached corpus. Tests, and nothing else, call this. */
export function forgetExamples(): void {
    corpus = null
}

async function walk(): Promise<ExampleOut[]> {
    const rows: ExampleOut[] = []
    let after: string | null = null
    for (let page = 0; page < PAGE_LIMIT; page += 1) {
        // A cursor walk is sequential by definition: the next page is named by this one.
        // oxlint-disable-next-line no-await-in-loop
        const answer: Page<ExampleOut> = await readExamples(after)
        rows.push(...answer.items.map(complete))
        after = answer.next
        if (after === null) break
    }
    return rows
}

/** A row with every list on it, so nothing downstream has to ask whether the server sent one. */
function complete(row: ExampleOut): ExampleOut {
    return { ...row, requires: { ...NOTHING_REQUIRED, ...row.requires } }
}

/** Read one example with the text a copy of it copies. */
export function readExample(code: string): Promise<ExampleDetail> {
    return apiJson<ExampleDetail>(`/examples/${encodeURIComponent(code)}`)
}

/** What this instance holds of what a document may need, or null where a read has not landed. */
export interface Holdings {
    blocks: string[] | null
    connections: string[] | null
    schemas: string[] | null
}

/**
 * The three listings a requirement is checked against, read together.
 *
 * A refusal of one is that one being unknown rather than the screen failing: a reader whose
 * account may not list connections still gets the blocks checked.
 */
export async function readHoldings(): Promise<Holdings> {
    const [catalog, connections, schemas] = await Promise.allSettled([
        readCatalog(),
        readConnections(),
        readSchemas(),
    ])
    return {
        blocks: catalog.status === 'fulfilled' ? catalog.value.blocks.map((one) => one.id) : null,
        connections:
            connections.status === 'fulfilled' ? connections.value.items.map((one) => one.code) : null,
        schemas: schemas.status === 'fulfilled' ? schemas.value.items.map((one) => one.code) : null,
    }
}

/** What kind of thing one requirement is, which decides how it is said and what checks it. */
export type Need = 'block' | 'connection' | 'schema' | 'pipeline' | 'storage' | 'worker'

/** One thing a document needs, and whether this instance has it. */
export interface Requirement {
    kind: Need
    name: string
    /** True held, false missing, null nothing here can answer -- an unread listing, or a pipeline. */
    met: boolean | null
}

/** How each kind of requirement is counted, singular and plural. `_COUNTED` in the CLI. */
const COUNTED: readonly (readonly [Need, string, string])[] = [
    ['connection', 'connection', 'connections'],
    ['schema', 'schema', 'schemas'],
    ['pipeline', 'pipeline', 'pipelines'],
    ['storage', 'storage scheme', 'storage schemes'],
    ['block', 'block', 'blocks'],
    ['worker', 'worker tag', 'worker tags'],
]

/**
 * Everything a document needs, in the order the summary counts them, checked where it can be.
 *
 * A PIPELINE, A STORAGE SCHEME AND A WORKER TAG ARE NOT CHECKED. What answers a `s3://` write
 * is a backend the catalog does not enumerate per scheme, what claims a worker tag is a node
 * that may be offline this minute, and a required pipeline is one this reader may be about to
 * apply -- so each is stated and none is called missing.
 */
export function requirementsOf(requires: Requirements, holdings: Holdings): Requirement[] {
    const held = (names: readonly string[] | null, name: string): boolean | null =>
        names === null ? null : names.includes(name)
    return [
        ...requires.connections.map((name) => ({
            kind: 'connection' as const,
            name,
            met: held(holdings.connections, name),
        })),
        ...requires.schemas.map((name) => ({
            kind: 'schema' as const,
            name,
            met: held(holdings.schemas, name),
        })),
        ...requires.pipelines.map((name) => ({ kind: 'pipeline' as const, name, met: null })),
        ...requires.storage.map((name) => ({ kind: 'storage' as const, name, met: null })),
        ...requires.blocks.map((name) => ({
            kind: 'block' as const,
            name,
            met: held(holdings.blocks, name),
        })),
        ...requires.workers.map((name) => ({ kind: 'worker' as const, name, met: null })),
    ]
}

/** How many of a document's requirements this instance has not got. */
export function missingCount(items: readonly Requirement[]): number {
    return items.filter((item) => item.met === false).length
}

/**
 * What a document needs, in one line: the counts, and how many of them are not here.
 *
 * Null where it needs nothing in particular, because a column saying "nothing" of a hundred
 * rows is a column of noise.
 */
export function requirementsSummary(items: readonly Requirement[]): string | null {
    if (items.length === 0) return null
    const counted = COUNTED.flatMap(([kind, one, many]) => {
        const held = items.filter((item) => item.kind === kind).length
        return held === 0 ? [] : [`${String(held)} ${held === 1 ? one : many}`]
    })
    const missing = missingCount(items)
    return missing === 0 ? counted.join(', ') : `${counted.join(', ')}, ${String(missing)} missing`
}

/**
 * What a document carries that an instance refuses to store, said as a phrase or not at all.
 *
 * A top-level `connections:` or `schemas:` section is a teaching aid: `dg run --local` reads
 * it and an apply refuses it, so the catalogue says so where somebody would otherwise copy it
 * and be refused.
 */
export function carriesNote(example: ExampleOut): string | null {
    if (example.carries.length === 0) return null
    return `carries ${example.carries.join(' and ')}`
}

/** What a listing is narrowed to, which is the whole of this screen's address. */
export interface ExampleFilters {
    /** What was typed, matched over the code, the name, the description and the tags. */
    needle: string
    /** Every tag that must be present, which is what repeating `tag` means on the wire. */
    tags: string[]
    /** One shelf, or the empty string for any. */
    shelf: string
    /** One plugin, or the empty string for any. */
    plugin: string
    /** Whether only the documents that may be copied are shown. */
    starters: boolean
    /** One block id the document must require, or the empty string for any. */
    block: string
}

export const EVERY_EXAMPLE: ExampleFilters = {
    needle: '',
    tags: [],
    shelf: '',
    plugin: '',
    starters: false,
    block: '',
}

/** The filters one address asks for, which is what a link to a narrowed listing carries. */
export function filtersFromQuery(query: URLSearchParams): ExampleFilters {
    return {
        needle: query.get('q') ?? '',
        tags: query.getAll('tag'),
        shelf: query.get('shelf') ?? '',
        plugin: query.get('plugin') ?? '',
        starters: query.get('starter') === 'true',
        block: query.get('block') ?? '',
    }
}

/** The address one set of filters is written as, with every empty one left out. */
export function queryOf(filters: ExampleFilters): URLSearchParams {
    const query = new URLSearchParams()
    if (filters.needle !== '') query.set('q', filters.needle)
    for (const tag of filters.tags) query.append('tag', tag)
    if (filters.shelf !== '') query.set('shelf', filters.shelf)
    if (filters.plugin !== '') query.set('plugin', filters.plugin)
    if (filters.starters) query.set('starter', 'true')
    if (filters.block !== '') query.set('block', filters.block)
    return query
}

/** Whether anything at all is being narrowed, which is what the empty state reads. */
export function anythingFiltered(filters: ExampleFilters): boolean {
    return (
        filters.needle !== '' ||
        filters.tags.length > 0 ||
        filters.shelf !== '' ||
        filters.plugin !== '' ||
        filters.starters ||
        filters.block !== ''
    )
}

/** The rows one set of filters leaves, over the whole corpus rather than a page of it. */
export function narrowExamples(rows: readonly ExampleOut[], filters: ExampleFilters): ExampleOut[] {
    const wanted = filters.needle.trim().toLowerCase()
    return rows.filter((row) => {
        if (filters.starters && !row.starter) return false
        if (filters.shelf !== '' && row.shelf !== filters.shelf) return false
        if (filters.plugin !== '' && row.plugin !== filters.plugin) return false
        if (!filters.tags.every((tag) => row.tags.includes(tag))) return false
        if (filters.block !== '' && !row.requires.blocks.includes(filters.block)) return false
        if (wanted === '') return true
        const read = `${row.code} ${row.name ?? ''} ${row.description ?? ''} ${row.tags.join(' ')}`
        return read.toLowerCase().includes(wanted)
    })
}

/** Every tag the corpus wears, once each, in the order a filter menu offers them. */
export function tagsOffered(rows: readonly ExampleOut[]): string[] {
    return [...new Set(rows.flatMap((row) => row.tags))].toSorted((left, right) => left.localeCompare(right))
}

/** Every shelf the corpus is filed on, once each, with the root shelf left out. */
export function shelvesOffered(rows: readonly ExampleOut[]): string[] {
    return [...new Set(rows.map((row) => row.shelf))]
        .filter((shelf) => shelf !== '')
        .toSorted((left, right) => left.localeCompare(right))
}

/** Every distribution contributing a shelf, once each. */
export function pluginsOffered(rows: readonly ExampleOut[]): string[] {
    return [...new Set(rows.map((row) => row.plugin))].toSorted((left, right) => left.localeCompare(right))
}

/**
 * How many documents require one block, keyed by the block's id.
 *
 * IT IS `requires.blocks`, AND SO IS THE LINK. What a count says has to be what pressing it
 * shows, so both read the one field the listing carries -- a document reaching a block its
 * `requires` forgot is under-counted here and absent from the filtered listing, which is one
 * answer rather than two.
 */
export function examplesPerBlock(rows: readonly ExampleOut[]): Map<string, number> {
    const counted = new Map<string, number>()
    for (const row of rows) {
        for (const block of new Set(row.requires.blocks)) {
            counted.set(block, (counted.get(block) ?? 0) + 1)
        }
    }
    return counted
}

/** One shelf of starters in the picker: what it is called, and the documents on it. */
export interface StarterShelf {
    label: string
    rows: ExampleOut[]
}

/**
 * The starters, shelved by the distribution they came from and then the directory they sit in.
 *
 * A pack's shelves and the core corpus's share names -- both have `recipes` -- so the heading
 * carries both halves, breadcrumbed the way the add-step menu breadcrumbs a block.
 */
export function shelveStarters(rows: readonly ExampleOut[]): StarterShelf[] {
    const shelves = new Map<string, ExampleOut[]>()
    for (const row of rows.filter((one) => one.starter)) {
        const label = row.shelf === '' ? row.plugin : `${row.plugin} ▸ ${row.shelf}`
        const shelf = shelves.get(label)
        if (shelf === undefined) shelves.set(label, [row])
        else shelf.push(row)
    }
    return [...shelves.entries()]
        .toSorted(([left], [right]) => left.localeCompare(right))
        .map(([label, held]) => ({
            label,
            rows: held.toSorted((left, right) => left.code.localeCompare(right.code)),
        }))
}

/** Whether one starter answers what was typed, every term matching, as the palette filters. */
export function starterMatches(row: ExampleOut, query: string): boolean {
    const terms = query.toLowerCase().split(/\s+/u).filter(Boolean)
    const read = `${row.code} ${row.name ?? ''} ${row.description ?? ''} ${row.tags.join(' ')}`.toLowerCase()
    return terms.every((term) => read.includes(term))
}
