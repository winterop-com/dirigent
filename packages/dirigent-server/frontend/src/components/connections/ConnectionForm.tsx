import { useMemo, useState } from 'react'

import { Instant } from '@/components/Instant'
import { KindChip } from '@/components/KindChip'
import { Refusable } from '@/components/Refusable'
import { Refusal } from '@/components/Refusal'
import { SecretField } from '@/components/connections/SecretField'
import { SchemaForm } from '@/components/pipeline/SchemaForm'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Description } from '@/components/Description'
import { useMayWrite } from '@/hooks/use-may-write'
import { type JsonMap, type Problem } from '@/lib/api'
import { refusalOf } from '@/lib/refusal'
import { firstShut } from '@/lib/roles'
import { patchBody, settingFields, updateConnection, type ConnectionOut } from '@/lib/connections'
import { separatelyUpdated } from '@/lib/format'
import { headingOf } from '@/lib/identity'
import { maySubmit, validateFields, withUnreadable, type FieldDescriptor } from '@/lib/schema-form'

/**
 * One connection's settings, edited beside the listing.
 *
 * THE FORM IS THE KIND'S SCHEMA, the same way a step's form is its block's. A connection kind
 * publishes its config as a JSON Schema and the catalog carries it, so `lib/schema-form` reads
 * the fields and `SchemaForm` renders them -- a port is a number box, an enum is a select, a
 * mapping is JSON, and every bound the schema states is checked before anything is sent. A kind
 * this instance no longer has installed publishes nothing, and the form falls back to the keys
 * the connection itself carries, because a credential outliving its plugin still has to be
 * readable and deletable.
 *
 * A SECRET IS NOT A SCHEMA FIELD HERE. The schema says a secret is a string, and rendering it
 * as one would put the redaction marker in a text box for somebody to edit. Every field the
 * kind declares secret is taken out of the generated form and drawn below it as a write-only
 * password box instead.
 *
 * BLANK KEEPS THE STORED SECRET. A password box starts empty and stays empty: there is nothing
 * to put in it, because no read anywhere returns a credential. Leaving it alone contributes
 * nothing to the body, so the marker the read showed goes back and the server keeps what it
 * has; typing into it replaces the credential with what was typed. `lib/connections` composes
 * the body, and a test asserts an empty box can never send an empty password.
 *
 * A BOX THAT DOES NOT PARSE SHUTS SAVE. The form keeps the last value that parsed, so saving
 * over a half-written JSON setting would send something other than what is on screen.
 *
 * THE KIND AND THE CODE ARE FIXED. `PATCH /connections/{code}` changes the name, the description
 * and the config, and nothing else: a connection of a different kind is a different connection,
 * and one addressed by a different code is a different connection too.
 *
 * A DIFFERENT CONNECTION IS A DIFFERENT FORM. The screen keys this on the connection's code, so
 * choosing another row builds a new form rather than carrying a half-typed edit onto the
 * credential it was not typed for.
 */
export function ConnectionForm({
    connection,
    schema,
    onSaved,
}: {
    connection: ConnectionOut
    /** The kind's published config schema, or nothing when the catalog does not carry one. */
    schema: JsonMap | null
    /** Called with what the server answered, so the row behind updates without a re-read. */
    onSaved: (row: ConnectionOut) => void
}) {
    const [named, setNamed] = useState(connection.name ?? '')
    const [description, setDescription] = useState(connection.description ?? '')
    const [values, setValues] = useState<JsonMap>(() => settingsOf(connection))
    const [secrets, setSecrets] = useState<Record<string, string>>({})
    const [unreadable, setUnreadable] = useState<ReadonlySet<string>>(() => new Set())
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)
    const [saved, setSaved] = useState(false)

    const heading = headingOf(connection)
    const fields = useMemo(() => formFields(connection, schema), [connection, schema])
    const problems = useMemo(() => validateFields(fields, values), [fields, values])
    const write = useMayWrite('admin')
    const shut = firstShut(
        write.why,
        maySubmit(problems, unreadable) ? undefined : 'A setting above is not what this kind accepts.',
    )

    const send = () => {
        const body = patchBody(connection, editsOf(connection, values, secrets), given(named), given(description))
        if (body === null) {
            setSaved(true)
            return
        }
        setBusy(true)
        setProblem(null)
        void updateConnection(connection.code, body)
            .then(
                (row) => {
                    setSecrets({})
                    setSaved(true)
                    onSaved(row)
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
        <div className="space-y-4 p-4">
            <div className="space-y-1">
                <p className="flex items-center gap-2">
                    <span className={heading.named ? 'text-sm font-semibold' : 'font-mono text-sm font-semibold'}>
                        {heading.title}
                    </span>
                    <KindChip kind={connection.kind} />
                    {heading.code !== null && (
                        <span className="text-muted-foreground font-mono text-xs">{heading.code}</span>
                    )}
                </p>
                <p className="text-faint text-xs">
                    Created <Instant at={connection.created_at} />
                    {separatelyUpdated(connection.created_at, connection.updated_at) && (
                        <>
                            {' · updated '}
                            <Instant at={connection.updated_at} />
                        </>
                    )}
                </p>
                <Description text={connection.description} />
            </div>

            <div className="space-y-1.5">
                <Label htmlFor="connection-name">Name</Label>
                <Input
                    id="connection-name"
                    value={named}
                    onChange={(event) => {
                        setNamed(event.target.value)
                        setSaved(false)
                    }}
                    placeholder="What to call this on screen"
                />
                <p className="text-faint text-xs">
                    Display only. Every reference to this credential is by its code, {connection.code}.
                </p>
            </div>

            <div className="space-y-1.5">
                <Label htmlFor="connection-description">Description</Label>
                <Textarea
                    id="connection-description"
                    className="h-24"
                    value={description}
                    onChange={(event) => {
                        setDescription(event.target.value)
                        setSaved(false)
                    }}
                    placeholder="What this credential is for. Markdown is rendered."
                />
            </div>

            <div className="space-y-3">
                <p className="text-faint text-xs font-semibold tracking-wide uppercase">Settings</p>
                <SchemaForm
                    fields={fields}
                    values={values}
                    problems={problems}
                    onChange={(name, value) => {
                        setValues((current) => ({ ...current, [name]: value }))
                        setSaved(false)
                    }}
                    onUnreadable={(name, message) => {
                        setUnreadable((current) => withUnreadable(current, name, message))
                    }}
                />
                {connection.secret_fields.map((name) => (
                    <SecretField
                        key={name}
                        id={`secret-${name}`}
                        name={name}
                        stored={isSet(connection.config[name])}
                        value={secrets[name] ?? ''}
                        onChange={(typed) => {
                            setSecrets((current) => ({ ...current, [name]: typed }))
                            setSaved(false)
                        }}
                    />
                ))}
            </div>

            {problem !== null && <Refusal problem={problem} />}

            <div className="flex items-center gap-2">
                <Refusable why={shut}>
                    <Button size="sm" onClick={send} disabled={busy || shut !== undefined} title={shut}>
                        {busy ? 'Saving' : 'Save'}
                    </Button>
                </Refusable>
                {saved && <span className="text-muted-foreground text-xs">Saved.</span>}
            </div>
        </div>
    )
}

/**
 * The fields this form has a control for.
 *
 * A kind whose plugin is no longer installed publishes no schema, and the connection's own keys
 * are what is left to go on -- read as text, or as JSON for anything that is not a string.
 */
function formFields(connection: ConnectionOut, schema: JsonMap | null): FieldDescriptor[] {
    const secret = new Set(connection.secret_fields)
    if (schema !== null) return settingFields(schema, connection.secret_fields)
    return Object.keys(connection.config)
        .filter((name) => !secret.has(name))
        .map((name) => ({
            name,
            kind: typeof connection.config[name] === 'string' ? 'text' : 'json',
            help: null,
            required: false,
            nullable: true,
            fallback: undefined,
            options: [],
            mediaType: null,
            hint: null,
            placeholder: '',
            bounds: {},
            accepts: [],
        }))
}

/** The values the form starts on: what the connection carries, minus its secrets. */
function settingsOf(connection: ConnectionOut): JsonMap {
    const secret = new Set(connection.secret_fields)
    const values: JsonMap = {}
    for (const [name, value] of Object.entries(connection.config)) {
        if (secret.has(name)) continue
        values[name] = value
    }
    return values
}

/** Whether the instance holds a credential for this field, which is all a read can say. */
function isSet(value: unknown): boolean {
    return value !== null && value !== undefined
}

/** A box that was emptied is that member cleared, not a member set to "". */
function given(text: string): string | null {
    const trimmed = text.trim()
    return trimmed === '' ? null : trimmed
}

/**
 * What was actually changed, which is the only thing that goes into the config sent back.
 *
 * A SECRET BOX LEFT BLANK IS ABSENT. Not an empty string, which is a password somebody chose:
 * absent, so the value the read showed for it -- the marker the server keeps a credential by --
 * is what goes back on the wire.
 */
function editsOf(connection: ConnectionOut, values: JsonMap, secrets: Record<string, string>): JsonMap {
    const edits: JsonMap = {}
    for (const [name, value] of Object.entries(values)) {
        if (!Object.is(value, connection.config[name])) edits[name] = value
    }
    for (const [name, typed] of Object.entries(secrets)) {
        if (typed === '') continue
        edits[name] = typed
    }
    return edits
}
