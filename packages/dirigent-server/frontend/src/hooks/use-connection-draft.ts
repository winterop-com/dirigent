import { useMemo, useState } from 'react'
import { useSchemaForm, type SchemaFormState } from '@winterop-com/sokkel-ui/schema/SchemaForm'

import { useMayWrite } from '@/hooks/use-may-write'
import { type JsonMap, type Problem } from '@/lib/api'
import { connectionBody, createShut, draftFor, type ConnectionDraft } from '@/lib/connection-draft'
import { createConnection, type ConnectionOut, type SurfaceEntry } from '@/lib/connections'
import { formSchema } from '@/lib/form-schema'
import { LABELS } from '@/lib/labels'
import { refusalOf } from '@/lib/refusal'
import { firstShut } from '@/lib/roles'

/**
 * One connection being minted, wherever the form asking for it is drawn.
 *
 * TWO SURFACES ASK FOR A CREDENTIAL AND NEITHER OWNS THE ASKING. The Connections screen's
 * dialog and the row of the Apply dialog's offer that says the document names a connection this
 * instance has not got are the same question with different things already known, so the state,
 * the validation and the write are here and each surface draws controls over them.
 *
 * THE FIELDS ARE THE KIND'S, so there are none until a kind is settled -- which is why a form
 * handed a kind by the document can draw its settings on the first render, and one asking for a
 * kind has nothing to draw until somebody picks one. Choosing another kind empties the settings,
 * which belong to the schema that asked for them. A field the kind declares secret is a secret
 * field in that form, and one left empty is left out of what is sent.
 *
 * A REFUSAL IS THE SERVER'S AND NOTHING DISMISSES ON ONE. A code already taken and a config the
 * kind's model does not accept each arrive as a problem document, and the surface draws it
 * beside the boxes it is about.
 */
export interface ConnectionDraftForm {
    draft: ConnectionDraft
    /** The kind chosen, or null while none is, which is what publishes the settings schema. */
    chosen: SurfaceEntry | null
    /** The kind's settings, its secrets among them, drawn from the kind's schema. */
    form: SchemaFormState
    /** Why Create is shut: this account's gate, or what the form is still missing. */
    shut: string | undefined
    busy: boolean
    problem: Problem | null
    setCode: (code: string) => void
    chooseKind: (kind: string) => void
    setName: (name: string) => void
    setDescription: (description: string) => void
    /** Mint it, and hand the row back to whatever is behind the form. */
    create: (onCreated: (row: ConnectionOut) => void) => void
}

/**
 * Hold one connection being typed.
 *
 * `code` and `kind` are what the caller already knows -- the document's own, for the offer's
 * row -- and the draft opens on them whether or not a control is drawn to change them.
 */
export function useConnectionDraft(
    kinds: readonly SurfaceEntry[],
    code = '',
    kind: string | null = null,
): ConnectionDraftForm {
    const [draft, setDraft] = useState<ConnectionDraft>(() => draftFor(code, kind))
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)

    const write = useMayWrite('admin')
    const chosen = kinds.find((one) => one.id === draft.kind) ?? null
    const schema = useMemo(
        () => formSchema(chosen?.config_schema, { secrets: chosen?.secret_fields ?? [] }),
        [chosen],
    )
    const form = useSchemaForm(schema, { initial: {} })

    return {
        draft,
        chosen,
        form,
        // A kind settled by a document rather than picked from the catalog may be one this
        // instance has not installed, and there is no config schema to ask against -- so the
        // form says which kind rather than minting a credential with nothing in it.
        shut: firstShut(
            write.why,
            createShut(draft),
            draft.kind !== '' && chosen === null ? LABELS.connections.kind_unknown(draft.kind) : undefined,
        ),
        busy,
        problem,
        setCode: (next) => {
            setDraft((current) => ({ ...current, code: next }))
        },
        chooseKind: (next) => {
            setDraft((current) => ({ ...current, kind: next }))
            form.setValue({})
        },
        setName: (next) => {
            setDraft((current) => ({ ...current, name: next }))
        },
        setDescription: (next) => {
            setDraft((current) => ({ ...current, description: next }))
        },
        create: (onCreated) => {
            if (!form.submit()) return
            setBusy(true)
            setProblem(null)
            void createConnection(connectionBody(draft, (form.value ?? {}) as JsonMap))
                .then(
                    (row) => {
                        setDraft(draftFor(code, kind))
                        form.setValue({})
                        onCreated(row)
                    },
                    (error: unknown) => {
                        setProblem(refusalOf(error))
                    },
                )
                .finally(() => {
                    setBusy(false)
                })
        },
    }
}
