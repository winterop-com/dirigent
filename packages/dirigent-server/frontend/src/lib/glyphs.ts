/**
 * What a kind is, as a mark.
 *
 * A GLYPH IDENTIFIES A KIND AND NEVER A STATE. `lib/kinds` gives a kind its hue; this gives it
 * the mark a reader tells it apart by, so a listing whose rows all lead with the same dot and
 * the same word can be read at a glance. A state is the status tokens' job, and nothing here
 * answers one.
 *
 * ONE MAP, AND EVERY SCREEN DRAWS OUT OF IT. A connection kind and a notifier are the same word,
 * so a kind is given a mark here once and nowhere else: adding a kind is adding one entry below.
 *
 * TOTAL BY CONSTRUCTION. Kinds arrive from whichever packs an instance installed, so the mapping
 * is what this bundle names plus the neutral glyph for everything it does not -- a kind nobody
 * here has seen gets a mark rather than a hole beside the ones that have one.
 *
 * A PACK MAY SEND ITS OWN MARK, AND IT IS PATH DATA OR IT IS NOT DRAWN. A connection kind
 * declares one path on the same 24-unit grid, which reaches here through the catalog. What
 * arrives is a string off the wire, so it is held to what registration held it to -- non-empty,
 * ASCII, path-data characters, a size -- before anything puts it in front of a browser.
 */

import {
    Container,
    Database,
    Dot,
    GitBranch,
    Globe,
    HardDrive,
    ListOrdered,
    Mail,
    ScrollText,
    Webhook,
} from 'lucide-react'
import { createElement, type ComponentType, type SVGProps } from 'react'

import { SlackMark } from '@/components/alerting/SlackMark'

/** What draws a mark: an icon from the set, or one drawn here because the set ships none. */
export type Glyph = ComponentType<SVGProps<SVGSVGElement>>

/** What a kind with no mark of its own is drawn as, rather than a gap. */
export const NEUTRAL_GLYPH: Glyph = Dot

/**
 * The kinds this repository ships, each keyed by the code the wire answers with.
 *
 * `kafka` and `rabbitmq` share the queue: two kinds that are the same sort of thing may wear
 * that sort's mark, and the code beside it is what names the one in front of somebody.
 *
 * A map rather than an object: the key is a code off the wire, and one spelling a member of
 * `Object.prototype` would answer with a function where a glyph belongs.
 */
const KIND_GLYPHS = new Map<string, Glyph>([
    ['docker', Container],
    ['email', Mail],
    ['git', GitBranch],
    ['http', Globe],
    ['kafka', ListOrdered],
    ['log', ScrollText],
    ['rabbitmq', ListOrdered],
    ['s3', HardDrive],
    ['slack', SlackMark],
    ['sql', Database],
    ['webhook', Webhook],
])

/** The path data the installed packs declare, by the code the wire answers with. */
export type KindMarks = ReadonlyMap<string, string>

/** No pack has declared anything, which is what a screen draws out of until a catalog is read. */
export const NO_MARKS: KindMarks = new Map<string, string>()

/** How much path data one mark may carry, which is the limit registration holds a pack to. */
const MARK_LIMIT = 4096

/** Everything an SVG path's `d` is written out of: the commands, numbers, and separators. */
const PATH_DATA = /^[MmZzLlHhVvCcSsQqTtAaEe0-9,.+\-\s]+$/

/** Whether a string a pack sent is path data, rather than anything else a browser would read. */
function drawable(mark: string): boolean {
    return mark.trim() !== '' && mark.length <= MARK_LIMIT && PATH_DATA.test(mark)
}

/**
 * One glyph per declared path, so a kind's mark is one component across every render.
 *
 * A component built fresh on each call is a different type each time, which remounts whatever
 * drew it and defeats every memo above it.
 */
const DECLARED = new Map<string, Glyph>()

/** A glyph drawing one declared path, on the grid and in the ink every other glyph uses. */
function pathGlyph(mark: string): Glyph {
    const held = DECLARED.get(mark)
    if (held !== undefined) return held
    const glyph: Glyph = (props) =>
        createElement(
            'svg',
            {
                xmlns: 'http://www.w3.org/2000/svg',
                width: 24,
                height: 24,
                viewBox: '0 0 24 24',
                fill: 'currentColor',
                ...props,
            },
            createElement('path', { d: mark }),
        )
    DECLARED.set(mark, glyph)
    return glyph
}

/**
 * The mark one kind is known by: this bundle's, then the pack's, then the neutral one.
 *
 * The built-in map wins for the kinds it names, so an instance cannot be made to draw something
 * else where a reader has learned a mark. `marks` is the catalog's, and a kind with neither an
 * entry above nor path data here is drawn by the neutral glyph rather than a gap.
 */
export function kindGlyph(kind: string, marks: KindMarks = NO_MARKS): Glyph {
    const shipped = KIND_GLYPHS.get(kind)
    if (shipped !== undefined) return shipped
    const declared = marks.get(kind)
    if (declared !== undefined && drawable(declared)) return pathGlyph(declared)
    return NEUTRAL_GLYPH
}
