import { useCallback, useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { Surface } from '@winterop-com/sokkel-ui/Section'
import { Description } from '@/components/Description'
import { Instant, instantFact } from '@/components/Instant'
import {
    DescriptionList,
    DescriptionListGroup,
    type Description as FactItem,
} from '@winterop-com/sokkel-ui/DescriptionList'
import { Mark } from '@/components/Mark'
import { WindowedSource } from '@/components/pipeline/WindowedSource'
import { ProgramReference } from '@/components/pipeline/ProgramReference'
import { Refusal, sayRefusal } from '@/components/Refusal'
import { StatusChip } from '@winterop-com/sokkel-ui/StatusChip'
import { Field } from '@winterop-com/sokkel-ui/Field'
import { TextField } from '@winterop-com/sokkel-ui/TextField'
import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import { ConfirmDialog } from '@winterop-com/sokkel-ui/DialogShell'
import { ProblemLine } from '@winterop-com/sokkel-ui/Problem'
import { Question } from '@/components/Question'
import { DIALOG_WORDS } from '@/lib/library-words'
import { useMayWrite } from '@/hooks/use-may-write'
import { usePaged } from '@/hooks/use-paged'
import { BODY_HINT, given, SUBJECT_HINT, TEMPLATE_MEDIA_TYPE } from '@/lib/alert-form'
import {
    deleteRule,
    importanceNote,
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
import { kindGlyph } from '@/lib/glyphs'
import { headingOf, type Addressable } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import { refusalLine, refusalOf } from '@/lib/refusal'
import { InlineCode } from '@winterop-com/sokkel-ui/InlineCode'
import { Chip } from '@winterop-com/sokkel-ui/Chip'
import { TextLink } from '@winterop-com/sokkel-ui/TextLink'

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
    const [deleting, setDeleting] = useState(false)
    const [removing, setRemoving] = useState(false)
    const [refused, setRefused] = useState<Problem | null>(null)
    // Which rule the form is open on rather than whether it is: this panel is one component
    // the listing re-renders with whichever rule is chosen, so a form left open would other-
    // wise open on the next rule with the last one's text in it.
    const [editingCode, setEditingCode] = useState<string | null>(null)
    const editing = editingCode === rule.code
    const write = useMayWrite()
    const declared = rule.declared ? LABELS.alerting.declared_why(rule.pipeline ?? '') : undefined
    const rewrite = {
        may: write.may && declared === undefined,
        why: write.why ?? declared,
    }
    const floor = importanceNote(rule.importance)
    const settings: FactItem[] = [
        { term: LABELS.word.event, value: LABELS.alerting.event[rule.event] },
        {
            term: LABELS.word.scope,
            value: (
                <span className="flex flex-wrap items-baseline gap-x-1.5">
                    {scopeNote(rule)}
                    {floor !== null && <span className="text-xs text-muted-foreground">{floor}</span>}
                </span>
            ),
        },
        {
            term: LABELS.word.delivers_through,
            value: <Target notifier={rule.notifier} connection={rule.connection} />,
        },
        { term: LABELS.word.throttle, value: throttleNote(rule.throttle) },
    ]
    const text: FactItem[] = [
        {
            term: LABELS.word.subject,
            value: (
                <span className="flex flex-wrap items-baseline gap-2">
                    {rule.template === null ? (
                        <span className="text-muted-foreground">{LABELS.word.none}</span>
                    ) : (
                        <span className="font-mono text-xs break-all">{rule.template}</span>
                    )}
                    <Button
                        variant="ghost"
                        size="xs"
                        reason={rewrite.why}
                        onClick={() => {
                            setEditingCode(rule.code)
                        }}
                    >
                        {LABELS.action.edit}
                    </Button>
                </span>
            ),
        },
        ...(rule.body === null
            ? []
            : [
                  {
                      term: LABELS.word.body,
                      wide: true,
                      value: (
                          <span className="line-clamp-3 font-mono text-xs break-words whitespace-pre-wrap">
                              {rule.body}
                          </span>
                      ),
                  },
              ]),
    ]
    const lastSent: FactItem = {
        term: LABELS.alerting.last_sent,
        value:
            rule.last_sent_at === null ? (
                <span className="text-muted-foreground">{LABELS.word.never}</span>
            ) : (
                <Instant at={rule.last_sent_at} />
            ),
    }

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
        setRemoving(true)
        setRefused(null)
        void deleteRule(rule.code)
            .then(
                () => {
                    setDeleting(false)
                    onDeleted()
                },
                (error: unknown) => {
                    setRefused(refusalOf(error))
                },
            )
            .finally(() => {
                setRemoving(false)
            })
    }

    return (
        <div className="space-y-4 p-4">
            <Head thing={rule}>
                {rule.paused && <Chip>{LABELS.state.armed.paused}</Chip>}
                {!rule.active && <Chip>{LABELS.state.armed.off}</Chip>}
                {rule.declared && <Chip>{LABELS.alerting.declared}</Chip>}
            </Head>
            <Description text={rule.description} />

            {editing ? (
                <DescriptionListGroup termWidth="auto" className="gap-y-2">
                    <DescriptionList items={settings} />
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
                    <DescriptionList items={[lastSent]} />
                </DescriptionListGroup>
            ) : (
                <DescriptionList termWidth="auto" items={[...settings, ...text, lastSent]} />
            )}

            <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" disabled={busy} reason={write.why} onClick={toggle}>
                    {rule.paused ? LABELS.action.resume : LABELS.action.pause}
                </Button>
                <Button variant="outline" size="sm" reason={write.why} onClick={onTest}>
                    {LABELS.action.asks(LABELS.action.send_test)}
                </Button>
                <Button
                    variant="outline"
                    size="sm"
                    className="ml-auto"
                    destructiveHover
                    disabled={busy}
                    reason={rewrite.why}
                    onClick={() => {
                        setRefused(null)
                        setDeleting(true)
                    }}
                >
                    {LABELS.action.delete.verb}
                </Button>
            </div>

            <ConfirmDialog
                open={deleting}
                onOpenChange={setDeleting}
                question={<Question ask={LABELS.alerting.delete_ask} code={rule.code} />}
                confirm={{
                    label: LABELS.action.delete.verb,
                    onConfirm: remove,
                    destructive: true,
                    why: rewrite.why,
                    busy: removing,
                    busyLabel: LABELS.action.delete.busy,
                }}
                words={DIALOG_WORDS}
                status={refused === null ? undefined : <ProblemLine>{refusalLine(refused)}</ProblemLine>}
            />

            <div className="space-y-2">
                <p className="text-xs text-muted-foreground">{LABELS.alerting.recent_deliveries}</p>
                {!state.read && <p className="text-xs text-faint">{LABELS.shell.reading}</p>}
                {state.read && mine.length === 0 && (
                    <p className="text-xs text-faint">{LABELS.alerting.deliveries_empty}</p>
                )}
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

    const subjectId = `rule-${rule.code}-subject`
    const bodyId = `rule-${rule.code}-body`

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
        <Surface tone="well" pad className="space-y-3">
            <TextField
                id={subjectId}
                label={LABELS.word.subject}
                mono
                autoComplete="off"
                value={template}
                placeholder={LABELS.alerting.subject_placeholder}
                onChange={setTemplate}
                help={SUBJECT_HINT}
            />

            <Field id={bodyId} label={LABELS.word.body} description={BODY_HINT}>
                <WindowedSource
                    id={bodyId}
                    name={LABELS.alerting.body_pane}
                    label={LABELS.alerting.body_pane}
                    windowLabel={LABELS.alerting.body_pane_windowed(LABELS.alerting.body_pane)}
                    value={body}
                    mediaType={TEMPLATE_MEDIA_TYPE}
                    placeholder={LABELS.alerting.body_placeholder}
                    className="h-40 min-h-32"
                    aside={<ProgramReference mediaType={TEMPLATE_MEDIA_TYPE} />}
                    onChange={setBody}
                />
            </Field>

            {problem !== null && <Refusal problem={problem} />}

            <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={onDone}>
                    {LABELS.action.cancel}
                </Button>
                <Button size="sm" disabled={busy} onClick={save}>
                    {busy ? LABELS.action.save.busy : LABELS.action.save.verb}
                </Button>
            </div>
        </Surface>
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

            {/* A test is raised by nothing, and the event on its row is a placeholder the queue
                needed rather than something that happened -- so it is not drawn. */}
            <DescriptionList
                termWidth="auto"
                items={[
                    ...(notification.rule === null
                        ? [
                              {
                                  term: LABELS.alerting.raised_by,
                                  value: (
                                      <span className="text-muted-foreground">
                                          {LABELS.alerting.raised_by_test}
                                      </span>
                                  ),
                              },
                          ]
                        : [
                              {
                                  term: LABELS.word.event,
                                  value: LABELS.alerting.event[notification.event],
                              },
                              {
                                  term: LABELS.word.rule.label,
                                  value: notification.rule,
                                  code: true,
                              },
                          ]),
                    {
                        term: LABELS.word.delivers_through,
                        value: (
                            <Channel notifier={notification.notifier} connection={notification.connection} />
                        ),
                    },
                    {
                        term: LABELS.word.run.label,
                        value: <Run notification={notification} />,
                    },
                    {
                        term: LABELS.alerting.queued_at,
                        value: instantFact(notification.created_at),
                    },
                    notification.status === 'sent'
                        ? {
                              term: LABELS.alerting.sent_at,
                              value: instantFact(notification.sent_at),
                          }
                        : {
                              term: LABELS.alerting.next_try,
                              value: instantFact(notification.available_at),
                          },
                    {
                        term: LABELS.word.attempt.heading,
                        value: LABELS.alerting.attempts_of.bare(
                            notification.attempt,
                            notification.max_attempts,
                        ),
                        numeric: true,
                    },
                ]}
            />

            {notification.error !== null && (
                <div className="space-y-1">
                    <p className="text-xs text-muted-foreground">{LABELS.alerting.channel_said}</p>
                    <p className="text-xs break-words text-critical">{notification.error}</p>
                    <p className="text-xs text-faint">{LABELS.alerting.latest_refusal_only}</p>
                </div>
            )}

            <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" disabled={busy} reason={write.why} onClick={again}>
                    {LABELS.action.retry_now}
                </Button>
                {notification.run_id !== null && (
                    <Button variant="outline" size="sm" render={<Link to={`/runs/${notification.run_id}`} />}>
                        {LABELS.alerting.open_run}
                    </Button>
                )}
            </div>
        </div>
    )
}

const notificationId = (row: NotificationOut) => row.id

/**
 * The one target a rule names: the connection it delivers through, or the process log.
 *
 * A TARGET IS A CHANNEL, AND IT IS DRAWN AS ONE: the kind's mark, then the code. The sender
 * follows from the connection, so the mark is what says which channel this is, and the word
 * beside it would be saying that twice. A rule that names no connection has only the sender to
 * name, and that sender is `log`.
 */
export function Target({ notifier, connection }: { notifier: string; connection: string | null }) {
    return (
        <span className="flex min-w-0 items-center gap-1.5">
            <Mark glyph={kindGlyph(notifier)} />
            {connection === null ? (
                <span className="truncate text-sm" title={notifier}>
                    {notifier}
                </span>
            ) : (
                <InlineCode value={connection} bare size="xs" />
            )}
        </span>
    )
}

/** The channel a message leaves by: the notifier, and the credential where there is one. */
export function Channel({ notifier, connection }: { notifier: string; connection: string | null }) {
    return (
        <span className="flex min-w-0 flex-wrap items-baseline gap-1.5">
            <span className="text-sm">{notifier}</span>
            {connection !== null && <InlineCode value={connection} tone="muted" bare size="xs" />}
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
    if (notification.run_id === null)
        return <span className="text-muted-foreground">{LABELS.alerting.no_run}</span>
    const named = notification.run_pipeline ?? LABELS.alerting.a_run
    return (
        <TextLink variant="data" href={`/runs/${notification.run_id}`}>
            <span className="text-sm">{named}</span>
            {notification.run_started_at !== null && (
                <Instant
                    focusable={false}
                    className="ml-1.5 text-xs text-muted-foreground"
                    at={notification.run_started_at}
                />
            )}
        </TextLink>
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
