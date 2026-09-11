import { Check, Clock3, Copy } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { Picker } from '@/components/Picker'
import { SchemaForm } from '@/components/pipeline/SchemaForm'
import { Refusable } from '@/components/Refusable'
import { Refusal } from '@/components/Refusal'
import { Segmented } from '@/components/Segmented'
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
import { Input } from '@/components/ui/input'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from '@/components/ui/input-group'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useMayWrite } from '@/hooks/use-may-write'
import { type JsonMap, type Problem } from '@/lib/api'
import { formatMoment } from '@/lib/format'
import { headingOf } from '@/lib/identity'
import type { PickerOption } from '@/lib/picker'
import { byTitle, paramsOf, priorityOf, readAllPipelines, readPipeline } from '@/lib/pipelines'
import { refusalOf } from '@/lib/refusal'
import { firstShut } from '@/lib/roles'
import type { RunPriority } from '@/lib/runs'
import { fieldsOf, maySubmit, validateFields, withUnreadable, type FieldDescriptor } from '@/lib/schema-form'
import {
    browserZone,
    generatedSecret,
    given,
    INHERITED,
    mappedPaths,
    PRIORITIES,
    readValues,
    unreadySchedule,
    unreadyWebhook,
    writeValues,
    zoneOffset,
    zonesOffered,
} from '@/lib/trigger-form'
import {
    createSchedule,
    createWebhook,
    previewSchedule,
    type ScheduleIn,
    type WebhookTokenOut,
} from '@/lib/triggers'

/** Which clock a new schedule is declared with. Exactly one, which is what the core accepts. */
type Clock = 'cron' | 'interval' | 'at'

const CLOCKS: { value: Clock; label: string; hint: string }[] = [
    { value: 'cron', label: 'Cron', hint: '0 5 * * *' },
    { value: 'interval', label: 'Interval', hint: '15m' },
    { value: 'at', label: 'One time', hint: '2026-06-01T09:00:00Z' },
]

/** How long a clock is left alone before it is read back, so a keystroke is not a request. */
const PREVIEW_DELAY = 300

/** Why Create is shut while the pinned parameters are not a value the pipeline would take. */
const PARAMS_SHUT = 'A pinned parameter is not what this pipeline takes.'

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

    const chosen = useChosenPipeline(pipeline)
    const params = usePinned(chosen.fields)
    const reading = useFirings(open, clock, expression, timezone)
    const zones = useZones()

    const send = () => {
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

    const written = CLOCKS.find((one) => one.value === clock) ?? CLOCKS[0]
    const write = useMayWrite()
    const shut = firstShut(
        write.why,
        unreadySchedule(pipeline, code, expression),
        reading.kind === 'refused' ? reading.detail : undefined,
        params.ready ? undefined : PARAMS_SHUT,
    )

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-xl" showCloseButton={false}>
                <DialogHeader>
                    <DialogTitle>New schedule</DialogTitle>
                </DialogHeader>

                <div className="space-y-2">
                    <Label htmlFor="schedule-pipeline">Pipeline</Label>
                    <Picker
                        id="schedule-pipeline"
                        label="Pipeline"
                        value={pipeline}
                        options={pipelines}
                        placeholder="Search by name or code"
                        onChange={(picked) => {
                            setPipeline(picked)
                            params.reset()
                        }}
                    />
                </div>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <Field
                        id="schedule-code"
                        label="Code"
                        value={code}
                        onChange={setCode}
                        placeholder="nightly"
                        mono
                    />
                    <Field
                        id="schedule-name"
                        label="Name"
                        value={named}
                        onChange={setNamed}
                        placeholder="What to call it on screen"
                    />
                </div>

                <Field
                    id="schedule-description"
                    label="Description"
                    value={description}
                    onChange={setDescription}
                    placeholder="What this clock is for"
                />

                <div className="space-y-2">
                    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                        <div className="space-y-2">
                            <Label>Clock</Label>
                            <Segmented
                                label="Clock"
                                size="md"
                                value={clock}
                                options={CLOCKS.map((one) => ({ value: one.value, label: one.label }))}
                                onChoose={setClock}
                            />
                        </div>
                        <Field
                            id="schedule-expression"
                            label={written.label}
                            value={expression}
                            onChange={setExpression}
                            placeholder={written.hint}
                            mono
                        />
                    </div>
                    <ClockReading reading={reading} zone={timezone} />
                </div>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <div className="space-y-2">
                        <Label htmlFor="schedule-timezone">Timezone</Label>
                        <Picker
                            id="schedule-timezone"
                            label="Timezone"
                            value={timezone}
                            options={zones}
                            placeholder="Search by zone or offset"
                            onChange={setTimezone}
                        />
                    </div>
                    <PriorityField
                        id="schedule-priority"
                        value={priority}
                        pipeline={chosen.priority}
                        onChange={setPriority}
                    />
                </div>

                <ParamsBox chosen={pipeline !== ''} fields={chosen.fields} params={params} />

                {problem !== null && <Refusal problem={problem} />}

                <DialogFooter>
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

/** What a rate limit defaults to, which is what `WebhookIn` defaults to. */
const RATE_LIMIT = 60

/**
 * Declare one webhook on a pipeline, and read its token back exactly once.
 *
 * THE TOKEN IS ANSWERED HERE AND NOWHERE ELSE AGAIN. The instance keeps only its hash, so
 * `POST .../webhooks` answering a token is the one moment it is readable; the dialog that
 * shows it is the reader's only chance to copy it, and rotating is what replaces one that
 * was lost.
 *
 * THE MAPPING IS THE PIPELINE'S OWN PARAMETERS, ONE ROW EACH. A payload reaches a run only
 * through a parameter the pipeline declares, so the rows are the parameters and what somebody
 * writes against each is the path into the payload -- rather than a box of JSON in which a
 * parameter that does not exist looks exactly like one that does.
 */
export function NewWebhook({
    open,
    onOpenChange,
    onMinted,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    /** Called with the minted token, which the screen shows once and then forgets. */
    onMinted: (token: WebhookTokenOut) => void
}) {
    const pipelines = usePipelines(open)
    const [pipeline, setPipeline] = useState('')
    const [code, setCode] = useState('')
    const [named, setNamed] = useState('')
    const [description, setDescription] = useState('')
    const [paths, setPaths] = useState<Record<string, string>>({})
    const [secret, setSecret] = useState('')
    const [rate, setRate] = useState(String(RATE_LIMIT))
    const [priority, setPriority] = useState<string>(INHERITED)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)

    const chosen = useChosenPipeline(pipeline)

    const send = () => {
        setBusy(true)
        setProblem(null)
        void createWebhook(pipeline, {
            code: code.trim(),
            name: given(named),
            description: given(description),
            params_from_payload: mappedPaths(paths),
            hmac_secret: secret === '' ? null : secret,
            rate_limit_per_minute: Number(rate) || RATE_LIMIT,
            priority: priority === INHERITED ? null : (priority as RunPriority),
        })
            .then(
                (token) => {
                    onMinted(token)
                    setCode('')
                    setNamed('')
                    setDescription('')
                    setSecret('')
                    setPaths({})
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

    const write = useMayWrite()
    const shut = firstShut(write.why, unreadyWebhook(pipeline, code))

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-xl" showCloseButton={false}>
                <DialogHeader>
                    <DialogTitle>New webhook</DialogTitle>
                </DialogHeader>

                <div className="space-y-2">
                    <Label htmlFor="webhook-pipeline">Pipeline</Label>
                    <Picker
                        id="webhook-pipeline"
                        label="Pipeline"
                        value={pipeline}
                        options={pipelines}
                        placeholder="Search by name or code"
                        onChange={(picked) => {
                            setPipeline(picked)
                            setPaths({})
                        }}
                    />
                </div>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <Field
                        id="webhook-code"
                        label="Code"
                        value={code}
                        onChange={setCode}
                        placeholder="upstream-publish"
                        mono
                    />
                    <Field
                        id="webhook-name"
                        label="Name"
                        value={named}
                        onChange={setNamed}
                        placeholder="What to call it on screen"
                    />
                </div>

                <Field
                    id="webhook-description"
                    label="Description"
                    value={description}
                    onChange={setDescription}
                    placeholder="What sends to this endpoint"
                />

                <div className="space-y-2">
                    <Label>Payload mapping</Label>
                    <div className="max-h-[32vh] overflow-y-auto rounded-md border border-border p-3">
                        {chosen.fields.length === 0 ? (
                            <p className="text-sm text-muted-foreground">
                                {pipeline === ''
                                    ? 'No pipeline chosen.'
                                    : 'This pipeline takes no parameters.'}
                            </p>
                        ) : (
                            <div className="space-y-3">
                                {chosen.fields.map((field) => (
                                    <div key={field.name} className="grid grid-cols-2 items-start gap-3">
                                        <div className="space-y-0.5">
                                            <Label
                                                htmlFor={`mapping-${field.name}`}
                                                className="font-mono text-sm"
                                            >
                                                {field.name}
                                            </Label>
                                            {field.required && (
                                                <p className="text-xs text-primary">required</p>
                                            )}
                                        </div>
                                        <Input
                                            id={`mapping-${field.name}`}
                                            className="font-mono"
                                            spellCheck={false}
                                            placeholder="$."
                                            value={paths[field.name] ?? ''}
                                            onChange={(event) => {
                                                setPaths((held) => ({
                                                    ...held,
                                                    [field.name]: event.target.value,
                                                }))
                                            }}
                                        />
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                    <p className="text-xs text-faint">
                        One JSONPath per parameter the pipeline declares. Anything else in the payload is
                        ignored.
                    </p>
                </div>

                <div className="space-y-2">
                    <Label htmlFor="webhook-secret">Signing secret</Label>
                    <InputGroup className="bg-field dark:bg-field">
                        <InputGroupInput
                            id="webhook-secret"
                            type="password"
                            autoComplete="new-password"
                            value={secret}
                            onChange={(event) => {
                                setSecret(event.target.value)
                            }}
                            placeholder="Leave empty for an unsigned endpoint"
                        />
                        <InputGroupAddon align="inline-end">
                            <InputGroupButton
                                onClick={() => {
                                    setSecret(generatedSecret())
                                }}
                            >
                                Generate
                            </InputGroupButton>
                        </InputGroupAddon>
                    </InputGroup>
                </div>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <Field
                        id="webhook-rate"
                        label="Deliveries a minute"
                        value={rate}
                        onChange={setRate}
                        placeholder={String(RATE_LIMIT)}
                        mono
                    />
                    <PriorityField
                        id="webhook-priority"
                        value={priority}
                        pipeline={chosen.priority}
                        onChange={setPriority}
                    />
                </div>

                {problem !== null && <Refusal problem={problem} />}

                <DialogFooter>
                    <p className="mr-auto self-center text-xs text-muted-foreground">
                        Its token is shown once, after Create.
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

/**
 * A token, the one time it is readable.
 *
 * There is no read that answers this again: closing this dialog is the moment the token stops
 * being available to anybody who did not copy it, and the only way back is a rotation, which
 * makes a different one and invalidates this.
 */
export function MintedToken({ token, onClose }: { token: WebhookTokenOut; onClose: () => void }) {
    const [copied, setCopied] = useState(false)

    const copy = () => {
        void navigator.clipboard.writeText(token.token).then(
            () => {
                setCopied(true)
            },
            () => {
                // A denied clipboard is not a failure worth a card: the token is on screen and
                // can be selected.
            },
        )
    }

    return (
        <Dialog
            open
            onOpenChange={(next) => {
                if (!next) onClose()
            }}
        >
            <DialogContent className="sm:max-w-xl" showCloseButton={false}>
                <DialogHeader>
                    <DialogTitle>The token for {token.code}</DialogTitle>
                    <DialogDescription>
                        This instance keeps only its hash. This is the only time it can be read; rotating the
                        webhook is how a lost token is replaced.
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-2 rounded-lg border border-border bg-secondary/40 p-3">
                    <p className="font-mono text-xs break-all" data-testid="webhook-token">
                        {token.token}
                    </p>
                    <Button variant="outline" size="sm" onClick={copy}>
                        {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
                        {copied ? 'Copied' : 'Copy token'}
                    </Button>
                </div>

                <div className="space-y-1">
                    <p className="text-xs text-muted-foreground">Where to POST</p>
                    <p className="font-mono text-xs break-all">{token.url_path}</p>
                </div>

                <DialogFooter>
                    <Button onClick={onClose}>Done</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

/** What a clock says about itself under the box it was written in. */
type Reading =
    /** Nothing has been written yet, so there is nothing to read back. */
    | { kind: 'blank' }
    /** The next firings, oldest first, in the zone the schedule declares. */
    | { kind: 'firings'; firings: string[] }
    /** What the parser made of it, in its own words. */
    | { kind: 'refused'; detail: string }

/** The next three firings, or what is wrong with the expression, in one muted line. */
function ClockReading({ reading, zone }: { reading: Reading; zone: string }) {
    if (reading.kind === 'blank') return null
    return (
        <p className="flex items-baseline gap-1.5 text-xs text-muted-foreground" data-testid="clock-reading">
            <Clock3 className="size-3 shrink-0 self-center" aria-hidden />
            {reading.kind === 'refused'
                ? reading.detail
                : reading.firings.map((firing) => formatMoment(firing, zone)).join(' · ')}
        </p>
    )
}

/**
 * What a clock would fire, read back from the instance as it is typed.
 *
 * A KEYSTROKE IS NOT A REQUEST. The expression is left alone for a moment before it is asked
 * about, and an answer to an expression somebody has since changed is dropped rather than
 * drawn under the one they are now writing.
 */
function useFirings(open: boolean, clock: Clock, expression: string, timezone: string): Reading {
    const written = expression.trim()
    // What the answer on screen belongs to, so an answer to a clock somebody has since changed
    // is not drawn under the one they are now writing.
    const asked = `${clock} ${timezone} ${written}`
    const [answered, setAnswered] = useState<{ asked: string; reading: Reading } | null>(null)

    useEffect(() => {
        if (!open || written === '') return
        let live = true
        const timer = setTimeout(() => {
            void previewSchedule({ [clock]: written, timezone }).then(
                (answer) => {
                    if (live) setAnswered({ asked, reading: { kind: 'firings', firings: answer.firings } })
                },
                (error: unknown) => {
                    const detail = refusalOf(error).detail ?? 'This clock cannot be read.'
                    if (live) setAnswered({ asked, reading: { kind: 'refused', detail } })
                },
            )
        }, PREVIEW_DELAY)
        return () => {
            live = false
            clearTimeout(timer)
        }
    }, [open, asked, clock, timezone, written])

    if (written === '') return { kind: 'blank' }
    return answered !== null && answered.asked === asked ? answered.reading : { kind: 'blank' }
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
                        return { value: row.code, label: heading.title, aside: heading.code ?? '' }
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
        () => zonesOffered().map((zone) => ({ value: zone, label: zone, aside: zoneOffset(zone) })),
        [],
    )
}

/** What the chosen pipeline takes and what its own runs are claimed at. */
function useChosenPipeline(code: string): { fields: FieldDescriptor[]; priority: RunPriority | null } {
    // Keyed by the pipeline it was read for, so choosing another one draws that one's form
    // rather than the last one's for a frame, with nothing cleared from inside an effect.
    const [read, setRead] = useState<{ of: string; document: JsonMap | null }>({ of: '', document: null })

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
    const fields = useMemo(() => fieldsOf(paramsOf(document)), [document])
    return { fields, priority: document === null ? null : priorityOf(document) }
}

/** The pinned parameters, held as one map and edited as either of its two readings. */
interface Params {
    values: JsonMap
    /** Whether what is on screen is a value the pipeline would take. */
    ready: boolean
    /** Which reading is in front of somebody. */
    mode: 'form' | 'json'
    show: (mode: 'form' | 'json') => void
    /** The JSON reading's own text, and what is wrong with it. */
    text: string
    unreadable: string | null
    write: (text: string) => void
    set: (name: string, value: unknown) => void
    touch: (name: string) => void
    report: (name: string, message: string | null) => void
    stated: ReadonlySet<string> | undefined
    problems: Record<string, string>
    reset: () => void
}

/**
 * One map of pinned parameters, read as the pipeline's own form or as the JSON it would send.
 *
 * THE TWO READINGS ARE ONE VALUE. Switching to JSON writes the map out; typing JSON that parses
 * writes it back, so a value entered in either is there in the other. What does not parse is the
 * box's own until it does -- the map stays the last one that parsed, and Create is shut, because
 * a schedule pinned from a half-written box would pin something nobody typed.
 */
function usePinned(fields: FieldDescriptor[]): Params {
    const [values, setValues] = useState<JsonMap>({})
    const [mode, setMode] = useState<'form' | 'json'>('form')
    const [text, setText] = useState('{}')
    const [unreadable, setUnreadable] = useState<string | null>(null)
    const [touched, setTouched] = useState<ReadonlySet<string>>(() => new Set())
    const [unreadableFields, setUnreadableFields] = useState<ReadonlySet<string>>(() => new Set())
    const problems = validateFields(fields, values)

    const reset = () => {
        setValues({})
        setText('{}')
        setUnreadable(null)
        setTouched(new Set())
        setUnreadableFields(new Set())
    }

    return {
        values,
        ready: unreadable === null && maySubmit(problems, unreadableFields),
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
                setValues(read.values)
                return
            }
            setUnreadable(read.message)
        },
        set: (name, value) => {
            setValues((current) => {
                const next = { ...current }
                if (value === undefined) delete next[name]
                else next[name] = value
                return next
            })
        },
        touch: (name) => {
            setTouched((current) => (current.has(name) ? current : new Set(current).add(name)))
        },
        report: (name, message) => {
            setUnreadableFields((current) => withUnreadable(current, name, message))
        },
        stated: touched,
        problems,
        // A value pinned for one pipeline is not a value for the next, so choosing another one
        // is what empties them; the caller is what knows a pipeline was chosen.
        reset,
    }
}

/** The pinned parameters, in whichever of their two readings is in front of somebody. */
function ParamsBox({
    chosen,
    fields,
    params,
}: {
    /** Whether a pipeline has been chosen, which is what an empty box says the reason is. */
    chosen: boolean
    fields: FieldDescriptor[]
    params: Params
}) {
    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
                <Label>Pinned parameters</Label>
                <Segmented
                    label="How the parameters are written"
                    value={params.mode}
                    options={[
                        { value: 'form' as const, label: 'Form' },
                        { value: 'json' as const, label: 'JSON' },
                    ]}
                    onChoose={params.show}
                />
            </div>
            <div className="max-h-[32vh] overflow-y-auto rounded-md border border-border p-3">
                {fields.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                        {chosen ? 'This pipeline takes no parameters.' : 'No pipeline chosen.'}
                    </p>
                ) : params.mode === 'form' ? (
                    <SchemaForm
                        fields={fields}
                        values={params.values}
                        problems={params.problems}
                        stated={params.stated}
                        onChange={params.set}
                        onTouch={params.touch}
                        onUnreadable={params.report}
                    />
                ) : (
                    <div className="space-y-1">
                        <Textarea
                            aria-label="Pinned parameters as JSON"
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
            </div>
        </div>
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
        <div className="space-y-2">
            <Label htmlFor={id}>Priority</Label>
            <Select
                value={value}
                onValueChange={(chosen: string | null) => {
                    onChange(chosen ?? INHERITED)
                }}
            >
                <SelectTrigger id={id} className="w-full">
                    {/* The trigger draws the row that was chosen, rather than the token it is
                        addressed by, which is what a value with no priority in it would say. */}
                    <SelectValue>
                        {(chosen: string) => <Priority chosen={chosen} pipeline={pipeline} />}
                    </SelectValue>
                </SelectTrigger>
                <SelectContent>
                    <SelectItem value={INHERITED}>
                        <Priority chosen={INHERITED} pipeline={pipeline} />
                    </SelectItem>
                    {PRIORITIES.map((one) => (
                        <SelectItem key={one} value={one}>
                            {one}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    )
}

/** One priority row: the word itself, or the pipeline's own beside the row that takes it. */
function Priority({ chosen, pipeline }: { chosen: string; pipeline: RunPriority | null }) {
    if (chosen !== INHERITED) return chosen
    return (
        <>
            The pipeline&apos;s
            {pipeline !== null && <span className="font-mono text-muted-foreground"> {pipeline}</span>}
        </>
    )
}

/** One labelled box, which is most of both dialogs. */
function Field({
    id,
    label,
    value,
    onChange,
    placeholder,
    mono,
}: {
    id: string
    label: string
    value: string
    onChange: (value: string) => void
    placeholder: string
    mono?: boolean
}) {
    return (
        <div className="space-y-2">
            <Label htmlFor={id}>{label}</Label>
            <Input
                id={id}
                className={mono === true ? 'font-mono' : undefined}
                spellCheck={false}
                value={value}
                onChange={(event) => {
                    onChange(event.target.value)
                }}
                placeholder={placeholder}
            />
        </div>
    )
}
