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
 */
function ChannelCard({ channel }: { channel: Channel }) {
    const view = channelView(channel)
    return (
        <li className="flex items-start justify-between gap-3 rounded-lg border border-border bg-card p-3">
            <span
                className="flex min-w-0 items-center gap-2"
                title={
                    channel.connection === null
                        ? channel.notifier
                        : `${channel.notifier} ${channel.connection}`
                }
            >
                <ChannelMark glyph={channelGlyph(channel.notifier)} />
                <span className="flex min-w-0 flex-col">
                    <span className="truncate text-sm font-medium">{channel.notifier}</span>
                    {channel.connection !== null && (
                        <span className="truncate font-mono text-xs text-muted-foreground">
                            {channel.connection}
                        </span>
                    )}
                </span>
            </span>
            <span className="flex shrink-0 flex-col items-end">
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <span
                        className="status-dot shrink-0"
                        style={{ '--chip': TONES[view.tone] } as CSSProperties}
                    />
                    {view.label}
                </span>
                {channel.last_check_at !== null && (
                    <Instant className="text-xs text-faint" at={channel.last_check_at} />
                )}
                {view.detail !== null && (
                    <span className="max-w-48 truncate text-xs text-faint" title={view.detail}>
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
