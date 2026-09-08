import { useSyncExternalStore } from 'react'

/** Below `md`. The same 768px the utilities' `md:` variant is, said once in JS. */
const BELOW_MD = '(max-width: 767px)'

/** Below `lg`, which is where a listing stops being a table. */
const BELOW_LG = '(max-width: 1023px)'

interface Watch {
    subscribe: (listener: () => void) => () => void
    read: () => boolean
}

function watch(query: string): Watch {
    const media = typeof window === 'undefined' ? null : window.matchMedia(query)
    return {
        subscribe: (listener) => {
            media?.addEventListener('change', listener)
            return () => {
                media?.removeEventListener('change', listener)
            }
        },
        read: () => media?.matches ?? false,
    }
}

const shell = watch(BELOW_MD)
const table = watch(BELOW_LG)

/** What a query answers where there is no window at all, which is a wide one. */
const WIDE = () => false

/**
 * Whether the window is below the shell's breakpoint.
 *
 * A CLASS WHERE A CLASS WILL DO, THIS WHERE IT WILL NOT. Hiding one of two renderings with
 * `md:hidden` leaves both in the document, so every row, label and control exists twice --
 * two elements with one accessible name, and a listing a screen reader reads through twice.
 * Where the two forms are the same content drawn differently, only one of them is built.
 */
export function useSmallScreen(): boolean {
    return useSyncExternalStore(shell.subscribe, shell.read, WIDE)
}

/**
 * Whether a listing is too narrow to be a table.
 *
 * THE TABLE'S BREAKPOINT IS NOT THE SHELL'S. At 768 the content column beside the rail is
 * about 500px, which is a phone's width for four columns, so a listing takes the card form
 * until `lg` while everything else about a small screen turns at `md`.
 */
export function useNarrowTable(): boolean {
    return useSyncExternalStore(table.subscribe, table.read, WIDE)
}
