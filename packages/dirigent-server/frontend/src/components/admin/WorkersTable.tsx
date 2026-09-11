import { ListTable, type Column } from '@/components/list/ListTable'
import { PageState } from '@/components/PageState'
import { StatusChip } from '@/components/run/StatusChip'
import { Badge } from '@/components/ui/badge'
import { formatInstant, formatRelative } from '@/lib/format'
import type { Paged } from '@/lib/paging'
import { anyTagged, type WorkerOut } from '@/lib/workers'

/** What one row is keyed by. A worker's name is its identity in the registry. */
const workerId = (worker: WorkerOut) => worker.id

/**
 * The nodes claiming work, drawn once and shown in two places.
 *
 * A WORKER STATE IS NOT A RUN STATE, and it is drawn in the same chip anyway: `running` indexes
 * a status token and `starting`, `draining` and `stopped` fall back to the neutral pair, which
 * is what `lib/status` does with any state this bundle has no colour for. The alternative was a
 * second chip that had to be kept level with the first.
 *
 * TWO WARNINGS SIT BESIDE THE STATE, because neither is a state. A worker the server has
 * stopped hearing from still says `running`, and the fact worth reading is how long ago it was
 * last seen; a worker whose catalog is not this server's answers perfectly well and will run
 * something other than what this server thinks it will.
 */
export function WorkersTable({
    state,
    more,
    empty,
}: {
    state: Paged<WorkerOut>
    more: () => void
    /** The line the empty card states, which differs between the dashboard and the screen. */
    empty: string
}) {
    return (
        <PageState
            loading={!state.read}
            problem={state.problem}
            empty={state.rows.length === 0}
            emptyMessage={empty}
        >
            <ListTable
                columns={columnsFor(state.rows)}
                rows={state.rows}
                rowKey={workerId}
                rowClassName={(worker) => (worker.status === 'stopped' ? 'opacity-60' : undefined)}
                reading={state.reading}
                next={state.next}
                onMore={more}
                noun="workers"
            />
        </PageState>
    )
}

/**
 * The columns this listing draws, which is every column plus Tags when a tag exists.
 *
 * An instance that never routes by tag has a column of dashes to read past otherwise.
 */
function columnsFor(workers: readonly WorkerOut[]): Column<WorkerOut>[] {
    return anyTagged(workers) ? COLUMNS : COLUMNS.filter((column) => column.id !== 'tags')
}

const COLUMNS: Column<WorkerOut>[] = [
    {
        id: 'name',
        header: 'Worker',
        cell: (worker) => <span className="text-sm font-medium">{worker.name}</span>,
    },
    {
        id: 'hostname',
        header: 'Host',
        className: 'font-mono text-xs',
        cell: (worker) => <span className="text-muted-foreground">{worker.hostname}</span>,
    },
    {
        id: 'version',
        header: 'Version',
        className: 'font-mono text-xs',
        cell: (worker) => <span className="text-muted-foreground">{worker.version}</span>,
    },
    {
        id: 'status',
        header: 'Status',
        cell: (worker) => (
            <span className="flex flex-wrap items-center gap-2">
                <StatusChip status={worker.status} />
                {worker.stale && (
                    <span className="text-xs text-warning" title={formatInstant(worker.last_seen_at)}>
                        last seen {formatRelative(worker.last_seen_at)}
                    </span>
                )}
                {!worker.code_matches_server && (
                    <Badge
                        variant="destructive"
                        title={worker.catalog_digest ?? 'no catalog digest reported'}
                    >
                        different catalog
                    </Badge>
                )}
            </span>
        ),
    },
    {
        id: 'concurrency',
        header: 'Concurrency',
        className: 'text-right font-mono text-xs',
        cell: (worker) => <span>{worker.concurrency}</span>,
    },
    {
        id: 'tags',
        header: 'Tags',
        cell: (worker) =>
            worker.tags.length === 0 ? null : (
                <span className="flex flex-wrap gap-1">
                    {worker.tags.map((tag) => (
                        <Badge key={tag} variant="outline">
                            {tag}
                        </Badge>
                    ))}
                </span>
            ),
    },
    {
        id: 'seen',
        header: 'Last seen',
        className: 'text-xs',
        cell: (worker) => (
            <span className="text-muted-foreground" title={formatInstant(worker.last_seen_at)}>
                {formatRelative(worker.last_seen_at)}
            </span>
        ),
    },
]
