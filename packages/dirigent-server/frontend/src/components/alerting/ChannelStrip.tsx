import type { CSSProperties } from 'react'
import { Link } from 'react-router'

import { Instant } from '@/components/Instant'
import { channelView, type Channel } from '@/lib/alerting'
import { newConnectionPath } from '@/lib/connections'
import { channelGlyph, type Glyph } from '@/lib/glyphs'
import { cn } from '@/lib/utils'

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
 *
 * A CHANNEL NOTHING IS SET UP FOR IS QUIET, AND CARRIES THE ONE THING THAT CHANGES THAT. What it
 * says about itself is dimmed the way a rule that delivers nothing is; the way in keeps its ink,
 * because a control dimmed past its own contrast is one somebody cannot read. Its second line is
 * that link rather than a sentence saying again what the word above it already said.
 */
function ChannelCard({ channel }: { channel: Channel }) {
    const view = channelView(channel)
    const unset = view.label === 'not set up'
    return (
        <li className="flex items-start gap-2 rounded-lg border border-border bg-card p-3">
            <ChannelMark glyph={channelGlyph(channel.notifier)} dim={unset} />
            <span className="flex min-w-0 flex-1 flex-col">
                <span
                    className={cn('flex min-h-7 items-center justify-between gap-2', unset && 'opacity-60')}
                >
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
                {unset && (
                    <Link
                        to={newConnectionPath(channel.notifier)}
                        className="control-link w-fit rounded-sm text-xs text-primary-ink hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
                    >
                        Set up {channel.notifier}
                    </Link>
                )}
            </span>
        </li>
    )
}

/** The mark that says which channel this is, in the tile every glyph in this app is drawn in. */
function ChannelMark({ glyph: Glyph, dim }: { glyph: Glyph; dim: boolean }) {
    return (
        <span
            className={cn(
                'flex size-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground',
                dim && 'opacity-60',
            )}
        >
            <Glyph className="size-4" aria-hidden />
        </span>
    )
}
