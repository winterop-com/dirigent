/**
 * What a field's code names, and where it was found.
 *
 * A block's config schema marks a string as holding the code of a connection or of a schema, and
 * the form draws that thing under the box. This module is the whole of the finding -- a value,
 * the document being edited and the two listings in, an answer out -- and the row renders the
 * answer and decides nothing.
 *
 * A CARRIED SCHEMA COMES FIRST, which is the order the engine resolves one in: a document's own
 * top-level `schemas:` section answers a gate's code before anything the instance holds, so a
 * document that carries every shape it names runs on its own. A row that named the instance's
 * copy would be naming something the run will not read.
 *
 * NOTHING IS MISSING WHILE A LISTING IS NULL, the rule `lib/requirements` is built on. A read
 * that has not landed is `unread` rather than `missing`, because a screen that said "not stored"
 * for the half second before the schemas listing arrives would teach a reader to stop believing
 * it.
 *
 * A REFERENCE NAMES NO CODE. The document language lets `${...}` stand wherever a value goes, so
 * a field written as one holds a value the run will compute rather than a key anything can be
 * looked up by, and there is nothing to resolve or to draw.
 */

import type { JsonMap } from '@/lib/api'
import type { ConnectionOut } from '@/lib/connections'
import type { SchemaOut } from '@/lib/schemas'

/** Where a schema's code was answered, and by what. */
export type SchemaResolution =
    | { source: 'carried'; body: JsonMap }
    | { source: 'instance'; schema: SchemaOut }
    | { source: 'missing' }
    | { source: 'unread' }

/** Where a connection's code was answered, and by what. */
export type ConnectionResolution =
    | { source: 'instance'; connection: ConnectionOut }
    | { source: 'missing' }
    | { source: 'unread' }

/**
 * The code one field value names, or null when it names none.
 *
 * Empty is nothing to look up, a value that is not text is not a code, and a value carrying
 * `${...}` is a reference the engine resolves at run time rather than a key.
 */
export function codeNamed(value: unknown): string | null {
    if (typeof value !== 'string') return null
    const code = value.trim()
    if (code === '' || code.includes('${')) return null
    return code
}

/** The schemas a document carries under its own top-level section, by code. */
export function carriedSchemas(document: JsonMap | null): Record<string, JsonMap> {
    const carried = document?.schemas
    if (carried === null || carried === undefined || typeof carried !== 'object' || Array.isArray(carried)) {
        return {}
    }
    const bodies: Record<string, JsonMap> = {}
    for (const [code, body] of Object.entries(carried as JsonMap)) {
        if (body !== null && typeof body === 'object' && !Array.isArray(body)) bodies[code] = body as JsonMap
    }
    return bodies
}

/** What a schema's code resolves to: the document's own copy, then the instance's, then neither. */
export function resolveSchema(
    document: JsonMap | null,
    code: string,
    held: readonly SchemaOut[] | null,
): SchemaResolution {
    const carried = carriedSchemas(document)[code]
    if (carried !== undefined) return { source: 'carried', body: carried }
    if (held === null) return { source: 'unread' }
    const stored = held.find((one) => one.code === code)
    return stored === undefined ? { source: 'missing' } : { source: 'instance', schema: stored }
}

/** What a connection's code resolves to. A document carries no connections a server would store. */
export function resolveConnection(code: string, held: readonly ConnectionOut[] | null): ConnectionResolution {
    if (held === null) return { source: 'unread' }
    const stored = held.find((one) => one.code === code)
    return stored === undefined ? { source: 'missing' } : { source: 'instance', connection: stored }
}
