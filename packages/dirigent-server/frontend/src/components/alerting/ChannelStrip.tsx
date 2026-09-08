import type { CSSProperties } from 'react'

import { Instant } from '@/components/Instant'
import { channelView, type Channel } from '@/lib/alerting'

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

/** One channel: what it is, what it delivers through, and when it was last proved. */
function ChannelCard({ channel }: { channel: Channel }) {
    const view = channelView(channel)
    return (
        <li className="border-border bg-card flex items-start justify-between gap-3 rounded-lg border p-3">
            <span
                className="flex min-w-0 items-baseline gap-2"
                title={channel.connection === null ? channel.notifier : `${channel.notifier} ${channel.connection}`}
            >
                <span className="status-dot shrink-0" style={{ '--chip': TONES[view.tone] } as CSSProperties} />
                <span className="shrink-0 text-sm font-medium">{channel.notifier}</span>
                {channel.connection !== null && (
                    <span className="text-muted-foreground truncate font-mono text-xs">{channel.connection}</span>
                )}
            </span>
            <span className="flex shrink-0 flex-col items-end">
                <span className="text-muted-foreground text-xs">{view.label}</span>
                {channel.last_check_at !== null && <Instant className="text-faint text-xs" at={channel.last_check_at} />}
                {view.detail !== null && (
                    <span className="text-faint max-w-48 truncate text-xs" title={view.detail}>
                        {view.detail}
                    </span>
                )}
            </span>
        </li>
    )
}
