/**
 * What a document carries that an instance will not store, and the way forward from that refusal.
 *
 * THE REFUSAL STAYS. A document may carry its own `connections:` and its own `schemas:` so that
 * it runs alone under `dg run --local`; an applied document is stored, versioned and exported,
 * so the apply refuses one that does and a reference by code is the single contract. What was
 * missing was never a way to store a carried section -- it was the way forward at the point of
 * failure, which is what this decides.
 *
 * IT IS `dg pipeline new`, IN ONE PRESS. The CLI copies a starter, lifts every carried section
 * out, names the codes under `requires:`, and then prints what the instance still has to hold.
 * The lift is `lib/starters.uncarry`, the same text rewrite the CLI makes; this is the list that
 * goes with it, and what the instance still has to hold is not advice -- a document naming a
 * connection or a schema this instance has not got is refused by the apply itself, so the list
 * says which and the button stays shut until pressing it would work.
 *
 * FOUR CASES, AND THE LIST SAYS WHICH. A carried entry meets an instance that has nothing under
 * that code (`create`), one that holds the same thing (`already here`), or one that holds
 * something else under the same name (`differs`). The fourth is a document that only names a
 * code under `requires:` and carries nothing -- there is nothing here to create from, and the
 * apply's own issues and the editor's Requires chips are what say it, through `lib/requirements`.
 *
 * `differs` IS NOT ACTED ON. A stored schema is what every other pipeline naming that code
 * validates against, so replacing it from a document being applied would change what those
 * pipelines mean, and an apply that quietly bound this document's gate to a different shape
 * than the one written in it would be worse still. The row says the codes collide and the
 * button is shut; resolving it is a deliberate act elsewhere.
 *
 * A CODE IS NOT INVENTED HERE. The code a carried schema is stored under is the key the document
 * already writes it under, which is what every `validate.schema` step in it references and what
 * goes under `requires.schemas`. Nothing generates it and nothing here changes it: another code
 * would leave those references pointing at nothing.
 *
 * A SCHEMA IS CREATED AND A CONNECTION IS NOT. A carried schema is a shape: it holds no
 * credential, and storing it under the code the document already names is the same resource in
 * the place an instance keeps one. A connection's config can hold a credential in a field the
 * kind declares secret -- and in one it does not, since a `sql` or a `git` connection's `url`
 * carries a password or a token inline -- so nothing here can read a carried connection and say
 * no credential is in it. Sealing a value afterwards does not unread it either: it travelled in
 * the document, in the clear, through whatever carried the document. Nor can a carried
 * connection be compared with a stored one, because a read redacts every secret field, so
 * `differs` cannot be told from `already here` for one; both are reasons a connection is left to
 * the Connections screen, and the notes under the list say so.
 */

import type { JsonMap, Problem } from '@/lib/api'
import { LABELS } from '@/lib/labels'

/** The sections a document may carry, which an instance refuses to store. `CARRIED` in core. */
export const CARRIED = ['connections', 'schemas'] as const

/** The refusal codes an apply answers a carried section with. `dirigent_core.messages`. */
const REFUSAL_CODES: ReadonlySet<string> = new Set([
    'document.carried_connections',
    'document.carried_schemas',
])

/** Which kind of thing one carried entry is, which decides what may be done with it. */
export type CarriedKind = 'schema' | 'connection'

/** What becomes of one entry of a carried section when the document is applied. */
export type CarriedAction =
    /** Stored on this instance from what the document carries, under the code it uses. */
    | 'create'
    /** The instance holds it already, and the document will name the instance's own. */
    | 'held'
    /** The instance holds something else under that code, which nothing here resolves. */
    | 'differs'
    /** The instance has not got it and nothing here stores it, so the apply is refused. */
    | 'missing'

/** One entry of a carried section, and what becomes of it. */
export interface CarriedItem {
    kind: CarriedKind
    /** The code the document addresses it by, which is what every reference to it names. */
    code: string
    action: CarriedAction
    /** The kind a carried connection declares, which is what creating one by hand needs. */
    connectionKind: string | null
    /** The schema body the document carried, which is what a create stores. */
    body: JsonMap | null
}

/** One stored schema, as much of it as this comparison needs. A `SchemaOut` is one. */
export interface StoredSchema {
    code: string
    body: JsonMap
}

/** What this instance holds of what a document carries, or null where a read has not landed. */
export interface Held {
    /** Every carried code this instance holds a schema under, with the body it holds. */
    schemas: readonly StoredSchema[] | null
    /** Every carried code this instance holds a connection under. */
    connections: readonly string[] | null
}

/** Nothing read yet, which is what the offer waits on rather than calling a code missing. */
export const NOTHING_READ: Held = { schemas: null, connections: null }

/** Whether a refusal is the one a carried section makes, which is what the offer answers. */
export function carriedRefusal(problem: Problem | null): boolean {
    if (problem === null) return false
    return problem.problems.some((issue) => REFUSAL_CODES.has(issue.code))
}

/** The codes a document carries, by section, which is what the instance is asked about. */
export function carriedCodes(document: JsonMap): { schemas: string[]; connections: string[] } {
    return {
        schemas: Object.keys(sectionIn(document, 'schemas')),
        connections: Object.keys(sectionIn(document, 'connections')),
    }
}

/**
 * Every entry the document carries, and what becomes of each.
 *
 * `mayCreate` is whether this account passes the gate in front of `POST /schemas`: an operator
 * applies and an admin stores a schema, so for an operator a carried schema is missing rather
 * than created, and the button is shut rather than failing half way through.
 */
export function carriedItems(document: JsonMap, held: Held, mayCreate: boolean): CarriedItem[] {
    return [
        ...Object.entries(sectionIn(document, 'schemas')).map(([code, body]) => ({
            kind: 'schema' as const,
            code,
            action: schemaAction(code, asMap(body), held.schemas, mayCreate),
            connectionKind: null,
            body: asMap(body),
        })),
        ...Object.entries(sectionIn(document, 'connections')).map(([code, definition]) => ({
            kind: 'connection' as const,
            code,
            action: (held.connections?.includes(code) ?? false) ? ('held' as const) : ('missing' as const),
            connectionKind: kindOf(definition),
            body: null,
        })),
    ]
}

/** Whether the document carries anything at all. */
export function anythingCarried(document: JsonMap): boolean {
    return CARRIED.some((section) => Object.keys(sectionIn(document, section)).length > 0)
}

/** The schemas the offer stores, each with the body and the code to store it under. */
export function creations(items: readonly CarriedItem[]): CarriedItem[] {
    return items.filter((item) => item.action === 'create' && item.body !== null)
}

/**
 * Why applying would still be refused or would mean something else, or nothing when it is safe.
 *
 * A code the document carries that this instance holds a different thing under comes first: the
 * apply would go through and the pipeline would be bound to the instance's shape rather than the
 * one written in the document, which is the one outcome nobody would see. After it come the
 * things the apply refuses of its own accord, said here before the button is pressed rather than
 * afterwards as a plan that wrote nothing.
 */
export function offerBlocked(items: readonly CarriedItem[]): string | undefined {
    const words = LABELS.editor.carried
    const differing = codesOf(items, 'schema', 'differs')
    if (differing.length > 0) {
        const named = differing.join(', ')
        return differing.length > 1 ? words.differs_why_many(named) : words.differs_why_one(named)
    }
    const connections = codesOf(items, 'connection', 'missing')
    if (connections.length > 0) {
        const named = connections.join(', ')
        return connections.length > 1 ? words.no_connection_many(named) : words.no_connection_one(named)
    }
    if (codesOf(items, 'schema', 'missing').length > 0) return words.no_schema_gate
    return undefined
}

/** What one row says becomes of it, in the words a requirements list already reads in. */
export function actionWord(item: CarriedItem): string {
    return LABELS.editor.carried.state[item.action]
}

/**
 * The one line over the list, which is what this dialog is for said once.
 *
 * The refusal itself is not drawn beside it. The server writes one sentence for every surface
 * and a sentence is not a way forward; the list under this says which thing is in which state
 * and the controls say what to do, so saying it again in the server's words would be the same
 * fact three times and the loudest copy of it would be the one nobody can act on.
 */
export function offerNote(items: readonly CarriedItem[]): string {
    const made = creations(items).length
    const words = LABELS.editor.carried
    return words.note(made === 0 ? words.names_only : made === 1 ? words.stores_one : words.stores_many)
}

/**
 * Why a carried connection is not one of the things applying stores, or nothing when none is.
 *
 * It is the reason and not the remedy: the control beside it is the remedy, and a sentence
 * telling somebody where to go while a button goes there is the same instruction twice.
 */
export function connectionNote(items: readonly CarriedItem[]): string | undefined {
    if (codesOf(items, 'connection', 'missing').length === 0) return undefined
    return LABELS.editor.carried.connection_note
}

/** What was stored, said once it has been: the toast a write nothing on screen is waiting for. */
export function storedNote(made: readonly CarriedItem[]): string {
    return LABELS.editor.carried.stored(made.length, made.map((one) => one.code).join(', '))
}

/** The carried connections this instance has not got, which is what a door is offered for. */
export function missingConnections(items: readonly CarriedItem[]): CarriedItem[] {
    return items.filter((item) => item.kind === 'connection' && item.action === 'missing')
}

/** The codes of one kind in one state, in the order the document writes them. */
function codesOf(items: readonly CarriedItem[], kind: CarriedKind, action: CarriedAction): string[] {
    return items.filter((item) => item.kind === kind && item.action === action).map((item) => item.code)
}

/** What one carried section holds, keyed by code, or nothing when the document carries none. */
function sectionIn(document: JsonMap, section: (typeof CARRIED)[number]): Record<string, unknown> {
    return asMap(document[section]) ?? {}
}

/**
 * What becomes of one carried schema: created, the instance's own already, or a collision.
 *
 * The comparison is over parsed JSON on both sides -- the document came through the YAML reader
 * and the stored body through the wire -- so key order and indentation are gone before it runs
 * and what is left is a difference in the schema itself.
 */
function schemaAction(
    code: string,
    body: JsonMap | null,
    held: readonly StoredSchema[] | null,
    mayCreate: boolean,
): CarriedAction {
    const stored = held?.find((one) => one.code === code)
    if (held === null || stored === undefined) return mayCreate ? 'create' : 'missing'
    return sameJson(stored.body, body) ? 'held' : 'differs'
}

/** Whether two parsed JSON values are the same value, whatever order their keys arrived in. */
export function sameJson(left: unknown, right: unknown): boolean {
    if (left === right) return true
    if (Array.isArray(left) || Array.isArray(right)) {
        if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) return false
        return left.every((one, index) => sameJson(one, right[index]))
    }
    if (left === null || right === null) return false
    if (typeof left !== 'object' || typeof right !== 'object') return false
    const ours = left as JsonMap
    const theirs = right as JsonMap
    const keys = Object.keys(ours)
    if (keys.length !== Object.keys(theirs).length) return false
    return keys.every((key) => key in theirs && sameJson(ours[key], theirs[key]))
}

/** The kind a carried connection declares, or null when it declares none. */
function kindOf(definition: unknown): string | null {
    const kind = asMap(definition)?.kind
    return typeof kind === 'string' ? kind : null
}

function asMap(value: unknown): JsonMap | null {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
    return value as JsonMap
}
