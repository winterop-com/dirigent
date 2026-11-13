import { Instant } from '@/components/Instant'
import { refusedTable } from '@/components/Refusal'
import { DataTable, type DataColumn } from '@winterop-com/sokkel-ui/DataTable'
import { StatusChip } from '@winterop-com/sokkel-ui/StatusChip'
import { Chip } from '@winterop-com/sokkel-ui/Chip'
import { LISTING } from '@/lib/library-words'
import { formatInstant, formatRelative } from '@/lib/format'
import { LABELS } from '@/lib/labels'
import { rowsRead, type Paged } from '@/lib/paging'
import { anyTagged, type WorkerOut } from '@/lib/workers'

/** What one row is keyed by. A worker's name is its identity in the registry. */
const workerId = (worker: WorkerOut) => worker.id

/**
 * The nodes claiming work, read a page at a time; a refused read stands in place of the rows,
 * with Try again.
 *
 * A WORKER STATE IS NOT A RUN STATE, and it is drawn in the same chip anyway: `running` indexes
 * a status color and `starting`, `draining` and `stopped` fall back to the neutral one, which
 * is what the status parts do with any state `lib/status` has no color for. The alternative was a
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
    reload,
}: {
    state: Paged<WorkerOut>
    more: () => void
    reload: () => void
}) {
    const rows = state.problem === null ? state.rows : []
    return (
        <DataTable
            {...LISTING}
            rowHeight="auto"
            columns={columnsFor(rows)}
            rows={rows}
            rowKey={workerId}
            rowTone={(worker) => (worker.status === 'stopped' ? 'muted' : undefined)}
            hasMore={state.problem === null && state.next !== null}
            loading={state.reading}
            onLoadMore={more}
            {...refusedTable(state.problem, reload)}
            foot={
                rows.length === 0
                    ? undefined
                    : rowsRead(rows.length, LABELS.word.worker.count, state.next !== null)
            }
            empty={LABELS.workers.empty}
        />
    )
}

/**
 * The columns this listing draws, which is every column plus Tags when a tag exists.
 *
 * An instance that never routes by tag has a column of dashes to read past otherwise. The
 * worker's name is capped at what the other columns leave it at `lg`, less where Tags is drawn.
 */
function columnsFor(workers: readonly WorkerOut[]): DataColumn<WorkerOut>[] {
    if (anyTagged(workers)) return [{ ...NAME, maxWidth: '15rem' }, ...COLUMNS]
    return [{ ...NAME, maxWidth: '20rem' }, ...COLUMNS.filter((column) => column.id !== 'tags')]
}

const NAME: DataColumn<WorkerOut> = {
    id: 'name',
    header: LABELS.word.worker.label,
    width: 'content',
    cell: (worker) => (
        <span className="block truncate font-mono text-sm font-medium" title={worker.name}>
            {worker.name}
        </span>
    ),
}

const COLUMNS: DataColumn<WorkerOut>[] = [
    {
        id: 'hostname',
        header: LABELS.word.host,
        width: 'minmax(4rem,1fr)',
        cell: (worker) => (
            <span className="block truncate font-mono text-xs text-muted-foreground" title={worker.hostname}>
                {worker.hostname}
            </span>
        ),
    },
    {
        id: 'version',
        header: LABELS.word.version.label,
        width: 'minmax(3.5rem,1fr)',
        cell: (worker) => <span className="font-mono text-xs text-muted-foreground">{worker.version}</span>,
    },
    {
        id: 'status',
        header: LABELS.word.status,
        width: 'minmax(5.5rem,1fr)',
        cell: (worker) => (
            <span className="flex flex-wrap items-center gap-2">
                <StatusChip status={worker.status} />
                {worker.stale && (
                    <span className="text-xs text-warning" title={formatInstant(worker.last_seen_at)}>
                        {LABELS.workers.last_seen_ago(formatRelative(worker.last_seen_at))}
                    </span>
                )}
                {!worker.code_matches_server && (
                    <Chip tone="critical" title={worker.catalog_digest ?? LABELS.workers.no_digest}>
                        {LABELS.workers.mismatch_badge}
                    </Chip>
                )}
            </span>
        ),
    },
    {
        id: 'concurrency',
        header: LABELS.word.concurrency,
        width: 'minmax(5rem,1fr)',
        align: 'end',
        cell: (worker) => <span className="font-mono text-xs">{worker.concurrency}</span>,
    },
    {
        id: 'tags',
        header: LABELS.word.tags,
        width: 'minmax(4.5rem,1fr)',
        cell: (worker) =>
            worker.tags.length === 0 ? null : (
                <span className="flex flex-wrap gap-1">
                    {worker.tags.map((tag) => (
                        <Chip key={tag} tone="outline" mono>
                            {tag}
                        </Chip>
                    ))}
                </span>
            ),
    },
    {
        id: 'seen',
        header: LABELS.word.last_seen,
        width: 'minmax(4rem,1fr)',
        cell: (worker) => <Instant className="text-xs text-muted-foreground" at={worker.last_seen_at} />,
    },
]
