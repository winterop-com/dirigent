import { Link } from 'react-router'

import { Instant } from '@/components/Instant'
import { Mark } from '@/components/Mark'
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
 * THE NAME READS WHOLE AND THE DETAIL TAKES WHAT IS LEFT. The name identifies the row -- a code
 * cut in half names nothing -- so it is drawn at the width it needs, up to half the row and never
 * below six characters; the detail is prose written to be cut and truncates in the rest, with the
 * whole of it on its title; the instant is a value out of a fixed vocabulary and holds its own
 * width. Nothing on the row is unbounded, so the card has no width at which it scrolls sideways.
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
                    <p className="text-xs text-muted-foreground">
                        {reading
                            ? 'Reading from the server'
                            : 'The workers claiming work, and every connection.'}
                    </p>
                </div>

                <ul className="max-h-64 grow overflow-y-auto">
                    {rows.map((row) => {
                        const to =
                            row.kind === 'connection'
                                ? '/connections'
                                : role === 'admin'
                                  ? '/admin/workers'
                                  : null
                        const body = (
                            <>
                                {/* How it is, then what it is. A worker is not a kind, so it
                                    draws nothing in the mark's place and holds the width, or
                                    the codes under it would not line up. */}
                                <span className="flex shrink-0 items-center gap-1.5">
                                    <span
                                        className={cn('size-2 shrink-0 rounded-full', DOTS[row.tone])}
                                        aria-hidden
                                    />
                                    {row.mark === null ? (
                                        <span className="size-4 shrink-0" aria-hidden />
                                    ) : (
                                        <Mark glyph={row.mark} />
                                    )}
                                </span>
                                <span
                                    className="max-w-[55%] min-w-[6ch] truncate font-mono text-xs"
                                    title={row.label}
                                >
                                    {row.label}
                                </span>
                                <span className="flex min-w-0 flex-1 items-baseline justify-end gap-2">
                                    <span
                                        className="truncate text-xs text-muted-foreground"
                                        title={row.detail}
                                    >
                                        {row.detail}
                                    </span>
                                    {row.at !== null && (
                                        <Instant className="shrink-0 text-xs text-faint" at={row.at} />
                                    )}
                                </span>
                            </>
                        )
                        return (
                            <li key={`${row.kind}:${row.id}`} className="border-t border-border">
                                {to === null ? (
                                    <span className="flex min-w-0 items-center gap-2 px-3 py-1.5">
                                        {body}
                                    </span>
                                ) : (
                                    <Link
                                        to={to}
                                        className="control-link flex min-w-0 items-center gap-2 px-3 py-1.5 hover:bg-accent/60"
                                    >
                                        {body}
                                    </Link>
                                )}
                            </li>
                        )
                    })}
                </ul>

                <p className="border-t border-border px-3 py-2 text-xs text-muted-foreground">{note}</p>
            </CardContent>
        </Card>
    )
}
