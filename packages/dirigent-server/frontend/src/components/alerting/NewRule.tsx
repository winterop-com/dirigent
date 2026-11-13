import { useEffect, useState } from 'react'

import { Field, TargetPicker } from '@/components/alerting/fields'
import { WindowedSource } from '@/components/pipeline/WindowedSource'
import { ProgramReference } from '@/components/pipeline/ProgramReference'
import { Picker } from '@/components/Picker'
import { Refusal } from '@/components/Refusal'
import { Segmented } from '@winterop-com/sokkel-ui/Segmented'
import { DialogShell } from '@winterop-com/sokkel-ui/DialogShell'
import { Label } from '@winterop-com/sokkel-ui/primitives/label'
import { useMayWrite } from '@/hooks/use-may-write'
import {
    ANY_IMPORTANCE,
    BODY_HINT,
    floorChosen,
    given,
    IMPORTANCE_FLOORS,
    LOG_TARGET,
    SCOPES,
    SUBJECT_HINT,
    targetChosen,
    targetOptions,
    TEMPLATE_MEDIA_TYPE,
    unreadyRule,
} from '@/lib/alert-form'
import { ALERT_EVENTS, createRule, type AlertEvent, type AlertScope } from '@/lib/alerting'
import type { Problem } from '@/lib/api'
import type { ConnectionOut } from '@/lib/connections'
import { DIALOG_WORDS } from '@/lib/design-system'
import { headingOf } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import type { PickerOption } from '@/lib/picker'
import { byTitle, readAllPipelines, type Importance } from '@/lib/pipelines'
import { refusalOf } from '@/lib/refusal'
import { firstShut } from '@/lib/roles'

/** What a rule is declared with when nobody says otherwise: no window at all. */
const NO_THROTTLE = '0s'

/** What a screen reader and a test call the body pane. */
const BODY_LABEL = LABELS.alerting.body_pane

/**
 * Declare one rule: an event, at a scope, through one channel.
 *
 * A RULE NAMES ONE TARGET. The channel is a connection and the notifier is that connection's
 * kind, so there is one picker and no pair to disagree -- and the row somebody chose says
 * underneath it which sender it implied.
 *
 * THIS DIALOG DECLARES; IT DOES NOT SEND. A rule fires when a run settles, so nothing here
 * proves a channel works -- Send a test is the verb that does, and the footer says so.
 */
export function NewRule({
    open,
    onOpenChange,
    notifiers,
    connections,
    onCreated,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    notifiers: readonly string[]
    connections: readonly ConnectionOut[]
    onCreated: () => void
}) {
    const [code, setCode] = useState('')
    const [named, setNamed] = useState('')
    const [description, setDescription] = useState('')
    const [event, setEvent] = useState<AlertEvent>('run_failed')
    const [scope, setScope] = useState<AlertScope>('global')
    const [pipeline, setPipeline] = useState('')
    const [floor, setFloor] = useState<Importance | typeof ANY_IMPORTANCE>(ANY_IMPORTANCE)
    const [connection, setConnection] = useState(LOG_TARGET)
    const [template, setTemplate] = useState('')
    const [body, setBody] = useState('')
    const [throttle, setThrottle] = useState(NO_THROTTLE)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)

    const pipelines = usePipelines(open)
    const write = useMayWrite()
    const shut = firstShut(write.why, unreadyRule({ code, scope, pipeline, throttle }))

    const send = () => {
        setBusy(true)
        setProblem(null)
        void createRule({
            code: code.trim(),
            name: given(named),
            description: given(description),
            event,
            scope,
            pipeline: scope === 'pipeline' ? pipeline : null,
            importance: floorChosen(floor),
            connection: targetChosen(connection),
            template: given(template),
            body: given(body),
            throttle: throttle.trim(),
        })
            .then(
                () => {
                    onCreated()
                    setCode('')
                    setNamed('')
                    setDescription('')
                    setTemplate('')
                    setBody('')
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
        <DialogShell
            words={DIALOG_WORDS}
            open={open}
            onOpenChange={onOpenChange}
            width="xl"
            title={LABELS.alerting.new_rule.button}
            footer={LABELS.alerting.declare_only}
            confirm={{
                label: LABELS.action.create.verb,
                busy,
                busyLabel: LABELS.action.create.busy,
                why: shut,
                onConfirm: send,
            }}
        >
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <Field
                    id="rule-code"
                    label={LABELS.word.code}
                    value={code}
                    onChange={setCode}
                    placeholder={LABELS.alerting.code_placeholder}
                    mono
                />
                <Field
                    id="rule-name"
                    label={LABELS.word.name.label}
                    value={named}
                    onChange={setNamed}
                    placeholder={LABELS.alerting.name_placeholder}
                />
            </div>

            <Field
                id="rule-description"
                label={LABELS.word.description}
                value={description}
                onChange={setDescription}
                placeholder={LABELS.alerting.description_placeholder}
            />

            <div className="space-y-2">
                <Label>{LABELS.word.event}</Label>
                <Segmented
                    label={LABELS.word.event}
                    size="md"
                    value={event}
                    options={ALERT_EVENTS.map((one) => ({
                        value: one,
                        label: LABELS.alerting.event[one],
                    }))}
                    onValueChange={setEvent}
                />
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div className="space-y-2">
                    <Label>{LABELS.word.scope}</Label>
                    <Segmented
                        label={LABELS.word.scope}
                        size="md"
                        value={scope}
                        options={SCOPES}
                        onValueChange={setScope}
                    />
                </div>
                {scope === 'pipeline' && (
                    <div className="space-y-2">
                        <Label htmlFor="rule-pipeline">{LABELS.word.pipeline.label}</Label>
                        <Picker
                            id="rule-pipeline"
                            label={LABELS.word.pipeline.label}
                            value={pipeline}
                            options={pipelines}
                            placeholder={LABELS.alerting.pipeline_search}
                            onChange={setPipeline}
                        />
                    </div>
                )}
            </div>

            <div className="space-y-2">
                <Label>{LABELS.word.importance}</Label>
                <p className="text-xs text-faint">{LABELS.alerting.importance_hint}</p>
                <Segmented
                    label={LABELS.word.importance}
                    size="md"
                    value={floor}
                    options={IMPORTANCE_FLOORS}
                    onValueChange={setFloor}
                />
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <TargetPicker
                    id="rule-connection"
                    options={targetOptions(notifiers, connections)}
                    value={connection}
                    onChange={setConnection}
                />
            </div>

            <Field
                id="rule-subject"
                label={LABELS.word.subject}
                value={template}
                onChange={setTemplate}
                placeholder={LABELS.alerting.subject_placeholder}
                mono
                hint={SUBJECT_HINT}
            />

            <div className="space-y-2">
                <Label>{LABELS.word.body}</Label>
                <p className="text-xs text-faint">{BODY_HINT}</p>
                <WindowedSource
                    name={BODY_LABEL}
                    label={BODY_LABEL}
                    windowLabel={LABELS.alerting.body_pane_windowed(BODY_LABEL)}
                    value={body}
                    mediaType={TEMPLATE_MEDIA_TYPE}
                    placeholder={LABELS.alerting.body_placeholder}
                    className="h-40 min-h-32"
                    aside={<ProgramReference mediaType={TEMPLATE_MEDIA_TYPE} />}
                    onChange={setBody}
                />
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <Field
                    id="rule-throttle"
                    label={LABELS.word.throttle}
                    value={throttle}
                    onChange={setThrottle}
                    placeholder={LABELS.alerting.throttle_placeholder}
                    mono
                />
            </div>

            {problem !== null && <Refusal problem={problem} />}
        </DialogShell>
    )
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
