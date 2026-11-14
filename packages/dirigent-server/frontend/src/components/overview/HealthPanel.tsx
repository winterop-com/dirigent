import { Instant } from '@/components/Instant'
import { Mark } from '@/components/Mark'
import { ListRow, ListRows } from '@winterop-com/sokkel-ui/ListRow'
import { Section } from '@winterop-com/sokkel-ui/Section'
import { useStore } from '@winterop-com/sokkel-ui/hooks/use-store'
import { authStore } from '@/lib/auth'
import type { HealthRow } from '@/lib/home'
import { LABELS } from '@/lib/labels'
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
 * THE NAME READS WHOLE AND THE DETAIL TAKES WHAT IS LEFT. Each row is a dense mono `ListRow`:
 * the name identifies the row -- a code cut in half names nothing -- so it is drawn at the width it
 * needs; the detail is prose written to be cut and truncates in the rest, with the whole of it on
 * the row's title; the instant is a value out of a fixed vocabulary and holds its own width.
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
        <Section
            title={LABELS.word.health}
            meta={reading ? LABELS.shell.reading : undefined}
            flush
            bodyClassName="flex flex-col"
        >
            <ListRows flush label={LABELS.word.health} className="max-h-64 grow overflow-y-auto">
                {rows.map((row) => {
                    const to =
                        row.kind === 'connection'
                            ? '/connections'
                            : role === 'admin'
                              ? '/admin/workers'
                              : undefined
                    return (
                        <ListRow
                            key={`${row.kind}:${row.id}`}
                            dense
                            mono
                            href={to}
                            icon={
                                <>
                                    {/* How it is, then what it is. A worker is not a kind, so it draws
                                        nothing in the mark's place and holds the width, or the codes
                                        under it would not line up. */}
                                    <span
                                        className={cn('size-2 shrink-0 rounded-full', DOTS[row.tone])}
                                        title={row.tip ?? undefined}
                                    />
                                    {row.mark === null ? (
                                        <span className="size-4 shrink-0" />
                                    ) : (
                                        <Mark glyph={row.mark} />
                                    )}
                                </>
                            }
                            title={row.label}
                            detail={row.detail}
                            tooltip={`${row.label}: ${row.detail}`}
                            aside={
                                row.at === null ? undefined : (
                                    <Instant
                                        focusable={to === undefined}
                                        className="text-faint"
                                        at={row.at}
                                    />
                                )
                            }
                        />
                    )
                })}
            </ListRows>

            <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground">{note}</p>
        </Section>
    )
}
