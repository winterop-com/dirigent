import { CalendarPlus, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { ApiChip } from '@/components/ApiChip'
import { ListTable, type Column } from '@/components/list/ListTable'
import { PageHeader, PageState } from '@/components/PageState'
import { PipelineRef } from '@/components/PipelineRef'
import { Chip, Clock, Dot, NextFire, OwnerChip } from '@/components/triggers/marks'
import { MintedToken, NewSchedule } from '@/components/triggers/NewTrigger'
import { SchedulePanel, SourcePanel } from '@/components/triggers/TriggerPanel'
import { useMayWrite } from '@/hooks/use-may-write'
import { usePaged } from '@/hooks/use-paged'
import { formatInstant, formatRelative } from '@/lib/format'
import { headingOf, type Addressable } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import { closePanel, fillPanel, openPanel } from '@/lib/panels'
import { LIST_GROUP, registerActions } from '@/lib/palette'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import {
    listensTo,
    readSourcePage,
    sourceId,
    stateView,
    type SourceOut,
    type SourceTokenOut,
} from '@/lib/sources'
import { cn } from '@/lib/utils'
import {
    firingView,
    nextFireView,
    readSchedulePage,
    scheduleId,
    type ScheduleOut,
    type ScheduleRow,
} from '@/lib/triggers'

/**
 * Everything that fires a pipeline without a person: the sources a pipeline listens on, and
 * the clocks.
 *
 * SOURCES ARE READ ON THEIR OWN CURSOR. `/sources` lists every source on the instance, so that
 * section pages by itself; the schedules section pages over the pipelines walk below.
 *
 * SCHEDULES ARE A WALK OVER PIPELINES. This API has no listing of every schedule on the
 * instance -- a schedule hangs off the pipeline it fires -- so the screen walks pipelines and
 * reads the schedules of the ones the pipelines listing already counted at least one of.
 *
 * MANAGED IS NOT A LOCK, IT IS A SOURCE. A trigger a document declared changes when that
 * document is applied again, and the chip says so; whether it is paused is the instance's,
 * and that is the verb the panel offers.
 */
export function Triggers() {
    const [chosen, setChosen] = useState<string | null>(null)
    const [creating, setCreating] = useState<'schedule' | null>(null)
    const [minted, setMinted] = useState<SourceTokenOut | null>(null)
    // What a verb has since made of a row, over the page it was read on.
    const [fresher, setFresher] = useState<Record<string, ScheduleRow>>({})

    const { state, more, reload } = usePaged(readSchedulePage, scheduleId)
    const listed = usePaged(readSourcePage, sourceId)
    const reloadSources = listed.reload
    const [chosenSource, setChosenSource] = useState<string | null>(null)
    const [fresherSources, setFresherSources] = useState<Record<string, SourceOut>>({})
    const sources = useMemo(
        () => listed.state.rows.map((row) => fresherSources[sourceId(row)] ?? row),
        [fresherSources, listed.state.rows],
    )
    const openSource = sources.find((row) => sourceId(row) === chosenSource) ?? null

    const schedules = useMemo(
        () => state.rows.map((row) => fresher[scheduleId(row)] ?? row),
        [fresher, state.rows],
    )
    const scheduleCols = useMemo(() => scheduleColumns(schedules), [schedules])
    const open = schedules.find((row) => scheduleId(row) === chosen) ?? null

    const held = useCallback((row: ScheduleRow) => {
        setFresher((current) => ({ ...current, [scheduleId(row)]: row }))
    }, [])

    useEffect(() => {
        setScreenStatus({ note: null, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [])

    useEffect(() => {
        if (openSource === null) return
        return fillPanel(
            [
                {
                    id: 'source',
                    label: LABELS.word.input_source.label,
                    render: () => (
                        <SourcePanel
                            source={openSource}
                            pipelineName={null}
                            onChanged={(row: SourceOut) => {
                                setFresherSources((current) => ({
                                    ...current,
                                    [sourceId(row)]: row,
                                }))
                            }}
                            onMinted={setMinted}
                        />
                    ),
                },
            ],
            { screen: 'triggers' },
        )
    }, [openSource])

    useEffect(() => {
        if (open === null) return
        return fillPanel(
            [
                {
                    id: 'trigger',
                    label: LABELS.word.schedule.label,
                    render: () => (
                        <SchedulePanel
                            pipeline={open.pipeline}
                            pipelineName={open.pipelineName}
                            schedule={open.schedule}
                            onChanged={(schedule: ScheduleOut) => {
                                held({ ...open, schedule })
                            }}
                        />
                    ),
                },
            ],
            { screen: 'triggers' },
        )
    }, [held, open])

    const write = useMayWrite()
    const mayWrite = write.may

    useEffect(() => {
        return registerActions([
            // A row this account's role would be refused is a row the palette does not offer.
            ...(mayWrite
                ? [
                      {
                          id: 'triggers:schedule',
                          title: LABELS.triggers.schedule.new,
                          group: LIST_GROUP,
                          screen: true,
                          icon: CalendarPlus,
                          keywords: ['cron', 'interval', 'clock', 'create'],
                          run: () => {
                              setCreating('schedule')
                          },
                      },
                  ]
                : []),
            {
                id: 'triggers:reload',
                title: LABELS.triggers.reload,
                group: LIST_GROUP,
                screen: true,
                icon: RefreshCw,
                keywords: ['refresh', 'reload'],
                run: () => {
                    reload()
                    reloadSources()
                },
            },
        ])
    }, [mayWrite, reload, reloadSources])

    const select = (row: ScheduleRow) => {
        setChosenSource(null)
        setChosen(scheduleId(row))
        openPanel()
    }

    const selectSource = (row: SourceOut) => {
        setChosen(null)
        setChosenSource(sourceId(row))
        openPanel()
    }

    /** What taking the open row back means here, whichever of the two listings it is in. */
    const unchoose = () => {
        setChosen(null)
        setChosenSource(null)
        closePanel()
    }

    return (
        <>
            <PageHeader
                title={LABELS.screen.triggers.name}
                aside={<ApiChip tag="triggers" />}
                actions={[
                    {
                        id: 'schedule',
                        label: LABELS.triggers.schedule.new,
                        icon: CalendarPlus,
                        disabled: !write.may,
                        why: write.why,
                        onClick: () => {
                            setCreating('schedule')
                        },
                    },
                ]}
            />

            <PageState
                loading={!state.read || !listed.state.read}
                problem={state.problem ?? listed.state.problem}
                empty={schedules.length === 0 && sources.length === 0}
                emptyMessage={LABELS.triggers.empty}
            >
                <div className="space-y-6">
                    <section className="space-y-2">
                        <h2 className="text-sm font-semibold">{LABELS.word.input_source.heading}</h2>
                        {sources.length === 0 ? (
                            <p className="text-sm text-muted-foreground">{LABELS.triggers.source.empty}</p>
                        ) : (
                            <ListTable
                                columns={sourceColumns(sources)}
                                rows={sources}
                                rowKey={sourceId}
                                reading={listed.state.reading}
                                next={listed.state.next}
                                onMore={listed.more}
                                noun={LABELS.word.input_source.count}
                                onSelect={selectSource}
                                selected={(row) => sourceId(row) === chosenSource}
                                onClose={unchoose}
                            />
                        )}
                    </section>

                    <section className="space-y-2">
                        <h2 className="text-sm font-semibold">{LABELS.word.schedule.heading}</h2>
                        {schedules.length === 0 ? (
                            <p className="text-sm text-muted-foreground">{LABELS.triggers.schedule.empty}</p>
                        ) : (
                            <ListTable
                                columns={scheduleCols}
                                rows={schedules}
                                rowKey={scheduleId}
                                reading={state.reading}
                                next={state.next}
                                onMore={more}
                                noun={LABELS.word.schedule.count}
                                onSelect={select}
                                selected={(row) => scheduleId(row) === chosen}
                                onClose={unchoose}
                            />
                        )}
                    </section>
                </div>
            </PageState>

            <NewSchedule
                open={creating === 'schedule'}
                onOpenChange={(next) => {
                    setCreating(next ? 'schedule' : null)
                }}
                onCreated={reload}
            />
            {minted !== null && (
                <MintedToken
                    token={minted}
                    onClose={() => {
                        setMinted(null)
                    }}
                />
            )}
        </>
    )
}

const SOURCE_COLUMNS: Column<SourceOut>[] = [
    {
        id: 'source',
        header: LABELS.word.input_source.label,
        kind: 'title',
        cell: (row) => <Titled thing={row}>{null}</Titled>,
    },
    {
        id: 'pipeline',
        header: LABELS.word.pipeline.label,
        kind: 'prose',
        cell: (row) => <PipelineRef code={row.pipeline} name={null} />,
    },
    {
        id: 'listens',
        header: LABELS.triggers.source.listens,
        kind: 'prose',
        className: 'font-mono text-xs',
        cell: (row) => {
            const listens = listensTo(row)
            return listens === null ? (
                <span className="text-muted-foreground">{row.kind}</span>
            ) : (
                <span className="block truncate" title={listens}>
                    {listens}
                </span>
            )
        },
    },
    {
        id: 'state',
        header: LABELS.word.state,
        className: 'text-xs',
        cell: (row) => {
            const view = stateView(row)
            return (
                <span className="flex items-center gap-2">
                    <Dot tone={view.tone} />
                    {view.label}
                </span>
            )
        },
    },
    {
        id: 'in_flight',
        header: LABELS.word.in_flight.heading,
        className: 'text-right font-mono text-xs',
        cell: (row) =>
            row.in_flight === 0 && row.max_in_flight === null ? null : (
                <span className="text-muted-foreground">
                    {row.max_in_flight === null
                        ? String(row.in_flight)
                        : LABELS.triggers.source.bounded(String(row.in_flight), String(row.max_in_flight))}
                </span>
            ),
    },
    {
        id: 'last',
        header: LABELS.triggers.source.last_input,
        className: 'text-xs',
        cell: (row) =>
            row.last_input_at === null ? (
                <span className="text-faint">{LABELS.word.never}</span>
            ) : (
                <span className="text-muted-foreground" title={formatInstant(row.last_input_at)}>
                    {formatRelative(row.last_input_at)}
                </span>
            ),
    },
]

/** The source columns, leaving out In flight where no row has a run in flight or a bound on them. */
function sourceColumns(rows: readonly SourceOut[]): Column<SourceOut>[] {
    if (rows.some((row) => row.in_flight > 0 || row.max_in_flight !== null)) return SOURCE_COLUMNS
    return SOURCE_COLUMNS.filter((column) => column.id !== 'in_flight')
}

const SCHEDULE_COLUMNS: Column<ScheduleRow>[] = [
    {
        id: 'schedule',
        header: LABELS.word.schedule.label,
        kind: 'title',
        cell: (row) => (
            <Titled thing={row.schedule}>
                <OwnerChip managed={row.schedule.managed} document={row.schedule.trigger_document} />
                {row.schedule.paused && <Chip>{LABELS.state.armed.paused}</Chip>}
            </Titled>
        ),
    },
    {
        id: 'pipeline',
        header: LABELS.word.pipeline.label,
        kind: 'prose',
        cell: (row) => <PipelineRef code={row.pipeline} name={row.pipelineName} />,
    },
    {
        id: 'clock',
        header: LABELS.word.clock,
        cell: (row) => <Clock schedule={row.schedule} />,
    },
    {
        id: 'timezone',
        header: LABELS.word.timezone,
        className: 'text-xs',
        cell: (row) => <span className="text-muted-foreground">{row.schedule.timezone}</span>,
    },
    {
        id: 'next',
        header: LABELS.word.next,
        className: 'text-xs',
        // The paused chip in the title cell already says why there is no instant.
        cell: (row) =>
            nextFireView(row.schedule).kind === 'paused' ? null : <NextFire schedule={row.schedule} />,
    },
    {
        id: 'last',
        header: LABELS.word.firing.last,
        cell: (row) => <LastFiring row={row} />,
    },
]

/** The schedule columns, leaving out Next where every row is paused and so has none. */
function scheduleColumns(rows: readonly ScheduleRow[]): Column<ScheduleRow>[] {
    if (rows.some((row) => nextFireView(row.schedule).kind !== 'paused')) return SCHEDULE_COLUMNS
    return SCHEDULE_COLUMNS.filter((column) => column.id !== 'next')
}

/**
 * One trigger's lead cell: the title on one line, and beneath it the code when the title is a
 * name, who declared it, and any state it is in. Two lines at most, so a row's height never
 * depends on how many chips it wears.
 */
function Titled({ thing, children }: { thing: Addressable; children: ReactNode }) {
    const heading = headingOf(thing)
    return (
        <span className="flex min-w-0 flex-col gap-1">
            <span
                className={cn('truncate', heading.named ? 'font-semibold' : 'font-mono font-semibold')}
                title={heading.title}
            >
                {heading.title}
            </span>
            <span className="flex min-w-0 items-center gap-2">
                {heading.code !== null && (
                    <span className="truncate font-mono text-xs text-muted-foreground" title={heading.code}>
                        {heading.code}
                    </span>
                )}
                {children}
            </span>
        </span>
    )
}

/** When a schedule last fired, and what came of that firing. */
function LastFiring({ row }: { row: ScheduleRow }) {
    if (row.schedule.last_fired_at === null)
        return <span className="text-xs text-faint">{LABELS.word.never}</span>
    const view = row.latest === null ? null : firingView(row.latest)
    return (
        <span className="flex items-center gap-2 text-xs">
            {view !== null && <Dot tone={view.tone} />}
            <span className="text-muted-foreground" title={formatInstant(row.schedule.last_fired_at)}>
                {formatRelative(row.schedule.last_fired_at)}
            </span>
            {view !== null && <span>{view.label}</span>}
            {view !== null && view.runId !== null && (
                <Link
                    className="font-mono text-primary-ink hover:underline"
                    to={`/runs/${view.runId}`}
                    onClick={(event) => {
                        event.stopPropagation()
                    }}
                >
                    {LABELS.word.run.term}
                </Link>
            )}
            {view !== null && view.detail !== null && (
                <span className="max-w-48 truncate text-muted-foreground" title={view.detail}>
                    {view.detail}
                </span>
            )}
        </span>
    )
}
