import { useEffect, useRef } from 'react'
import { useSchemaForm } from '@winterop-com/sokkel-ui/schema/SchemaForm'
import type { JsonSchema } from '@winterop-com/sokkel-ui/schema/read'

import { GeneratedForm, type FormReferences } from '@/components/schema/GeneratedForm'
import type { JsonMap } from '@/lib/api'
import { deferReference, hasFields } from '@/lib/form-schema'
import { LABELS } from '@/lib/labels'
import { sameJson } from '@/lib/schema-form'

/**
 * A form over one map of a document, held by the document: what is typed is handed to
 * `onChange`, and a value changed elsewhere, such as in the source pane, replaces what the form
 * holds. Under `deferred` a `${...}` value is left unchecked.
 */
export function DocumentForm({
    schema,
    value,
    onChange,
    references,
    deferred = false,
}: {
    schema: JsonSchema
    value: JsonMap
    onChange: (value: JsonMap) => void
    references?: FormReferences
    deferred?: boolean
}) {
    const form = useSchemaForm(schema, { initial: value, deferred: deferred ? deferReference : undefined })
    const written = useRef<unknown>(value)
    const report = useRef(onChange)
    const replace = form.setValue

    useEffect(() => {
        report.current = onChange
    })

    useEffect(() => {
        if (sameJson(value, written.current)) return
        written.current = value
        replace(value)
    }, [value, replace])

    useEffect(() => {
        if (sameJson(form.value, written.current)) return
        written.current = form.value
        report.current(isMap(form.value) ? form.value : {})
    }, [form.value])

    if (!hasFields(schema))
        return <p className="text-sm text-muted-foreground">{LABELS.form.no_configuration}</p>
    return <GeneratedForm form={form} references={references} deferred={deferred} />
}

function isMap(value: unknown): value is JsonMap {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
}
