import { CalendarPlus, RefreshCw, Webhook } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { ApiChip } from '@/components/ApiChip'
import { ListTable, type Column } from '@/components/list/ListTable'
import { PageHeader, PageState } from '@/components/PageState'
import { PipelineRef } from '@/components/PipelineRef'
import { Chip, Clock, Dot, NextFire, OwnerChip, WatchState } from '@/components/triggers/marks'
import { MintedToken, NewSchedule, NewWebhook } from '@/components/triggers/NewTrigger'
import { SchedulePanel, WatchPanel, WebhookPanel } from '@/components/triggers/TriggerPanel'
import { useMayWrite } from '@/hooks/use-may-write'
import { usePaged } from '@/hooks/use-paged'
import { formatInstant, formatRelative } from '@/lib/format'
import { headingOf, type Addressable } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import { closePanel, fillPanel, openPanel } from '@/lib/panels'
import { LIST_GROUP, registerActions } from '@/lib/palette'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { cn } from '@/lib/utils'
import {
    deliveryView,
    firingView,
    hookPath,
    nextFireView,
    readTriggerPage,
    signing,
    triggerId,
    watchView,
    type ScheduleOut,
    type ScheduleRow,
    type TriggerRow,
    type WatchOut,
    type WatchRow,
    type WebhookOut,
    type WebhookRow,
    type WebhookTokenOut,
} from '@/lib/triggers'

/**
 * Everything that fires a pipeline without a person: the clocks, the inbound endpoints, and the
 * watches that keep a run waiting on a sensor.
 *
 * THREE SECTIONS, ONE WALK. This API has no listing of every schedule on the instance -- a
 * trigger hangs off the pipeline it fires -- so the screen walks pipelines and reads the
 * triggers of the ones the pipelines listing already counted at least one of. Every section
 * grows from the same page, which is why every foot states the same walk and one "load more"
 * carries them together.
 *
 * MANAGED IS NOT A LOCK, IT IS A SOURCE. A trigger a document declared changes when that
 * document is applied again, and the chip says so; whether it is paused, whether it accepts
 * deliveries, and what token it answers on are the instance's, and those are the verbs the
 * panel offers. A watch is only ever declared by a document, so there is no New for one.
 */
export function Triggers() {
    const [chosen, setChosen] = useState<string | null>(null)
    const [creating, setCreating] = useState<'schedule' | 'webhook' | null>(null)
    const [minted, setMinted] = useState<WebhookTokenOut | null>(null)
    // What a verb has since made of a row, over the page it was read on.
    const [fresher, setFresher] = useState<Record<string, TriggerRow>>({})

    const { state, more, reload } = usePaged(readTriggerPage, triggerId)

    const rows = useMemo(() => state.rows.map((row) => fresher[triggerId(row)] ?? row), [fresher, state.rows])
    const schedules = useMemo(() => rows.filter(isSchedule), [rows])
    const webhooks = useMemo(() => rows.filter(isWebhook), [rows])
    const watches = useMemo(() => rows.filter(isWatch), [rows])
    const scheduleCols = useMemo(() => scheduleColumns(schedules), [schedules])
    const watchCols = useMemo(() => watchColumns(watches), [watches])
    const open = rows.find((row) => triggerId(row) === chosen) ?? null

    const held = useCallback((row: TriggerRow) => {
        setFresher((current) => ({ ...current, [triggerId(row)]: row }))
    }, [])

    useEffect(() => {
        setScreenStatus({ note: null, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [])

    useEffect(() => {
        if (open === null) return
        return fillPanel(
            [
                {
                    id: 'trigger',
                    label: PANEL_LABEL[open.kind],
                    render: () => {
                        switch (open.kind) {
                            case 'schedule':
                                return (
                                    <SchedulePanel
                                        pipeline={open.pipeline}
                                        pipelineName={open.pipelineName}
                                        schedule={open.schedule}
                                        onChanged={(schedule: ScheduleOut) => {
                                            held({ ...open, schedule })
                                        }}
                                    />
                                )
                            case 'webhook':
                                return (
                                    <WebhookPanel
                                        pipeline={open.pipeline}
                                        pipelineName={open.pipelineName}
                                        webhook={open.webhook}
                                        onChanged={(webhook: WebhookOut) => {
                                            held({ ...open, webhook })
                                        }}
                                        onMinted={setMinted}
                                    />
                                )
                            case 'watch':
                                return (
                                    <WatchPanel
                                        pipeline={open.pipeline}
                                        pipelineName={open.pipelineName}
                                        watch={open.watch}
                                        onChanged={(watch: WatchOut) => {
                                            held({ ...open, watch })
                                        }}
                                    />
                                )
                        }
                    },
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
                      {
                          id: 'triggers:webhook',
                          title: LABELS.triggers.webhook.new,
                          group: LIST_GROUP,
                          screen: true,
                          icon: Webhook,
                          keywords: ['hook', 'inbound', 'token', 'create'],
                          run: () => {
                              setCreating('webhook')
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
                run: reload,
            },
        ])
    }, [mayWrite, reload])

    const select = (row: TriggerRow) => {
        setChosen(triggerId(row))
        openPanel()
    }

    /** What taking the open row back means here, whichever of the three listings it is in. */
    const unchoose = () => {
        setChosen(null)
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
                    {
                        id: 'webhook',
                        label: LABELS.triggers.webhook.new,
                        icon: Webhook,
                        disabled: !write.may,
                        why: write.why,
                        onClick: () => {
                            setCreating('webhook')
                        },
                    },
                ]}
            />

            <PageState
                loading={!state.read}
                problem={state.problem}
                empty={rows.length === 0}
                emptyMessage={LABELS.triggers.empty}
            >
                <div className="space-y-6">
                    <section className="space-y-2">
                        <h2 className="text-sm font-semibold">{LABELS.triggers.schedule.heading}</h2>
                        {schedules.length === 0 ? (
                            <p className="text-sm text-muted-foreground">{LABELS.triggers.schedule.empty}</p>
                        ) : (
                            <ListTable
                                columns={scheduleCols}
                                rows={schedules}
                                rowKey={triggerId}
                                reading={state.reading}
                                next={state.next}
                                onMore={more}
                                noun={LABELS.triggers.schedule.noun}
                                onSelect={select}
                                selected={(row) => triggerId(row) === chosen}
                                onClose={unchoose}
                            />
                        )}
                    </section>

                    <section className="space-y-2">
                        <h2 className="text-sm font-semibold">{LABELS.triggers.webhook.heading}</h2>
                        {webhooks.length === 0 ? (
                            <p className="text-sm text-muted-foreground">{LABELS.triggers.webhook.empty}</p>
                        ) : (
                            <ListTable
                                columns={WEBHOOK_COLUMNS}
                                rows={webhooks}
                                rowKey={triggerId}
                                reading={state.reading}
                                next={state.next}
                                onMore={more}
                                noun={LABELS.triggers.webhook.noun}
                                onSelect={select}
                                selected={(row) => triggerId(row) === chosen}
                                onClose={unchoose}
                            />
                        )}
                    </section>

                    <section className="space-y-2">
                        <h2 className="text-sm font-semibold">{LABELS.triggers.watch.heading}</h2>
                        {watches.length === 0 ? (
                            <p className="text-sm text-muted-foreground">{LABELS.triggers.watch.empty}</p>
                        ) : (
                            <ListTable
                                columns={watchCols}
                                rows={watches}
                                rowKey={triggerId}
                                reading={state.reading}
                                next={state.next}
                                onMore={more}
                                noun={LABELS.triggers.watch.noun}
                                onSelect={select}
                                selected={(row) => triggerId(row) === chosen}
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
            <NewWebhook
                open={creating === 'webhook'}
                onOpenChange={(next) => {
                    setCreating(next ? 'webhook' : null)
                }}
                onMinted={(token) => {
                    setMinted(token)
                    reload()
                }}
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

const isSchedule = (row: TriggerRow): row is ScheduleRow => row.kind === 'schedule'
const isWebhook = (row: TriggerRow): row is WebhookRow => row.kind === 'webhook'
const isWatch = (row: TriggerRow): row is WatchRow => row.kind === 'watch'

/** What the panel's strip calls the trigger it holds. */
const PANEL_LABEL: Record<TriggerRow['kind'], string> = {
    schedule: LABELS.word.schedule,
    webhook: LABELS.word.webhook,
    watch: LABELS.word.watch,
}

const SCHEDULE_COLUMNS: Column<ScheduleRow>[] = [
    {
        id: 'schedule',
        header: LABELS.word.schedule,
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
        header: LABELS.word.pipeline,
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
        header: LABELS.triggers.schedule.last_firing,
        cell: (row) => <LastFiring row={row} />,
    },
]

const WEBHOOK_COLUMNS: Column<WebhookRow>[] = [
    {
        id: 'webhook',
        header: LABELS.word.webhook,
        kind: 'title',
        cell: (row) => (
            <Titled thing={row.webhook}>
                <OwnerChip managed={row.webhook.managed} document={row.webhook.trigger_document} />
                {!row.webhook.active && <Chip>{LABELS.state.armed.disabled}</Chip>}
            </Titled>
        ),
    },
    {
        id: 'pipeline',
        header: LABELS.word.pipeline,
        kind: 'prose',
        cell: (row) => <PipelineRef code={row.pipeline} name={row.pipelineName} />,
    },
    {
        id: 'endpoint',
        header: LABELS.word.endpoint,
        kind: 'prose',
        className: 'font-mono text-xs',
        cell: (row) => (
            <span className="block truncate" title={LABELS.triggers.webhook.post(hookPath(row.webhook))}>
                {LABELS.triggers.webhook.post(hookPath(row.webhook))}
            </span>
        ),
    },
    {
        id: 'signed',
        header: LABELS.word.signature,
        className: 'text-xs',
        cell: (row) => <span className="text-muted-foreground">{signing(row.webhook)}</span>,
    },
    {
        id: 'rate',
        header: LABELS.triggers.webhook.rate,
        className: 'text-right font-mono text-xs',
        cell: (row) => (
            <span className="text-muted-foreground">
                {LABELS.triggers.webhook.rate_per_minute(String(row.webhook.rate_limit_per_minute))}
            </span>
        ),
    },
    {
        id: 'last',
        header: LABELS.triggers.webhook.last_delivery,
        cell: (row) => <LastDelivery row={row} />,
    },
]

const WATCH_COLUMNS: Column<WatchRow>[] = [
    {
        id: 'watch',
        header: LABELS.word.watch,
        kind: 'title',
        cell: (row) => (
            <Titled thing={row.watch}>
                <OwnerChip managed={row.watch.managed} document={row.watch.trigger_document} />
                {row.watch.paused && <Chip>{LABELS.state.armed.paused}</Chip>}
            </Titled>
        ),
    },
    {
        id: 'pipeline',
        header: LABELS.word.pipeline,
        kind: 'prose',
        cell: (row) => <PipelineRef code={row.pipeline} name={row.pipelineName} />,
    },
    {
        id: 'step',
        header: LABELS.word.step,
        className: 'font-mono text-xs',
        cell: (row) => <span className="font-mono text-muted-foreground">{row.watch.step}</span>,
    },
    {
        id: 'waiting',
        header: LABELS.triggers.watch.waiting,
        // The paused chip in the title cell already says why nothing is waiting.
        cell: (row) => (watchView(row.watch).kind === 'paused' ? null : <WatchState watch={row.watch} />),
    },
    {
        id: 'error',
        header: LABELS.triggers.watch.last_error,
        kind: 'prose',
        cell: (row) =>
            row.watch.last_error === null ? null : (
                <span className="block truncate text-xs text-muted-foreground" title={row.watch.last_error}>
                    {row.watch.last_error}
                </span>
            ),
    },
]

/** The schedule columns, leaving out Next where every row is paused and so has none. */
function scheduleColumns(rows: readonly ScheduleRow[]): Column<ScheduleRow>[] {
    if (rows.some((row) => nextFireView(row.schedule).kind !== 'paused')) return SCHEDULE_COLUMNS
    return SCHEDULE_COLUMNS.filter((column) => column.id !== 'next')
}

/**
 * The watch columns, leaving out Waiting where every row is paused and the error column where
 * no row has an error to show.
 */
function watchColumns(rows: readonly WatchRow[]): Column<WatchRow>[] {
    const waiting = rows.some((row) => watchView(row.watch).kind !== 'paused')
    const erred = rows.some((row) => row.watch.last_error !== null)
    return WATCH_COLUMNS.filter(
        (column) => (waiting || column.id !== 'waiting') && (erred || column.id !== 'error'),
    )
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
        return <span className="text-xs text-faint">{LABELS.triggers.schedule.never_fired}</span>
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
                    {LABELS.triggers.run}
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

/** When something last arrived, and what came of it. */
function LastDelivery({ row }: { row: WebhookRow }) {
    if (row.webhook.last_delivery_at === null)
        return <span className="text-xs text-faint">{LABELS.word.never}</span>
    const view = row.latest === null ? null : deliveryView(row.latest)
    return (
        <span className="flex items-center gap-2 text-xs">
            {view !== null && <Dot tone={view.tone} />}
            <span className="text-muted-foreground" title={formatInstant(row.webhook.last_delivery_at)}>
                {formatRelative(row.webhook.last_delivery_at)}
            </span>
            {view !== null && view.runId !== null && (
                <Link
                    className="font-mono text-primary-ink hover:underline"
                    to={`/runs/${view.runId}`}
                    onClick={(event) => {
                        event.stopPropagation()
                    }}
                >
                    {LABELS.triggers.run}
                </Link>
            )}
            {view !== null && view.reason !== null && (
                <span className="max-w-48 truncate text-muted-foreground" title={view.reason}>
                    {view.reason}
                </span>
            )}
        </span>
    )
}
