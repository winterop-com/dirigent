import {
    SchemaForm,
    type SchemaFieldControl,
    type SchemaFieldRenderer,
    type SchemaFormState,
} from '@winterop-com/sokkel-ui/schema/SchemaForm'
import { Input } from '@winterop-com/sokkel-ui/primitives/input'

import { ProgramReference } from '@/components/pipeline/ProgramReference'
import { ReferenceRow } from '@/components/pipeline/ReferenceRow'
import { WindowedSource } from '@/components/pipeline/WindowedSource'
import type { JsonMap } from '@/lib/api'
import type { ConnectionOut } from '@/lib/connections'
import { drawnAs, readJson, refersTo } from '@/lib/form-schema'
import { LABELS } from '@/lib/labels'
import { hasReference } from '@/lib/references'
import type { SchemaOut } from '@/lib/schemas'

/** What a field naming a connection or a schema is resolved against. */
export interface FormReferences {
    document: JsonMap | null
    schemas: SchemaOut[] | null
    connections: ConnectionOut[] | null
}

/**
 * A form drawn from a JSON Schema by sokkel-ui's `SchemaForm`, with dirigent's own controls for
 * the fields the library draws as plain boxes: a program in the editor of its language, a value
 * the library can only take as JSON text as a JSON buffer, a field naming a connection or a schema
 * with that thing under it, and, under `deferred`, a `${...}` reference in a field whose control
 * cannot hold text (a number, a choice, a switch, an object, a list, a map) as the text.
 */
export function GeneratedForm({
    form,
    references,
    deferred = false,
}: {
    form: SchemaFormState
    references?: FormReferences
    deferred?: boolean
}) {
    return (
        <SchemaForm
            form={form}
            field={fieldControl(form, references, deferred)}
            requiredMark="word"
            fallbacks
        />
    )
}

function fieldControl(
    form: SchemaFormState,
    references: FormReferences | undefined,
    deferred: boolean,
): SchemaFieldRenderer {
    return (field) => {
        const drawn = drawnAs(field.schema, form.schema)
        if (deferred && (drawn === 'value' || drawn === 'other') && hasReference(field.value))
            return <TextBox field={field} />
        if (drawn === 'program') return <ProgramBox field={field} />
        if (drawn === 'json') return <JsonBox field={field} form={form} />
        const refers = refersTo(field.schema)
        if (refers !== null && references !== undefined)
            return (
                <div className="flex flex-col gap-1.5">
                    <TextBox field={field} />
                    <ReferenceRow
                        refers={refers}
                        value={field.value}
                        document={references.document}
                        schemas={references.schemas}
                        connections={references.connections}
                    />
                </div>
            )
        return undefined
    }
}

/** The field's own name, which labels a buffer and its window. */
function nameOf(field: SchemaFieldControl): string {
    return field.label ?? String(field.path[field.path.length - 1] ?? '')
}

/** One line of text in mono; emptied, the key is taken out. */
function TextBox({ field }: { field: SchemaFieldControl }) {
    return (
        <Input
            id={field.id}
            className="font-mono"
            spellCheck={false}
            aria-invalid={field.invalid || undefined}
            readOnly={field.readOnly}
            value={typeof field.value === 'string' ? field.value : ''}
            onBlur={field.touch}
            onChange={(event) => {
                field.set(event.target.value === '' ? undefined : event.target.value)
            }}
        />
    )
}

/** A program, in the editor of the language its `contentMediaType` names. */
function ProgramBox({ field }: { field: SchemaFieldControl }) {
    const name = nameOf(field)
    const mediaType = typeof field.schema.contentMediaType === 'string' ? field.schema.contentMediaType : null
    return (
        <WindowedSource
            name={name}
            label={name}
            windowLabel={LABELS.form.in_window(name)}
            value={typeof field.value === 'string' ? field.value : ''}
            mediaType={mediaType}
            className="h-48 min-h-32"
            readOnly={field.readOnly}
            aside={<ProgramReference mediaType={mediaType} />}
            onBlur={field.touch}
            onChange={(text) => {
                field.set(text === '' ? undefined : text)
            }}
        />
    )
}

/** A JSON value, in a JSON buffer; text that does not parse is held as the form's draft. */
function JsonBox({ field, form }: { field: SchemaFieldControl; form: SchemaFormState }) {
    const name = nameOf(field)
    const draft = form.draft(field.path)
    const text = readJson(draft, field.value)
    return (
        <WindowedSource
            name={name}
            label={name}
            windowLabel={LABELS.form.in_window(name)}
            value={text}
            mediaType="application/json"
            className="h-32 min-h-24"
            readOnly={field.readOnly}
            onBlur={field.touch}
            onChange={(raw) => {
                if (raw === text) return
                try {
                    field.set(raw.trim() === '' ? undefined : (JSON.parse(raw) as unknown))
                } catch {
                    // The text stays as typed, and the form says it does not parse.
                }
                form.setDraft(field.path, raw)
            }}
        />
    )
}
