/**
 * The schema resources, as this bundle reads them.
 *
 * THE FIELD NAMES ARE THE WIRE'S. Every interface here mirrors a pydantic model in
 * `dirigent_client.schemas.schemas` member for member.
 *
 * A SCHEMA IS LOCALLY AUTHORED. What an instance holds is a JSON Schema somebody wrote to
 * say what a payload should look like -- never fetched or introspected from anywhere. Its
 * code, name and description are the schema's own `$id`, `title` and `description`, settled
 * when it is stored, so what this bundle reads back is a portable schema rather than a
 * wrapper around one.
 */

import { apiJson, apiSend, type JsonMap, type Page } from '@/lib/api'
import { PAGE } from '@/lib/paging'

/** A schema as every response shows it: the identity quartet and the schema body. `SchemaOut`. */
export interface SchemaOut {
    id: string
    /** The key this schema is addressed by, and the name `requires.schemas` reaches it under. */
    code: string
    /** What to call it on screen, when the schema gave itself a `title`. */
    name: string | null
    /** Long-form, from the schema's own `description`. */
    description: string | null
    /** The JSON Schema itself. */
    body: JsonMap
    created_at: string
    updated_at: string
}

/** Read one page of schemas, in code order. */
export function readSchemas(after: string | null = null): Promise<Page<SchemaOut>> {
    const query = new URLSearchParams({ limit: String(PAGE) })
    if (after !== null) query.set('after', after)
    return apiJson<Page<SchemaOut>>(`/schemas?${query.toString()}`)
}

/** Store a JSON Schema, letting the server take its identity from the schema's own keywords. */
export function createSchema(body: JsonMap, code: string | null): Promise<SchemaOut> {
    const payload: JsonMap = { body }
    if (code !== null && code !== '') payload.code = code
    return apiSend<SchemaOut>('/schemas', 'POST', payload)
}

/** Remove a schema. */
export function deleteSchema(code: string): Promise<void> {
    return apiSend<void>(`/schemas/${encodeURIComponent(code)}`, 'DELETE', {})
}

/**
 * What the schemas listing says when it has nothing in it.
 *
 * A schema is authored, not discovered, so an empty instance is one nobody has written a
 * shape for yet -- which is what the empty state says, rather than a bare "none".
 */
export function schemasNote(rows: readonly SchemaOut[]): string | null {
    if (rows.length === 0) return null
    return `${String(rows.length)} ${rows.length === 1 ? 'schema' : 'schemas'}`
}
