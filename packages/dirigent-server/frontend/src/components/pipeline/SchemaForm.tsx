import { useEffect, useRef, useState } from 'react'

import { MarkdownLine } from '@/components/Markdown'
import { CodePane } from '@/components/pipeline/CodePane'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { WindowedPane } from '@/components/WindowedPane'
import type { JsonMap } from '@/lib/api'
import {
    effectiveValue,
    fallbackText,
    inputText,
    optionToken,
    parseInput,
    sameJson,
    type FieldDescriptor,
} from '@/lib/schema-form'

/**
 * A form generated from a JSON Schema.
 *
 * IT RENDERS DESCRIPTORS AND DECIDES NOTHING. Which control a field takes, what its bounds are
 * and what is wrong with a value are all `lib/schema-form`, so the same decisions hold for a
 * block's config and for a pipeline's parameters, and both are tested in plain Node.
 *
 * THE LABEL IS THE KEY AND NOTHING ELSE, so a form's controls are addressable by the word the
 * document carries. Whether a field is required is said beside the label rather than inside it,
 * because a marker inside the label becomes part of the control's name.
 *
 * A PROBLEM IS NOTHING UNTIL SOMEBODY HAS BEEN THERE. A form that marked a field invalid before
 * it had been touched would be telling somebody off for opening it, so a caller may pass
 * `stated` to say which fields have been left or asked to submit: a problem with any other
 * field is neither written out nor drawn on the control, and the button the caller owns is what
 * stays shut in the meantime.
 *
 * A PROGRAM IS EDITED AS A PROGRAM. A field whose schema published a `contentMediaType` holds
 * source, and it gets the same Monaco every document in this app is written in -- through the
 * same lazy pane, so a form of ordinary fields fetches no editor. It names itself rather than
 * being named by the label beside it: an editor is not one control for a `for` to point at.
 *
 * A CONTROL SHOWS WHAT WOULD RUN. A field the document does not carry renders the schema's own
 * default, so a switch over `default: true` starts on rather than showing off while the server
 * fills in true; touching it writes the value it then shows.
 *
 * THE TEXT IN A BOX IS THE BOX'S UNTIL IT PARSES. A control that re-read its value from the
 * document on every keystroke could not be typed a decimal point or a half-written JSON list
 * into, so each holds its own text and writes to the document only when what was typed is a
 * value. What does not parse is said under that field and told to the owner through
 * `onUnreadable`, because a form whose text does not parse may not be submitted.
 */
export function SchemaForm({
    fields,
    values,
    problems,
    stated,
    disabled,
    onChange,
    onTouch,
    onUnreadable,
}: {
    fields: FieldDescriptor[]
    /** The values the document carries, by field name. */
    values: JsonMap
    /** What the schema says is wrong with each field, from `validateFields`. */
    problems: Record<string, string>
    /** Whose problem is said and marked. Every one of them when the caller names none. */
    stated?: ReadonlySet<string>
    /** Why nothing may be edited, or nothing when it may. */
    disabled?: string
    onChange: (name: string, value: unknown) => void
    /** Called when a field is left, which is what earns it the right to be told off. */
    onTouch?: (name: string) => void
    /** Called with why a field's text is not a value, or null once it is one again. */
    onUnreadable?: (name: string, message: string | null) => void
}) {
    if (fields.length === 0) {
        return <p className="text-sm text-muted-foreground">This takes no configuration.</p>
    }
    return (
        <div className="flex flex-col gap-4">
            {fields.map((field) => (
                <Field
                    key={field.name}
                    field={field}
                    value={values[field.name]}
                    problem={problems[field.name] ?? null}
                    stated={stated === undefined || stated.has(field.name)}
                    disabled={disabled}
                    onChange={(value) => {
                        onChange(field.name, value)
                    }}
                    onTouch={() => {
                        onTouch?.(field.name)
                    }}
                    onUnreadable={(message) => {
                        onUnreadable?.(field.name, message)
                    }}
                />
            ))}
        </div>
    )
}

/** One labelled control, its help, and whatever is wrong with it. */
function Field({
    field,
    value,
    problem,
    stated,
    disabled,
    onChange,
    onTouch,
    onUnreadable,
}: {
    field: FieldDescriptor
    value: unknown
    problem: string | null
    /** Whether this field's problem is written out, or only marked on the control. */
    stated: boolean
    disabled?: string
    onChange: (value: unknown) => void
    onTouch: () => void
    onUnreadable: (message: string | null) => void
}) {
    const id = `field-${field.name}`
    const [unreadable, setUnreadable] = useState<string | null>(null)
    // A field that goes away takes its unreadable text with it: a form whose fields changed, or
    // a dialog opened again, must not be blocked by a box nobody can see any more.
    const report = useRef(onUnreadable)
    useEffect(() => {
        report.current = onUnreadable
    })
    useEffect(
        () => () => {
            report.current(null)
        },
        [],
    )
    const shown = unreadable ?? (stated ? problem : null)
    const fallback = fallbackText(field)

    return (
        <div className="flex flex-col gap-1.5">
            <div className="flex flex-wrap items-baseline gap-x-2">
                <Label
                    htmlFor={field.kind === 'code' || field.kind === 'json' ? undefined : id}
                    className="font-mono text-sm font-medium"
                >
                    {field.name}
                </Label>
                {field.required && <span className="text-xs text-primary">required</span>}
                {field.hint !== null && <span className="text-xs text-faint">{field.hint}</span>}
                {fallback !== null && <span className="text-xs text-faint">default {fallback}</span>}
            </div>
            <Control
                id={id}
                field={field}
                value={value}
                invalid={shown !== null}
                disabled={disabled !== undefined}
                onChange={onChange}
                onUnreadable={(message) => {
                    setUnreadable(message)
                    onUnreadable(message)
                }}
                onTouch={onTouch}
            />
            {field.help !== null && (
                <p className="text-xs text-muted-foreground">
                    <MarkdownLine text={field.help} />
                </p>
            )}
            {field.kind === 'json' && fallback !== null && (
                <p className="text-xs text-faint">An empty box submits the default.</p>
            )}
            {shown !== null && (
                <p className="text-xs text-critical" role="alert">
                    {shown}
                </p>
            )}
        </div>
    )
}

function Control({
    id,
    field,
    value,
    invalid,
    disabled,
    onChange,
    onUnreadable,
    onTouch,
}: {
    id: string
    field: FieldDescriptor
    value: unknown
    invalid: boolean
    disabled: boolean
    onChange: (value: unknown) => void
    onUnreadable: (message: string | null) => void
    onTouch: () => void
}) {
    if (field.kind === 'switch') {
        return (
            <Switch
                id={id}
                disabled={disabled}
                checked={effectiveValue(field, value) === true}
                onBlur={onTouch}
                onCheckedChange={(checked) => {
                    onChange(checked)
                }}
            />
        )
    }
    if (field.kind === 'select') {
        // A choice is addressed by a token and submitted as the JSON the schema listed it as,
        // so an integer enum writes 1 rather than "1".
        const chosen = field.options.find((option) => sameJson(option.value, value))
        return (
            <Select
                value={chosen === undefined ? '' : optionToken(chosen.value)}
                disabled={disabled}
                onValueChange={(token) => {
                    const picked = field.options.find((option) => optionToken(option.value) === token)
                    onChange(picked === undefined ? undefined : picked.value)
                }}
            >
                <SelectTrigger id={id} size="sm" className="w-full" aria-invalid={invalid} onBlur={onTouch}>
                    <SelectValue
                        placeholder={field.fallback === undefined ? 'unset' : String(field.fallback)}
                    />
                </SelectTrigger>
                <SelectContent>
                    {field.options.map((option) => (
                        <SelectItem key={optionToken(option.value)} value={optionToken(option.value)}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        )
    }
    return (
        <TextControl
            id={id}
            field={field}
            value={value}
            invalid={invalid}
            disabled={disabled}
            onChange={onChange}
            onUnreadable={onUnreadable}
            onTouch={onTouch}
        />
    )
}

/** A box holding its own text, which reaches the document only once what is in it is a value. */
function TextControl({
    id,
    field,
    value,
    invalid,
    disabled,
    onChange,
    onUnreadable,
    onTouch,
}: {
    id: string
    field: FieldDescriptor
    value: unknown
    invalid: boolean
    disabled: boolean
    onChange: (value: unknown) => void
    onUnreadable: (message: string | null) => void
    onTouch: () => void
}) {
    const [text, setText] = useState(() => inputText(field, value))
    // What this control last wrote. A value that arrived from anywhere else -- the source pane,
    // another step being chosen -- is what the box is re-seeded from.
    const written = useRef<unknown>(value)

    useEffect(() => {
        if (Object.is(value, written.current)) return
        written.current = value
        setText(inputText(field, value))
        onUnreadable(null)
        // `onUnreadable` is a setState and stable; re-seeding on it would fight the typing.
        // oxlint-disable-next-line react/exhaustive-deps
    }, [field, value])

    const write = (next: string) => {
        setText(next)
        const parsed = parseInput(field, next)
        if (!parsed.ok) {
            onUnreadable(parsed.message)
            return
        }
        onUnreadable(null)
        written.current = parsed.value
        onChange(parsed.value)
    }

    // A program and a value edited as JSON are the same pane at two heights, and both open in
    // a window: `WindowedPane` owns that gesture, and the window and the box name one path, so
    // monaco hands them one buffer and closing the window loses nothing.
    if (field.kind === 'code' || field.kind === 'json') {
        const mediaType = field.kind === 'json' ? 'application/json' : field.mediaType
        const path = `config/${field.name}`
        return (
            <WindowedPane
                name={field.name}
                className="overflow-hidden rounded-md border border-border"
                onBlur={onTouch}
                windowed={
                    <CodePane
                        value={text}
                        mediaType={mediaType}
                        path={path}
                        label={`${field.name}, in a window`}
                        className="min-h-0 flex-1"
                        readOnly={disabled}
                        onChange={write}
                    />
                }
            >
                <CodePane
                    value={text}
                    mediaType={mediaType}
                    path={path}
                    label={field.name}
                    placeholder={field.placeholder}
                    className={field.kind === 'json' ? 'h-32 min-h-24' : 'h-48 min-h-32'}
                    readOnly={disabled}
                    onChange={write}
                />
            </WindowedPane>
        )
    }
    return (
        <Input
            id={id}
            type={field.kind === 'text' ? 'text' : 'text'}
            inputMode={field.kind === 'text' ? undefined : 'decimal'}
            spellCheck={false}
            disabled={disabled}
            aria-invalid={invalid}
            placeholder={field.placeholder}
            value={text}
            onBlur={onTouch}
            onChange={(event) => {
                write(event.target.value)
            }}
        />
    )
}
