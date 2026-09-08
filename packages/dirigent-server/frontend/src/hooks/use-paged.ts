/**
 * One screen's walk through a cursor-paged listing.
 *
 * `lib/paging` decides what each answer does to the rows; this is the part that needs a browser:
 * the reads, and the recheck when a tab comes back into view.
 *
 * THE QUESTION IS PART OF THE STATE. A screen whose filters changed is asking a different
 * question, and the rows read for the old one are not an answer to it -- so the rows are held
 * beside the question they were read for, and a question nobody is asking any more has no rows
 * rather than the wrong ones. An answer carries the question it answers all the way to the fold:
 * one whose question has been left behind changes nothing, so a read still in flight when the
 * filters change cannot put its rows, or its question, back into what is held.
 *
 * THE RECHECK IS NOT A POLL. Nothing here runs on a timer. A tab nobody is looking at costs this
 * server nothing, and a tab that comes back reads page one once -- which for a newest-first
 * listing is exactly the rows that arrived while it was away.
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { useHeartbeat } from '@/hooks/use-heartbeat'

import { ApiError, type Page } from '@/lib/api'
import { appended, noRows, noted, prepended, refused, started, type Paged } from '@/lib/paging'

/** A listing and the three things a screen does to it. */
export interface Paging<T> {
    state: Paged<T>
    /** Read the next page. Does nothing while a read is in flight or at the end of the listing. */
    more: () => void
    /** Throw away every page read and ask the same question again. */
    reload: () => void
    /** Say the reader has seen what the last recheck brought in. */
    note: () => void
}

/** The rows a screen holds, beside the question they were read for. */
export interface Held<T> {
    asked: unknown
    paged: Paged<T>
}

/**
 * What is held after one answer.
 *
 * `asked` is the question the answer went out with and `asking` the one the screen is on now: an
 * answer to a question nobody is asking any more leaves what is held untouched, rows and question
 * both. An answer to the current question is folded into the rows held for it, and into empty rows
 * when what is held answers something else.
 */
export function folded<T>(
    held: Held<T>,
    asked: unknown,
    asking: unknown,
    change: (current: Paged<T>) => Paged<T>,
): Held<T> {
    if (asked !== asking) return held
    return { asked, paged: change(held.asked === asked ? held.paged : noRows<T>()) }
}

/**
 * Read a listing one page at a time.
 *
 * `read` fetches one page from a cursor, and its identity is the question being asked: a screen
 * whose filters changed passes a new function, and this starts the listing over.
 */
export function usePaged<T>(
    read: (after: string | null) => Promise<Page<T>>,
    idOf: (row: T) => string,
    pulse?: number | null,
): Paging<T> {
    const [again, setAgain] = useState(0)
    const [held, setHeld] = useState<Held<T>>(() => ({ asked: null, paged: noRows<T>() }))

    const question = useMemo(() => ({ read, again }), [again, read])
    const state = held.asked === question ? held.paged : noRows<T>()

    // The question the screen is on now, which the fold checks an answer's question against.
    // It moves in the commit that changes the question, before any answer can land.
    const asking = useRef<unknown>(question)
    useLayoutEffect(() => {
        asking.current = question
    }, [question])

    /** Fold one answer into the rows, and only into the rows of the question it answers. */
    const apply = useCallback(
        (change: (current: Paged<T>) => Paged<T>) => {
            setHeld((current) => folded(current, question, asking.current, change))
        },
        [question],
    )

    // The cursor "load more" continues from is the one held when it is pressed, not the one
    // captured by whichever render registered the handler.
    const carried = useRef<Paged<T>>(state)
    useEffect(() => {
        carried.current = state
    }, [state])

    useEffect(() => {
        void read(null).then(
            (page) => {
                apply((current) => appended(current, page, idOf))
            },
            (error: unknown) => {
                apply((current) => refused(current, problemOf(error)))
            },
        )
    }, [apply, idOf, read])

    const more = useCallback(() => {
        const current = carried.current
        if (current.reading || current.next === null) return
        apply(started)
        void read(current.next).then(
            (page) => {
                apply((carrying) => appended(carrying, page, idOf))
            },
            (error: unknown) => {
                apply((carrying) => refused(carrying, problemOf(error)))
            },
        )
    }, [apply, idOf, read])

    // A pulsed listing stays quietly current: page one is read again every few watched
    // seconds and folded in at the head, and a beat that fails changes nothing -- what is
    // on screen stays, and the next beat asks again.
    const look = useCallback(() => {
        void read(null).then(
            (page) => {
                apply((current) => prepended(current, page, idOf))
            },
            () => {
                // The beat is not the read this screen was asked for.
            },
        )
    }, [apply, idOf, read])
    useHeartbeat(look, pulse ?? null)

    const note = useCallback(() => {
        apply(noted)
    }, [apply])

    const reload = useCallback(() => {
        setAgain((count) => count + 1)
    }, [])

    return { state, more, reload, note }
}

/** What a failed read leaves on the screen: the problem document, or nothing to show. */
function problemOf(error: unknown) {
    return error instanceof ApiError ? error.problem : null
}
