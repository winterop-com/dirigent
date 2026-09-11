import { BellPlus, RefreshCw, Send } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { AdminOnly } from '@/components/admin/AdminOnly'
import { Channel, NotificationPanel, Run, RulePanel } from '@/components/alerting/AlertPanels'
import { ChannelStrip } from '@/components/alerting/ChannelStrip'
import { NewRule } from '@/components/alerting/NewRule'
import { EMPTY_TEST, SendTest, type TestDraft } from '@/components/alerting/SendTest'
import { ApiChip } from '@/components/ApiChip'
import { Instant } from '@/components/Instant'
import { ANY, Choice } from '@/components/list/Choice'
import { ListTable, type Column } from '@/components/list/ListTable'
import { PageHeader, PageState } from '@/components/PageState'
import { StatusChip } from '@/components/run/StatusChip'
import { useMayWrite } from '@/hooks/use-may-write'
import { usePaged } from '@/hooks/use-paged'
import { EVENT_LABELS } from '@/lib/alert-form'
import {
    channelsOf,
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
import { headingOf } from '@/lib/identity'
import { ADMIN_GROUP, registerActions } from '@/lib/palette'
import { fillPanel, openPanel } from '@/lib/panels'
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
    const [filters, setFilters] = useState<NotificationFilters>({ status: ANY, notifier: ANY })
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
                        label: 'Rule',
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
                                    openTest({
                                        notifier: rule.notifier,
                                        connection: rule.connection ?? '',
                                        subject: '',
                                    })
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
                        label: 'Notification',
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
                          title: 'New alert rule',
                          group: ADMIN_GROUP,
                          screen: true,
                          icon: BellPlus,
                          keywords: ['alert', 'event', 'create'],
                          run: () => {
                              setCreating(true)
                          },
                      },
                      {
                          id: 'alerting:test',
                          title: 'Send a test through a channel',
                          group: ADMIN_GROUP,
                          screen: true,
                          icon: Send,
                          keywords: ['alert', 'notification', 'try'],
                          run: () => {
                              openTest(EMPTY_TEST)
                          },
                      },
                  ]
                : []),
            {
                id: 'alerting:reload',
                title: 'Read the alert rules again',
                group: ADMIN_GROUP,
                screen: true,
                icon: RefreshCw,
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

    return (
        <>
            <PageHeader
                title="Alerting"
                aside={<ApiChip tag="alerts" />}
                actions={[
                    {
                        id: 'test',
                        label: 'Send a test',
                        icon: Send,
                        variant: 'outline',
                        disabled: !write.may,
                        why: write.why,
                        onClick: () => {
                            openTest(EMPTY_TEST)
                        },
                    },
                    {
                        id: 'rule',
                        label: 'New rule',
                        icon: BellPlus,
                        disabled: !write.may,
                        why: write.why,
                        onClick: () => {
                            setCreating(true)
                        },
                    },
                ]}
            />

            <section className="mb-6 space-y-2">
                <h2 className="text-sm font-semibold">Channels</h2>
                {!channels.read ? (
                    <p className="text-sm text-faint">Reading from the server</p>
                ) : channels.rows.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No channel is installed.</p>
                ) : (
                    <ChannelStrip channels={channels.rows} />
                )}
            </section>

            <section className="space-y-2">
                <h2 className="text-sm font-semibold">Rules</h2>
                <PageState
                    loading={!rules.state.read}
                    problem={rules.state.problem}
                    empty={ruleRows.length === 0}
                    emptyMessage="No rules."
                >
                    <ListTable
                        columns={RULE_COLUMNS}
                        rows={ruleRows}
                        rowKey={ruleId}
                        rowClassName={(rule) => (ruleLive(rule) ? undefined : 'opacity-60')}
                        reading={rules.state.reading}
                        next={rules.state.next}
                        onMore={rules.more}
                        noun="rules"
                        onSelect={chooseRule}
                        selected={(rule) => rule.id === chosenRule}
                    />
                </PageState>
            </section>

            <section className="mt-8 space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <h2 className="text-sm font-semibold">Notifications</h2>
                    <div className="flex flex-wrap gap-2">
                        <Choice
                            label="Status"
                            value={filters.status}
                            anything="Any status"
                            options={NOTIFICATION_STATUSES.map((one) => ({
                                value: one,
                                label: one,
                                mark: <StatusChip status={one} />,
                            }))}
                            onChange={(status) => {
                                setFilters((held) => ({ ...held, status }))
                            }}
                        />
                        <Choice
                            label="Notifier"
                            value={filters.notifier}
                            anything="Any notifier"
                            options={notifierOptions(channels.rows)}
                            onChange={(notifier) => {
                                setFilters((held) => ({ ...held, notifier }))
                            }}
                        />
                    </div>
                </div>
                <PageState
                    loading={!notifications.state.read}
                    problem={notifications.state.problem}
                    empty={notificationRows.length === 0}
                    emptyMessage="Nothing queued."
                >
                    <ListTable
                        columns={NOTIFICATION_COLUMNS}
                        rows={notificationRows}
                        rowKey={notificationId}
                        reading={notifications.state.reading}
                        next={notifications.state.next}
                        onMore={notifications.more}
                        noun="notifications"
                        onSelect={chooseNotification}
                        selected={(row) => row.id === chosenNotification}
                    />
                </PageState>
            </section>

            <NewRule
                open={creating}
                onOpenChange={setCreating}
                notifiers={notifiersOf(channels.rows)}
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
function useChannels(): { rows: ChannelRow[]; read: boolean } {
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
    return { rows, read: notifiers !== null && connections !== null }
}

const RULE_COLUMNS: Column<AlertRuleOut>[] = [
    {
        id: 'rule',
        header: 'Rule',
        cell: (rule) => {
            const heading = headingOf(rule)
            return (
                <span className="flex flex-wrap items-baseline gap-2">
                    <span className={heading.named ? 'text-sm font-medium' : 'font-mono text-sm font-medium'}>
                        {heading.title}
                    </span>
                    {heading.code !== null && (
                        <span className="font-mono text-xs text-muted-foreground">{heading.code}</span>
                    )}
                </span>
            )
        },
    },
    {
        id: 'event',
        header: 'Event',
        cell: (rule) => <span className="text-sm">{EVENT_LABELS[rule.event]}</span>,
    },
    {
        id: 'scope',
        header: 'Scope',
        cell: (rule) => (
            <span className={rule.scope === 'pipeline' ? 'font-mono text-xs' : 'text-sm'}>
                {scopeNote(rule)}
            </span>
        ),
    },
    {
        id: 'delivers',
        header: 'Delivers through',
        cell: (rule) => <Channel notifier={rule.notifier} connection={rule.connection} />,
    },
    {
        id: 'throttle',
        header: 'Throttle',
        className: 'font-mono text-xs',
        cell: (rule) => <span className="text-muted-foreground">{throttleNote(rule.throttle)}</span>,
    },
    {
        id: 'sent',
        header: 'Last sent',
        className: 'text-xs',
        cell: (rule) =>
            rule.last_sent_at === null ? (
                <span className="text-muted-foreground">never</span>
            ) : (
                <Instant className="text-muted-foreground" at={rule.last_sent_at} />
            ),
    },
    {
        id: 'live',
        header: 'State',
        cell: (rule) =>
            rule.paused ? (
                <span className="text-xs text-muted-foreground">paused</span>
            ) : rule.active ? (
                <span className="text-xs text-good">active</span>
            ) : (
                <span className="text-xs text-muted-foreground">off</span>
            ),
    },
]

const NOTIFICATION_COLUMNS: Column<NotificationOut>[] = [
    {
        id: 'status',
        header: 'Status',
        cell: (notification) => <StatusChip status={notification.status} />,
    },
    {
        id: 'subject',
        header: 'Subject',
        cell: (notification) => (
            <span className="flex flex-col">
                <span className="text-sm">{notification.subject}</span>
                {notification.error !== null && (
                    <span className="max-w-96 truncate text-xs text-critical" title={notification.error}>
                        {notification.error}
                    </span>
                )}
            </span>
        ),
    },
    {
        id: 'delivers',
        header: 'Delivers through',
        cell: (notification) => (
            <Channel notifier={notification.notifier} connection={notification.connection} />
        ),
    },
    {
        id: 'run',
        header: 'Run',
        cell: (notification) => <Run notification={notification} />,
    },
    {
        id: 'queued',
        header: 'Queued',
        className: 'text-xs',
        cell: (notification) => <Instant className="text-muted-foreground" at={notification.created_at} />,
    },
    {
        id: 'sent',
        header: 'Sent',
        className: 'text-xs',
        cell: (notification) =>
            notification.status === 'sent' ? (
                <Instant className="text-muted-foreground" at={notification.sent_at} />
            ) : notification.attempt > 0 ? (
                <span className="text-faint">
                    {notification.attempt} of {notification.max_attempts} attempts
                </span>
            ) : null,
    },
]
