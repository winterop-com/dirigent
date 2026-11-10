import { describe, expect, it } from 'vitest'

import { formatTest } from '@winterop-com/sokkel-ui/schema/formats'

import { DIRIGENT_FORMATS, isHumaneDuration, isSize } from '@/lib/schema-formats'

function check(name: string, value: string): boolean {
    const format = formatTest(DIRIGENT_FORMATS[name])
    if (format === true) return true
    return format instanceof RegExp ? format.test(value) : format(value)
}

function say(name: string): string | undefined {
    const format = DIRIGENT_FORMATS[name]
    return typeof format === 'object' && !(format instanceof RegExp) ? format.say : undefined
}

describe('humane-duration', () => {
    it.each(['30s', '1h30m', '250ms', '1.5d', '2w', '90', '0.5', ' 5m '])('accepts %j', (value) => {
        expect(isHumaneDuration(value)).toBe(true)
    })

    it.each(['', 'PT5M', '5 m', '-1', '5x', 'm', '1e'])('refuses %j', (value) => {
        expect(isHumaneDuration(value)).toBe(false)
    })
})

describe('size', () => {
    it.each(['64mb', '64MiB', '1.5kb', '4096', '0b', '1GB'])('accepts %j', (value) => {
        expect(isSize(value)).toBe(true)
    })

    it.each(['', '-1', '1.5', '1.5b', 'mb', '64 xb', '64m'])('refuses %j', (value) => {
        expect(isSize(value)).toBe(false)
    })
})

describe('the rest of dirigent formats', () => {
    it('takes any storage URI, since the schemes are the server to know', () => {
        expect(check('storage-uri', 'nowhere://at/all')).toBe(true)
    })

    it('holds a UUID to its version and variant', () => {
        expect(check('uuid7', '01890a5d-ac96-774b-bcce-b302099a8057')).toBe(true)
        expect(check('uuid7', '{01890a5dac96774bbcceb302099a8057}')).toBe(true)
        expect(check('uuid4', '01890a5d-ac96-774b-bcce-b302099a8057')).toBe(false)
        expect(check('uuid7', '01890a5d-ac96-774b-7cce-b302099a8057')).toBe(false)
    })

    it('reads a ULID in either case and refuses its excluded letters', () => {
        expect(check('ulid', '01ARZ3NDEKTSV4RRFFQ69G5FAV')).toBe(true)
        expect(check('ulid', '01arz3ndektsv4rrffq69g5fav')).toBe(true)
        expect(check('ulid', '01ARZ3NDEKTSV4RRFFQ69G5FAI')).toBe(false)
        expect(check('ulid', '81ARZ3NDEKTSV4RRFFQ69G5FAV')).toBe(false)
    })

    it('holds a digest to its length and base64 to its padding', () => {
        expect(check('md5', 'd41d8cd98f00b204e9800998ecf8427e')).toBe(true)
        expect(check('sha1', 'd41d8cd98f00b204e9800998ecf8427e')).toBe(false)
        expect(check('base64', '')).toBe(true)
        expect(check('base64', 'aGk=')).toBe(true)
        expect(check('base64', 'aGk')).toBe(false)
    })
})

describe('what a value in the wrong format says', () => {
    it('reads the words a person types, never the format name', () => {
        expect(say('humane-duration')).toBe('Expected a duration such as 30s or 5m')
        expect(say('size')).toBe('Expected bytes, or a size such as 16KB or 2MB')
        expect(say('uuid7')).toBe('Expected a version 7 UUID')
        expect(say('sha256')).toBe('Expected a SHA-256 digest in hex')
    })

    it('gives every format that can fail words of its own', () => {
        for (const [name, format] of Object.entries(DIRIGENT_FORMATS)) {
            if (format === true) continue
            expect(say(name), name).toMatch(/^Expected \S/)
        }
    })
})
