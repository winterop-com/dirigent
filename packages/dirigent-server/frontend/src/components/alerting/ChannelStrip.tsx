import type { CSSProperties } from 'react'

import { Instant } from '@/components/Instant'
import { channelView, type Channel } from '@/lib/alerting'
import { channelGlyph, type Glyph } from '@/lib/glyphs'

/** What each reading is painted in, named through the semantic aliases rather than a colour. */
const TONES: Record<'good' | 'critical' | 'quiet', string> = {
    good: 'var(--good)',
    critical: 'var(--critical)',
    quiet: 'var(--faint)',
}

/**
 * The channels an alert can leave by, and what each one last proved about itself.
 *
 * A CHANNEL THAT QUIETLY STOPPED IS THE THING THIS STRIP EXISTS FOR. The rules below say what
 * would be sent; this says whether there is anywhere for it to go. The reading is the
 * connection's own last health check -- the same one `dg connection check` writes -- so nothing
 * here decides whether a channel is well, it only says when that was last asked.
 */
export function ChannelStrip({ channels }: { channels: readonly Channel[] }) {
    return (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {channels.map((channel) => (
                <ChannelCard key={channel.id} channel={channel} />
            ))}
        </ul>
    )
}

/**
 * One channel: what it is, what it delivers through, and when it was last proved.
 *
 * THE GLYPH SAYS WHICH CHANNEL AND THE DOT SAYS HOW IT IS. The mark leads the card in muted ink
 * and carries no state; the reading's dot stands against the word it is the colour of, so the
 * two are read as the two facts they are rather than as one loud head.
 *
 * ONE TILE AND ONE COLUMN BESIDE IT. The tile is the height of the title's own row, so the glyph
 * and the notifier share a line, and everything this card says in words -- the notifier, the
 * connection's code, what the check said -- begins at that column's edge. The reading keeps the
 * right of the first two rows, so the word and the instant under it read as one block.
 */
function ChannelCard({ channel }: { channel: Channel }) {
    const view = channelView(channel)
    return (
        <li className="flex items-start gap-2 rounded-lg border border-border bg-card p-3">
            <ChannelMark glyph={channelGlyph(channel.notifier)} />
            <span className="flex min-w-0 flex-1 flex-col">
                <span className="flex min-h-7 items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium" title={channel.notifier}>
                        {channel.notifier}
                    </span>
                    <span className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
                        <span
                            className="status-dot shrink-0"
                            style={{ '--chip': TONES[view.tone] } as CSSProperties}
                        />
                        {view.label}
                    </span>
                </span>
                {(channel.connection !== null || channel.last_check_at !== null) && (
                    <span className="flex items-baseline justify-between gap-2">
                        {channel.connection !== null && (
                            <span
                                className="truncate font-mono text-xs text-muted-foreground"
                                title={channel.connection}
                            >
                                {channel.connection}
                            </span>
                        )}
                        {channel.last_check_at !== null && (
                            <Instant
                                className="ml-auto shrink-0 text-xs text-faint"
                                at={channel.last_check_at}
                            />
                        )}
                    </span>
                )}
                {view.detail !== null && (
                    <span className="truncate text-xs text-faint" title={view.detail}>
                        {view.detail}
                    </span>
                )}
            </span>
        </li>
    )
}

/** The mark that says which channel this is, in the tile every glyph in this app is drawn in. */
function ChannelMark({ glyph: Glyph }: { glyph: Glyph }) {
    return (
        <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
            <Glyph className="size-4" aria-hidden />
        </span>
    )
}
