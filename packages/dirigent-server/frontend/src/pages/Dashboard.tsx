import { useCallback, useEffect, type ReactNode } from 'react'

import { useHeartbeat } from '@/hooks/use-heartbeat'
import { Link, useNavigate } from 'react-router'

import { ApiChip } from '@/components/ApiChip'
import { RefreshControl } from '@/components/RefreshControl'
import { RefreshCw } from 'lucide-react'
import { Instant } from '@/components/Instant'
import { HealthPanel } from '@/components/overview/HealthPanel'
import { LOOK_COLUMNS } from '@/components/overview/LookRow'
import { RunsChart } from '@/components/overview/RunsChart'
import { StatTile, TilePlaceholder } from '@/components/overview/TileCard'
import { ListTable, type Column } from '@/components/list/ListTable'
import { PageHeader, PageState } from '@/components/PageState'
import { StatusChip } from '@/components/run/StatusChip'
import { useStore } from '@/hooks/use-store'
import { refreshSeconds } from '@/lib/refresh'
import { useRead } from '@/hooks/use-read'
import { readConnections } from '@/lib/connections'
import {
    healthNote,
    healthRows,
    hourlyRuns,
    liveRuns,
    nextFires,
    readSchedulesAhead,
    statTiles,
    type NextFire,
} from '@/lib/home'
import { headingOf } from '@/lib/identity'
import { DAY, needsALook, TILE_PAGE, withPipelines } from '@/lib/overview'
import { DASHBOARD_GROUP, registerActions } from '@/lib/palette'
import { EVERY_RUN, readRuns, type RunOut } from '@/lib/runs'
import { currentOffset } from '@/lib/times'
import { cn } from '@/lib/utils'
import { readWorkers } from '@/lib/workers'

/**
 * The front door: how this instance is doing, before anybody picks a noun.
 *
 * NO ENDPOINT WAS ADDED FOR THIS SCREEN, AND NONE OF THEM IS ADMIN'S. Every fact here is
 * composed in the browser out of listings the server answers for any account -- the runs
 * listing, the pipelines listing, a pipeline's own schedules, the worker registry and the
 * connections listing -- so an operator sees the whole screen. The admin overview asks these
 * questions and more that do need the role, and what the two screens share is drawn by the same
 * components.
 *
 * EVERY NUMBER AND EVERY SECTION LEAVES. A dashboard's job is to be left, so a tile links to
 * the listing narrowed the way the tile counted, each heading is the screen that owns the noun,
 * and every row is the thing it is about.
 *
 * ONE READ OF THE PIPELINES LISTING SERVES TWO SECTIONS. It is what a failed run's pipeline is
 * called, the step that run died in, and which pipelines are worth asking for schedules.
 *
 * ONE READ OF THE DAY SERVES FOUR TILES AND THE CHART. The window is read once, at the largest
 * page this API answers, and everything about the last 24 hours is counted out of those rows --
 * so no two things on this screen can disagree about a day they both drew from.
 */
export function Dashboard() {
    const day = useRead(useCallback(() => readRuns({ ...EVERY_RUN, since: DAY }, null, TILE_PAGE), []))
    const running = useRead(useCallback(() => readRuns({ ...EVERY_RUN, status: 'running' }, null), []))
    const queued = useRead(useCallback(() => readRuns({ ...EVERY_RUN, status: 'queued' }, null), []))
    const failed = useRead(useCallback(() => readRuns({ ...EVERY_RUN, status: 'failed' }, null), []))
    const messy = useRead(
        useCallback(() => readRuns({ ...EVERY_RUN, status: 'completed_with_errors' }, null), []),
    )
    const ahead = useRead(readSchedulesAhead)
    const workers = useRead(useCallback(() => readWorkers(null), []))
    const connections = useRead(useCallback(() => readConnections(null), []))

    const { again: readDayAgain } = day
    const { again: readRunningAgain } = running
    const { again: readQueuedAgain } = queued
    const { again: readFailedAgain } = failed
    const { again: readMessyAgain } = messy
    const { again: readAheadAgain } = ahead
    const { again: readWorkersAgain } = workers
    const { again: readConnectionsAgain } = connections

    const again = useCallback(() => {
        readDayAgain()
        readRunningAgain()
        readQueuedAgain()
        readFailedAgain()
        readMessyAgain()
        readAheadAgain()
        readWorkersAgain()
        readConnectionsAgain()
    }, [
        readAheadAgain,
        readConnectionsAgain,
        readDayAgain,
        readFailedAgain,
        readMessyAgain,
        readQueuedAgain,
        readRunningAgain,
        readWorkersAgain,
    ])

    useEffect(() => {
        return registerActions([
            {
                id: 'dashboard:refresh',
                title: 'Refresh the dashboard',
                group: DASHBOARD_GROUP,
                screen: true,
                icon: RefreshCw,
                keywords: ['refresh', 'reload', 'home'],
                run: again,
            },
        ])
    }, [again])

    const navigate = useNavigate()
    useHeartbeat(again, useStore(refreshSeconds))

    const live = liveRuns(running.value?.items ?? [], queued.value?.items ?? [])
    const look = withPipelines(
        needsALook(failed.value?.items ?? [], messy.value?.items ?? []),
        ahead.value?.pipelines ?? [],
    )
    const fires = nextFires(ahead.value?.schedules ?? [])
    const tiles = statTiles(day.value, running.value, queued.value)

    // The chart is the day tile's own rows, bucketed here rather than read a second time -- one
    // page of at most `TILE_PAGE` runs, which is the largest this API answers in one request.
    const now = new Date()
    const buckets = hourlyRuns(day.value?.items ?? [], now, currentOffset(now))

    // The panel is drawn where its two listings answered. Both are reads any signed-in account
    // may make, so what decides this is the answer rather than the role -- and an instance that
    // refuses them leaves the chart the whole width instead of a card saying nothing.
    const healthReadable = workers.problem === null && connections.problem === null

    return (
        <>
            <PageHeader
                title="Dashboard"
                aside={
                    <>
                        <ApiChip tag="runs" />
                        <RefreshControl onRefresh={again} />
                    </>
                }
            />

            <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
                {tiles.map((slot) =>
                    slot.tile === null ? (
                        <TilePlaceholder key={slot.id} />
                    ) : (
                        <StatTile key={slot.id} tile={slot.tile} />
                    ),
                )}
            </div>

            <div className="mb-6 grid gap-3 lg:grid-cols-3">
                <div className={cn(healthReadable ? 'lg:col-span-2' : 'lg:col-span-3')}>
                    {day.problem === null ? (
                        <RunsChart buckets={buckets} reading={!day.read} />
                    ) : (
                        <PageState loading={false} problem={day.problem} empty={false}>
                            {null}
                        </PageState>
                    )}
                </div>
                {healthReadable && (
                    <HealthPanel
                        rows={healthRows(workers.value?.items ?? [], connections.value?.items ?? [])}
                        note={healthNote(workers.value?.items ?? [], connections.value?.items ?? [])}
                        reading={!workers.read || !connections.read}
                    />
                )}
            </div>

            <Section title="Right now" to="/runs">
                <PageState
                    loading={!running.read || !queued.read}
                    problem={running.problem ?? queued.problem}
                    empty={live.length === 0}
                    emptyMessage="Nothing is running and nothing is waiting."
                >
                    <ListTable
                        chrome={{ footer: false }}
                        columns={LIVE_COLUMNS}
                        rows={live}
                        rowKey={(run) => run.id}
                        reading={false}
                        next={null}
                        onMore={NOTHING_MORE}
                        noun="runs"
                        onSelect={(run) => void navigate(`/runs/${run.id}`)}
                    />
                </PageState>
            </Section>

            <Section title="Needs a look" to="/runs">
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
            </Section>

            <Section title="Next fires" to="/triggers">
                <PageState
                    loading={!ahead.read}
                    problem={ahead.problem}
                    empty={fires.length === 0}
                    emptyMessage="No schedule is due to fire."
                >
                    <ListTable
                        chrome={{ footer: false }}
                        columns={FIRE_COLUMNS}
                        rows={fires}
                        rowKey={(fire) => `${fire.pipeline}:${fire.schedule.code}`}
                        reading={false}
                        next={null}
                        onMore={NOTHING_MORE}
                        noun="firings"
                        onSelect={(fire) => void navigate(`/pipelines/${encodeURIComponent(fire.pipeline)}`)}
                    />
                </PageState>
            </Section>
        </>
    )
}

/**
 * One section: what it is, the screen that owns it, and the one line saying what is in it.
 *
 * The heading is the link, because a section of a dashboard is a place a reader is on their way
 * out of and a heading that went nowhere would leave them looking for the way.
 */
function Section({ title, to, children }: { title: string; to: string; children: ReactNode }) {
    return (
        <section className="mb-6 space-y-2 last:mb-0">
            <div className="space-y-1">
                <h2 className="text-sm font-semibold">
                    <Link to={to} className="hover:text-primary">
                        {title}
                    </Link>
                </h2>
            </div>
            {children}
        </section>
    )
}

/** A load-more that never fires: these tables show what the read answered and no more. */
const NOTHING_MORE = () => {
    // The dashboard's tables are windows, not walks; the listing screens page.
}

/** The in-flight table's columns: what it is, where it runs, and since when. */
const LIVE_COLUMNS: Column<RunOut>[] = [
    {
        id: 'status',
        header: 'Status',
        cell: (run) => <StatusChip status={run.status} />,
    },
    {
        id: 'pipeline',
        header: 'Pipeline',
        cell: (run) => <span className="font-mono text-sm">{headingOf({ code: run.pipeline }).title}</span>,
    },
    {
        id: 'since',
        header: 'Since',
        className: 'text-right',
        cell: (run) => <Instant className="text-xs text-faint" at={run.started_at ?? run.created_at} />,
    },
]

/** The next-fires table's columns: the pipeline, which of its clocks, and when it goes off. */
const FIRE_COLUMNS: Column<NextFire>[] = [
    {
        id: 'pipeline',
        header: 'Pipeline',
        cell: (fire) => <span className="font-mono text-sm">{headingOf({ code: fire.pipeline }).title}</span>,
    },
    {
        id: 'schedule',
        header: 'Schedule',
        cell: (fire) => {
            const schedule = headingOf(fire.schedule)
            return (
                <span className="flex min-w-0 items-baseline gap-2">
                    <span
                        className={cn('truncate text-xs', schedule.named ? 'text-foreground' : 'font-mono')}
                    >
                        {schedule.title}
                    </span>
                    {schedule.code !== null && (
                        <span className="shrink-0 font-mono text-xs text-muted-foreground">
                            {schedule.code}
                        </span>
                    )}
                </span>
            )
        },
    },
    {
        id: 'fires',
        header: 'Fires',
        className: 'text-right',
        cell: (fire) => <Instant className="text-xs text-faint" at={fire.at} />,
    },
]
