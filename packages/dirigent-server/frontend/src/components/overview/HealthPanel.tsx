import { Link } from 'react-router'

import { Instant } from '@/components/Instant'
import { Card, CardContent } from '@/components/ui/card'
import { useStore } from '@/hooks/use-store'
import { authStore } from '@/lib/auth'
import type { HealthRow } from '@/lib/home'
import type { TileTone } from '@/lib/overview'
import { cn } from '@/lib/utils'

/** How each tone fills a dot: the four semantic aliases, and the absence of one. */
const DOTS: Record<TileTone, string> = {
    neutral: 'bg-muted-foreground',
    good: 'bg-good',
    info: 'bg-info',
    warning: 'bg-warning',
    critical: 'bg-critical',
}

/**
 * What this instance depends on, and whether it is well.
 *
 * TWO REGISTRIES, ONE QUESTION. A worker that has gone quiet and a connection that will not
 * answer are the same news to somebody opening this screen -- something this instance needs is
 * not there -- so they are one list rather than two panels asking a reader to check both.
 *
 * THE NAME IS WHAT IDENTIFIES A ROW, so it does not truncate before the detail beside it does:
 * a code cut in half names nothing, while a refusal cut short still says what kind of refusal
 * it was, and the whole of it is on the element's title.
 *
 * THE FOOT SAYS ONLY WHAT IS NOT PERFECT. The rows carry the detail; the line under them is
 * what a reader who is not reading the rows has to know, and where everything is well that is
 * one sentence saying so.
 *
 * A ROW LINKS TO THE SCREEN THAT OWNS IT -- a connection to the connections listing, a worker
 * to the workers table -- and wears the hover that says so. A worker's screen is the admin's,
 * so for anybody else the worker rows are facts rather than doors, and wear nothing.
 */
export function HealthPanel({ rows, note, reading }: { rows: HealthRow[]; note: string; reading: boolean }) {
    const role = useStore(authStore).identity?.role ?? null
    return (
        <Card className="gap-0 p-0">
            <CardContent className="flex h-full flex-col p-0">
                <div className="space-y-1 px-3 py-3">
                    <h2 className="text-sm font-semibold">Health</h2>
                    <p className="text-muted-foreground text-xs">
                        {reading ? 'Reading from the server' : 'The workers claiming work, and every connection.'}
                    </p>
                </div>

                <ul className="max-h-64 grow overflow-y-auto">
                    {rows.map((row) => {
                        const to = row.kind === 'connection' ? '/connections' : role === 'admin' ? '/admin/workers' : null
                        const body = (
                            <>
                                <span className={cn('size-2 shrink-0 rounded-full', DOTS[row.tone])} aria-hidden />
                                <span className="max-w-[55%] shrink-0 truncate font-mono text-xs" title={row.label}>
                                    {row.label}
                                </span>
                                <span className="ml-auto flex min-w-0 items-baseline gap-2">
                                    <span className="text-muted-foreground truncate text-xs" title={row.detail}>
                                        {row.detail}
                                    </span>
                                    {row.at !== null && (
                                        <Instant className="text-faint shrink-0 text-xs" at={row.at} />
                                    )}
                                </span>
                            </>
                        )
                        return (
                            <li key={`${row.kind}:${row.id}`} className="border-border border-t">
                                {to === null ? (
                                    <span className="flex items-center gap-3 px-3 py-1.5">{body}</span>
                                ) : (
                                    <Link
                                        to={to}
                                        className="hover:bg-accent/60 flex items-center gap-3 px-3 py-1.5"
                                    >
                                        {body}
                                    </Link>
                                )}
                            </li>
                        )
                    })}
                </ul>

                <p className="text-muted-foreground border-border border-t px-3 py-2 text-xs">{note}</p>
            </CardContent>
        </Card>
    )
}
