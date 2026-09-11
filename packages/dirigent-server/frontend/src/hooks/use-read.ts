/**
 * One read that is not a listing.
 *
 * `hooks/use-paged` is the cursor walk a table does. This is its one-page sibling: a screen that
 * needs a single document -- what this instance is, whether it is ready, how the last day of
 * runs came out -- holds it here rather than growing its own copy of "reading, refused, landed"
 * three times over.
 *
 * THE FUNCTION'S IDENTITY IS THE QUESTION, the same rule `usePaged` follows: a caller that
 * passes a new function is asking something else, so the answer to the old question is
 * discarded rather than left on screen under a heading that has moved on.
 *
 * ASKING AGAIN IS QUIET. The same question re-asked keeps its last answer on screen until the
 * new one lands: a dashboard that blinks into a loading card every beat is louder than the
 * news it carries. Only a different question starts from nothing.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import { ApiError, type Problem } from '@/lib/api'

/** One read, as far as it has got. */
export interface Answer<T> {
    /** What the server answered, or null until it has. */
    value: T | null
    problem: Problem | null
    reading: boolean
    /** Whether the read has landed, which is what tells an empty answer from an unread one. */
    read: boolean
}

const UNREAD = { value: null, problem: null, reading: true, read: false }

export interface Reading<T> extends Answer<T> {
    /** Ask the same question again. */
    again: () => void
}

export function useRead<T>(read: () => Promise<T>): Reading<T> {
    const [round, setRound] = useState(0)
    const [held, setHeld] = useState<{ asked: unknown; answer: Answer<T> }>(() => ({
        asked: null,
        answer: UNREAD,
    }))

    const question = useMemo(() => ({ read, round }), [read, round])
    const stale = held.asked !== null && (held.asked as { read: unknown }).read === question.read
    const answer =
        held.asked === question
            ? held.answer
            : stale
              ? { ...held.answer, reading: true }
              : (UNREAD as Answer<T>)

    useEffect(() => {
        let wanted = true
        void question.read().then(
            (value) => {
                if (wanted)
                    setHeld({ asked: question, answer: { value, problem: null, reading: false, read: true } })
            },
            (error: unknown) => {
                if (!wanted) return
                const problem = error instanceof ApiError ? error.problem : null
                setHeld({ asked: question, answer: { value: null, problem, reading: false, read: true } })
            },
        )
        return () => {
            wanted = false
        }
    }, [question])

    const again = useCallback(() => {
        setRound((count) => count + 1)
    }, [])

    return { ...answer, again }
}
