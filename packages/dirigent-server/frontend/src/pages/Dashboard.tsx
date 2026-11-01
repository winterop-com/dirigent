import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { RefreshCw } from 'lucide-react'
import { Link } from 'react-router'

import { ApiChip } from '@/components/ApiChip'
import { Code } from '@/components/ds/Code'
import { PageHeader } from '@/components/ds/PageHeader'
import { Panel } from '@/components/ds/Panel'
import { TextLink } from '@/components/ds/TextLink'
import { MiniGraph } from '@/components/graph/MiniGraph'
import { Instant } from '@/components/Instant'
import { HealthPanel } from '@/components/overview/HealthPanel'
import { RunsChart } from '@/components/overview/RunsChart'
import { PageState } from '@/components/PageState'
import { RefreshControl } from '@/components/RefreshControl'
import { StatusChip, StatusDot } from '@/components/run/StatusChip'
import { useHeartbeat } from '@/hooks/use-heartbeat'
import { useRead } from '@/hooks/use-read'
import { useStore } from '@/hooks/use-store'
import { readConnections } from '@/lib/connections'
import { elapsedBetween, formatDuration } from '@/lib/format'
import {
    healthNote,
    healthRows,
    hourlyRuns,
    liveRuns,
    medianDurations,
    nextFires,
    readSchedulesAhead,
} from '@/lib/home'
import { headingOf } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import { kindMarks } from '@/lib/marks'
import { DAY, needsALook, TILE_PAGE, withPipelines, type LookEntry } from '@/lib/overview'
import { DASHBOARD_GROUP, registerActions } from '@/lib/palette'
import { refreshSeconds } from '@/lib/refresh'
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
 * connections listing -- so an operator sees the whole screen.
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
    const marks = useStore(kindMarks)
    const day = useRead(
        useCallback(async () => {
            const page = await readRuns({ ...EVERY_RUN, since: DAY }, null, TILE_PAGE)
            return { page, at: new Date() }
        }, []),
    )
    const [opened] = useState(() => new Date())
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
                title: LABELS.dashboard.refresh,
                group: DASHBOARD_GROUP,
                screen: true,
                icon: RefreshCw,
                keywords: ['refresh', 'reload', 'home'],
                run: again,
            },
        ])
    }, [again])

    useHeartbeat(again, useStore(refreshSeconds))

    const live = liveRuns(running.value?.items ?? [], queued.value?.items ?? [])
    const look = withPipelines(
        needsALook(failed.value?.items ?? [], messy.value?.items ?? []),
        ahead.value?.pipelines ?? [],
    )
    const fires = nextFires(ahead.value?.schedules ?? [])
    const names = new Map((ahead.value?.pipelines ?? []).map((row) => [row.code, row.name]))
    const dayRuns = day.value?.page.items ?? []
    const durations = medianDurations(dayRuns)
    const recent = dayRuns.slice(0, RECENT_ROWS)

    // The chart is the day's own rows, bucketed here rather than read a second time -- one page of
    // at most `TILE_PAGE` runs, which is the largest this API answers in one request. Its hours end
    // when those rows were read, not when the screen last rendered.
    const now = day.value?.at ?? opened
    const buckets = hourlyRuns(dayRuns, now, currentOffset(now))

    // The panel is drawn where its two listings answered. Both are reads any signed-in account
    // may make, so what decides this is the answer rather than the role -- and an instance that
    // refuses them leaves the chart the whole width instead of a card saying nothing.
    const healthReadable = workers.problem === null && connections.problem === null

    return (
        <>
            <PageHeader
                title={LABELS.screen.dashboard.name}
                aside={
                    <>
                        <ApiChip tag="runs" />
                        <RefreshControl onRefresh={again} />
                    </>
                }
            />

            {(failed.problem !== null || messy.problem !== null || look.length > 0) && (
                <Section title={LABELS.dashboard.troubled_runs} to="/runs" count={look.length}>
                    <PageState
                        loading={!failed.read || !messy.read}
                        problem={failed.problem ?? messy.problem}
                        empty={false}
                    >
                        {look.map((entry) => (
                            <TroubledRow key={entry.run.id} entry={entry} />
                        ))}
                    </PageState>
                </Section>
            )}

            <div className="mb-8 grid items-start gap-5 xl:grid-cols-[1.35fr_1fr]">
                <div className={cn('flex min-w-0 flex-col gap-5', !healthReadable && 'xl:col-span-2')}>
                    {day.problem === null ? (
                        <RunsChart buckets={buckets} reading={!day.read} />
                    ) : (
                        <PageState loading={false} problem={day.problem} empty={false}>
                            {null}
                        </PageState>
                    )}
                    {durations.length > 0 && (
                        <Panel
                            title={LABELS.dashboard.durations.title}
                            meta={LABELS.dashboard.durations.median}
                            bodyClassName="py-1"
                        >
                            <div>
                                {durations.map((row) => (
                                    <Link
                                        key={row.pipeline}
                                        to={`/pipelines/${encodeURIComponent(row.pipeline)}`}
                                        className="flex items-baseline gap-3 border-t border-border py-2 text-sm first:border-t-0 hover:underline"
                                    >
                                        <PipelineTitle
                                            code={row.pipeline}
                                            name={names.get(row.pipeline) ?? null}
                                        />
                                        <span className="w-16 shrink-0 text-right font-mono text-xs font-medium">
                                            {formatDuration(row.median_ms)}
                                        </span>
                                    </Link>
                                ))}
                            </div>
                        </Panel>
                    )}
                </div>
                {healthReadable && (
                    <HealthPanel
                        rows={healthRows(workers.value?.items ?? [], connections.value?.items ?? [], marks)}
                        note={healthNote(workers.value?.items ?? [], connections.value?.items ?? [])}
                        reading={!workers.read || !connections.read}
                    />
                )}
            </div>

            {live.length > 0 && (
                <Section title={LABELS.word.in_flight.heading} to="/runs" count={live.length}>
                    {live.map((run) => (
                        <RecentRow key={run.id} run={run} name={names.get(run.pipeline) ?? null} />
                    ))}
                </Section>
            )}

            {recent.length > 0 && (
                <Section title={LABELS.dashboard.recent_runs} to="/runs" link={LABELS.dashboard.all_runs}>
                    {recent.map((run) => (
                        <RecentRow key={run.id} run={run} name={names.get(run.pipeline) ?? null} />
                    ))}
                </Section>
            )}

            {fires.length > 0 && (
                <Section title={LABELS.dashboard.next_firings} to="/triggers">
                    {fires.map((fire) => {
                        const schedule = headingOf(fire.schedule)
                        return (
                            <Link
                                key={`${fire.pipeline}:${fire.schedule.code}`}
                                to={`/pipelines/${encodeURIComponent(fire.pipeline)}`}
                                className="flex items-center gap-4 border-t border-border px-5 py-2.5 first:border-t-0 hover:bg-muted"
                            >
                                <PipelineTitle code={fire.pipeline} name={names.get(fire.pipeline) ?? null} />
                                <span className="min-w-0 truncate text-xs text-muted-foreground">
                                    {schedule.title}
                                </span>
                                <Instant
                                    className="w-18 shrink-0 text-right text-xs text-muted-foreground"
                                    at={fire.at}
                                />
                            </Link>
                        )
                    })}
                </Section>
            )}
        </>
    )
}

/** How many runs the recent-runs list draws; the runs screen holds the rest. */
const RECENT_ROWS = 6

/**
 * One section: what it is, the screen that owns it, and how many it holds.
 *
 * The heading is the link, because a section of a dashboard is a place a reader is on their way
 * out of and a heading that went nowhere would leave them looking for the way.
 */
function Section({
    title,
    to,
    count,
    link,
    children,
}: {
    title: string
    to: string
    count?: number
    link?: string
    children: ReactNode
}) {
    return (
        <Panel
            className="mb-6 last:mb-0"
            inset={false}
            title={
                <Link to={to} className="hover:underline">
                    {title}
                </Link>
            }
            meta={count === undefined ? undefined : String(count)}
            aside={
                link === undefined ? undefined : (
                    <TextLink variant="aside" to={to} className="text-xs font-normal">
                        {link}
                    </TextLink>
                )
            }
        >
            {children}
        </Panel>
    )
}

/** A pipeline headed the way every screen heads one, on one line that truncates. */
function PipelineTitle({ code, name }: { code: string; name: string | null }) {
    return (
        <span className="flex min-w-0 flex-1 items-baseline gap-2.5">
            <span
                className={cn('min-w-0 truncate', name === null && 'font-mono text-xs')}
                title={name ?? code}
            >
                {name ?? code}
            </span>
            {name !== null && <Code value={code} className="shrink" />}
        </span>
    )
}

/** A run that needs a look: its pipeline's shape with the failed step filled, and what it said. */
function TroubledRow({ entry }: { entry: LookEntry }) {
    const { run } = entry
    return (
        <Link
            to={`/runs/${run.id}`}
            className="flex flex-wrap items-center gap-x-7 gap-y-3 border-t border-border px-5 py-4 first:border-t-0 hover:bg-muted"
        >
            <div className="flex h-13 w-59 shrink-0 items-center overflow-hidden">
                <MiniGraph steps={entry.shape} failed={entry.failedStep} width={236} height={52} />
            </div>
            <div className="min-w-0 flex-[999_1_320px]">
                <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-0.5">
                    <span
                        className={cn(
                            'min-w-0 truncate text-title font-semibold',
                            entry.name === null && 'font-mono',
                        )}
                    >
                        {entry.name ?? run.pipeline}
                    </span>
                    {entry.name !== null && <Code value={run.pipeline} />}
                </div>
                {(entry.failedStep !== null || run.error !== null) && (
                    <p className="mt-1.5 text-sm break-words">
                        {entry.failedStep !== null && (
                            <Code value={entry.failedStep} tone="body" className="font-medium" />
                        )}
                        {entry.failedStep !== null && run.error !== null && (
                            <span className="text-muted-foreground"> · </span>
                        )}
                        {run.error}
                    </p>
                )}
                <div className="mt-2 flex flex-wrap items-center gap-x-3.5 gap-y-1.5 text-xs">
                    <StatusChip status={run.status} />
                    <Instant
                        className="text-muted-foreground"
                        at={run.finished_at ?? run.started_at ?? run.created_at}
                    />
                    {run.error_code !== null && <Code value={run.error_code} />}
                </div>
            </div>
        </Link>
    )
}

/** A run on one line: its state as a dot, its pipeline, how long it took, and when. */
function RecentRow({ run, name }: { run: RunOut; name: string | null }) {
    const took = elapsedBetween(run.started_at, run.finished_at)
    return (
        <Link
            to={`/runs/${run.id}`}
            className="flex items-center gap-4 border-t border-border px-5 py-2.5 first:border-t-0 hover:bg-muted"
        >
            <StatusDot status={run.status} />
            <PipelineTitle code={run.pipeline} name={name} />
            <span className="w-16 shrink-0 text-right font-mono text-xs text-muted-foreground">
                {took === null ? null : formatDuration(took)}
            </span>
            <Instant
                className="w-18 shrink-0 text-right text-xs text-muted-foreground"
                at={run.started_at ?? run.created_at}
            />
        </Link>
    )
}
