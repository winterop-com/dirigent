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
import type { ComponentType, SVGProps } from 'react'

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

/** The mark one kind is known by, or the neutral glyph for a kind this bundle cannot name. */
export function kindGlyph(kind: string): Glyph {
    return KIND_GLYPHS.get(kind) ?? NEUTRAL_GLYPH
}
