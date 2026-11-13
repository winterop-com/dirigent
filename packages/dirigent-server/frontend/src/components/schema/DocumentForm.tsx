import { useSchemaForm } from '@winterop-com/sokkel-ui/schema/SchemaForm'
import type { JsonSchema } from '@winterop-com/sokkel-ui/schema/read'

import { GeneratedForm, type FormReferences } from '@/components/schema/GeneratedForm'
import type { JsonMap } from '@/lib/api'
import { deferReference, hasFields } from '@/lib/form-schema'
import { LABELS } from '@/lib/labels'
import { SCHEMA_FORM_WORDS } from '@/lib/library-words'

/**
 * A form over one map of a document, held by the document: it draws `value` and hands each change
 * to `onChange`, so a value changed elsewhere, such as in the source pane, is what it draws. Under
 * `deferred` a `${...}` value is left unchecked; under `fold` the fields neither required nor set
 * wait behind one disclosure.
 */
export function DocumentForm({
    schema,
    value,
    onChange,
    references,
    deferred = false,
    fold = false,
}: {
    schema: JsonSchema
    value: JsonMap
    onChange: (value: JsonMap) => void
    references?: FormReferences
    deferred?: boolean
    fold?: boolean
}) {
    const form = useSchemaForm(schema, {
        words: SCHEMA_FORM_WORDS,
        value,
        onChange: (next) => {
            onChange(isMap(next) ? next : {})
        },
        deferred: deferred ? deferReference : undefined,
    })

    if (!hasFields(schema))
        return <p className="text-sm text-muted-foreground">{LABELS.form.no_configuration}</p>
    return <GeneratedForm form={form} references={references} deferred={deferred} fold={fold} />
}

function isMap(value: unknown): value is JsonMap {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
}
