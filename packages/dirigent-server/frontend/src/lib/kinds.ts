/**
 * What a thing is, as a colour.
 *
 * A KIND IS NOT A STATUS. A status says how something is going and is drawn from the state
 * machine's own token; a kind says what something is -- an operator or a sensor, a cron or an
 * interval, an http credential or a database one -- and a listing of them reads far faster when
 * each family holds one hue. `--kind-<family>` in index.css is that hue and `.kind-chip` is
 * the fill rule, so nothing here writes a colour: it names one.
 *
 * TOTAL BY CONSTRUCTION. Kinds arrive off the wire from whichever plugins an instance has
 * installed, so this bundle cannot hold a table of them. What it holds is a family for every
 * kind it names itself, and a stable hash into the same six families for every kind it does
 * not -- which means a kind nobody here has ever seen still gets one colour and keeps it,
 * rather than falling into an uncoloured default beside the ones that have a family.
 */

/** The families, which are the hues declared in index.css. */
export const KIND_FAMILIES = ['green', 'jade', 'teal', 'blue', 'violet', 'pink'] as const

export type KindFamily = (typeof KIND_FAMILIES)[number]

/**
 * The kinds this app names itself, each pinned to a family.
 *
 * Kinds that stand beside one another on a screen are given hues that stand apart: a schedule
 * beside a webhook, an operator beside a sensor, one clock beside the next.
 */
const NAMED: Readonly<Record<string, KindFamily>> = {
    // Block kinds: what the catalog publishes.
    operator: 'blue',
    sensor: 'teal',
    // Trigger kinds: what fires a pipeline without a person.
    schedule: 'green',
    webhook: 'violet',
    // Schedule clocks, which are the kinds a schedule comes in.
    cron: 'green',
    interval: 'jade',
    one_time: 'blue',
}

/**
 * Which family one kind is drawn in.
 *
 * A named kind keeps its family whatever else is installed. Anything else is hashed, so the
 * same connection kind is the same colour on every screen and in every session -- and a
 * plugin installed tomorrow does not move the colour of one installed today.
 */
export function kindFamily(kind: string): KindFamily {
    const named = NAMED[kind]
    if (named !== undefined) return named
    return KIND_FAMILIES[hash(kind) % KIND_FAMILIES.length]
}

/** The custom properties `.kind-chip` reads: the family's hue, and the ink legible on it. */
export function kindTokens(kind: string): { '--chip': string; '--chip-ink': string } {
    const family = kindFamily(kind)
    return { '--chip': `var(--kind-${family})`, '--chip-ink': `var(--kind-${family}-ink)` }
}

/** A kind as a person reads it: the wire spells with underscores, a reader does not. */
export function kindLabel(kind: string): string {
    return kind.replaceAll('_', ' ')
}

/** FNV-1a over the kind's characters, which is stable across sessions and across builds. */
function hash(text: string): number {
    let value = 0x811c9dc5
    for (let index = 0; index < text.length; index += 1) {
        value ^= text.charCodeAt(index)
        value = Math.imul(value, 0x01000193) >>> 0
    }
    return value
}
