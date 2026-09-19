import { X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { MarkdownLine } from '@/components/Markdown'
import { CodePane } from '@/components/pipeline/CodePane'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { WindowedPane } from '@/components/WindowedPane'
import { ProgramReference } from '@/components/pipeline/ProgramReference'
import { ReferenceRow } from '@/components/pipeline/ReferenceRow'
import type { JsonMap } from '@/lib/api'
import type { ConnectionOut } from '@/lib/connections'
import type { SchemaOut } from '@/lib/schemas'
import {
    effectiveValue,
    fallbackText,
    foldLabel,
    inputText,
    optionLabel,
    optionToken,
    pairProblems,
    pairRows,
    pairsOf,
    pairsReference,
    pairsValue,
    parseInput,
    partition,
    sameJson,
    switchCell,
    type FieldDescriptor,
    type Pair,
} from '@/lib/schema-form'
import { cn } from '@/lib/utils'

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
 * A FIELD THAT NAMES A THING SHOWS THE THING. Where the caller hands over the listings, a field
 * whose schema says its value is the code of a connection or a schema draws that thing under the
 * control: one shut row, and the definition under it when it is opened. A form with no listings
 * behind it -- the run dialog, the connection form -- passes none and draws none.
 *
 * A CONTROL SHOWS WHAT WOULD RUN. A field the document does not carry renders the schema's own
 * default, so a switch over `default: true` starts on rather than showing off while the server
 * fills in true; touching it writes the value it then shows.
 *
 * WHAT IS NEEDED IS IN FRONT, AND THE REST IS A LINK. Under `fold`, the fields the schema requires
 * and the optional ones the document already sets are drawn -- required in body ink with its
 * marker, optional in muted -- and the optional keys nothing has answered sit behind one link
 * that opens them in place. The split is read from the values this form opened with, so a key
 * being filled in now does not jump over the fold under the hands typing it; choosing another
 * step is another form, and it opens folded again.
 *
 * A MAP OF SCALARS IS A TABLE OF PAIRS. A `pairs` field draws a key column and a value column,
 * one row per entry in the document's own order, and a blank row at the foot to type the next
 * pair into. What it writes is the plain object, so the document, a run's parameters and a
 * connection's config all keep the shape they had. A key written twice marks its row and is not
 * written until it is fixed, which shuts the caller's verb the same way unreadable text does.
 * A field carrying a reference instead of a map is not a table at all: the reference is the text
 * it was written as, said beside the label, and clearing the box brings the table back.
 *
 * THE TEXT IN A BOX IS THE BOX'S UNTIL IT PARSES. A control that re-read its value from the
 * document on every keystroke could not be typed a decimal point or a half-written JSON list
 * into, so each holds its own text and writes to the document only when what was typed is a
 * value. What does not parse is said under that field and told to the owner through
 * `onUnreadable`, because a form whose text does not parse may not be submitted.
 */
/** What a form needs to draw the thing a marked field names: the document, and both listings. */
export interface FormReferences {
    document: JsonMap | null
    schemas: SchemaOut[] | null
    connections: ConnectionOut[] | null
}

export function SchemaForm({
    fields,
    values,
    problems,
    stated,
    disabled,
    fold,
    references,
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
    /** Whether the optional fields nothing has answered sit behind a link. */
    fold?: boolean
    /** What a field that names a connection or a schema is resolved against, or nothing. */
    references?: FormReferences
    onChange: (name: string, value: unknown) => void
    /** Called when a field is left, which is what earns it the right to be told off. */
    onTouch?: (name: string) => void
    /** Called with why a field's text is not a value, or null once it is one again. */
    onUnreadable?: (name: string, message: string | null) => void
}) {
    // The values this form opened with, which is what the split is read from.
    const [opened] = useState(values)
    const { open, folded } = useMemo(
        () => (fold === true ? partition(fields, opened) : { open: fields, folded: [] }),
        [fold, fields, opened],
    )
    const [expanded, setExpanded] = useState(false)

    if (fields.length === 0) {
        return <p className="text-sm text-muted-foreground">This takes no configuration.</p>
    }

    const draw = (field: FieldDescriptor) => (
        <Field
            key={field.name}
            field={field}
            value={values[field.name]}
            problem={problems[field.name] ?? null}
            stated={stated === undefined || stated.has(field.name)}
            disabled={disabled}
            references={references}
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
    )

    return (
        <div className="flex flex-col gap-4">
            {open.map(draw)}
            {folded.length > 0 &&
                (expanded ? (
                    folded.map(draw)
                ) : (
                    <Button
                        variant="link"
                        className="w-fit px-0 text-primary-ink"
                        onClick={() => {
                            setExpanded(true)
                        }}
                    >
                        {foldLabel(folded.length)}
                    </Button>
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
    references,
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
    references?: FormReferences
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
    // A reference stands for the whole map, so there is a table to draw only when there is none.
    const reference = field.kind === 'pairs' ? pairsReference(value) : null
    // Whether one control carries the label's `for`. A pane and a table are not one control.
    const single =
        field.kind === 'pairs' ? reference !== null : field.kind !== 'code' && field.kind !== 'json'

    return (
        <div className="flex flex-col gap-1.5">
            <div className="flex flex-wrap items-baseline gap-x-2">
                <Label
                    htmlFor={single ? id : undefined}
                    className={cn(
                        'font-mono text-sm font-medium',
                        field.required ? 'text-foreground' : 'text-muted-foreground',
                    )}
                >
                    {field.name}
                </Label>
                {field.required && <span className="text-xs text-primary">required</span>}
                {/* A field written as a reference is not a table, so what a cell would take is
                    not what this field is about. */}
                {field.hint !== null && reference === null && (
                    <span className="text-xs text-faint">{field.hint}</span>
                )}
                {reference !== null && <span className="text-xs text-faint">a reference, not a table</span>}
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
            {field.refers !== null && references !== undefined && (
                <ReferenceRow
                    refers={field.refers}
                    value={value}
                    document={references.document}
                    schemas={references.schemas}
                    connections={references.connections}
                />
            )}
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
                    {/* The trigger draws the choice as the option reads rather than the token it
                        is addressed by, which is JSON and would put `GET` in quotes. */}
                    <SelectValue>
                        {() =>
                            chosen === undefined
                                ? field.fallback === undefined
                                    ? 'unset'
                                    : optionLabel(field.fallback)
                                : chosen.label
                        }
                    </SelectValue>
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
    if (field.kind === 'pairs') {
        const reference = pairsReference(value)
        if (reference !== null) {
            return (
                <Input
                    id={id}
                    className="font-mono"
                    spellCheck={false}
                    disabled={disabled}
                    aria-invalid={invalid}
                    value={reference}
                    onBlur={onTouch}
                    onChange={(event) => {
                        const next = event.target.value
                        onChange(next.trim() === '' ? undefined : next)
                    }}
                />
            )
        }
        return (
            <PairsTable
                field={field}
                value={value}
                disabled={disabled}
                onChange={onChange}
                onUnreadable={onUnreadable}
                onTouch={onTouch}
            />
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

/**
 * A map of scalars, edited as the two-column table it is.
 *
 * THE ROWS ARE THE TABLE'S AND THE DOCUMENT GETS THE OBJECT. A half-typed row -- a key with no
 * value, a value with no key -- is on screen but not in the document, so the rows are held here
 * and `pairsValue` is what the document is written from. A map with nothing left in it removes
 * its key rather than writing `{}`, which is the rule every other control here follows.
 *
 * A CELL THAT IS NOT A VALUE AND A KEY WRITTEN TWICE ARE THE SAME REFUSAL. Both mark the cell
 * and go out through `onUnreadable`, because in both cases the document carries something other
 * than what is on screen and the caller's verb has to stay shut until it does not.
 */
function PairsTable({
    field,
    value,
    disabled,
    onChange,
    onUnreadable,
    onTouch,
}: {
    field: FieldDescriptor
    value: unknown
    disabled: boolean
    onChange: (value: unknown) => void
    onUnreadable: (message: string | null) => void
    onTouch: () => void
}) {
    const [rows, setRows] = useState<Pair[]>(() => pairsOf(field, value))
    // What this table last wrote, compared as JSON: a value that arrived from anywhere else --
    // the source pane, another step being chosen -- is what the rows are re-seeded from.
    const written = useRef<unknown>(value)

    useEffect(() => {
        if (sameJson(value, written.current)) return
        written.current = value
        setRows(pairsOf(field, value))
        onUnreadable(null)
        // `onUnreadable` is a setState and stable; re-seeding on it would fight the typing.
        // oxlint-disable-next-line react/exhaustive-deps
    }, [field, value])

    const problems = pairProblems(field, rows)
    const marked = (row: number, where: 'key' | 'value') =>
        problems.some((one) => one.row === row && one.where === where)

    const put = (next: readonly Pair[]) => {
        const grown = pairRows(field, next)
        setRows(grown)
        const wrong = pairProblems(field, grown)
        onUnreadable(wrong.length === 0 ? null : wrong[0].message)
        const map = pairsValue(field, grown)
        const carried = Object.keys(map).length === 0 ? undefined : map
        written.current = carried
        onChange(carried)
    }

    const change = (index: number, part: Partial<Pair>) => {
        put(rows.map((row, at) => (at === index ? { ...row, ...part } : row)))
    }

    return (
        <table className="w-full table-fixed" aria-label={field.name}>
            <thead>
                <tr>
                    <th
                        scope="col"
                        className="w-2/5 pr-1.5 text-left text-xs font-normal text-muted-foreground"
                    >
                        key
                    </th>
                    <th scope="col" className="pr-1.5 text-left text-xs font-normal text-muted-foreground">
                        value
                    </th>
                    <th scope="col" className="w-6">
                        <span className="sr-only">remove</span>
                    </th>
                </tr>
            </thead>
            <tbody>
                {rows.map((row, index) => (
                    // The rows are a list somebody is typing into and every cell is controlled
                    // from `rows`, so the position is the identity.
                    // oxlint-disable-next-line react/no-array-index-key
                    <tr key={index}>
                        <td className="pt-1 pr-1.5 align-middle">
                            <Input
                                className="font-mono"
                                spellCheck={false}
                                disabled={disabled}
                                aria-invalid={marked(index, 'key')}
                                aria-label={`${field.name} key ${String(index + 1)}`}
                                placeholder="key"
                                value={row.key}
                                onBlur={onTouch}
                                onChange={(event) => {
                                    change(index, { key: event.target.value })
                                }}
                            />
                        </td>
                        <td className="pt-1 pr-1.5 align-middle">
                            {switchCell(field) ? (
                                <Switch
                                    disabled={disabled}
                                    aria-label={`${field.name} value ${String(index + 1)}`}
                                    checked={row.text === 'true'}
                                    onBlur={onTouch}
                                    onCheckedChange={(checked) => {
                                        change(index, { text: checked ? 'true' : 'false' })
                                    }}
                                />
                            ) : (
                                <Input
                                    className="font-mono"
                                    spellCheck={false}
                                    disabled={disabled}
                                    aria-invalid={marked(index, 'value')}
                                    aria-label={`${field.name} value ${String(index + 1)}`}
                                    placeholder="value"
                                    value={row.text}
                                    onBlur={onTouch}
                                    onChange={(event) => {
                                        change(index, { text: event.target.value })
                                    }}
                                />
                            )}
                        </td>
                        <td className="pt-1 align-middle">
                            {index < rows.length - 1 && (
                                <Button
                                    variant="ghost"
                                    size="icon-xs"
                                    disabled={disabled}
                                    aria-label={removeLabel(field.name, row, index)}
                                    onClick={() => {
                                        put(rows.filter((_, at) => at !== index))
                                    }}
                                >
                                    <X className="size-3" aria-hidden />
                                </Button>
                            )}
                        </td>
                    </tr>
                ))}
            </tbody>
        </table>
    )
}

/** What the remove control on one row is called, which is the pair it takes away. */
function removeLabel(name: string, row: Pair, index: number): string {
    const key = row.key.trim()
    return key === '' ? `Remove row ${String(index + 1)} from ${name}` : `Remove ${key} from ${name}`
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
                aside={field.kind === 'code' ? <ProgramReference mediaType={mediaType} /> : undefined}
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
