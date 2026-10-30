import { useEffect } from 'react'

import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useStore } from '@/hooks/use-store'
import { formatRelative } from '@/lib/format'
import { LABELS } from '@/lib/labels'
import {
    RECHECK_INTERVAL_MS,
    checkServer,
    identityLine,
    serverStatus,
    statusWords,
    type ServerState,
    type ServerStatus,
} from '@/lib/server-status'
import { cn } from '@/lib/utils'

export const SERVER_STATUS_LABEL = LABELS.shell.instance.label

/** What each state paints and says. The settings dialog's Health row draws the same pair. */
export const TONE: Record<ServerState, { dot: string; word: string }> = {
    unknown: { dot: 'bg-muted-foreground', word: LABELS.state.server.asking },
    healthy: { dot: 'bg-good', word: LABELS.state.server.healthy },
    degraded: { dot: 'bg-warning', word: LABELS.state.server.degraded },
    unhealthy: { dot: 'bg-critical', word: LABELS.state.server.unhealthy },
    offline: { dot: 'bg-critical', word: LABELS.state.server.offline },
}

/** The ink the words beside the dot are in, for the states that have words. */
const WORD_INK: Partial<Record<ServerState, string>> = {
    degraded: 'text-warning-ink',
    unhealthy: 'text-critical-ink',
    offline: 'text-critical-ink',
}

export function Dot({ state, wide }: { state: ServerState; wide?: boolean }) {
    return (
        <span
            className={cn('shrink-0 rounded-full', wide ? 'size-2.5' : 'size-2', TONE[state].dot)}
            aria-hidden
        />
    )
}

/** Everything the dot does not say: which instance, how it is, what it runs, and every check. */
function Details({ status }: { status: ServerStatus }) {
    return (
        <span className="flex flex-col items-start gap-1">
            <span className="font-medium">{identityLine(status)}</span>
            <span>
                {TONE[status.state].word}
                {status.checkedAt !== null && (
                    <span className="opacity-70">
                        {' '}
                        {LABELS.word.checked.term} {formatRelative(new Date(status.checkedAt).toISOString())}
                    </span>
                )}
            </span>
            <span>
                {LABELS.word.version.term}{' '}
                <span className="font-mono">{status.version ?? LABELS.shell.instance.unknown}</span>
            </span>
            {status.checks.map((check) => (
                <span key={check.name}>
                    <span className="font-mono">{check.name}</span> {check.status}
                    {check.detail !== null && <span className="opacity-70"> {check.detail}</span>}
                </span>
            ))}
        </span>
    )
}

/**
 * How this instance is doing, as one dot: the details are its tooltip, and words appear beside it
 * only when something is wrong.
 *
 * The dot re-asks on a slow clock, when the tab comes back and as its tooltip opens, so what the
 * tooltip says is as fresh as the hover. A press opens the settings dialog's Server pane.
 */
export function ServerStatusButton({ onOpen }: { onOpen: () => void }) {
    const status = useStore(serverStatus)
    const words = statusWords(status.state)

    useEffect(() => {
        void checkServer()
        const clock = setInterval(() => void checkServer(), RECHECK_INTERVAL_MS)
        const onVisible = () => {
            if (!document.hidden) void checkServer()
        }
        document.addEventListener('visibilitychange', onVisible)
        return () => {
            clearInterval(clock)
            document.removeEventListener('visibilitychange', onVisible)
        }
    }, [])

    return (
        <Tooltip
            onOpenChange={(next) => {
                if (next) void checkServer()
            }}
        >
            <TooltipTrigger
                render={
                    <Button
                        variant="ghost"
                        size="sm"
                        className="cursor-pointer gap-2 px-2"
                        aria-label={LABELS.shell.instance.said(TONE[status.state].word)}
                        onClick={onOpen}
                    />
                }
            >
                <Dot state={status.state} />
                {words !== null && (
                    <span className={cn('text-xs font-medium', WORD_INK[status.state])}>{words}</span>
                )}
            </TooltipTrigger>
            <TooltipContent side="bottom" align="end">
                <Details status={status} />
            </TooltipContent>
        </Tooltip>
    )
}
