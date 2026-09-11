import { CalendarPlus, RefreshCw, Webhook } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { ApiChip } from '@/components/ApiChip'
import { ListTable, type Column } from '@/components/list/ListTable'
import { PageHeader, PageState } from '@/components/PageState'
import { Chip, Clock, Dot, NextFire, OwnerChip } from '@/components/triggers/marks'
import { MintedToken, NewSchedule, NewWebhook } from '@/components/triggers/NewTrigger'
import { SchedulePanel, WebhookPanel } from '@/components/triggers/TriggerPanel'
import { useMayWrite } from '@/hooks/use-may-write'
import { usePaged } from '@/hooks/use-paged'
import { formatInstant, formatRelative } from '@/lib/format'
import { headingOf, type Addressable } from '@/lib/identity'
import { fillPanel, openPanel } from '@/lib/panels'
import { LIST_GROUP, registerActions } from '@/lib/palette'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import {
    deliveryView,
    firingView,
    hookPath,
    readTriggerPage,
    signing,
    triggerId,
    type ScheduleOut,
    type ScheduleRow,
    type TriggerRow,
    type WebhookOut,
    type WebhookRow,
    type WebhookTokenOut,
} from '@/lib/triggers'

/**
 * Everything that fires a pipeline without a person: the clocks, and the inbound endpoints.
 *
 * TWO SECTIONS, ONE WALK. This API has no listing of every schedule on the instance -- a
 * trigger hangs off the pipeline it fires -- so the screen walks pipelines and reads the
 * triggers of the ones the pipelines listing already counted at least one of. Both sections
 * grow from the same page, which is why both feet state the same walk and one "load more"
 * carries them together.
 *
 * MANAGED IS NOT A LOCK, IT IS A SOURCE. A trigger a document declared changes when that
 * document is applied again, and the chip says so; whether it is paused, whether it accepts
 * deliveries, and what token it answers on are the instance's, and those are the verbs the
 * panel offers.
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
                    label: open.kind === 'schedule' ? 'Schedule' : 'Webhook',
                    render: () =>
                        open.kind === 'schedule' ? (
                            <SchedulePanel
                                pipeline={open.pipeline}
                                schedule={open.schedule}
                                onChanged={(schedule: ScheduleOut) => {
                                    held({ ...open, schedule })
                                }}
                            />
                        ) : (
                            <WebhookPanel
                                pipeline={open.pipeline}
                                webhook={open.webhook}
                                onChanged={(webhook: WebhookOut) => {
                                    held({ ...open, webhook })
                                }}
                                onMinted={setMinted}
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
                          title: 'New schedule',
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
                          title: 'New webhook',
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
                title: 'Read the triggers again',
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

    return (
        <>
            <PageHeader
                title="Triggers"
                aside={<ApiChip tag="triggers" />}
                actions={[
                    {
                        id: 'schedule',
                        label: 'New schedule',
                        icon: CalendarPlus,
                        disabled: !write.may,
                        why: write.why,
                        onClick: () => {
                            setCreating('schedule')
                        },
                    },
                    {
                        id: 'webhook',
                        label: 'New webhook',
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
                emptyMessage="Nothing fires on its own. A document declares them under its triggers key."
            >
                <div className="space-y-6">
                    <section className="space-y-2">
                        <h2 className="text-sm font-semibold">Schedules</h2>
                        {schedules.length === 0 ? (
                            <p className="text-sm text-muted-foreground">
                                No schedules. A document declares one under its triggers key.
                            </p>
                        ) : (
                            <ListTable
                                columns={SCHEDULE_COLUMNS}
                                rows={schedules}
                                rowKey={triggerId}
                                reading={state.reading}
                                next={state.next}
                                onMore={more}
                                noun="schedules"
                                onSelect={select}
                                selected={(row) => triggerId(row) === chosen}
                            />
                        )}
                    </section>

                    <section className="space-y-2">
                        <h2 className="text-sm font-semibold">Webhooks</h2>
                        {webhooks.length === 0 ? (
                            <p className="text-sm text-muted-foreground">No webhooks.</p>
                        ) : (
                            <ListTable
                                columns={WEBHOOK_COLUMNS}
                                rows={webhooks}
                                rowKey={triggerId}
                                reading={state.reading}
                                next={state.next}
                                onMore={more}
                                noun="webhooks"
                                onSelect={select}
                                selected={(row) => triggerId(row) === chosen}
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

const SCHEDULE_COLUMNS: Column<ScheduleRow>[] = [
    {
        id: 'schedule',
        header: 'Schedule',
        cell: (row) => (
            <Titled thing={row.schedule}>
                <OwnerChip managed={row.schedule.managed} document={row.schedule.trigger_document} />
                {row.schedule.paused && <Chip>paused</Chip>}
            </Titled>
        ),
    },
    {
        id: 'pipeline',
        header: 'Pipeline',
        cell: (row) => (
            <Link
                className="text-sm hover:text-primary"
                to={`/pipelines/${encodeURIComponent(row.pipeline)}`}
                onClick={(event) => {
                    event.stopPropagation()
                }}
            >
                {row.pipeline}
            </Link>
        ),
    },
    {
        id: 'clock',
        header: 'Clock',
        cell: (row) => <Clock schedule={row.schedule} />,
    },
    {
        id: 'timezone',
        header: 'Timezone',
        className: 'text-xs',
        cell: (row) => <span className="text-muted-foreground">{row.schedule.timezone}</span>,
    },
    {
        id: 'next',
        header: 'Next',
        className: 'text-xs',
        cell: (row) => <NextFire schedule={row.schedule} />,
    },
    {
        id: 'last',
        header: 'Last firing',
        cell: (row) => <LastFiring row={row} />,
    },
]

const WEBHOOK_COLUMNS: Column<WebhookRow>[] = [
    {
        id: 'webhook',
        header: 'Webhook',
        cell: (row) => (
            <Titled thing={row.webhook}>
                <OwnerChip managed={row.webhook.managed} document={row.webhook.trigger_document} />
                {!row.webhook.active && <Chip>disabled</Chip>}
            </Titled>
        ),
    },
    {
        id: 'pipeline',
        header: 'Pipeline',
        cell: (row) => (
            <Link
                className="text-sm hover:text-primary"
                to={`/pipelines/${encodeURIComponent(row.pipeline)}`}
                onClick={(event) => {
                    event.stopPropagation()
                }}
            >
                {row.pipeline}
            </Link>
        ),
    },
    {
        id: 'endpoint',
        header: 'Endpoint',
        className: 'font-mono text-xs',
        cell: (row) => <span>POST {hookPath(row.webhook)}</span>,
    },
    {
        id: 'signed',
        header: 'Signature',
        className: 'text-xs',
        cell: (row) => <span className="text-muted-foreground">{signing(row.webhook)}</span>,
    },
    {
        id: 'rate',
        header: 'Rate',
        className: 'text-right font-mono text-xs',
        cell: (row) => (
            <span className="text-muted-foreground">{String(row.webhook.rate_limit_per_minute)}/min</span>
        ),
    },
    {
        id: 'last',
        header: 'Last delivery',
        cell: (row) => <LastDelivery row={row} />,
    },
]

/**
 * One trigger's lead cell: the title on one line, and beneath it the code when the title is a
 * name, who declared it, and any state it is in. Two lines at most, so a row's height never
 * depends on how many chips it wears.
 */
function Titled({ thing, children }: { thing: Addressable; children: ReactNode }) {
    const heading = headingOf(thing)
    return (
        <span className="flex flex-col gap-1">
            <span className={heading.named ? 'font-semibold' : 'font-mono font-semibold'}>
                {heading.title}
            </span>
            <span className="flex items-center gap-2">
                {heading.code !== null && (
                    <span className="font-mono text-xs text-muted-foreground">{heading.code}</span>
                )}
                {children}
            </span>
        </span>
    )
}

/** When a schedule last fired, and what came of that firing. */
function LastFiring({ row }: { row: ScheduleRow }) {
    if (row.schedule.last_fired_at === null) return <span className="text-xs text-faint">never fired</span>
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
                    className="font-mono text-primary hover:underline"
                    to={`/runs/${view.runId}`}
                    onClick={(event) => {
                        event.stopPropagation()
                    }}
                >
                    run
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
    if (row.webhook.last_delivery_at === null) return <span className="text-xs text-faint">never</span>
    const view = row.latest === null ? null : deliveryView(row.latest)
    return (
        <span className="flex items-center gap-2 text-xs">
            {view !== null && <Dot tone={view.tone} />}
            <span className="text-muted-foreground" title={formatInstant(row.webhook.last_delivery_at)}>
                {formatRelative(row.webhook.last_delivery_at)}
            </span>
            {view !== null && view.runId !== null && (
                <Link
                    className="font-mono text-primary hover:underline"
                    to={`/runs/${view.runId}`}
                    onClick={(event) => {
                        event.stopPropagation()
                    }}
                >
                    run
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
