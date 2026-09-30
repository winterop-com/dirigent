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
import { LABELS } from '@/lib/labels'
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

/** Read one schema by the code it is addressed by. */
export function readSchema(code: string): Promise<SchemaOut> {
    return apiJson<SchemaOut>(`/schemas/${encodeURIComponent(code)}`)
}

/** Store a JSON Schema, letting the server take its identity from the schema's own keywords. */
export function createSchema(body: JsonMap, code: string | null): Promise<SchemaOut> {
    const payload: JsonMap = { body }
    if (code !== null && code !== '') payload.code = code
    return apiSend<SchemaOut>('/schemas', 'POST', payload)
}

/** What editing a schema may change; the code is fixed once minted. `SchemaUpdate`. */
export interface SchemaUpdate {
    name?: string | null
    description?: string | null
    body?: JsonMap
}

/** Send an edit. A member left out of the body is a member the server leaves alone. */
export function updateSchema(code: string, body: SchemaUpdate): Promise<SchemaOut> {
    return apiSend<SchemaOut>(`/schemas/${encodeURIComponent(code)}`, 'PATCH', body)
}

/** Remove a schema. */
export function deleteSchema(code: string): Promise<void> {
    return apiSend<void>(`/schemas/${encodeURIComponent(code)}`, 'DELETE', {})
}

/** The stored schema as an editor opens it: the shape itself, indented to be read. */
export function bodyText(schema: Pick<SchemaOut, 'body'>): string {
    return JSON.stringify(schema.body, null, 2)
}

/**
 * The PATCH body one edit sends, or nothing at all when nothing changed.
 *
 * A member left out is a member the server leaves alone, so a name or a description nobody
 * touched is not sent back and a form with no edits at all sends no request. `body` is passed
 * only where the text stopped being what `bodyText` opened on, because a schema that came back
 * through the same stringify is the schema the instance already holds.
 */
export function schemaPatch(
    row: Pick<SchemaOut, 'name' | 'description'>,
    named: string | null,
    description: string | null,
    body: JsonMap | undefined,
): SchemaUpdate | null {
    const payload: SchemaUpdate = {}
    if (named !== row.name) payload.name = named
    if (description !== row.description) payload.description = description
    if (body !== undefined) payload.body = body
    return Object.keys(payload).length === 0 ? null : payload
}

/**
 * The whole schema, as a replacement of one the instance holds under that code.
 *
 * A CREATE READS THE SCHEMA'S OWN KEYWORDS AND AN UPDATE DOES NOT. `POST /schemas` takes the
 * name and the description from `title` and `description` where the write gives none, and
 * `PATCH /schemas/{code}` leaves both alone. So replacing a stored schema with a schema written
 * somewhere else sends the identity that schema declares alongside its body, or the instance
 * would keep labels belonging to a shape it no longer holds.
 */
export function wholeSchema(body: JsonMap): SchemaUpdate {
    return { body, name: keyword(body, 'title'), description: keyword(body, 'description') }
}

/** One of the schema's own string keywords, or null where it declares none. */
function keyword(body: JsonMap, name: 'title' | 'description'): string | null {
    const said = body[name]
    return typeof said === 'string' ? said : null
}

/**
 * What the schemas listing says when it has nothing in it.
 *
 * A schema is authored, not discovered, so an empty instance is one nobody has written a
 * shape for yet -- which is what the empty state says, rather than a bare "none".
 */
export function schemasNote(rows: readonly SchemaOut[]): string | null {
    if (rows.length === 0) return null
    const said = rows.length === 1 ? LABELS.schemas.count.one : LABELS.schemas.count.many
    return said(String(rows.length))
}
