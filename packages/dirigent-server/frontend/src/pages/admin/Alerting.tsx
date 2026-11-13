import { useCallback, useEffect, useMemo, useState } from 'react'

import { AdminOnly } from '@/components/admin/AdminOnly'
import { Channel, NotificationPanel, Run, RulePanel, Target } from '@/components/alerting/AlertPanels'
import { ChannelStrip } from '@/components/alerting/ChannelStrip'
import { NewRule } from '@/components/alerting/NewRule'
import { EMPTY_TEST, SendTest, type TestDraft } from '@/components/alerting/SendTest'
import { ApiChip } from '@/components/ApiChip'
import { Instant } from '@/components/Instant'
import { FilterChip } from '@winterop-com/sokkel-ui/FilterChip'
import { PageHeader } from '@/components/ds/PageHeader'
import { filterWords, oneChosen, SECTION_LISTING, shutWith } from '@/lib/design-system'
import { DataTable, type DataColumn } from '@winterop-com/sokkel-ui/DataTable'
import { InlineCode } from '@winterop-com/sokkel-ui/InlineCode'
import { ItemHeading } from '@winterop-com/sokkel-ui/ItemHeading'
import { Section } from '@winterop-com/sokkel-ui/Section'
import { refusedTable } from '@/components/Refusal'
import { StatusChip } from '@winterop-com/sokkel-ui/StatusChip'
import { useMayWrite } from '@/hooks/use-may-write'
import { usePaged } from '@/hooks/use-paged'
import { useRowPress } from '@/hooks/use-row-press'
import { LOG_TARGET } from '@/lib/alert-form'
import {
    channelsOf,
    importanceNote,
    narrowed,
    NOTIFICATION_STATUSES,
    readAlertRules,
    readNotifications,
    readNotifiers,
    ruleLive,
    scopeNote,
    throttleNote,
    type AlertRuleOut,
    type Channel as ChannelRow,
    type NotificationFilters,
    type NotificationOut,
} from '@/lib/alerting'
import { readConnections, type ConnectionOut } from '@/lib/connections'
import { ICONS } from '@/lib/icons'
import { itemOf } from '@/lib/identity'
import { counted, LABELS } from '@/lib/labels'
import { ADMIN_GROUP, registerActions } from '@/lib/palette'
import { closePanel, fillPanel, openPanel } from '@/lib/panels'
import { rowsRead } from '@/lib/paging'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'

const ruleId = (rule: AlertRuleOut) => rule.id
const notificationId = (notification: NotificationOut) => notification.id

/**
 * The rules that watch runs, the channels they leave by, and the queue they leave through.
 *
 * THE STRIP ANSWERS "WHERE?" BEFORE THE TABLE ANSWERS "WHAT?". A rule names a channel, and a
 * channel is a notifier and the credential it delivers through -- so the first thing on the
 * screen is which channels this instance actually has and when each was last proved. A channel
 * that quietly stopped is otherwise invisible, because the thing that would say so is the
 * channel.
 *
 * A TEST IS QUEUED, THEN WATCHED. `POST /alert-rules/$test` answers 202 and a worker delivers,
 * so the dialog stays open and reads the row back until it settles rather than reporting that
 * the API accepted it.
 *
 * ONE PANEL, TWO THINGS IN IT. A rule and a notification are each opened from their own table
 * into the screen's panel, and choosing one closes the other: there is one right-hand column,
 * and two things claiming it at once would be two answers to the question "what am I looking
 * at".
 */
export function AdminAlerting() {
    return (
        <AdminOnly>
            <Alerting />
        </AdminOnly>
    )
}

function Alerting() {
    const [creating, setCreating] = useState(false)
    // The draft and a count of how many times the dialog has been opened. The count is the
    // dialog's `key`, so each open mounts a fresh one whose boxes start from this draft.
    const [testing, setTesting] = useState<{ draft: TestDraft; opened: number } | null>(null)
    const [chosenRule, setChosenRule] = useState<string | null>(null)
    const [chosenNotification, setChosenNotification] = useState<string | null>(null)
    const [filters, setFilters] = useState<NotificationFilters>({ status: '', notifier: '' })
    // What a verb has since made of a row, over the page it was read on.
    const [fresherRules, setFresherRules] = useState<Record<string, AlertRuleOut>>({})
    const [fresherRows, setFresherRows] = useState<Record<string, NotificationOut>>({})

    const rules = usePaged(
        useCallback((after: string | null) => readAlertRules(after), []),
        ruleId,
    )
    const notifications = usePaged(
        useCallback((after: string | null) => readNotifications(filters, after), [filters]),
        notificationId,
    )
    const channels = useChannels()

    const { reload: reloadRules } = rules
    const { reload: reloadNotifications } = notifications

    const ruleRows = useMemo(
        () => rules.state.rows.map((row) => fresherRules[row.id] ?? row),
        [fresherRules, rules.state.rows],
    )
    const notificationRows = useMemo(
        () => notifications.state.rows.map((row) => fresherRows[row.id] ?? row),
        [fresherRows, notifications.state.rows],
    )

    const openRule = ruleRows.find((row) => row.id === chosenRule) ?? null
    const openNotification = notificationRows.find((row) => row.id === chosenNotification) ?? null

    const openTest = useCallback((draft: TestDraft) => {
        setTesting((held) => ({ draft, opened: (held?.opened ?? 0) + 1 }))
    }, [])

    useEffect(() => {
        setScreenStatus({ note: null, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [])

    useEffect(() => {
        if (openRule !== null) {
            const rule = openRule
            return fillPanel(
                [
                    {
                        id: 'rule',
                        label: LABELS.word.rule.label,
                        render: () => (
                            <RulePanel
                                rule={rule}
                                onChanged={(changed) => {
                                    setFresherRules((held) => ({ ...held, [changed.id]: changed }))
                                }}
                                onDeleted={() => {
                                    setChosenRule(null)
                                    reloadRules()
                                }}
                                onTest={() => {
                                    openTest({ connection: rule.connection ?? LOG_TARGET, subject: '' })
                                }}
                            />
                        ),
                    },
                ],
                { screen: 'alerting' },
            )
        }
        if (openNotification !== null) {
            const row = openNotification
            return fillPanel(
                [
                    {
                        id: 'notification',
                        label: LABELS.word.notification.label,
                        render: () => (
                            <NotificationPanel
                                notification={row}
                                onChanged={(changed) => {
                                    setFresherRows((held) => ({ ...held, [changed.id]: changed }))
                                }}
                            />
                        ),
                    },
                ],
                { screen: 'alerting' },
            )
        }
        return undefined
    }, [openNotification, openRule, openTest, reloadRules])

    const write = useMayWrite('admin')
    const mayWrite = write.may

    useEffect(() => {
        return registerActions([
            // A row this account's role would be refused is a row the palette does not offer.
            ...(mayWrite
                ? [
                      {
                          id: 'alerting:rule',
                          title: LABELS.alerting.new_rule.palette,
                          group: ADMIN_GROUP,
                          screen: true,
                          icon: ICONS.create_rule,
                          keywords: ['alert', 'event', 'create'],
                          run: () => {
                              setCreating(true)
                          },
                      },
                      {
                          id: 'alerting:test',
                          title: LABELS.alerting.palette.send_test,
                          group: ADMIN_GROUP,
                          screen: true,
                          icon: ICONS.send_test,
                          keywords: ['alert', 'notification', 'try'],
                          run: () => {
                              openTest(EMPTY_TEST)
                          },
                      },
                  ]
                : []),
            {
                id: 'alerting:reload',
                title: LABELS.alerting.palette.reload,
                group: ADMIN_GROUP,
                screen: true,
                icon: ICONS.refresh,
                keywords: ['refresh', 'reload'],
                run: () => {
                    reloadRules()
                    reloadNotifications()
                },
            },
        ])
    }, [mayWrite, openTest, reloadNotifications, reloadRules])

    const chooseRule = (rule: AlertRuleOut) => {
        setChosenNotification(null)
        setChosenRule(rule.id)
        openPanel()
    }

    const chooseNotification = (row: NotificationOut) => {
        setChosenRule(null)
        setChosenNotification(row.id)
        openPanel()
    }

    /** What taking the open row back means here: the pane empties, whichever listing filled it. */
    const unchoose = () => {
        setChosenRule(null)
        setChosenNotification(null)
        closePanel()
    }

    const pressRule = useRowPress(chooseRule, (rule) => rule.id === chosenRule, unchoose)
    const pressNotification = useRowPress(
        chooseNotification,
        (row) => row.id === chosenNotification,
        unchoose,
    )

    return (
        <>
            <PageHeader
                title={LABELS.screen.alerting.name}
                lead={<ApiChip tag="alerts" />}
                items={[
                    {
                        id: 'test',
                        label: LABELS.action.asks(LABELS.action.send_test),
                        icon: <ICONS.send_test aria-hidden />,
                        ...shutWith(!write.may, write.why),
                        onSelect: () => {
                            openTest(EMPTY_TEST)
                        },
                    },
                ]}
                primary={{
                    id: 'rule',
                    label: LABELS.alerting.new_rule.button,
                    icon: <ICONS.create_rule aria-hidden />,
                    ...shutWith(!write.may, write.why),
                    onSelect: () => {
                        setCreating(true)
                    },
                }}
            />

            <div className="flex flex-col gap-6">
                <ChannelStrip channels={channels.rows} read={channels.read} />

                <Section
                    title={LABELS.word.rule.heading}
                    meta={
                        ruleRows.length === 0
                            ? undefined
                            : rowsRead(ruleRows.length, LABELS.word.rule.count, rules.state.next !== null)
                    }
                    flush
                >
                    <DataTable
                        {...SECTION_LISTING}
                        rowHeight="auto"
                        columns={RULE_COLUMNS}
                        rows={ruleRows}
                        rowKey={ruleId}
                        rowTone={(rule) => (ruleLive(rule) ? undefined : 'muted')}
                        hasMore={rules.state.next !== null}
                        loading={!rules.state.read || rules.state.reading}
                        onLoadMore={rules.more}
                        onOpen={pressRule}
                        opened={(rule) => rule.id === chosenRule}
                        {...refusedTable(rules.state.problem, reloadRules, SECTION_LISTING.words)}
                        empty={LABELS.alerting.rules_empty}
                    />
                </Section>

                <Section
                    title={LABELS.word.notification.heading}
                    meta={
                        notificationRows.length === 0
                            ? undefined
                            : rowsRead(
                                  notificationRows.length,
                                  LABELS.word.notification.count,
                                  notifications.state.next !== null,
                              )
                    }
                    actions={
                        <span className="flex gap-2 font-normal">
                            <FilterChip
                                facet={LABELS.word.status}
                                options={NOTIFICATION_STATUSES.map((one) => ({
                                    value: one,
                                    label: one,
                                    row: <StatusChip status={one} />,
                                }))}
                                value={
                                    filters.status === '' ? undefined : <StatusChip status={filters.status} />
                                }
                                {...oneChosen(filters.status, (status) => {
                                    setFilters((held) => ({ ...held, status }))
                                })}
                                words={filterWords(LABELS.alerting.any_status)}
                            />
                            <FilterChip
                                facet={LABELS.alerting.notifier}
                                options={notifierOptions(channels.rows)}
                                {...oneChosen(filters.notifier, (notifier) => {
                                    setFilters((held) => ({ ...held, notifier }))
                                })}
                                words={filterWords(LABELS.alerting.any_notifier)}
                            />
                        </span>
                    }
                    flush
                >
                    <DataTable
                        {...SECTION_LISTING}
                        rowHeight="auto"
                        columns={NOTIFICATION_COLUMNS}
                        rows={notificationRows}
                        rowKey={notificationId}
                        hasMore={notifications.state.next !== null}
                        loading={!notifications.state.read || notifications.state.reading}
                        onLoadMore={notifications.more}
                        onOpen={pressNotification}
                        opened={(row) => row.id === chosenNotification}
                        {...refusedTable(
                            notifications.state.problem,
                            reloadNotifications,
                            SECTION_LISTING.words,
                        )}
                        empty={
                            narrowed(filters)
                                ? LABELS.alerting.notifications_empty_filtered
                                : LABELS.alerting.notifications_empty
                        }
                    />
                </Section>
            </div>

            <NewRule
                open={creating}
                onOpenChange={setCreating}
                notifiers={notifiersOf(channels.rows)}
                connections={channels.connections}
                onCreated={reloadRules}
            />

            <SendTest
                key={testing?.opened ?? 0}
                open={testing !== null}
                draft={testing?.draft ?? EMPTY_TEST}
                onOpenChange={(next) => {
                    if (!next) setTesting(null)
                }}
                notifiers={notifiersOf(channels.rows)}
                connections={channels.connections}
                onQueued={reloadNotifications}
                onOpenQueue={(id) => {
                    setTesting(null)
                    setChosenRule(null)
                    setChosenNotification(id)
                    reloadNotifications()
                    openPanel()
                }}
            />
        </>
    )
}

/** The notifiers behind the channel strip, each named once however many connections it has. */
function notifiersOf(channels: readonly ChannelRow[]): string[] {
    return [...new Set(channels.map((one) => one.notifier))]
}

/** The notifier filter's rows, which are the channels this instance can deliver through. */
function notifierOptions(channels: readonly ChannelRow[]) {
    return notifiersOf(channels).map((one) => ({ value: one, label: one }))
}

/**
 * The channels this instance has: the notifiers it installed, times the credentials it holds.
 *
 * Read once when the screen mounts. Neither listing is long, and neither changes while somebody
 * is reading this screen -- a notifier arrives with a deploy and a connection with a write on
 * another screen.
 *
 * WHETHER THE READ HAS ANSWERED IS ITS OWN FACT. An instance that has not answered yet and one
 * with no channel at all are different things, and a strip that said "no channel is installed"
 * while it was still asking would be telling an alarming lie for as long as the read took.
 */
function useChannels(): { rows: ChannelRow[]; connections: ConnectionOut[]; read: boolean } {
    const [notifiers, setNotifiers] = useState<string[] | null>(null)
    const [connections, setConnections] = useState<ConnectionOut[] | null>(null)

    useEffect(() => {
        let live = true
        void readNotifiers().then(
            (rows) => {
                if (live) setNotifiers(rows)
            },
            () => {
                if (live) setNotifiers([])
            },
        )
        void readConnections().then(
            (page) => {
                if (live) setConnections(page.items)
            },
            () => {
                if (live) setConnections([])
            },
        )
        return () => {
            live = false
        }
    }, [])

    const rows = useMemo(() => channelsOf(notifiers ?? [], connections ?? []), [connections, notifiers])
    return { rows, connections: connections ?? [], read: notifiers !== null && connections !== null }
}

/**
 * What a rule watches: the pipeline or the whole instance, and the floor it fires at.
 *
 * A pipeline's code is mono and the floor is a phrase, so the two are set apart rather than
 * joined into one string a single face would have to carry.
 */
function Scope({ rule }: { rule: AlertRuleOut }) {
    const floor = importanceNote(rule.importance)
    return (
        <span className="flex min-w-0 flex-wrap items-baseline gap-x-1.5">
            {rule.scope === 'pipeline' ? (
                <InlineCode value={scopeNote(rule)} bare size="xs" />
            ) : (
                <span className="text-sm">{scopeNote(rule)}</span>
            )}
            {floor !== null && <span className="text-xs text-muted-foreground">{floor}</span>}
        </span>
    )
}

const RULE_COLUMNS: DataColumn<AlertRuleOut>[] = [
    {
        id: 'rule',
        header: LABELS.word.rule.label,
        width: 'minmax(15.5rem,2fr)',
        stackTitle: 'free',
        cell: (rule) => <ItemHeading {...itemOf(rule)} as="span" />,
    },
    {
        id: 'event',
        header: LABELS.word.event,
        width: 'minmax(5rem,1fr)',
        cell: (rule) => <span className="text-sm">{LABELS.alerting.event[rule.event]}</span>,
    },
    {
        id: 'scope',
        header: LABELS.word.scope,
        width: 'minmax(4.5rem,1fr)',
        cell: (rule) => <Scope rule={rule} />,
    },
    {
        id: 'delivers',
        header: LABELS.word.delivers_through,
        width: 'minmax(6.5rem,1fr)',
        cell: (rule) => <Target notifier={rule.notifier} connection={rule.connection} />,
    },
    {
        id: 'throttle',
        header: LABELS.word.throttle,
        width: 'minmax(3.5rem,1fr)',
        cell: (rule) => (
            <span className="font-mono text-xs text-muted-foreground">{throttleNote(rule.throttle)}</span>
        ),
    },
    {
        id: 'sent',
        header: LABELS.alerting.last_sent,
        width: 'minmax(4rem,1fr)',
        cell: (rule) =>
            rule.last_sent_at === null ? (
                <span className="text-xs text-muted-foreground">{LABELS.word.never}</span>
            ) : (
                <Instant className="text-xs text-muted-foreground" at={rule.last_sent_at} />
            ),
    },
    {
        id: 'live',
        header: LABELS.word.state,
        width: 'minmax(3rem,1fr)',
        cell: (rule) =>
            rule.paused ? (
                <span className="text-xs text-muted-foreground">{LABELS.state.armed.paused}</span>
            ) : rule.active ? (
                <span className="text-xs text-good">{LABELS.state.armed.active}</span>
            ) : (
                <span className="text-xs text-muted-foreground">{LABELS.state.armed.off}</span>
            ),
    },
]

const NOTIFICATION_COLUMNS: DataColumn<NotificationOut>[] = [
    {
        id: 'status',
        header: LABELS.word.status,
        width: 'content',
        cell: (notification) => <StatusChip status={notification.status} />,
    },
    {
        id: 'subject',
        header: LABELS.word.subject,
        width: 'minmax(10rem,2fr)',
        cell: (notification) => (
            <span className="flex min-w-0 flex-col">
                <span className="truncate text-sm" title={notification.subject}>
                    {notification.subject}
                </span>
                {notification.error !== null && (
                    <span className="truncate text-xs text-critical" title={notification.error}>
                        {notification.error}
                    </span>
                )}
            </span>
        ),
    },
    {
        id: 'delivers',
        header: LABELS.word.delivers_through,
        width: 'minmax(6.5rem,1fr)',
        cell: (notification) => (
            <Channel notifier={notification.notifier} connection={notification.connection} />
        ),
    },
    {
        id: 'run',
        header: LABELS.word.run.label,
        width: 'minmax(9rem,1fr)',
        cell: (notification) => <Run notification={notification} />,
    },
    {
        id: 'queued',
        header: LABELS.alerting.queued_at,
        width: 'minmax(5rem,1fr)',
        cell: (notification) => (
            <Instant className="text-xs text-muted-foreground" at={notification.created_at} />
        ),
    },
    {
        id: 'sent',
        header: LABELS.alerting.sent_at,
        width: 'minmax(5rem,1fr)',
        cell: (notification) =>
            notification.status === 'sent' ? (
                <Instant className="text-xs text-muted-foreground" at={notification.sent_at} />
            ) : notification.attempt > 0 ? (
                <span className="text-xs text-faint">
                    {counted(notification.max_attempts, LABELS.alerting.attempts_of.counted)(
                        notification.attempt,
                        notification.max_attempts,
                    )}
                </span>
            ) : null,
    },
]
