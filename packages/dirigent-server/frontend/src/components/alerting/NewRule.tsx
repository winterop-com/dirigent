import { useEffect, useState } from 'react'

import { TargetPicker } from '@/components/alerting/fields'
import { WindowedSource } from '@/components/pipeline/WindowedSource'
import { ProgramReference } from '@/components/pipeline/ProgramReference'
import { AsyncSelect } from '@winterop-com/sokkel-ui/AsyncSelect'
import { Refusal } from '@/components/Refusal'
import { Segmented } from '@winterop-com/sokkel-ui/Segmented'
import { DialogShell } from '@winterop-com/sokkel-ui/DialogShell'
import { Field } from '@winterop-com/sokkel-ui/Field'
import { TextField } from '@winterop-com/sokkel-ui/TextField'
import { useMayWrite } from '@/hooks/use-may-write'
import {
    ANY_IMPORTANCE,
    BODY_HINT,
    floorChosen,
    given,
    IMPORTANCE_FLOORS,
    LOG_TARGET,
    ruleCodeIssue,
    SCOPES,
    SUBJECT_HINT,
    targetChosen,
    targetOptions,
    TEMPLATE_MEDIA_TYPE,
    throttleIssue,
    unreadyRule,
} from '@/lib/alert-form'
import { ALERT_EVENTS, createRule, type AlertEvent, type AlertScope } from '@/lib/alerting'
import type { Problem } from '@/lib/api'
import type { ConnectionOut } from '@/lib/connections'
import { DIALOG_WORDS, FIELD_WORDS, pickerWords } from '@/lib/design-system'
import { headingOf } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import { matchesOption, type PickerOption } from '@/lib/picker'
import { byTitle, readAllPipelines, type Importance } from '@/lib/pipelines'
import { refusalOf } from '@/lib/refusal'
import { firstShut } from '@/lib/roles'

/** What a rule is declared with when nobody says otherwise: no window at all. */
const NO_THROTTLE = '0s'

/** No box left yet: what a dialog opens on. */
const NONE_LEFT = { code: false, throttle: false }

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
    // Which boxes have been left once, so a required one says so only after somebody was there.
    const [left, setLeft] = useState(NONE_LEFT)

    const pipelines = usePipelines(open)
    const write = useMayWrite()
    const shut = firstShut(write.why, unreadyRule({ code, scope, pipeline, throttle }))
    const codeIssue = left.code ? (ruleCodeIssue(code) ?? null) : null

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
                    setLeft(NONE_LEFT)
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
            onOpenChange={(next) => {
                if (!next) setLeft(NONE_LEFT)
                onOpenChange(next)
            }}
            width="xl"
            title={LABELS.alerting.new_rule.button}
            footer={LABELS.alerting.declare_only}
            status={problem === null ? undefined : <Refusal problem={problem} />}
            confirm={{
                label: LABELS.action.create.verb,
                busy,
                busyLabel: LABELS.action.create.busy,
                why: shut,
                onConfirm: send,
            }}
        >
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <TextField
                    id="rule-code"
                    label={LABELS.word.code}
                    required
                    requiredMark="word"
                    words={FIELD_WORDS}
                    error={codeIssue}
                    mono
                    autoComplete="off"
                    value={code}
                    placeholder={LABELS.alerting.code_placeholder}
                    onChange={setCode}
                    onBlur={() => {
                        setLeft((was) => ({ ...was, code: true }))
                    }}
                />
                <TextField
                    id="rule-name"
                    label={LABELS.word.name.label}
                    value={named}
                    onChange={setNamed}
                    placeholder={LABELS.alerting.name_placeholder}
                    autoComplete="off"
                />
            </div>

            <TextField
                id="rule-description"
                label={LABELS.word.description}
                value={description}
                onChange={setDescription}
                placeholder={LABELS.alerting.description_placeholder}
                autoComplete="off"
            />

            <Field id="rule-event" label={LABELS.word.event}>
                <Segmented
                    id="rule-event"
                    label={LABELS.word.event}
                    size="md"
                    value={event}
                    options={ALERT_EVENTS.map((one) => ({
                        value: one,
                        label: LABELS.alerting.event[one],
                    }))}
                    onValueChange={setEvent}
                />
            </Field>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <Field id="rule-scope" label={LABELS.word.scope}>
                    <Segmented
                        id="rule-scope"
                        label={LABELS.word.scope}
                        size="md"
                        value={scope}
                        options={SCOPES}
                        onValueChange={setScope}
                    />
                </Field>
                {scope === 'pipeline' && (
                    <Field
                        id="rule-pipeline"
                        label={LABELS.word.pipeline.label}
                        required
                        requiredMark="word"
                        words={FIELD_WORDS}
                    >
                        <AsyncSelect
                            id="rule-pipeline"
                            items={pipelines}
                            filter={matchesOption}
                            itemKey={(option) => option.value}
                            itemLabel={(option) => option.label}
                            itemMeta={(option) => option.aside}
                            monoMeta
                            metaInValue
                            value={pipelines.find((option) => option.value === pipeline) ?? null}
                            words={pickerWords(LABELS.alerting.pipeline_search)}
                            onValueChange={(picked) => {
                                setPipeline(picked === null ? '' : picked.value)
                            }}
                        />
                    </Field>
                )}
            </div>

            <Field
                id="rule-importance"
                label={LABELS.word.importance}
                description={LABELS.alerting.importance_hint}
            >
                <Segmented
                    id="rule-importance"
                    label={LABELS.word.importance}
                    size="md"
                    value={floor}
                    options={IMPORTANCE_FLOORS}
                    onValueChange={setFloor}
                />
            </Field>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <TargetPicker
                    id="rule-connection"
                    options={targetOptions(notifiers, connections)}
                    value={connection}
                    onChange={setConnection}
                />
            </div>

            <TextField
                id="rule-subject"
                label={LABELS.word.subject}
                value={template}
                onChange={setTemplate}
                placeholder={LABELS.alerting.subject_placeholder}
                autoComplete="off"
                mono
                help={SUBJECT_HINT}
            />

            <Field id="rule-body" label={LABELS.word.body} description={BODY_HINT}>
                <WindowedSource
                    id="rule-body"
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
            </Field>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <TextField
                    id="rule-throttle"
                    label={LABELS.word.throttle}
                    value={throttle}
                    onChange={setThrottle}
                    onBlur={() => {
                        setLeft((was) => ({ ...was, throttle: true }))
                    }}
                    error={left.throttle ? (throttleIssue(throttle) ?? null) : null}
                    placeholder={LABELS.alerting.throttle_placeholder}
                    autoComplete="off"
                    mono
                />
            </div>
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
                        return {
                            value: row.code,
                            label: heading.title,
                            aside: heading.code ?? '',
                        }
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
