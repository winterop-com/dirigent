import { Instant } from '@/components/Instant'
import type { Column } from '@/components/list/ListTable'
import { StatusChip } from '@/components/run/StatusChip'
import { headingOf } from '@/lib/identity'
import type { LookEntry } from '@/lib/overview'
import { cn } from '@/lib/utils'

/**
 * The needs-a-look table's columns, shared by the dashboard and the admin overview.
 *
 * A TABLE, BECAUSE THE VALUES NEED NAMING. A run in trouble is a status, a pipeline, the
 * step it died in and when -- four different kinds of value on one line, and a header row
 * is what says which is which.
 *
 * TITLE ELSE CODE, AND THE CODE ALWAYS ON SCREEN. The pipeline is headed the way every other
 * screen heads one: the name where there is one with the code in mono beside it, and where
 * there is none the code is the title and wears the mono face itself, so it is never drawn
 * twice.
 */
export const LOOK_COLUMNS: Column<LookEntry>[] = [
    {
        id: 'status',
        header: 'Status',
        cell: (entry) => <StatusChip status={entry.run.status} />,
    },
    {
        id: 'pipeline',
        header: 'Pipeline',
        cell: (entry) => {
            const heading = headingOf({ code: entry.run.pipeline, name: entry.name })
            return (
                <span className="flex min-w-0 items-baseline gap-2">
                    <span className={cn('truncate text-sm', !heading.named && 'font-mono')}>
                        {heading.title}
                    </span>
                    {heading.code !== null && (
                        <span className="shrink-0 font-mono text-xs text-muted-foreground">
                            {heading.code}
                        </span>
                    )}
                </span>
            )
        },
    },
    {
        id: 'step',
        header: 'Failed at',
        cell: (entry) =>
            entry.failedStep === null ? null : <span className="font-mono text-xs">{entry.failedStep}</span>,
    },
    {
        id: 'error',
        header: 'Error',
        className: 'hidden lg:table-cell',
        cell: (entry) =>
            entry.run.error === null ? null : (
                <span
                    className="block max-w-80 truncate text-xs text-muted-foreground"
                    title={entry.run.error}
                >
                    {entry.run.error}
                </span>
            ),
    },
    {
        id: 'when',
        header: 'When',
        className: 'text-right',
        cell: (entry) => (
            <Instant className="text-xs text-faint" at={entry.run.started_at ?? entry.run.created_at} />
        ),
    },
]
