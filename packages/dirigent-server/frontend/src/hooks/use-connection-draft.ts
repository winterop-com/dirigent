import { useMemo, useState } from 'react'

import { useMayWrite } from '@/hooks/use-may-write'
import { type Problem } from '@/lib/api'
import {
    connectionBody,
    createShut,
    draftFor,
    withKind,
    withSecret,
    withSetting,
    type ConnectionDraft,
} from '@/lib/connection-draft'
import { createConnection, settingFields, type ConnectionOut, type SurfaceEntry } from '@/lib/connections'
import { LABELS } from '@/lib/labels'
import { refusalOf } from '@/lib/refusal'
import { firstShut } from '@/lib/roles'
import { validateFields, withUnreadable, type FieldDescriptor } from '@/lib/schema-form'

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
 * kind has nothing to draw until somebody picks one.
 *
 * A REFUSAL IS THE SERVER'S AND NOTHING DISMISSES ON ONE. A code already taken and a config the
 * kind's model does not accept each arrive as a problem document, and the surface draws it
 * beside the boxes it is about.
 */
export interface ConnectionDraftForm {
    draft: ConnectionDraft
    /** The kind chosen, or null while none is, which is what publishes the settings schema. */
    chosen: SurfaceEntry | null
    /** The controls the kind's schema asks for, minus every field it declares secret. */
    fields: FieldDescriptor[]
    problems: Record<string, string>
    /** Which fields a problem may be stated for yet, or nothing once a create was asked for. */
    stated: ReadonlySet<string> | undefined
    /** Why Create is shut: this account's gate, or what the form is still missing. */
    shut: string | undefined
    busy: boolean
    problem: Problem | null
    setCode: (code: string) => void
    chooseKind: (kind: string) => void
    setName: (name: string) => void
    setDescription: (description: string) => void
    setSetting: (name: string, value: unknown) => void
    setSecret: (name: string, typed: string) => void
    touch: (name: string) => void
    markUnreadable: (name: string, message: string | null) => void
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
    const [touched, setTouched] = useState<ReadonlySet<string>>(() => new Set())
    const [unreadable, setUnreadable] = useState<ReadonlySet<string>>(() => new Set())
    const [asked, setAsked] = useState(false)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)

    const write = useMayWrite('admin')
    const chosen = kinds.find((one) => one.id === draft.kind) ?? null
    const fields = useMemo(
        () => settingFields(chosen?.config_schema ?? null, chosen?.secret_fields ?? []),
        [chosen],
    )
    const problems = useMemo(() => validateFields(fields, draft.values), [fields, draft.values])

    return {
        draft,
        chosen,
        fields,
        problems,
        // A required field is not a complaint until somebody has been there or asked to create.
        stated: asked ? undefined : touched,
        // A kind settled by a document rather than picked from the catalog may be one this
        // instance has not installed, and there is no config schema to ask against -- so the
        // form says which kind rather than minting a credential with nothing in it.
        shut: firstShut(
            write.why,
            createShut(draft, problems, unreadable),
            draft.kind !== '' && chosen === null ? LABELS.connections.kind_unknown(draft.kind) : undefined,
        ),
        busy,
        problem,
        setCode: (next) => {
            setDraft((current) => ({ ...current, code: next }))
        },
        chooseKind: (next) => {
            setDraft((current) => withKind(current, next))
            setTouched(new Set())
            setUnreadable(new Set())
            setAsked(false)
        },
        setName: (next) => {
            setDraft((current) => ({ ...current, name: next }))
        },
        setDescription: (next) => {
            setDraft((current) => ({ ...current, description: next }))
        },
        setSetting: (name, value) => {
            setDraft((current) => withSetting(current, name, value))
        },
        setSecret: (name, typed) => {
            setDraft((current) => withSecret(current, name, typed))
        },
        touch: (name) => {
            setTouched((current) => (current.has(name) ? current : new Set(current).add(name)))
        },
        markUnreadable: (name, message) => {
            setUnreadable((current) => withUnreadable(current, name, message))
        },
        create: (onCreated) => {
            setAsked(true)
            setBusy(true)
            setProblem(null)
            void createConnection(connectionBody(draft))
                .then(
                    (row) => {
                        setDraft(draftFor(code, kind))
                        setTouched(new Set())
                        setUnreadable(new Set())
                        setAsked(false)
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
