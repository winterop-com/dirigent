import { useNavigate } from 'react-router'
import { useCallback, useEffect } from 'react'

import { ApiChip } from '@/components/ApiChip'
import { RefreshControl } from '@/components/RefreshControl'
import { RefreshCw } from 'lucide-react'
import { AdminOnly } from '@/components/admin/AdminOnly'
import { WorkersTable } from '@/components/admin/WorkersTable'
import { LOOK_COLUMNS } from '@/components/overview/LookRow'
import { ListTable } from '@/components/list/ListTable'
import { TileCard, TilePlaceholder } from '@/components/overview/TileCard'
import { PageHeader, PageState } from '@/components/PageState'
import { usePaged } from '@/hooks/use-paged'
import { useHeartbeat } from '@/hooks/use-heartbeat'
import { useRead } from '@/hooks/use-read'
import { useStore } from '@/hooks/use-store'
import { readConnections } from '@/lib/connections'
import {
    connectionsTile,
    DAY,
    dayTile,
    needsALook,
    nowTile,
    schedulesTile,
    TILE_PAGE,
    withPipelines,
    workersTile,
    type Tile,
} from '@/lib/overview'
import { readPipelines } from '@/lib/pipelines'
import { ADMIN_GROUP, registerActions } from '@/lib/palette'
import { EVERY_RUN, readRuns } from '@/lib/runs'
import { refreshSeconds } from '@/lib/refresh'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { readWorkers, type WorkerOut } from '@/lib/workers'

/** What the status bar states on the right of every admin screen. */

const workerId = (worker: WorkerOut) => worker.id

/**
 * What this instance is doing, and what wants somebody.
 *
 * NO ENDPOINT WAS ADDED FOR THIS SCREEN. Every number is composed in the browser out of
 * listings this API already answers, so a tile cannot disagree with the screen it links to
 * about a number they both draw from the same rows. `lib/overview` holds the composers, and
 * they are pure.
 *
 * EVERY TILE IS A LINK. A dashboard's whole job is to be left, and a number with nowhere to go
 * is a number somebody then has to go and find another way.
 *
 * THE WORKERS TABLE AND THE WORKERS TILE ARE ONE READ. The tile counts the rows the table below
 * it is already holding, rather than asking the registry the same question twice.
 */
/** A load-more that never fires: this table shows what the read answered and no more. */
const NOTHING_MORE = () => {
    // The overview's table is a window, not a walk; the runs screen pages.
}

export function AdminOverview() {
    return (
        <AdminOnly>
            <Overview />
        </AdminOnly>
    )
}

function Overview() {
    const day = useRead(useCallback(() => readRuns({ ...EVERY_RUN, since: DAY }, null, TILE_PAGE), []))
    const failed = useRead(useCallback(() => readRuns({ ...EVERY_RUN, status: 'failed' }, null), []))
    const messy = useRead(
        useCallback(() => readRuns({ ...EVERY_RUN, status: 'completed_with_errors' }, null), []),
    )
    const connections = useRead(useCallback(() => readConnections(null), []))
    // The schedules tile counts off this page, so it asks for as many pipelines as one request
    // answers rather than a table's page.
    const pipelines = useRead(useCallback(() => readPipelines(null, [], TILE_PAGE), []))
    const workers = usePaged(
        useCallback((after: string | null) => readWorkers(after), []),
        workerId,
    )

    const {
        again: readDayAgain,
        value: dayValue,
        problem: dayProblem,
        read: dayRead,
    } = day
    const { again: readFailedAgain } = failed
    const { again: readMessyAgain } = messy
    const { again: readConnectionsAgain } = connections
    const { again: readPipelinesAgain } = pipelines
    const { reload: reloadWorkers } = workers

    const again = useCallback(() => {
        readDayAgain()
        readFailedAgain()
        readMessyAgain()
        readConnectionsAgain()
        readPipelinesAgain()
        reloadWorkers()
    }, [readConnectionsAgain, readDayAgain, readFailedAgain, readMessyAgain, readPipelinesAgain, reloadWorkers])

    const navigate = useNavigate()
    useHeartbeat(again, useStore(refreshSeconds))

    useEffect(() => {
        setScreenStatus({ note: null, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [])

    useEffect(() => {
        return registerActions([
            {
                id: 'admin:reload',
                title: 'Refresh the overview',
                group: ADMIN_GROUP,
                screen: true,
                icon: RefreshCw,
                keywords: ['refresh', 'reload', 'dashboard'],
                run: again,
            },
        ])
    }, [again])

    // Keyed by what the tile is rather than by where it sits, so a tile whose read has not
    // landed holds its own place instead of the row shifting under a reader as each arrives.
    const tiles: { id: string; tile: Tile | null }[] = [
        { id: 'day', tile: dayValue === null ? null : dayTile(dayValue) },
        { id: 'now', tile: dayValue === null ? null : nowTile(dayValue) },
        {
            id: 'workers',
            tile: workers.state.read ? workersTile({ items: workers.state.rows, next: workers.state.next }) : null,
        },
        { id: 'connections', tile: connections.value === null ? null : connectionsTile(connections.value) },
        { id: 'schedules', tile: pipelines.value === null ? null : schedulesTile(pipelines.value) },
    ]

    const look = withPipelines(
        needsALook(failed.value?.items ?? [], messy.value?.items ?? []),
        pipelines.value?.items ?? [],
    )

    return (
        <>
            <PageHeader
                title="Overview"
                aside={
                    <>
                        <ApiChip tag="system" />
                        <RefreshControl onRefresh={again} />
                    </>
                }
            />

            <div className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                {tiles.map((slot) =>
                    slot.tile === null ? <TilePlaceholder key={slot.id} /> : <TileCard key={slot.id} tile={slot.tile} />,
                )}
            </div>

            {dayRead && dayProblem !== null && (
                <PageState loading={false} problem={dayProblem} empty={false}>
                    {null}
                </PageState>
            )}

            <section className="mb-6 space-y-2">
                <div className="space-y-1">
                    <h2 className="text-sm font-semibold">Needs a look</h2>
                    <p className="text-muted-foreground text-sm">
                        Every run that failed or finished with errors, newest first.
                    </p>
                </div>
                <PageState
                    loading={!failed.read || !messy.read}
                    problem={failed.problem ?? messy.problem}
                    empty={look.length === 0}
                    emptyMessage="Nothing has failed or finished with errors."
                >
                    <ListTable
                        chrome={{ footer: false }}
                        columns={LOOK_COLUMNS}
                        rows={look}
                        rowKey={(entry) => entry.run.id}
                        reading={false}
                        next={null}
                        onMore={NOTHING_MORE}
                        noun="runs"
                        onSelect={(entry) => void navigate(`/runs/${entry.run.id}`)}
                    />
                </PageState>
            </section>

            <section className="space-y-2">
                <h2 className="text-sm font-semibold">Workers</h2>
                <WorkersTable
                    state={workers.state}
                    more={workers.more}
                    empty="No workers. Start one with dg worker; nothing is claimed until one registers."
                />
            </section>
        </>
    )
}
