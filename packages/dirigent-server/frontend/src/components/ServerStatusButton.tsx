import { useEffect, useState } from 'react'

import { ChevronDown } from 'lucide-react'

import { useNavigate } from 'react-router'

import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useStore } from '@/hooks/use-store'
import { authStore, signOut } from '@/lib/auth'
import { LOGIN_PATH } from '@/lib/nav'
import { formatRelative } from '@/lib/format'
import { RECHECK_INTERVAL_MS, checkServer, identityLine, serverStatus, type ServerState } from '@/lib/server-status'
import { cn } from '@/lib/utils'

export const SERVER_STATUS_LABEL = 'Instance'

/** What each state paints and says. The settings dialog's Health row draws the same pair. */
export const TONE: Record<ServerState, { dot: string; word: string }> = {
    unknown: { dot: 'bg-muted-foreground', word: 'asking…' },
    healthy: { dot: 'bg-good', word: 'healthy' },
    degraded: { dot: 'bg-warning', word: 'degraded' },
    unhealthy: { dot: 'bg-critical', word: 'unhealthy' },
    offline: { dot: 'bg-critical', word: 'offline' },
}

/** One fact about the instance, on the row every fact here shares. */
function Fact({ term, detail }: { term: string; detail: string }) {
    return (
        <div className="row-hover col-span-2 grid grid-cols-subgrid px-3 py-0.5">
            <dt className="text-faint">{term}</dt>
            <dd className="font-mono">{detail}</dd>
        </div>
    )
}

export function Dot({ state, wide }: { state: ServerState; wide?: boolean }) {
    return <span className={cn('rounded-full', wide ? 'size-2.5' : 'size-2', TONE[state].dot)} aria-hidden />
}

/**
 * The corner identity: which instance this is, what it is running, and how it is doing.
 *
 * THE INSTANCE IS NAMED, NOT MERELY COLOURED. A dot alone says the server is well without
 * saying which server, and a reader with a staging tab beside a production one has to know
 * that before they press anything. So the trigger is the dot and the name and environment
 * from `/system/info` -- a summary outside, and every detail, version included, within.
 *
 * The dot re-asks on a slow clock and when the tab comes back; the popover shows what the
 * last answer carried and re-asks as it opens, so its rows are as fresh as the click.
 *
 * THE SESSION LIVES HERE TOO: the account and its way out sit at the bottom of the same
 * popover, so the corner holds everything about "this instance, this session" behind one
 * button instead of loose chrome on the bar.
 */
export function ServerStatusButton() {
    const status = useStore(serverStatus)
    const auth = useStore(authStore)
    const navigate = useNavigate()
    const [open, setOpen] = useState(false)

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
        <DropdownMenu
            open={open}
            onOpenChange={(next) => {
                setOpen(next)
                if (next) void checkServer()
            }}
        >
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="ghost"
                        size="sm"
                        className="cursor-pointer gap-2 rounded-md px-2"
                        aria-label={SERVER_STATUS_LABEL}
                    >
                        <Dot state={status.state} />
                        <span className="max-w-64 truncate text-sm font-medium">{identityLine(status)}</span>
                        <ChevronDown className="text-faint size-3" aria-hidden />
                    </Button>
                }
            />
            <DropdownMenuContent align="end" className="w-80 min-w-80 p-0">
                <div className="row-hover flex items-center gap-2 px-3 py-2">
                    <Dot state={status.state} wide />
                    <span className="text-sm font-medium">{TONE[status.state].word}</span>
                    {status.state === 'offline' && (
                        <span className="text-muted-foreground text-xs">the server did not answer</span>
                    )}
                    <span className="flex-1" />
                    {status.checkedAt !== null && (
                        <span className="text-faint text-xs">
                            checked {formatRelative(new Date(status.checkedAt).toISOString())}
                        </span>
                    )}
                </div>
                {/* WHAT THIS INSTANCE IS, said once in the app and said here. The status bar
                    used to repeat the version along its right edge, which is a fact appearing
                    twice in one shell. */}
                <dl className="border-border grid grid-cols-[auto_1fr] gap-x-3 border-t px-0 py-2 text-xs">
                    <Fact term="environment" detail={status.environment ?? 'not said'} />
                    <Fact term="version" detail={status.version ?? 'not said'} />
                    {status.checks.map((check) => (
                        <div key={check.name} className="row-hover col-span-2 grid grid-cols-subgrid px-3 py-0.5">
                            <dt className="text-faint">{check.name}</dt>
                            <dd className="flex flex-col">
                                <span className="flex items-center gap-1.5">
                                    <Dot
                                        state={
                                            check.status === 'healthy' || check.status === 'degraded'
                                                ? (check.status as ServerState)
                                                : 'unhealthy'
                                        }
                                    />
                                    {check.status}
                                </span>
                                {check.detail !== null && (
                                    <span
                                        className={cn(
                                            check.status === 'healthy' ? 'text-muted-foreground' : 'text-warning-ink',
                                        )}
                                    >
                                        {check.detail}
                                    </span>
                                )}
                            </dd>
                        </div>
                    ))}
                </dl>
                {auth.identity !== null && (
                    <div className="border-border flex items-center gap-2 border-t px-3 py-1.5">
                        <span className="font-mono text-sm">{auth.identity.username}</span>
                        <span className="flex-1" />
                        <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                                void signOut().then(() => navigate(LOGIN_PATH, { replace: true }))
                            }}
                        >
                            Sign out
                        </Button>
                    </div>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
