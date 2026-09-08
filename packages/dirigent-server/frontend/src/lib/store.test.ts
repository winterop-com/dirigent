import { describe, expect, test, vi } from 'vitest'

import { createStore } from '@/lib/store'

describe('a module store', () => {
    test('answers what it was built with until something changes it', () => {
        expect(createStore(3).get()).toBe(3)
    })

    test('publishes a change to every watcher', () => {
        const store = createStore('a')
        const first = vi.fn()
        const second = vi.fn()
        store.subscribe(first)
        store.subscribe(second)
        store.set('b')
        expect(store.get()).toBe('b')
        expect(first).toHaveBeenCalledOnce()
        expect(second).toHaveBeenCalledOnce()
    })

    test('publishes nothing when the value did not change, which is what stops a render loop', () => {
        const store = createStore('a')
        const seen = vi.fn()
        store.subscribe(seen)
        store.set('a')
        expect(seen).not.toHaveBeenCalled()
    })

    test('holds the reference it was given, so a snapshot is stable between changes', () => {
        const value = { open: true }
        const store = createStore(value)
        expect(store.get()).toBe(store.get())
        expect(store.get()).toBe(value)
    })

    test('an equal but distinct object is still a change, because identity is what a reader compares', () => {
        const store = createStore({ open: true })
        const seen = vi.fn()
        store.subscribe(seen)
        store.set({ open: true })
        expect(seen).toHaveBeenCalledOnce()
    })

    test('derives the next value from the current one', () => {
        const store = createStore(1)
        store.update((current) => current + 1)
        expect(store.get()).toBe(2)
    })

    test('a watcher that stops watching hears nothing more', () => {
        const store = createStore(0)
        const seen = vi.fn()
        store.subscribe(seen)()
        store.set(1)
        expect(seen).not.toHaveBeenCalled()
    })

    test('a watcher that unsubscribes from inside its own notification does not skip the next one', () => {
        const store = createStore(0)
        const order: string[] = []
        const stopFirst = store.subscribe(() => {
            order.push('first')
            stopFirst()
        })
        store.subscribe(() => {
            order.push('second')
        })
        store.set(1)
        expect(order).toEqual(['first', 'second'])
    })
})
