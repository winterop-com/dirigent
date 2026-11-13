import { useCallback, useMemo, useState } from 'react'
import {
    useSchemaForm,
    type SealedSecret,
    type SchemaFormState,
} from '@winterop-com/sokkel-ui/schema/SchemaForm'

import { useMayWrite } from '@/hooks/use-may-write'
import { type JsonMap, type Problem } from '@/lib/api'
import { patchBody, updateConnection, type ConnectionOut } from '@/lib/connections'
import { formSchema } from '@/lib/form-schema'
import { refusalOf } from '@/lib/refusal'
import { SCHEMA_FORM_WORDS } from '@/lib/library-words'

/** What the edit state of a connection's dialog holds, and what its Save does. */
export interface ConnectionEdit {
    named: string
    setNamed: (typed: string) => void
    description: string
    setDescription: (typed: string) => void
    /** The connection's settings, its secrets among them, drawn from its kind's schema. */
    form: SchemaFormState
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
 * A SECRET IS WRITE-ONLY. Every field the kind declares secret is a secret field, shown as set
 * where the connection holds one and left as it is unless it is replaced, so the marker the read
 * showed goes back and the server keeps what it has.
 *
 * SAVE SHOWS WHAT IS WRONG. Asking to save over a value the schema refuses, or a box that does not
 * parse, sends nothing and marks every field at fault.
 */
export function useConnectionEdit(connection: ConnectionOut, schema: JsonMap | null): ConnectionEdit {
    const [named, setNamed] = useState(connection.name ?? '')
    const [description, setDescription] = useState(connection.description ?? '')
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)

    const drawn = useMemo(
        () => formSchema(schema ?? carriedSchema(connection), { secrets: connection.secret_fields }),
        [connection, schema],
    )
    const sealed = useMemo(() => sealedOf(connection), [connection])
    const form = useSchemaForm(drawn, { initial: settingsOf(connection), sealed, words: SCHEMA_FORM_WORDS })
    const write = useMayWrite('admin')
    const shut = write.why

    const replace = form.setValue
    const reset = useCallback(() => {
        setNamed(connection.name ?? '')
        setDescription(connection.description ?? '')
        replace(settingsOf(connection))
        setProblem(null)
    }, [connection, replace])

    const save = (done: (row: ConnectionOut | null) => void) => {
        if (!form.submit()) return
        const body = patchBody(
            connection,
            editsOf(connection, (form.value ?? {}) as JsonMap),
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
        form,
        problem,
        busy,
        shut,
        reset,
        save,
    }
}

/**
 * The schema of a connection whose kind publishes none: a line of text for each setting it holds
 * as text, JSON for any other, and a secret field for each secret.
 */
function carriedSchema(connection: ConnectionOut): JsonMap {
    const secret = new Set(connection.secret_fields)
    return {
        type: 'object',
        properties: Object.fromEntries(
            Object.entries(connection.config).map(([name, value]) => [
                name,
                secret.has(name) || typeof value === 'string' ? { type: 'string' } : {},
            ]),
        ),
    }
}

/** The secrets the connection holds, which the form shows as set. */
function sealedOf(connection: ConnectionOut): SealedSecret[] {
    return connection.secret_fields
        .filter((name) => connection.config[name] !== null && connection.config[name] !== undefined)
        .map((name) => ({ path: [name] }))
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
 * What was actually changed, which is the only thing that goes into the config sent back: a
 * setting emptied is sent as cleared. A secret left as it is is absent from the form's value, so
 * the value the read showed for it is what goes back on the wire.
 */
function editsOf(connection: ConnectionOut, values: JsonMap): JsonMap {
    const edits: JsonMap = {}
    for (const name of Object.keys(settingsOf(connection))) {
        if (!Object.hasOwn(values, name)) edits[name] = undefined
    }
    for (const [name, value] of Object.entries(values)) {
        if (!Object.is(value, connection.config[name])) edits[name] = value
    }
    return edits
}
