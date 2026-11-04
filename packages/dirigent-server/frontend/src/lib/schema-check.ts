/**
 * Trying a value against a schema: what is sent, what came back, and where in the value it points.
 *
 * THE FIELD NAMES ARE THE WIRE'S. `SchemaCheck` and `SchemaViolation` mirror the pydantic models
 * in `dirigent_client.schemas.schemas` member for member.
 *
 * NOTHING UNREADABLE IS SENT. Both editors hold text, and text that is not JSON is said where it
 * was typed rather than handed to the server to refuse.
 *
 * A POINTER IS FOUND IN THE TEXT IT WAS CHECKED AGAINST. `spansOf` walks a JSON text once and
 * answers where each value stands, by the pointer that addresses it, so a failure can be marked
 * at the place it names. A failure at a place the text does not hold -- a required property that
 * is missing -- is marked at the nearest place that is there.
 */

import { apiSend, type JsonMap, type Problem } from '@/lib/api'
import { LABELS } from '@/lib/labels'

/** One way a value fails a schema. `SchemaViolation`. */
export interface SchemaViolation {
    /** A JSON Pointer into the value, empty for the value itself. */
    at: string
    /** The keyword that refused it. */
    keyword: string
    /** The way through the schema to that keyword. */
    schema_at: string
    message: string
}

/** What checking a value found. `SchemaCheck`. */
export interface SchemaCheck {
    valid: boolean
    /** Earliest place in the value first, a hundred at most. */
    errors: SchemaViolation[]
    /** How many failures there were past the ones listed. */
    omitted: number
}

/** Check a value against a schema body, which need not be stored. `POST /schemas/$check`. */
export function checkSchema(body: JsonMap, value: unknown): Promise<SchemaCheck> {
    return apiSend<SchemaCheck>('/schemas/$check', 'POST', { body, value })
}

/** What the two editors hold: something to send, or the one of them that cannot be read. */
export type CheckInput =
    | { kind: 'ready'; body: JsonMap; value: unknown }
    | { kind: 'unreadable'; which: 'schema' | 'value'; sentence: string }

/** Read both editors, the schema first, because a value is checked against it. */
export function checkInput(schemaText: string, valueText: string): CheckInput {
    const schema = readJson(schemaText)
    if (!schema.ok)
        return { kind: 'unreadable', which: 'schema', sentence: LABELS.schemas.unreadable(schema.error) }
    if (!isObject(schema.value)) {
        return { kind: 'unreadable', which: 'schema', sentence: LABELS.schemas.tester.not_an_object }
    }
    const value = readJson(valueText)
    if (!value.ok) {
        return {
            kind: 'unreadable',
            which: 'value',
            sentence: LABELS.schemas.tester.value_unreadable(value.error),
        }
    }
    return { kind: 'ready', body: schema.value, value: value.value }
}

/** One text read as JSON, or what the parser said about it. */
export function readJson(text: string): { ok: true; value: unknown } | { ok: false; error: string } {
    try {
        return { ok: true, value: JSON.parse(text) as unknown }
    } catch (error) {
        return { ok: false, error: error instanceof Error ? error.message : String(error) }
    }
}

function isObject(value: unknown): value is JsonMap {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * Whether the text in a schema editor is the shape the instance holds, however it is laid out.
 *
 * A body comes back from the server re-serialised, and a database may hold an object's keys in an
 * order of its own, so two texts are the same schema when they parse to the same JSON.
 */
export function holdsStored(text: string, body: JsonMap): boolean {
    const read = readJson(text)
    return read.ok && canonical(read.value) === canonical(body)
}

/** A JSON value written with every object's keys in order, so equal values are equal text. */
function canonical(value: unknown): string {
    if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
    if (isObject(value)) {
        const keys = Object.keys(value).toSorted()
        return `{${keys.map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`
    }
    return JSON.stringify(value)
}

/**
 * A value to start trying from, out of what the schema itself says, or nothing where it says none.
 *
 * The schema's first `examples` entry, else its `default`, else its `const`; an object schema
 * with none of those is the object its properties would make out of theirs.
 */
export function sampleOf(schema: unknown, depth = 0): unknown {
    if (!isObject(schema) || depth > 8) return undefined
    if (Array.isArray(schema.examples) && schema.examples.length > 0) return schema.examples[0]
    if ('default' in schema) return schema.default
    if ('const' in schema) return schema.const
    if (!isObject(schema.properties)) return undefined
    const made: JsonMap = {}
    for (const [key, property] of Object.entries(schema.properties)) {
        const sample = sampleOf(property, depth + 1)
        if (sample !== undefined) made[key] = sample as JsonMap[string]
    }
    return Object.keys(made).length === 0 ? undefined : made
}

/** The text a value editor starts from: the schema's own sample, or an empty object. */
export function sampleText(schema: unknown): string {
    return JSON.stringify(sampleOf(schema) ?? {}, null, 2)
}

/** Where one value stands in a JSON text, by character offsets. */
export interface Span {
    /** Where it starts: at its key, where it is a member of an object. */
    start: number
    /** Where it ends. */
    end: number
    /** Where the part worth marking ends: the whole of a scalar, the opening bracket of a container. */
    head: number
}

/**
 * Where every value of a JSON text stands, by the JSON Pointer that addresses it.
 *
 * The text is one `JSON.parse` already read, so the walk trusts its shape and answers an empty
 * map for anything else.
 */
export function spansOf(text: string): Map<string, Span> {
    const spans = new Map<string, Span>()
    let at = 0

    const skip = () => {
        while (at < text.length && ' \t\n\r'.includes(text[at] ?? '')) at += 1
    }
    const string = (): string => {
        const from = at
        at += 1
        while (at < text.length && text[at] !== '"') at += text[at] === '\\' ? 2 : 1
        at += 1
        return JSON.parse(text.slice(from, at)) as string
    }
    const value = (pointer: string, keyed: number | null) => {
        skip()
        const start = at
        const opening = text[at]
        if (opening === '{' || opening === '[') {
            at += 1
            skip()
            let index = 0
            while (at < text.length && text[at] !== '}' && text[at] !== ']') {
                if (opening === '{') {
                    const keyAt = at
                    const key = string()
                    skip()
                    at += 1
                    value(`${pointer}/${escapePart(key)}`, keyAt)
                } else {
                    value(`${pointer}/${index}`, null)
                    index += 1
                }
                skip()
                if (text[at] === ',') at += 1
                skip()
            }
            at += 1
            spans.set(pointer, { start: keyed ?? start, end: at, head: start + 1 })
            return
        }
        if (opening === '"') string()
        else while (at < text.length && !',]} \t\n\r'.includes(text[at] ?? '')) at += 1
        spans.set(pointer, { start: keyed ?? start, end: at, head: at })
    }

    try {
        value('', null)
    } catch {
        return new Map()
    }
    return spans
}

/** One part of a JSON Pointer, with the two characters a pointer reserves escaped. */
function escapePart(part: string): string {
    return part.replaceAll('~', '~0').replaceAll('/', '~1')
}

/** The place a pointer names, or the nearest place above it that the text holds. */
export function spanAt(spans: Map<string, Span>, pointer: string): Span | null {
    let looking = pointer
    for (;;) {
        const found = spans.get(looking)
        if (found !== undefined) return found
        if (looking === '') return null
        looking = looking.slice(0, looking.lastIndexOf('/'))
    }
}

/** A range of a buffer to mark, and what the mark says on hover. */
export interface Mark {
    start: number
    end: number
    message: string
}

/** Every failure as a mark on the value it was checked against. */
export function marksOf(text: string, errors: readonly SchemaViolation[]): Mark[] {
    const spans = spansOf(text)
    const marks: Mark[] = []
    for (const error of errors) {
        const span = spanAt(spans, error.at)
        if (span !== null) marks.push({ start: span.start, end: span.head, message: error.message })
    }
    return marks
}

/** What the server answered one check with, and the two texts it was asked about. */
export type CheckAnswer =
    | { kind: 'checked'; check: SchemaCheck; schema: string; value: string }
    | { kind: 'refused'; problem: Problem; schema: string; value: string }

/**
 * What the result says, out of what the editors hold now and the last answer to land.
 *
 * UNREADABLE TEXT IS SAID AT ONCE. Nothing was asked, so there is no answer to wait for.
 *
 * AN ANSWER STAYS UNTIL THE NEXT ONE LANDS. A check is asked again a moment after each keystroke,
 * and a verdict that blinked out under every one would be a result nobody can read while typing.
 * `current` says whether the answer is about the texts on screen, which is what decides whether
 * its places can be marked on the value: offsets into an older text point at the wrong things.
 */
export type CheckShown =
    | { kind: 'unreadable'; which: 'schema' | 'value'; sentence: string }
    | { kind: 'checking' }
    | { kind: 'refused'; problem: Problem; current: boolean }
    | { kind: 'checked'; check: SchemaCheck; current: boolean }

export function shownCheck(
    input: CheckInput,
    answer: CheckAnswer | null,
    schema: string,
    value: string,
): CheckShown {
    if (input.kind === 'unreadable') return input
    if (answer === null) return { kind: 'checking' }
    const current = answer.schema === schema && answer.value === value
    if (answer.kind === 'refused') return { kind: 'refused', problem: answer.problem, current }
    return { kind: 'checked', check: answer.check, current }
}

/** Where a failure is drawn on screen: its pointer, or the value itself where it has none. */
export function pointerLabel(pointer: string): string {
    return pointer === '' ? LABELS.schemas.tester.root : pointer
}
