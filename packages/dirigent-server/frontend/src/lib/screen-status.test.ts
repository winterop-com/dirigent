import { beforeEach, describe, expect, test } from 'vitest'

import { clearScreenStatus, screenStatus, setScreenStatus, streamNote } from '@/lib/screen-status'

beforeEach(() => {
    clearScreenStatus()
})

describe('what one run stream says along the foot of the shell', () => {
    test('says the state alone while the stream is up', () => {
        expect(streamNote('live')).toEqual({ note: 'live', tone: 'live' })
    })

    test('says a reconnect is a reconnect rather than leaving the last note standing', () => {
        expect(streamNote('reconnecting').tone).toBe('warn')
        expect(streamNote('connecting').tone).toBe('quiet')
    })

    test('says nothing once the run has settled, because a static note is not a state', () => {
        expect(streamNote('ended')).toEqual({ note: null, tone: 'quiet' })
    })
})

describe('the screen the bar is drawing for', () => {
    test('states a note and an identifier while it is mounted', () => {
        setScreenStatus({ note: 'live', tone: 'live', identifier: 'trace-1' })
        expect(screenStatus.get()).toEqual({ note: 'live', tone: 'live', identifier: 'trace-1' })
    })

    test('publishes nothing when it states the same thing again', () => {
        // The bar is subscribed for the life of the app: a run's stream reports its state on
        // every frame, and a re-render per log line is what that would cost.
        setScreenStatus({ note: 'live', tone: 'live', identifier: 'trace-1' })
        const before = screenStatus.get()
        setScreenStatus({ note: 'live', tone: 'live', identifier: 'trace-1' })
        expect(screenStatus.get()).toBe(before)
    })

    test('goes quiet when the screen that stated it is gone', () => {
        setScreenStatus({ note: 'live', tone: 'live', identifier: 'trace-1' })
        clearScreenStatus()
        expect(screenStatus.get()).toEqual({ note: null, tone: 'quiet', identifier: null })
    })
})
