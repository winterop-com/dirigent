import { useEffect, useState } from 'react'

import { ConnectionPicker, Field, NotifierPicker } from '@/components/alerting/fields'
import { Picker } from '@/components/Picker'
import { Refusable } from '@/components/Refusable'
import { Refusal } from '@/components/Refusal'
import { Segmented } from '@/components/Segmented'
import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogClose,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { useMayWrite } from '@/hooks/use-may-write'
import { EVENT_LABELS, needsConnection, SCOPES, SUBJECT_HINT, unreadyRule } from '@/lib/alert-form'
import { ALERT_EVENTS, createRule, type AlertEvent, type AlertScope } from '@/lib/alerting'
import type { Problem } from '@/lib/api'
import { headingOf } from '@/lib/identity'
import type { PickerOption } from '@/lib/picker'
import { byTitle, readAllPipelines } from '@/lib/pipelines'
import { refusalOf } from '@/lib/refusal'
import { firstShut } from '@/lib/roles'

/** What a rule is declared with when nobody says otherwise: no window at all. */
const NO_THROTTLE = '0s'

/**
 * Declare one rule: an event, at a scope, through a channel.
 *
 * A CHANNEL IS A NOTIFIER AND A CREDENTIAL. The wire takes both, and which credential is valid
 * depends on which channel was chosen -- so the connection picker offers the connections of the
 * notifier's own kind and is not drawn at all for `log`, which needs none. Choosing a different
 * notifier drops the connection beside it rather than carrying a credential of the wrong kind
 * across.
 *
 * THIS DIALOG DECLARES; IT DOES NOT SEND. A rule fires when a run settles, so nothing here
 * proves a channel works -- Send a test is the verb that does, and the footer says so.
 */
export function NewRule({
    open,
    onOpenChange,
    notifiers,
    onCreated,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    notifiers: readonly string[]
    onCreated: () => void
}) {
    const [code, setCode] = useState('')
    const [named, setNamed] = useState('')
    const [description, setDescription] = useState('')
    const [event, setEvent] = useState<AlertEvent>('run_failed')
    const [scope, setScope] = useState<AlertScope>('global')
    const [pipeline, setPipeline] = useState('')
    const [notifier, setNotifier] = useState('')
    const [connection, setConnection] = useState('')
    const [template, setTemplate] = useState('')
    const [throttle, setThrottle] = useState(NO_THROTTLE)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)

    const pipelines = usePipelines(open)
    const write = useMayWrite()
    const shut = firstShut(
        write.why,
        unreadyRule({ code, scope, pipeline, notifier, connection, throttle }),
    )

    const send = () => {
        setBusy(true)
        setProblem(null)
        void createRule({
            code: code.trim(),
            name: given(named),
            description: given(description),
            event,
            notifier,
            scope,
            pipeline: scope === 'pipeline' ? pipeline : null,
            connection: needsConnection(notifier) ? connection : null,
            template: given(template),
            throttle: throttle.trim(),
        })
            .then(
                () => {
                    onCreated()
                    setCode('')
                    setNamed('')
                    setDescription('')
                    setTemplate('')
                    onOpenChange(false)
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
            <DialogContent className="sm:max-w-xl" showCloseButton={false}>
                <DialogHeader>
                    <DialogTitle>New rule</DialogTitle>
                </DialogHeader>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <Field
                        id="rule-code"
                        label="Code"
                        value={code}
                        onChange={setCode}
                        placeholder="ops-slack-failed"
                        mono
                    />
                    <Field id="rule-name" label="Name" value={named} onChange={setNamed} placeholder="Tell the ops channel" />
                </div>

                <Field
                    id="rule-description"
                    label="Description"
                    value={description}
                    onChange={setDescription}
                    placeholder="What this rule is for"
                />

                <div className="space-y-2">
                    <Label>Event</Label>
                    <Segmented
                        label="Event"
                        size="md"
                        value={event}
                        options={ALERT_EVENTS.map((one) => ({ value: one, label: EVENT_LABELS[one] }))}
                        onChoose={setEvent}
                    />
                </div>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <div className="space-y-2">
                        <Label>Scope</Label>
                        <Segmented label="Scope" size="md" value={scope} options={SCOPES} onChoose={setScope} />
                    </div>
                    {scope === 'pipeline' && (
                        <div className="space-y-2">
                            <Label htmlFor="rule-pipeline">Pipeline</Label>
                            <Picker
                                id="rule-pipeline"
                                label="Pipeline"
                                value={pipeline}
                                options={pipelines}
                                placeholder="Search by name or code"
                                onChange={setPipeline}
                            />
                        </div>
                    )}
                </div>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <NotifierPicker
                        id="rule-notifier"
                        notifiers={notifiers}
                        value={notifier}
                        onChange={(picked) => {
                            setNotifier(picked)
                            setConnection('')
                        }}
                    />
                    {needsConnection(notifier) && (
                        <ConnectionPicker
                            id="rule-connection"
                            kind={notifier}
                            value={connection}
                            onChange={setConnection}
                        />
                    )}
                </div>

                <Field
                    id="rule-subject"
                    label="Subject"
                    value={template}
                    onChange={setTemplate}
                    placeholder="${run.pipeline} run ${run.status}"
                    mono
                    hint={SUBJECT_HINT}
                />

                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <Field
                        id="rule-throttle"
                        label="Throttle"
                        value={throttle}
                        onChange={setThrottle}
                        placeholder="15m"
                        mono
                    />
                </div>

                {problem !== null && <Refusal problem={problem} />}

                <DialogFooter>
                    <p className="text-muted-foreground mr-auto self-center text-xs">
                        A rule fires when a run settles. Nothing is sent now.
                    </p>
                    <DialogClose render={<Button variant="ghost" />}>Close</DialogClose>
                    <Refusable why={shut}>
                        <Button disabled={busy || shut !== undefined} title={shut} onClick={send}>
                            {busy ? 'Creating' : 'Create'}
                        </Button>
                    </Refusable>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

/** A box left empty is a field nobody set, which is null on the wire rather than "". */
function given(typed: string): string | null {
    const trimmed = typed.trim()
    return trimmed === '' ? null : trimmed
}

/** The pipelines a scoped rule may watch, read once when the dialog opens. */
function usePipelines(open: boolean): PickerOption[] {
    const [options, setOptions] = useState<PickerOption[]>([])

    useEffect(() => {
        if (!open) return
        let live = true
        void readAllPipelines().then(
            (rows) => {
                if (!live) return
                setOptions(
                    rows.toSorted(byTitle).map((row) => {
                        const heading = headingOf(row)
                        return { value: row.code, label: heading.title, aside: heading.code ?? '' }
                    }),
                )
            },
            () => {
                if (live) setOptions([])
            },
        )
        return () => {
            live = false
        }
    }, [open])

    return options
}
