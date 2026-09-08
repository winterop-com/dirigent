/**
 * What the add-step menu offers, as pure decisions over the catalog.
 *
 * THE SHELVES ARE THE CATALOG'S OWN. A block declares the group it belongs on, and that is
 * what `lib/blocks` shelves the /blocks screen by; the menu asks there rather than inventing a
 * second arrangement of the same blocks.
 *
 * A KEY IS DERIVED, NOT ASKED FOR. The menu places a step on one keystroke, so the key comes
 * from the block that was chosen and is made unique against the document's own; it is renamed
 * in the step's pane like anything else about it.
 */

import { familyOf, byGroup, type BlockEntry } from '@/lib/blocks'

/** One shelf of the menu: a heading and the blocks under it. */
export interface BlockShelf {
    /** The group the blocks declare. */
    shelf: string
    blocks: BlockEntry[]
}

/** One search result: the block, and the two halves its breadcrumb is drawn from. */
export interface BlockCrumb {
    entry: BlockEntry
    /** Everything before the first dot. */
    family: string
    /** Everything after it, which is the id's own remainder when there is no dot. */
    rest: string
}

/** What a step key may be, which is `StepName` in dirigent_common. */
const STEP_KEY = /^[a-z][a-z0-9_]*$/

/** The word a search may name a kind by, in the singular and in the plural. */
const KIND_WORDS: Readonly<Record<string, BlockEntry['kind']>> = {
    sensor: 'sensor',
    sensors: 'sensor',
    operator: 'operator',
    operators: 'operator',
}

/** The two halves of a block id, which the menu draws as `family ▸ rest`. */
export function crumbOf(entry: BlockEntry): BlockCrumb {
    const family = familyOf(entry.id)
    const dot = entry.id.indexOf('.')
    return { entry, family, rest: dot === -1 ? entry.id : entry.id.slice(dot + 1) }
}

/**
 * The shelves the menu opens on: every group, in name order.
 *
 * A sensor sits in its group like any other block, chipped so it reads as the one that
 * waits; searching the word `sensor` collects them when the kind is the question.
 */
export function blockShelves(blocks: readonly BlockEntry[]): BlockShelf[] {
    return byGroup(blocks).map(([shelf, members]) => ({ shelf, blocks: members }))
}

/**
 * The blocks a search finds, breadcrumbed, in id order.
 *
 * EVERY TERM MUST MATCH, the same rule the command palette's filter follows, so typing another
 * word narrows rather than widens. A term matches a block's id or its summary -- and `sensor`
 * and `operator` match by kind, because what somebody is looking for is often the shape of the
 * block rather than its name.
 */
export function searchBlocks(blocks: readonly BlockEntry[], needle: string): BlockCrumb[] {
    const terms = needle.toLowerCase().split(/\s+/).filter((term) => term !== '')
    if (terms.length === 0) return []
    return blocks
        .filter((entry) => terms.every((term) => matches(entry, term)))
        .toSorted((a, b) => a.id.localeCompare(b.id))
        .map(crumbOf)
}

function matches(entry: BlockEntry, term: string): boolean {
    if (KIND_WORDS[term] === entry.kind) return true
    return `${entry.id} ${entry.summary}`.toLowerCase().includes(term)
}

/**
 * The key a step added from the menu takes: the block's own name, made unique.
 *
 * `transform.jq` lands as `jq`, and a second one as `jq_2`. The id's family is dropped because
 * the remainder is what somebody would have typed, and anything the key pattern would refuse --
 * a dot, a dash, a leading digit -- becomes an underscore rather than a document the apply
 * would turn down.
 */
export function stepKeyFor(block: string, taken: readonly string[]): string {
    const base = keyBase(block)
    if (!taken.includes(base)) return base
    for (let suffix = 2; ; suffix += 1) {
        const candidate = `${base}_${String(suffix)}`
        if (!taken.includes(candidate)) return candidate
    }
}

function keyBase(block: string): string {
    const dot = block.indexOf('.')
    const rest = dot === -1 ? block : block.slice(dot + 1)
    const written = rest.toLowerCase().replaceAll(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
    if (written === '' || !STEP_KEY.test(written)) return `step_${written}`.replace(/_$/, '')
    return written
}
