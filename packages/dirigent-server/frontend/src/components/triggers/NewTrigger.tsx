import { useEffect, useMemo, useState } from 'react'

import { CronField } from '@winterop-com/sokkel-ui/CronField'
import { Field } from '@winterop-com/sokkel-ui/Field'
import { FieldGroup } from '@winterop-com/sokkel-ui/FieldGroup'
import { SelectField } from '@winterop-com/sokkel-ui/SelectField'
import { TextField } from '@winterop-com/sokkel-ui/TextField'
import { Surface } from '@winterop-com/sokkel-ui/Section'
import { AsyncSelect } from '@winterop-com/sokkel-ui/AsyncSelect'
import { GeneratedForm } from '@/components/schema/GeneratedForm'
import {
    SchemaIssueCount,
    useSchemaForm,
    type SchemaFormState,
} from '@winterop-com/sokkel-ui/schema/SchemaForm'
import type { JsonSchema } from '@winterop-com/sokkel-ui/schema/read'
import { Refusal } from '@/components/Refusal'
import { Segmented } from '@winterop-com/sokkel-ui/Segmented'
import { DialogShell } from '@winterop-com/sokkel-ui/DialogShell'
import { Textarea } from '@winterop-com/sokkel-ui/primitives/textarea'
import { useMayWrite } from '@/hooks/use-may-write'
import { type JsonMap, type Problem } from '@/lib/api'
import { DIALOG_WORDS, FIELD_WORDS, pickerWords } from '@/lib/design-system'
import { formatMoment } from '@/lib/format'
import { ICONS } from '@/lib/icons'
import { headingOf } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import { matchesOption, type PickerOption } from '@/lib/picker'
import { byTitle, paramsOf, priorityOf, readAllPipelines, readPipeline } from '@/lib/pipelines'
import { refusalOf } from '@/lib/refusal'
import { firstShut } from '@/lib/roles'
import type { RunPriority } from '@/lib/runs'
import { formSchema, hasFields } from '@/lib/form-schema'
import {
    browserZone,
    CRON_FIELD_WORDS,
    FIRINGS_READ,
    firingOf,
    given,
    INHERITED,
    PRIORITIES,
    readCron,
    readValues,
    unreadySchedule,
    writeValues,
    zoneOffset,
    zonesOffered,
} from '@/lib/trigger-form'
import { createSchedule, type ScheduleIn } from '@/lib/triggers'
import { useFirings, type Reading } from '@/hooks/use-firings'

/** No box left yet: what a dialog opens on. */
const NONE_LEFT = { code: false, expression: false }

/** Which clock a new schedule is declared with. Exactly one, which is what the core accepts. */
type Clock = 'cron' | 'interval' | 'at'

const CLOCK = LABELS.triggers.schedule.dialog.clock

const CLOCKS: { value: Clock; label: string; hint: string }[] = [
    { value: 'cron', label: CLOCK.cron.name, hint: CLOCK.cron.hint },
    { value: 'interval', label: CLOCK.interval.name, hint: CLOCK.interval.hint },
    { value: 'at', label: CLOCK.at.name, hint: CLOCK.at.hint },
]

/** Why Create is shut while the pinned parameters are not a value the pipeline would take. */
const PARAMS_SHUT = LABELS.triggers.schedule.dialog.params_refused

/**
 * Declare one schedule on a pipeline.
 *
 * A SCHEDULE BELONGS TO A PIPELINE, so the pipeline is a field rather than an assumption:
 * `POST /pipelines/{code}/triggers/schedules` is the only way to make one, and there is no
 * endpoint that mints a schedule attached to nothing. It is picked from the instance's own
 * listing rather than typed, because a code somebody has to remember is a code they leave the
 * screen to look up -- and picking one is what makes this dialog able to show the pipeline's
 * parameters and the priority its runs would otherwise take.
 *
 * ONE CLOCK, CHOSEN. The wire shape carries three fields and the core refuses a declaration
 * with two of them filled in, so the dialog offers a choice rather than three boxes somebody
 * could fill in twice.
 *
 * THE CLOCK IS READ BACK BEFORE IT IS DECLARED. `POST /schedules/$preview` computes the next
 * firings with the same core arithmetic the scheduler advances a stored schedule by, so what
 * this promises and what the instance would do cannot disagree; an expression nothing can read
 * says the parser's own sentence where the firings would be, and shuts Create.
 */
export function NewSchedule({
    open,
    onOpenChange,
    onCreated,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    onCreated: () => void
}) {
    const pipelines = usePipelines(open)
    const [pipeline, setPipeline] = useState('')
    const [code, setCode] = useState('')
    const [named, setNamed] = useState('')
    const [description, setDescription] = useState('')
    const [clock, setClock] = useState<Clock>('cron')
    const [expression, setExpression] = useState('')
    const [timezone, setTimezone] = useState(browserZone)
    const [priority, setPriority] = useState<string>(INHERITED)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)
    // Which boxes have been left once, so a required one says so only after somebody was there.
    const [left, setLeft] = useState(NONE_LEFT)

    const chosen = useChosenPipeline(pipeline)
    const params = usePinned(chosen.schema)
    const reading = useFirings(open, clock, expression, timezone)
    const zones = useZones()

    const send = () => {
        if (!params.submit()) return
        const payload: ScheduleIn = {
            code: code.trim(),
            name: given(named),
            description: given(description),
            timezone,
            params: params.values,
            priority: priority === INHERITED ? null : (priority as RunPriority),
        }
        payload[clock] = expression.trim()
        setBusy(true)
        setProblem(null)
        void createSchedule(pipeline, payload)
            .then(
                () => {
                    onCreated()
                    setCode('')
                    setNamed('')
                    setDescription('')
                    setExpression('')
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

    const codeIssue = left.code && code.trim() === '' ? LABELS.triggers.schedule.dialog.no_code : null
    const clockIssue =
        left.expression && expression.trim() === '' ? LABELS.triggers.schedule.dialog.no_clock : null
    const written = CLOCKS.find((one) => one.value === clock) ?? CLOCKS[0]
    const write = useMayWrite()
    const shut = firstShut(
        write.why,
        unreadySchedule(pipeline, code, expression),
        reading.kind === 'refused' ? reading.detail : undefined,
        params.ready ? undefined : PARAMS_SHUT,
    )

    return (
        <DialogShell
            words={DIALOG_WORDS}
            open={open}
            onOpenChange={(next) => {
                if (!next) setLeft(NONE_LEFT)
                onOpenChange(next)
            }}
            width="lg"
            title={LABELS.triggers.schedule.new}
            count={<SchemaIssueCount form={params.form} />}
            status={problem === null ? undefined : <Refusal problem={problem} />}
            confirm={{
                label: LABELS.action.create.verb,
                busy,
                busyLabel: LABELS.action.create.busy,
                why: shut,
                onConfirm: send,
            }}
        >
            <Field
                id="schedule-pipeline"
                label={LABELS.word.pipeline.label}
                required
                requiredMark="word"
                words={FIELD_WORDS}
            >
                <AsyncSelect
                    id="schedule-pipeline"
                    items={pipelines}
                    filter={matchesOption}
                    itemKey={(option) => option.value}
                    itemLabel={(option) => option.label}
                    itemDetail={(option) => option.aside}
                    value={pipelines.find((option) => option.value === pipeline) ?? null}
                    words={pickerWords(LABELS.triggers.dialog.pipeline_hint)}
                    onValueChange={(picked) => {
                        setPipeline(picked === null ? '' : picked.value)
                        params.reset()
                    }}
                />
            </Field>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <TextField
                    id="schedule-code"
                    label={LABELS.word.code}
                    required
                    requiredMark="word"
                    words={FIELD_WORDS}
                    error={codeIssue}
                    mono
                    value={code}
                    placeholder={LABELS.triggers.schedule.dialog.code_hint}
                    onChange={setCode}
                    onBlur={() => {
                        setLeft((was) => ({ ...was, code: true }))
                    }}
                />
                <TextField
                    id="schedule-name"
                    label={LABELS.word.name.label}
                    value={named}
                    onChange={setNamed}
                />
            </div>

            <TextField
                id="schedule-description"
                label={LABELS.word.description}
                value={description}
                onChange={setDescription}
                placeholder={LABELS.triggers.schedule.dialog.description_hint}
            />

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <Field id="schedule-timezone" label={LABELS.word.timezone}>
                    <AsyncSelect
                        id="schedule-timezone"
                        items={zones}
                        filter={matchesOption}
                        itemKey={(option) => option.value}
                        itemLabel={(option) => option.label}
                        itemDetail={(option) => option.aside}
                        value={zones.find((option) => option.value === timezone) ?? null}
                        words={pickerWords(LABELS.triggers.schedule.dialog.timezone_hint)}
                        onValueChange={(picked) => {
                            setTimezone(picked === null ? '' : picked.value)
                        }}
                    />
                </Field>
                <PriorityField
                    id="schedule-priority"
                    value={priority}
                    pipeline={chosen.priority}
                    onChange={setPriority}
                />
            </div>

            <Field id="schedule-clock-kind" label={LABELS.word.clock}>
                <Segmented
                    id="schedule-clock-kind"
                    label={LABELS.word.clock}
                    size="md"
                    value={clock}
                    options={CLOCKS.map((one) => ({
                        value: one.value,
                        label: one.label,
                    }))}
                    onValueChange={setClock}
                />
            </Field>

            {clock === 'cron' ? (
                <CronBox expression={expression} onChange={setExpression} zone={timezone} reading={reading} />
            ) : (
                <div className="space-y-2">
                    <TextField
                        id="schedule-expression"
                        label={written.label}
                        required
                        requiredMark="word"
                        words={FIELD_WORDS}
                        error={clockIssue}
                        mono
                        value={expression}
                        placeholder={written.hint}
                        onChange={setExpression}
                        onBlur={() => {
                            setLeft((was) => ({ ...was, expression: true }))
                        }}
                    />
                    <ClockReading reading={reading} zone={timezone} />
                </div>
            )}

            <ParamsBox chosen={pipeline !== ''} schema={chosen.schema} params={params} />
        </DialogShell>
    )
}

/** The next three firings, or what is wrong with the expression, in one muted line. */
function ClockReading({ reading, zone }: { reading: Reading; zone: string }) {
    if (reading.kind === 'blank' || reading.kind === 'pending') return null
    return (
        <p className="flex items-baseline gap-1.5 text-xs text-muted-foreground" data-testid="clock-reading">
            <ICONS.schedule className="size-3 shrink-0 self-center" aria-hidden />
            {reading.kind === 'refused'
                ? reading.detail
                : reading.firings.map((firing) => formatMoment(firing, zone)).join(' · ')}
        </p>
    )
}

/**
 * A cron clock, its reading in words, and the firings the instance reads back in the chosen zone.
 *
 * THE INSTANCE'S VERDICT IS THE FIELD'S. The box always carries an answer from the instance --
 * the firings, a refusal, or that it is still being asked -- so the box's own parse never marks
 * an expression, not even for the moment before the answer lands. Until it does, the box's own
 * count shows muted.
 */
function CronBox({
    expression,
    onChange,
    zone,
    reading,
}: {
    expression: string
    onChange: (expression: string) => void
    zone: string
    reading: Reading
}) {
    // Now, as of the last keystroke, which is what the box counts its own reading from.
    const [from, setFrom] = useState(() => new Date())
    const runs = useMemo(
        () => (reading.kind === 'firings' ? reading.firings.map((firing) => new Date(firing)) : null),
        [reading],
    )
    return (
        <CronField
            id="schedule-expression"
            value={expression}
            onChange={(next) => {
                setFrom(new Date())
                onChange(next)
            }}
            placeholder={CLOCK.cron.hint}
            from={from}
            count={FIRINGS_READ}
            timeZone={zone}
            runs={runs}
            runsPending={reading.kind === 'pending'}
            invalid={reading.kind === 'refused' ? reading.detail : undefined}
            describe={readCron}
            format={firingOf}
            required
            requiredMark="word"
            words={{ ...CRON_FIELD_WORDS, ...FIELD_WORDS }}
        />
    )
}

/** Every pipeline the instance holds, as the picker's rows, in the order they are read in. */
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
                // A listing this reader may not have is an empty picker: the dialog says why
                // Create is shut, and the refusal that matters is the one the create makes.
            },
        )
        return () => {
            live = false
        }
    }, [open])

    return options
}

/** Every zone this browser knows, each with what it is at right now. */
function useZones(): PickerOption[] {
    return useMemo(
        () =>
            zonesOffered().map((zone) => ({
                value: zone,
                label: zone,
                aside: zoneOffset(zone),
            })),
        [],
    )
}

/** What the chosen pipeline takes and what its own runs are claimed at. */
function useChosenPipeline(code: string): {
    schema: JsonSchema
    priority: RunPriority | null
} {
    // Keyed by the pipeline it was read for, so choosing another one draws that one's form
    // rather than the last one's for a frame, with nothing cleared from inside an effect.
    const [read, setRead] = useState<{ of: string; document: JsonMap | null }>({
        of: '',
        document: null,
    })

    useEffect(() => {
        if (code === '') return
        let live = true
        void readPipeline(code).then(
            (detail) => {
                if (live) setRead({ of: code, document: detail.document })
            },
            () => {
                // The create is what refuses a pipeline this reader cannot read, and it says so
                // where a refusal belongs.
            },
        )
        return () => {
            live = false
        }
    }, [code])

    const document = read.of === code ? read.document : null
    const schema = useMemo(() => formSchema(paramsOf(document)), [document])
    return { schema, priority: document === null ? null : priorityOf(document) }
}

/** The pinned parameters, held as one map and edited as either of its two readings. */
interface Params {
    form: SchemaFormState
    values: JsonMap
    /** Whether the JSON reading parses. */
    ready: boolean
    /** Which reading is in front of somebody. */
    mode: 'form' | 'json'
    show: (mode: 'form' | 'json') => void
    /** The JSON reading's own text, and what is wrong with it. */
    text: string
    unreadable: string | null
    write: (text: string) => void
    /** Shows every issue the form has, in the form, and whether none stops the create. */
    submit: () => boolean
    reset: () => void
}

/**
 * One map of pinned parameters, read as the pipeline's own form or as the JSON it would send.
 *
 * THE TWO READINGS ARE ONE VALUE. Switching to JSON writes the map out; typing JSON that parses
 * writes it back, so a value entered in either is there in the other. What does not parse is the
 * box's own until it does -- the map stays the last one that parsed, and Create is shut, because
 * a schedule pinned from a half-written box would pin something nobody typed. Asking to create
 * over a value the form refuses opens the form on it.
 */
function usePinned(schema: JsonSchema): Params {
    const form = useSchemaForm(schema, { initial: {} })
    const [mode, setMode] = useState<'form' | 'json'>('form')
    const [text, setText] = useState('{}')
    const [unreadable, setUnreadable] = useState<string | null>(null)
    const values = (form.value ?? {}) as JsonMap

    return {
        form,
        values,
        ready: unreadable === null,
        mode,
        show: (next) => {
            if (next === 'json') setText(writeValues(values))
            setUnreadable(null)
            setMode(next)
        },
        text,
        unreadable,
        write: (written) => {
            setText(written)
            const read = readValues(written)
            if (read.ok) {
                setUnreadable(null)
                form.setValue(read.values)
                return
            }
            setUnreadable(read.message)
        },
        submit: () => {
            const ok = form.submit()
            if (!ok) setMode('form')
            return ok
        },
        // A value pinned for one pipeline is not a value for the next, so choosing another one
        // is what empties them; the caller is what knows a pipeline was chosen.
        reset: () => {
            form.setValue({})
            setText('{}')
            setUnreadable(null)
        },
    }
}

/** The pinned parameters, in whichever of their two readings is in front of somebody. */
function ParamsBox({
    chosen,
    schema,
    params,
}: {
    /** Whether a pipeline has been chosen, which is what an empty box says the reason is. */
    chosen: boolean
    schema: JsonSchema
    params: Params
}) {
    return (
        <FieldGroup
            label={LABELS.word.pinned_parameters}
            actions={
                <Segmented
                    label={LABELS.triggers.dialog.params_written}
                    value={params.mode}
                    options={[
                        {
                            value: 'form' as const,
                            label: LABELS.triggers.dialog.params_form,
                        },
                        {
                            value: 'json' as const,
                            label: LABELS.triggers.dialog.params_json,
                        },
                    ]}
                    onValueChange={params.show}
                />
            }
        >
            <Surface tone="well" pad>
                {!hasFields(schema) ? (
                    <p className="text-sm text-muted-foreground">
                        {chosen ? LABELS.triggers.dialog.no_params : LABELS.triggers.dialog.no_pipeline}
                    </p>
                ) : params.mode === 'form' ? (
                    <GeneratedForm form={params.form} />
                ) : (
                    <div className="space-y-1">
                        <Textarea
                            aria-label={LABELS.triggers.dialog.params_json_label}
                            className="h-32 font-mono"
                            spellCheck={false}
                            value={params.text}
                            onChange={(event) => {
                                params.write(event.target.value)
                            }}
                        />
                        {params.unreadable !== null && (
                            <p className="text-xs text-critical" role="alert">
                                {params.unreadable}
                            </p>
                        )}
                    </div>
                )}
            </Surface>
        </FieldGroup>
    )
}

/** Which priority the trigger's runs carry, with the pipeline's own beside the row that takes it. */
function PriorityField({
    id,
    value,
    pipeline,
    onChange,
}: {
    id: string
    value: string
    /** The chosen pipeline's own priority, or nothing while no pipeline is chosen. */
    pipeline: RunPriority | null
    onChange: (value: string) => void
}) {
    return (
        <SelectField
            id={id}
            label={LABELS.word.priority}
            value={value}
            chosenDetail
            options={[
                {
                    value: INHERITED,
                    label: LABELS.triggers.dialog.priority_inherited,
                    detail: pipeline === null ? undefined : <span className="font-mono">{pipeline}</span>,
                },
                ...PRIORITIES.map((one) => ({ value: one, label: one })),
            ]}
            onChange={(chosen) => {
                onChange(chosen === '' ? INHERITED : chosen)
            }}
        />
    )
}
