import type { CSSProperties } from 'react'

import { statusLabel, statusTokens } from '@/lib/status'
import { cn } from '@/lib/utils'

/** The states worth animating: something is happening and nobody has to be told twice. */
const LIVE: ReadonlySet<string> = new Set(['running', 'queued', 'waiting', 'sending'])

/**
 * One state, drawn the one way this app draws a state.
 *
 * The fill rule is `.status-chip` in index.css and the hue is the `--status-<name>` token the
 * status string indexes, so a run's status in a heading and a step's status on the graph cannot
 * drift apart. Nothing here decides a colour.
 */
export function StatusChip({ status, className }: { status: string; className?: string }) {
    const live = LIVE.has(status)
    return (
        <span
            className={cn('status-chip font-medium', className)}
            data-status={status}
            data-live={live}
            style={statusTokens(status) as CSSProperties}
        >
            <span className="status-dot" aria-hidden />
            {statusLabel(status)}
        </span>
    )
}

/** A state with no room for its name: the dot alone, with the name as its title. */
export function StatusDot({ status, className }: { status: string; className?: string }) {
    return (
        <span
            className={cn('status-dot', className)}
            style={statusTokens(status) as CSSProperties}
            title={statusLabel(status)}
        />
    )
}
