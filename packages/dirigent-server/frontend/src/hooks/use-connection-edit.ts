import { useCallback, useMemo, useState } from 'react'

import { useMayWrite } from '@/hooks/use-may-write'
import { type JsonMap, type Problem } from '@/lib/api'
import { patchBody, settingFields, updateConnection, type ConnectionOut } from '@/lib/connections'
import { LABELS } from '@/lib/labels'
import { refusalOf } from '@/lib/refusal'
import { firstShut } from '@/lib/roles'
import { maySubmit, validateFields, withUnreadable, type FieldDescriptor } from '@/lib/schema-form'

/** What the edit state of a connection's dialog holds, and what its Save does. */
export interface ConnectionEdit {
    named: string
    setNamed: (typed: string) => void
    description: string
    setDescription: (typed: string) => void
    fields: FieldDescriptor[]
    values: JsonMap
    problems: Record<string, string>
    secrets: Record<string, string>
    setting: (name: string, value: unknown) => void
    secret: (name: string, typed: string) => void
    unreadable: (name: string, message: string | null) => void
    problem: Problem | null
    busy: boolean
    /** Why Save is shut, or nothing when it is not. */
    shut: string | undefined
    /** Start again from what the connection holds. */
    reset: () => void
    /** Send what was changed. `done` hears the row where something was written, else null. */
    save: (done: (row: ConnectionOut | null) => void) => void
}

/**
 * One connection's settings, being edited.
 *
 * THE FORM IS THE KIND'S SCHEMA, the same way a step's form is its block's. A kind this instance
 * no longer has installed publishes nothing, and the form falls back to the keys the connection
 * itself carries, because a credential outliving its plugin still has to be readable and
 * deletable.
 *
 * A SECRET IS NOT A SCHEMA FIELD HERE. Every field the kind declares secret is taken out of the
 * generated form and drawn as a write-only password box. A box left blank is absent from the body,
 * so the marker the read showed goes back and the server keeps what it has.
 *
 * A BOX THAT DOES NOT PARSE SHUTS SAVE. The form keeps the last value that parsed, so saving over
 * a half-written JSON setting would send something other than what is on screen.
 */
export function useConnectionEdit(connection: ConnectionOut, schema: JsonMap | null): ConnectionEdit {
    const [named, setNamed] = useState(connection.name ?? '')
    const [description, setDescription] = useState(connection.description ?? '')
    const [values, setValues] = useState<JsonMap>(() => settingsOf(connection))
    const [secrets, setSecrets] = useState<Record<string, string>>({})
    const [unreadableNames, setUnreadableNames] = useState<ReadonlySet<string>>(() => new Set())
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)

    const fields = useMemo(() => formFields(connection, schema), [connection, schema])
    const problems = useMemo(() => validateFields(fields, values), [fields, values])
    const write = useMayWrite('admin')
    const shut = firstShut(
        write.why,
        maySubmit(problems, unreadableNames) ? undefined : LABELS.connections.settings_refused,
    )

    const reset = useCallback(() => {
        setNamed(connection.name ?? '')
        setDescription(connection.description ?? '')
        setValues(settingsOf(connection))
        setSecrets({})
        setUnreadableNames(new Set())
        setProblem(null)
    }, [connection])

    const save = (done: (row: ConnectionOut | null) => void) => {
        const body = patchBody(
            connection,
            editsOf(connection, values, secrets),
            given(named),
            given(description),
        )
        if (body === null) {
            done(null)
            return
        }
        setBusy(true)
        setProblem(null)
        void updateConnection(connection.code, body)
            .then(done, (error: unknown) => {
                setProblem(refusalOf(error))
            })
            .finally(() => {
                setBusy(false)
            })
    }

    return {
        named,
        setNamed,
        description,
        setDescription,
        fields,
        values,
        problems,
        secrets,
        setting: (name, value) => {
            setValues((current) => ({ ...current, [name]: value }))
        },
        secret: (name, typed) => {
            setSecrets((current) => ({ ...current, [name]: typed }))
        },
        unreadable: (name, message) => {
            setUnreadableNames((current) => withUnreadable(current, name, message))
        },
        problem,
        busy,
        shut,
        reset,
        save,
    }
}

/** The fields this form has a control for, from the schema or from what the row itself carries. */
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
            refers: null,
            hint: null,
            placeholder: '',
            bounds: {},
            accepts: [],
            holds: [],
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

/** A box that was emptied is that member cleared, not a member set to "". */
function given(text: string): string | null {
    const trimmed = text.trim()
    return trimmed === '' ? null : trimmed
}

/**
 * What was actually changed, which is the only thing that goes into the config sent back.
 *
 * A SECRET BOX LEFT BLANK IS ABSENT. Not an empty string, which is a password somebody chose:
 * absent, so the value the read showed for it is what goes back on the wire.
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
