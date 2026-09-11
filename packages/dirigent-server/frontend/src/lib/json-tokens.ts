/**
 * Tokenising pretty-printed JSON, so a screen can colour it without an editor.
 *
 * The input is always this app's own rendering -- `asJson`'s indented output -- so the
 * grammar here is that shape and nothing looser: strings with their escapes, numbers,
 * the three literals, and everything between them as punctuation. A string followed by a
 * colon is a key, which is the one distinction a reader's eye actually uses.
 */

export type JsonTokenKind = 'key' | 'string' | 'number' | 'literal' | 'punctuation'

export interface JsonToken {
    kind: JsonTokenKind
    text: string
}

const PIECE = /("(?:[^"\\]|\\.)*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(true|false|null)/g

/** Split one rendered JSON text into the pieces a colour attaches to, in order. */
export function tokenizeJson(text: string): JsonToken[] {
    const tokens: JsonToken[] = []
    let at = 0
    for (const found of text.matchAll(PIECE)) {
        if (found.index > at) tokens.push({ kind: 'punctuation', text: text.slice(at, found.index) })
        const [, string, colon, number, literal] = found
        if (string !== undefined) {
            tokens.push({
                kind: colon === undefined ? 'string' : 'key',
                text: string,
            })
            if (colon !== undefined) tokens.push({ kind: 'punctuation', text: colon })
        } else if (number !== undefined) {
            tokens.push({ kind: 'number', text: number })
        } else if (literal !== undefined) {
            tokens.push({ kind: 'literal', text: literal })
        }
        at = found.index + found[0].length
    }
    if (at < text.length) tokens.push({ kind: 'punctuation', text: text.slice(at) })
    return tokens
}
