import { afterEach, describe, expect, test, vi } from 'vitest'

import { whenIdle } from '@/lib/idle'

/** The global this module reads, which not every browser has. */
type MaybeIdle = { requestIdleCallback?: (task: () => void, options?: { timeout: number }) => void }

afterEach(() => {
    delete (globalThis as MaybeIdle).requestIdleCallback
    vi.useRealTimers()
})

describe('speculative work waits for the browser', () => {
    test('an idle callback is what runs the task where there is one', () => {
        const idle = vi.fn()
        ;(globalThis as MaybeIdle).requestIdleCallback = idle
        const task = vi.fn()

        whenIdle(task)

        expect(idle).toHaveBeenCalledTimes(1)
        expect(task).not.toHaveBeenCalled()
        // It carries a deadline, so a browser that never goes idle still runs it.
        expect(idle.mock.calls[0][1]).toMatchObject({ timeout: expect.any(Number) })
    })

    test('a browser with no idle runs the task on a timer instead, and never synchronously', () => {
        vi.useFakeTimers()
        const task = vi.fn()

        whenIdle(task)
        expect(task).not.toHaveBeenCalled()

        vi.runAllTimers()
        expect(task).toHaveBeenCalledTimes(1)
    })
})
