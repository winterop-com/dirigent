import { useCallback, useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { Description } from '@/components/Description'
import { Instant } from '@/components/Instant'
import { CodePane } from '@/components/pipeline/CodePane'
import { ProgramReference } from '@/components/pipeline/ProgramReference'
import { Refusable } from '@/components/Refusable'
import { Refusal, sayRefusal } from '@/components/Refusal'
import { StatusChip } from '@/components/run/StatusChip'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { WindowedPane } from '@/components/WindowedPane'
import { useMayWrite } from '@/hooks/use-may-write'
import { usePaged } from '@/hooks/use-paged'
import { BODY_HINT, given, SUBJECT_HINT, TEMPLATE_MEDIA_TYPE } from '@/lib/alert-form'
import {
    deleteRule,
    eventLabel,
    NO_FILTERS,
    readNotifications,
    retryNotification,
    scopeNote,
    setRulePaused,
    throttleNote,
    updateRule,
    type AlertRuleOut,
    type AlertRuleUpdate,
    type NotificationOut,
} from '@/lib/alerting'
import type { Problem } from '@/lib/api'
import { headingOf, type Addressable } from '@/lib/identity'
import { refusalOf } from '@/lib/refusal'

/**
 * One rule beside the listing: what it says, what it has said lately, and what may be done to it.
 *
 * PAUSE IS THE INSTANCE'S, NOT THE DOCUMENT'S. Whether a rule delivers is operational state on
 * the row, so any rule may be held here -- including one a document declared -- and it keeps
 * holding when that document is applied again. What the rule watches and where it delivers came
 * from whoever declared it, and change by declaring it again.
 *
 * THE DELIVERIES ARE THE SAME QUEUE THE TABLE BELOW READS, narrowed to this rule by reading the
 * first page and keeping its own rows: there is no per-rule listing on the API, and a filter
 * this screen invented would be a second answer to a question the server already answers one
 * way.
 */
export function RulePanel({
    rule,
    onChanged,
    onDeleted,
    onTest,
}: {
    rule: AlertRuleOut
    onChanged: (rule: AlertRuleOut) => void
    onDeleted: () => void
    /** Opens Send a test with this rule's own channel filled in. */
    onTest: () => void
}) {
    const [busy, setBusy] = useState(false)
    // Which rule the form is open on rather than whether it is: this panel is one component
    // the listing re-renders with whichever rule is chosen, so a form left open would other-
    // wise open on the next rule with the last one's text in it.
    const [editingCode, setEditingCode] = useState<string | null>(null)
    const editing = editingCode === rule.code
    const write = useMayWrite()

    const read = useCallback((after: string | null) => readNotifications(NO_FILTERS, after), [])
    const { state } = usePaged(read, notificationId)
    const mine = state.rows.filter((row) => row.rule === rule.code)

    const toggle = () => {
        setBusy(true)
        void setRulePaused(rule.code, !rule.paused)
            .then(onChanged, sayRefusal)
            .finally(() => {
                setBusy(false)
            })
    }

    const remove = () => {
        setBusy(true)
        void deleteRule(rule.code)
            .then(onDeleted, sayRefusal)
            .finally(() => {
                setBusy(false)
            })
    }

    return (
        <div className="space-y-4 p-4">
            <Head thing={rule}>
                {rule.paused && <Chip>paused</Chip>}
                {!rule.active && <Chip>off</Chip>}
            </Head>
            <Description text={rule.description} />

            <dl className="space-y-1.5">
                <Fact label="Event">{eventLabel(rule.event)}</Fact>
                <Fact label="Scope">{scopeNote(rule)}</Fact>
                <Fact label="Delivers through">
                    <Channel notifier={rule.notifier} connection={rule.connection} />
                </Fact>
                <Fact label="Throttle">{throttleNote(rule.throttle)}</Fact>
                {editing ? (
                    <RuleText
                        key={rule.code}
                        rule={rule}
                        onDone={() => {
                            setEditingCode(null)
                        }}
                        onSaved={(saved) => {
                            onChanged(saved)
                            setEditingCode(null)
                        }}
                    />
                ) : (
                    <>
                        <Fact label="Subject">
                            <span className="flex flex-wrap items-baseline gap-2">
                                {rule.template === null ? (
                                    <span className="text-muted-foreground">none</span>
                                ) : (
                                    <span className="font-mono text-xs break-all">{rule.template}</span>
                                )}
                                <Refusable why={write.why}>
                                    <Button
                                        variant="ghost"
                                        size="xs"
                                        disabled={!write.may}
                                        title={write.why}
                                        onClick={() => {
                                            setEditingCode(rule.code)
                                        }}
                                    >
                                        Edit
                                    </Button>
                                </Refusable>
                            </span>
                        </Fact>
                        {rule.body !== null && (
                            <Fact label="Body">
                                <span className="line-clamp-3 font-mono text-xs break-words whitespace-pre-wrap">
                                    {rule.body}
                                </span>
                            </Fact>
                        )}
                    </>
                )}
                <Fact label="Last sent">
                    {rule.last_sent_at === null ? (
                        <span className="text-muted-foreground">never</span>
                    ) : (
                        <Instant at={rule.last_sent_at} />
                    )}
                </Fact>
            </dl>

            <div className="flex flex-wrap gap-2">
                <Refusable why={write.why}>
                    <Button
                        variant="outline"
                        size="sm"
                        disabled={busy || !write.may}
                        title={write.why}
                        onClick={toggle}
                    >
                        {rule.paused ? 'Resume' : 'Pause'}
                    </Button>
                </Refusable>
                <Refusable why={write.why}>
                    <Button
                        variant="outline"
                        size="sm"
                        disabled={!write.may}
                        title={write.why}
                        onClick={onTest}
                    >
                        Send a test
                    </Button>
                </Refusable>
                <Refusable why={write.why}>
                    <Button
                        variant="outline"
                        size="sm"
                        className="destructive-action ml-auto"
                        disabled={busy || !write.may}
                        title={write.why}
                        onClick={remove}
                    >
                        Delete
                    </Button>
                </Refusable>
            </div>

            <div className="space-y-2">
                <p className="text-xs text-muted-foreground">Recent deliveries</p>
                {!state.read && <p className="text-xs text-faint">Reading from the server</p>}
                {state.read && mine.length === 0 && <p className="text-xs text-faint">Nothing sent.</p>}
                <ul className="divide-y divide-border">
                    {mine.map((row) => (
                        <li key={row.id} className="row-hover -mx-4 flex items-center gap-2 px-4 py-2">
                            <StatusChip status={row.status} />
                            <span className="min-w-0 flex-1 truncate text-xs">{row.subject}</span>
                            <Instant className="shrink-0 text-xs text-faint" at={row.created_at} />
                        </li>
                    ))}
                </ul>
            </div>
        </div>
    )
}

/**
 * A rule's subject and body, edited where they are read.
 *
 * IT EXPANDS UNDER THE FACTS RATHER THAN OPENING A DIALOG over the panel that is already about
 * this rule. The refusal is `Refusal` beside the two controls, because a template the server
 * cannot compile is refused by field and by line and that sentence belongs next to the field it
 * names; nothing closes on one.
 *
 * A PATCH CARRIES WHAT CHANGED. The wire leaves out what it is not sent, so a subject nobody
 * touched is not resent with the body -- and a form saved with neither changed asks nothing.
 */
function RuleText({
    rule,
    onDone,
    onSaved,
}: {
    rule: AlertRuleOut
    onDone: () => void
    onSaved: (rule: AlertRuleOut) => void
}) {
    const [template, setTemplate] = useState(rule.template ?? '')
    const [body, setBody] = useState(rule.body ?? '')
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)

    const path = `alert-rule/${rule.code}/body`
    const subjectId = `rule-${rule.code}-subject`

    const save = () => {
        const patch: AlertRuleUpdate = {}
        if (given(template) !== rule.template) patch.template = given(template)
        if (given(body) !== rule.body) patch.body = given(body)
        if (Object.keys(patch).length === 0) {
            onDone()
            return
        }
        setBusy(true)
        setProblem(null)
        void updateRule(rule.code, patch)
            .then(onSaved, (error: unknown) => {
                setProblem(refusalOf(error))
            })
            .finally(() => {
                setBusy(false)
            })
    }

    return (
        <div className="space-y-3 rounded-lg border border-border bg-secondary/30 p-3">
            <div className="space-y-2">
                <Label htmlFor={subjectId}>Subject</Label>
                <Input
                    id={subjectId}
                    className="font-mono"
                    spellCheck={false}
                    autoComplete="off"
                    value={template}
                    placeholder="{{ run.pipeline }} run {{ run.status }}"
                    onChange={(event) => {
                        setTemplate(event.target.value)
                    }}
                />
                <p className="text-xs text-faint">{SUBJECT_HINT}</p>
            </div>

            <div className="space-y-2">
                <Label>Body</Label>
                <p className="text-xs text-faint">{BODY_HINT}</p>
                <WindowedPane
                    name="body"
                    className="overflow-hidden rounded-md border border-border bg-background"
                    aside={<ProgramReference mediaType={TEMPLATE_MEDIA_TYPE} />}
                    windowed={
                        <CodePane
                            value={body}
                            mediaType={TEMPLATE_MEDIA_TYPE}
                            path={path}
                            label="body, in a window"
                            className="min-h-0 flex-1"
                            onChange={setBody}
                        />
                    }
                >
                    <CodePane
                        value={body}
                        mediaType={TEMPLATE_MEDIA_TYPE}
                        path={path}
                        label="body"
                        placeholder="{{ run.pipeline }} ended {{ run.status }}: {{ run.url }}"
                        className="h-40 min-h-32"
                        onChange={setBody}
                    />
                </WindowedPane>
            </div>

            {problem !== null && <Refusal problem={problem} />}

            <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={onDone}>
                    Cancel
                </Button>
                <Button size="sm" disabled={busy} onClick={save}>
                    {busy ? 'Saving' : 'Save'}
                </Button>
            </div>
        </div>
    )
}

/**
 * One notification beside the queue: where it is, what it was for, and what it last said.
 *
 * ONLY THE LATEST REFUSAL IS STORED. The row carries one `error` and a count of attempts rather
 * than a row per try, so this panel says how many tries there have been and what the last one
 * answered -- it does not invent a history the instance never kept.
 */
export function NotificationPanel({
    notification,
    onChanged,
}: {
    notification: NotificationOut
    onChanged: (row: NotificationOut) => void
}) {
    const [busy, setBusy] = useState(false)
    const write = useMayWrite()

    const again = () => {
        setBusy(true)
        void retryNotification(notification.id)
            .then(onChanged, sayRefusal)
            .finally(() => {
                setBusy(false)
            })
    }

    return (
        <div className="space-y-4 p-4">
            <div className="space-y-1">
                <p className="flex flex-wrap items-center gap-2">
                    <StatusChip status={notification.status} />
                    <span className="text-sm font-semibold">{notification.subject}</span>
                </p>
            </div>

            <dl className="space-y-1.5">
                {/* A test is raised by nothing, and the event on its row is a placeholder the
                    queue needed rather than something that happened -- so it is not drawn. */}
                {notification.rule === null ? (
                    <Fact label="Raised by">
                        <span className="text-muted-foreground">a test, not a rule</span>
                    </Fact>
                ) : (
                    <>
                        <Fact label="Event">{eventLabel(notification.event)}</Fact>
                        <Fact label="Rule">
                            <span className="font-mono text-xs">{notification.rule}</span>
                        </Fact>
                    </>
                )}
                <Fact label="Delivers through">
                    <Channel notifier={notification.notifier} connection={notification.connection} />
                </Fact>
                <Fact label="Run">
                    <Run notification={notification} />
                </Fact>
                <Fact label="Queued">
                    <Instant at={notification.created_at} />
                </Fact>
                {notification.status === 'sent' ? (
                    <Fact label="Sent">
                        <Instant at={notification.sent_at} />
                    </Fact>
                ) : (
                    <Fact label="Next try">
                        <Instant at={notification.available_at} />
                    </Fact>
                )}
                <Fact label="Attempts">
                    {notification.attempt} of {notification.max_attempts}
                </Fact>
            </dl>

            {notification.error !== null && (
                <div className="space-y-1">
                    <p className="text-xs text-muted-foreground">What the channel said</p>
                    <p className="text-xs break-words text-critical">{notification.error}</p>
                    <p className="text-xs text-faint">
                        Only the latest refusal is kept. Earlier attempts are counted, not stored.
                    </p>
                </div>
            )}

            <div className="flex flex-wrap gap-2">
                <Refusable why={write.why}>
                    <Button
                        variant="outline"
                        size="sm"
                        disabled={busy || !write.may}
                        title={write.why}
                        onClick={again}
                    >
                        Retry now
                    </Button>
                </Refusable>
                {notification.run_id !== null && (
                    <Button variant="outline" size="sm" render={<Link to={`/runs/${notification.run_id}`} />}>
                        Open the run
                    </Button>
                )}
            </div>
        </div>
    )
}

const notificationId = (row: NotificationOut) => row.id

/** The channel a message leaves by: the notifier, and the credential where there is one. */
export function Channel({ notifier, connection }: { notifier: string; connection: string | null }) {
    return (
        <span className="flex flex-wrap items-baseline gap-1.5">
            <span className="text-sm">{notifier}</span>
            {connection !== null && (
                <span className="font-mono text-xs text-muted-foreground">{connection}</span>
            )}
        </span>
    )
}

/**
 * Which run a message is about, named by its pipeline and when it started.
 *
 * A RUN IS NOT ITS ID. What somebody recognises is which pipeline ran and when, so that is what
 * the cell says; the id is what the link carries.
 */
export function Run({ notification }: { notification: NotificationOut }) {
    if (notification.run_id === null) return <span className="text-muted-foreground">no run</span>
    const named = notification.run_pipeline ?? 'a run'
    return (
        <Link className="text-primary hover:underline" to={`/runs/${notification.run_id}`}>
            <span className="text-sm">{named}</span>
            {notification.run_started_at !== null && (
                <Instant className="ml-1.5 text-xs text-muted-foreground" at={notification.run_started_at} />
            )}
        </Link>
    )
}

/** A word a rule wears about itself. */
function Chip({ children }: { children: ReactNode }) {
    return (
        <span className="rounded-sm border border-border px-1.5 text-xs text-muted-foreground">
            {children}
        </span>
    )
}

/** One thing's title over its code, and whatever it is wearing. */
function Head({ thing, children }: { thing: Addressable; children: ReactNode }) {
    const heading = headingOf(thing)
    return (
        <p className="flex flex-wrap items-center gap-2">
            <span className={heading.named ? 'text-sm font-semibold' : 'font-mono text-sm font-semibold'}>
                {heading.title}
            </span>
            {children}
            {heading.code !== null && (
                <span className="font-mono text-xs text-muted-foreground">{heading.code}</span>
            )}
        </p>
    )
}

/** One fact, beside its label. */
function Fact({ label, children }: { label: string; children: ReactNode }) {
    return (
        <div className="flex flex-wrap items-baseline gap-2">
            <dt className="w-32 shrink-0 text-xs text-muted-foreground">{label}</dt>
            <dd className="min-w-0 text-sm">{children}</dd>
        </div>
    )
}
