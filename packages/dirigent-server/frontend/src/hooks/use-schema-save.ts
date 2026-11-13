import { useCallback, useState } from 'react'

import type { JsonMap, Problem } from '@/lib/api'
import { LABELS } from '@/lib/labels'
import { local, refusalOf } from '@/lib/refusal'
import { bodyText, holdDraft, schemaPatch, updateSchema, type SchemaOut } from '@/lib/schemas'

/**
 * Saving an edit of a stored schema, which the schema's page and its full-screen window share.
 *
 * Only what changed is sent: a body only where the text stopped being what `bodyText` opened on,
 * and nothing at all where nothing moved. Text that is not JSON is refused here, in the words the
 * editor's own refusal is said in, before anything is asked of the server. A save that lands lets
 * the draft go, because the instance now holds it.
 */
export function useSchemaSave(schema: SchemaOut, onSaved: (row: SchemaOut) => void) {
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)
    const [saved, setSaved] = useState(false)

    const save = useCallback(
        (named: string | null, description: string | null, text: string) => {
            setProblem(null)
            let body: JsonMap | undefined
            if (text !== bodyText(schema)) {
                try {
                    body = JSON.parse(text || '{}') as JsonMap
                } catch (error) {
                    setProblem(local(LABELS.schemas.unreadable(String(error))))
                    return
                }
            }
            const payload = schemaPatch(schema, named, description, body)
            if (payload === null) {
                setSaved(true)
                return
            }
            setBusy(true)
            void updateSchema(schema.code, payload)
                .then(
                    (row) => {
                        holdDraft(schema.code, text, text)
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
        },
        [onSaved, schema],
    )

    return { save, busy, saved, setSaved, problem }
}
