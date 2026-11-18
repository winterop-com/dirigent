import { useEffect, useMemo, useState } from 'react'
import type { JsonSchema } from '@winterop-com/sokkel-ui/schema/read'

import type { JsonMap } from '@/lib/api'
import { refusalsOf, type SchemaCheck } from '@/lib/form-refusals'
import { LABELS } from '@/lib/labels'

/**
 * Every field a form's schema check refuses, by its key, from the check the form's controls use.
 *
 * The checker carries ajv and is fetched on first use, the way the form fetches it, so the
 * answer is empty until it has loaded. A checker that cannot be fetched refuses the form whole.
 */
export function useFormRefusals(
    schema: JsonSchema,
    value: JsonMap,
    options: { deferred?: boolean; whole: string },
): Record<string, string> {
    const [check, setCheck] = useState<SchemaCheck | null>(null)
    const [failed, setFailed] = useState<string | null>(null)
    useEffect(() => {
        let live = true
        import('@winterop-com/sokkel-ui/schema/validate').then(
            (module) => {
                if (live) setCheck(() => module.validate)
            },
            (error: unknown) => {
                if (live) setFailed(error instanceof Error ? error.message : String(error))
            },
        )
        return () => {
            live = false
        }
    }, [])
    const { deferred = false, whole } = options
    return useMemo(() => {
        if (failed !== null) return { [whole]: LABELS.form.refusal.unchecked(failed) }
        if (check === null) return {}
        return refusalsOf(check, schema, value, { deferred, whole })
    }, [check, failed, schema, value, deferred, whole])
}
