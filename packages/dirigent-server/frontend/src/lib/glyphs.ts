/**
 * What a thing is, as a mark.
 *
 * A GLYPH IDENTIFIES A KIND AND NEVER A STATE. `lib/kinds` gives a kind its hue; this gives it
 * the mark a reader tells it apart by, so a strip of cards that all lead with the same dot and
 * the same word can be read at a glance. A state is the status tokens' job, and nothing here
 * answers one.
 *
 * TOTAL BY CONSTRUCTION. Notifiers arrive from whichever packs an instance installed, so the
 * mapping is what this bundle names plus the neutral glyph for everything it does not -- a
 * channel nobody here has seen gets a mark rather than a hole beside the cards that have one.
 */

import { Dot, Mail, ScrollText, Webhook } from 'lucide-react'
import type { ComponentType, SVGProps } from 'react'

import { SlackMark } from '@/components/alerting/SlackMark'

/** What draws a mark: an icon from the set, or one drawn here because the set ships none. */
export type Glyph = ComponentType<SVGProps<SVGSVGElement>>

/** What a thing with no mark of its own is drawn as, rather than a gap. */
export const NEUTRAL_GLYPH: Glyph = Dot

/**
 * The channels this repository ships, each keyed by the notifier's own id.
 *
 * A map rather than an object: the key is a code off the wire, and one spelling a member of
 * `Object.prototype` would answer with a function where a glyph belongs.
 */
const CHANNEL_GLYPHS = new Map<string, Glyph>([
    ['email', Mail],
    ['log', ScrollText],
    ['slack', SlackMark],
    ['webhook', Webhook],
])

/** The mark one channel is known by, or the neutral glyph for a notifier this bundle cannot name. */
export function channelGlyph(notifier: string): Glyph {
    return CHANNEL_GLYPHS.get(notifier) ?? NEUTRAL_GLYPH
}
