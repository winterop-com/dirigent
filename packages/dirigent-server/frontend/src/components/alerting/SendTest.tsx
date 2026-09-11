import { useEffect, useState } from 'react'

import { ConnectionPicker, Field, NotifierPicker } from '@/components/alerting/fields'
import { Instant } from '@/components/Instant'
import { Refusable } from '@/components/Refusable'
import { Refusal } from '@/components/Refusal'
import { StatusChip } from '@/components/run/StatusChip'
import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { useMayWrite } from '@/hooks/use-may-write'
import { needsConnection, unreadyTest } from '@/lib/alert-form'
import { deliverySettled, readNotification, sendTest, type NotificationOut } from '@/lib/alerting'
import type { Problem } from '@/lib/api'
import { refusalOf } from '@/lib/refusal'
import { firstShut } from '@/lib/roles'

/** How often the queued row is read back while it is still moving. */
const POLL_MS = 1000

/** How long the dialog watches before it stops asking and says where the row is. */
const POLL_LIMIT_MS = 60_000

/** What a test message says when nobody changes it, which is the server's own default. */
const DEFAULT_SUBJECT = 'dirigent test alert'

/** What the dialog opens with, which a rule's panel fills in from the rule. */
export interface TestDraft {
    notifier: string
    connection: string
    subject: string
}

/** Nothing chosen: the dialog opened from the screen's own verb rather than from a rule. */
export const EMPTY_TEST: TestDraft = { notifier: '', connection: '', subject: '' }

/**
 * Send one message through a channel and watch it land.
 *
 * THE DIALOG STAYS OPEN UNTIL THE ROW SETTLES. A test that closed on "queued" would say only
 * that the API accepted it, which is the one thing nobody was asking: what a test answers is
 * whether the channel took the message, and that is known when a worker has tried. So the row
 * is read back on a cadence until it is sent or failed, and a refusal shows the sentence the
 * channel itself gave.
 *
 * IT IS THE SAME DIALOG A RULE OPENS. A rule's panel passes its own notifier and connection in,
 * so proving the channel a rule uses is the rule's own verb rather than a form to fill in twice.
 */
export function SendTest({
    open,
    draft,
    onOpenChange,
    notifiers,
    onQueued,
    onOpenQueue,
}: {
    open: boolean
    draft: TestDraft
    onOpenChange: (open: boolean) => void
    notifiers: readonly string[]
    /** Called once the message is queued, so the listing behind shows the new row. */
    onQueued: () => void
    /** Called with the notification the dialog is watching, to show it in the queue. */
    onOpenQueue: (id: string) => void
}) {
    // The boxes are initialised from the draft and never reset by an effect: the screen gives
    // this dialog a fresh `key` each time it is opened, so a rule's own channel arrives as the
    // initial state rather than as a write that has to undo whatever the last send left behind.
    const [notifier, setNotifier] = useState(draft.notifier)
    const [connection, setConnection] = useState(draft.connection)
    const [subject, setSubject] = useState(draft.subject)
    const [watching, setWatching] = useState<string | null>(null)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)

    const delivery = useDelivery(watching)
    const write = useMayWrite()

    // The listing behind reads the queue once when the message is accepted and again when it
    // settles, because between those two the row moved and nothing else would say so.
    const settled = delivery !== null && deliverySettled(delivery.status) ? delivery.id : null
    useEffect(() => {
        if (settled !== null) onQueued()
        // The callback is the screen's own reload and is stable; the row settling is the event.
        // oxlint-disable-next-line react-hooks/exhaustive-deps
    }, [settled])
    const shut = firstShut(write.why, unreadyTest(notifier, connection))

    const send = () => {
        setBusy(true)
        setProblem(null)
        setWatching(null)
        void sendTest({
            notifier,
            connection: needsConnection(notifier) ? connection : null,
            ...(subject.trim() === '' ? {} : { subject: subject.trim() }),
        })
            .then(
                (queued) => {
                    setWatching(queued.notification_id)
                    onQueued()
                },
                (error: unknown) => {
                    setProblem(refusalOf(error))
                },
            )
            .finally(() => {
                setBusy(false)
            })
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-lg" showCloseButton={false}>
                <DialogHeader>
                    <DialogTitle>Send a test</DialogTitle>
                    <DialogDescription>
                        The message goes through the same queue a real alert does, and a worker delivers it.
                    </DialogDescription>
                </DialogHeader>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <NotifierPicker
                        id="test-notifier"
                        notifiers={notifiers}
                        value={notifier}
                        onChange={(picked) => {
                            setNotifier(picked)
                            setConnection('')
                        }}
                    />
                    {needsConnection(notifier) && (
                        <ConnectionPicker
                            id="test-connection"
                            kind={notifier}
                            value={connection}
                            onChange={setConnection}
                        />
                    )}
                </div>

                <Field
                    id="test-subject"
                    label="Subject"
                    value={subject}
                    onChange={setSubject}
                    placeholder={DEFAULT_SUBJECT}
                />

                {problem !== null && <Refusal problem={problem} />}
                {delivery !== null && <Delivery row={delivery} />}

                <DialogFooter>
                    <DialogClose render={<Button variant="ghost" />}>Close</DialogClose>
                    {watching !== null && (
                        <Button
                            variant="outline"
                            onClick={() => {
                                onOpenQueue(watching)
                            }}
                        >
                            Open in the queue
                        </Button>
                    )}
                    <Refusable why={shut}>
                        <Button disabled={busy || shut !== undefined} title={shut} onClick={send}>
                            {watching === null ? 'Send' : 'Send again'}
                        </Button>
                    </Refusable>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

/** Where the message got to: the row's own state, and the sentence behind a refusal. */
function Delivery({ row }: { row: NotificationOut }) {
    return (
        <div
            className="space-y-2 rounded-lg border border-border bg-secondary/40 p-3"
            data-testid="test-delivery"
            aria-live="polite"
        >
            <p className="flex flex-wrap items-center gap-2">
                <StatusChip status={row.status} />
                <span className="text-sm">{row.subject}</span>
            </p>
            <p className="text-xs text-muted-foreground">
                {row.status === 'sent' ? (
                    <>
                        Delivered <Instant at={row.sent_at} />.
                    </>
                ) : row.status === 'failed' ? (
                    <>
                        Given up after {row.attempt} of {row.max_attempts} attempts.
                    </>
                ) : row.attempt === 0 ? (
                    'Queued for the next worker pass.'
                ) : (
                    <>
                        Attempt {row.attempt} of {row.max_attempts}, next try{' '}
                        <Instant at={row.available_at} />.
                    </>
                )}
            </p>
            {row.error !== null && <p className="text-xs break-words text-critical">{row.error}</p>}
        </div>
    )
}

/**
 * Read one notification back until it settles.
 *
 * A POLL STOPS. Nothing moves a sent or failed row, so the timer clears itself the moment the
 * row reaches one of the two -- and it gives up after a minute either way, because a queue with
 * no worker on it would otherwise be asked forever.
 */
function useDelivery(id: string | null): NotificationOut | null {
    // The answer is held beside the question it answers, so a row read for the last send is
    // not on screen while the next one is still being queued -- and nothing has to be blanked
    // from inside the effect to make that true.
    const [held, setHeld] = useState<{ id: string; row: NotificationOut } | null>(null)

    useEffect(() => {
        if (id === null) return
        let live = true
        let timer: ReturnType<typeof setTimeout> | undefined
        const until = Date.now() + POLL_LIMIT_MS
        const ask = () => {
            void readNotification(id).then(
                (answer) => {
                    if (!live) return
                    setHeld({ id, row: answer })
                    if (deliverySettled(answer.status) || Date.now() > until) return
                    timer = setTimeout(ask, POLL_MS)
                },
                () => {
                    // A read that failed leaves what was last known on screen; the queue below
                    // is the other place the row is, and it is one click away.
                },
            )
        }
        ask()
        return () => {
            live = false
            if (timer !== undefined) clearTimeout(timer)
        }
    }, [id])

    return held !== null && held.id === id ? held.row : null
}
