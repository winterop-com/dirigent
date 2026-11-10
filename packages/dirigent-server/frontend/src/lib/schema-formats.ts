/**
 * The JSON Schema formats dirigent adds beside the standard ones, held to the rules the server
 * checks them by, so an editor and a form refuse what an apply would refuse and nothing more.
 *
 * `size` is held to the rule an apply reads a size by. `storage-uri` is checked on the server
 * against the schemes this instance's storage backends claim, which the browser does not know, so
 * any string passes it here. A pack's own formats are not registered and go unchecked. A value
 * that fails one says the format's words from `LABELS.form.format`, never the format's name.
 */

import {
    registerSchemaFormats,
    type SchemaFormats,
    type SchemaFormatTest,
} from '@winterop-com/sokkel-ui/schema/formats'

import { LABELS } from '@/lib/labels'

/** A bare number, as the server reads one with Python's `float`. */
const NUMBER = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i

/** A humane duration: one or more suffixed terms, such as `30s` or `1h30m`. */
const DURATION = /^(?:\d+(?:\.\d+)?(?:ms|[wdhms]))+$/

/** A humane size: one number and one unit, such as `64mb` or `1.5GiB`. */
const SIZE = /^(\d+(?:\.\d+)?)(t|g|m|k)?i?b$/i

const SIZE_UNITS: Record<string, number> = { '': 1, k: 1024, m: 1024 ** 2, g: 1024 ** 3, t: 1024 ** 4 }

/** A duration a document may write: a non-negative number of seconds, or the humane grammar. */
export function isHumaneDuration(value: string): boolean {
    const text = value.trim()
    if (NUMBER.test(text)) return Number(text) >= 0
    return DURATION.test(text)
}

/** A size a document may write: a whole, non-negative number of bytes, bare or with a unit. */
export function isSize(value: string): boolean {
    const text = value.trim()
    if (NUMBER.test(text)) {
        const bytes = Number(text)
        return Number.isInteger(bytes) && bytes >= 0
    }
    const match = SIZE.exec(text)
    if (match === null) return false
    const bytes = Number(match[1]) * SIZE_UNITS[(match[2] ?? '').toLowerCase()]
    return Number.isInteger(bytes)
}

/** A UUID of exactly this version, spelled any way Python's `uuid.UUID` reads one. */
function isUuidVersion(version: string): (value: string) => boolean {
    const digits = new RegExp(`^[0-9a-f]{12}${version}[0-9a-f]{3}[89ab][0-9a-f]{15}$`, 'i')
    return (value) => {
        const hex = value
            .replaceAll('urn:', '')
            .replaceAll('uuid:', '')
            .replace(/^\{+|\}+$/g, '')
            .replaceAll('-', '')
        return digits.test(hex)
    }
}

/** A format's check, and the sentence a value that fails it reads, from its words in the catalogue. */
function worded(test: SchemaFormatTest, words: keyof typeof LABELS.form.format) {
    return { test, say: LABELS.form.expected(LABELS.form.format[words]) }
}

/** Every format dirigent's server checks beyond the standard set, by the name a schema gives it. */
export const DIRIGENT_FORMATS: SchemaFormats = {
    'humane-duration': worded(isHumaneDuration, 'humane_duration'),
    size: worded(isSize, 'size'),
    'storage-uri': true,
    ulid: worded(/^[0-7][0-9A-HJKMNP-TV-Z]{25}$/i, 'ulid'),
    uuid4: worded(isUuidVersion('4'), 'uuid4'),
    uuid7: worded(isUuidVersion('7'), 'uuid7'),
    md5: worded(/^[0-9a-f]{32}$/i, 'md5'),
    sha1: worded(/^[0-9a-f]{40}$/i, 'sha1'),
    sha256: worded(/^[0-9a-f]{64}$/i, 'sha256'),
    sha512: worded(/^[0-9a-f]{128}$/i, 'sha512'),
    base64: worded(/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/, 'base64'),
}

/** Hand dirigent's formats to every schema check in the app. */
export function registerDirigentFormats(): void {
    registerSchemaFormats(DIRIGENT_FORMATS)
}
