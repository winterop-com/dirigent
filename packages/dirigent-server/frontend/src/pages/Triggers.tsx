import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { ApiChip } from '@/components/ApiChip'
import { Instant } from '@/components/Instant'
import { PageHeader } from '@/components/ds/PageHeader'
import { SECTION_LISTING, shutWith } from '@/lib/design-system'
import { DataTable, useTableCell, type DataColumn } from '@winterop-com/sokkel-ui/DataTable'
import { ItemHeading } from '@winterop-com/sokkel-ui/ItemHeading'
import { Section } from '@winterop-com/sokkel-ui/Section'
import { TextLink } from '@winterop-com/sokkel-ui/TextLink'
import { PageState } from '@/components/PageState'
import { PipelineRef } from '@/components/PipelineRef'
import { Chip, Clock, Dot, NextFire, OwnerChip } from '@/components/triggers/marks'
import { NewSchedule } from '@/components/triggers/NewTrigger'
import { SchedulePanel, SourcePanel } from '@/components/triggers/TriggerPanel'
import { useMayWrite } from '@/hooks/use-may-write'
import { usePaged } from '@/hooks/use-paged'
import { useRowPress } from '@/hooks/use-row-press'
import { ICONS } from '@/lib/icons'
import { headingOf, itemOf, type Addressable } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import { closePanel, fillPanel, openPanel } from '@/lib/panels'
import { rowsRead } from '@/lib/paging'
import { LIST_GROUP, registerActions } from '@/lib/palette'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { listensTo, readSourcePage, sourceId, stateView, type SourceOut } from '@/lib/sources'
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
                          icon: ICONS.create_schedule,
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
                icon: ICONS.refresh,
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

    const pressSource = useRowPress(selectSource, (row) => sourceId(row) === chosenSource, unchoose)
    const pressSchedule = useRowPress(select, (row) => scheduleId(row) === chosen, unchoose)

    return (
        <>
            <PageHeader
                title={LABELS.screen.triggers.name}
                lead={<ApiChip tag="triggers" />}
                primary={{
                    id: 'schedule',
                    label: LABELS.triggers.schedule.new,
                    icon: <ICONS.create_schedule aria-hidden />,
                    ...shutWith(!write.may, write.why),
                    onSelect: () => {
                        setCreating('schedule')
                    },
                }}
            />

            <PageState
                loading={!state.read || !listed.state.read}
                problem={state.problem ?? listed.state.problem}
                empty={schedules.length === 0 && sources.length === 0}
                emptyMessage={LABELS.triggers.empty}
            >
                <div className="flex flex-col gap-6">
                    <Section
                        title={LABELS.word.input_source.heading}
                        meta={
                            sources.length === 0
                                ? undefined
                                : rowsRead(
                                      sources.length,
                                      LABELS.word.input_source.count,
                                      listed.state.next !== null,
                                  )
                        }
                        flush
                    >
                        <PageState
                            bare
                            loading={false}
                            problem={null}
                            empty={sources.length === 0}
                            emptyMessage={LABELS.triggers.source.empty}
                        >
                            <DataTable
                                {...SECTION_LISTING}
                                rowHeight="auto"
                                columns={sourceColumns(sources)}
                                rows={sources}
                                rowKey={sourceId}
                                hasMore={listed.state.next !== null}
                                loading={listed.state.reading}
                                onLoadMore={listed.more}
                                onOpen={pressSource}
                                opened={(row) => sourceId(row) === chosenSource}
                            />
                        </PageState>
                    </Section>

                    <Section
                        title={LABELS.word.schedule.heading}
                        meta={
                            schedules.length === 0
                                ? undefined
                                : rowsRead(schedules.length, LABELS.word.schedule.count, state.next !== null)
                        }
                        flush
                    >
                        <PageState
                            bare
                            loading={false}
                            problem={null}
                            empty={schedules.length === 0}
                            emptyMessage={LABELS.triggers.schedule.empty}
                        >
                            <DataTable
                                {...SECTION_LISTING}
                                rowHeight="auto"
                                columns={scheduleCols}
                                rows={schedules}
                                rowKey={scheduleId}
                                hasMore={state.next !== null}
                                loading={state.reading}
                                onLoadMore={more}
                                onOpen={pressSchedule}
                                opened={(row) => scheduleId(row) === chosen}
                            />
                        </PageState>
                    </Section>
                </div>
            </PageState>

            <NewSchedule
                open={creating === 'schedule'}
                onOpenChange={(next) => {
                    setCreating(next ? 'schedule' : null)
                }}
                onCreated={reload}
            />
        </>
    )
}

const SOURCE_COLUMNS: DataColumn<SourceOut>[] = [
    {
        id: 'source',
        header: LABELS.word.input_source.label,
        width: 'minmax(11.5rem,2fr)',
        stackTitle: 'free',
        cell: (row) => <Titled thing={row}>{null}</Titled>,
    },
    {
        id: 'pipeline',
        header: LABELS.word.pipeline.label,
        width: 'minmax(12.5rem,1fr)',
        cell: (row) => <PipelineRef code={row.pipeline} name={null} />,
    },
    {
        id: 'listens',
        header: LABELS.triggers.source.listens,
        width: 'minmax(6.5rem,2fr)',
        cell: (row) => {
            const listens = listensTo(row)
            return listens === null ? (
                <span className="font-mono text-xs text-muted-foreground">{row.kind}</span>
            ) : (
                <span className="block truncate font-mono text-xs" title={listens}>
                    {listens}
                </span>
            )
        },
    },
    {
        id: 'state',
        header: LABELS.word.state,
        width: 'minmax(5rem,1fr)',
        cell: (row) => {
            const view = stateView(row)
            return (
                <span className="flex items-center gap-2 text-xs">
                    <Dot tone={view.tone} />
                    {view.label}
                </span>
            )
        },
    },
    {
        id: 'in_flight',
        header: LABELS.word.in_flight.heading,
        width: 'minmax(4rem,1fr)',
        align: 'end',
        cell: (row) =>
            row.in_flight === 0 && row.max_in_flight === null ? null : (
                <span className="font-mono text-xs text-muted-foreground">
                    {row.max_in_flight === null
                        ? String(row.in_flight)
                        : LABELS.triggers.source.bounded(String(row.in_flight), String(row.max_in_flight))}
                </span>
            ),
    },
    {
        id: 'last',
        header: LABELS.triggers.source.last_input,
        width: 'minmax(4.5rem,1fr)',
        cell: (row) =>
            row.last_input_at === null ? (
                <span className="text-xs text-faint">{LABELS.word.never}</span>
            ) : (
                <Instant className="text-xs text-muted-foreground" at={row.last_input_at} />
            ),
    },
]

/** The source columns, leaving out In flight where no row has a run in flight or a bound on them. */
function sourceColumns(rows: readonly SourceOut[]): DataColumn<SourceOut>[] {
    if (rows.some((row) => row.in_flight > 0 || row.max_in_flight !== null)) return SOURCE_COLUMNS
    return SOURCE_COLUMNS.filter((column) => column.id !== 'in_flight')
}

const SCHEDULE_COLUMNS: DataColumn<ScheduleRow>[] = [
    {
        id: 'schedule',
        header: LABELS.word.schedule.label,
        width: 'minmax(11.5rem,2fr)',
        stackTitle: 'free',
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
        width: 'minmax(12.5rem,1fr)',
        cell: (row) => <PipelineRef code={row.pipeline} name={row.pipelineName} />,
    },
    {
        id: 'clock',
        header: LABELS.word.clock,
        width: 'minmax(4.5rem,1fr)',
        cell: (row) => <Clock schedule={row.schedule} />,
    },
    {
        id: 'timezone',
        header: LABELS.word.timezone,
        width: 'minmax(5rem,1fr)',
        cell: (row) => (
            <span className="block truncate text-xs text-muted-foreground" title={row.schedule.timezone}>
                {row.schedule.timezone}
            </span>
        ),
    },
    {
        id: 'next',
        header: LABELS.word.next,
        width: 'minmax(4.5rem,1fr)',
        // The paused chip in the title cell already says why there is no instant.
        cell: (row) =>
            nextFireView(row.schedule).kind === 'paused' ? null : (
                <span className="text-xs whitespace-nowrap">
                    <NextFire schedule={row.schedule} />
                </span>
            ),
    },
    {
        id: 'last',
        header: LABELS.word.firing.last,
        width: 'minmax(4rem,2fr)',
        cell: (row) => <LastFiring row={row} />,
    },
]

/** The schedule columns, leaving out Next where every row is paused and so has none. */
function scheduleColumns(rows: readonly ScheduleRow[]): DataColumn<ScheduleRow>[] {
    if (rows.some((row) => nextFireView(row.schedule).kind !== 'paused')) return SCHEDULE_COLUMNS
    return SCHEDULE_COLUMNS.filter((column) => column.id !== 'next')
}

/**
 * One trigger's lead cell: the title on one line, and beneath it the code when the title is a
 * name, who declared it, and any state it is in. Two lines at most, so a row's height never
 * depends on how many chips it wears. On a card the chips follow the title and the code has the
 * line under it to itself.
 */
function Titled({ thing, children }: { thing: Addressable; children: ReactNode }) {
    const { stacked } = useTableCell()
    const heading = headingOf(thing)
    if (stacked) return <ItemHeading {...itemOf(thing)} as="span" chips={children} />
    return (
        <span className="flex min-w-0 flex-col gap-1">
            <span
                className={cn('truncate', heading.named ? 'font-semibold' : 'font-mono font-semibold')}
                title={heading.title}
            >
                {heading.title}
            </span>
            <span className="flex min-w-0 items-center gap-2 overflow-hidden">
                {heading.code !== null && (
                    <span
                        className="shrink-0 font-mono text-xs whitespace-nowrap text-muted-foreground"
                        title={heading.code}
                    >
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
        <span className="flex flex-wrap items-center gap-x-2 text-xs">
            {view !== null && <Dot tone={view.tone} />}
            <Instant className="text-muted-foreground" at={row.schedule.last_fired_at} />
            {view !== null && <span>{view.label}</span>}
            {view !== null && view.runId !== null && (
                <TextLink
                    variant="data"
                    code
                    href={`/runs/${view.runId}`}
                    onClick={(event) => {
                        event.stopPropagation()
                    }}
                >
                    {LABELS.word.run.term}
                </TextLink>
            )}
            {view !== null && view.detail !== null && (
                <span className="max-w-48 truncate text-muted-foreground" title={view.detail}>
                    {view.detail}
                </span>
            )}
        </span>
    )
}
