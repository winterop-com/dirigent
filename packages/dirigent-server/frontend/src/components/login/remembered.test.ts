import { afterEach, describe, expect, test } from 'vitest'

import { USERNAME_STORAGE_KEY, rememberUsername, rememberedUsername } from '@/components/login/remembered'

function deny(): never {
    throw new Error('storage denied')
}

/** A storage that holds what it is given, or one that refuses everything. */
function stubStorage(refusing = false): Map<string, string> {
    const held = new Map<string, string>()
    Object.defineProperty(globalThis, 'localStorage', {
        configurable: true,
        value: refusing
            ? { getItem: deny, setItem: deny, removeItem: deny }
            : {
                  getItem: (key: string) => held.get(key) ?? null,
                  setItem: (key: string, value: string) => held.set(key, value),
                  removeItem: (key: string) => held.delete(key),
              },
    })
    return held
}

afterEach(() => {
    Reflect.deleteProperty(globalThis, 'localStorage')
})

describe('the remembered username', () => {
    test('comes back as it was kept', () => {
        stubStorage()
        rememberUsername('admin')
        expect(rememberedUsername()).toBe('admin')
    })

    test('is the empty string when nothing was ever kept', () => {
        stubStorage()
        expect(rememberedUsername()).toBe('')
    })

    test('is forgotten rather than kept blank', () => {
        const held = stubStorage()
        rememberUsername('admin')
        rememberUsername('')
        expect(held.has(USERNAME_STORAGE_KEY)).toBe(false)
        expect(rememberedUsername()).toBe('')
    })

    test('is the empty string where storage refuses to be read', () => {
        stubStorage(true)
        expect(rememberedUsername()).toBe('')
    })

    test('keeping it where storage refuses to be written is not an error', () => {
        stubStorage(true)
        expect(() => {
            rememberUsername('admin')
        }).not.toThrow()
    })

    test('is the empty string where there is no storage at all', () => {
        expect(rememberedUsername()).toBe('')
    })
})
