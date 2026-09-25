import { useSyncExternalStore } from 'react'

/** Below `md`. The same 768px the utilities' `md:` variant is, said once in JS. */
const BELOW_MD = '(max-width: 767px)'

/** Below `lg`: a window no listing in this app can hold a table in, rail and padding included. */
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
const small = watch(BELOW_LG)

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
 * Whether the window is too small for any listing in this app to be a table.
 *
 * A FLOOR UNDER THE MEASUREMENT, NOT A REPLACEMENT FOR IT. Below `lg` the content column beside
 * the rail is about 500px and a two-column listing would measure itself as fitting one -- two
 * columns of twenty characters, which is a table by arithmetic and a card by reading it. From
 * `lg` up the listing's own box is the only thing that knows what it holds, panel included.
 */
export function useSmallWindow(): boolean {
    return useSyncExternalStore(small.subscribe, small.read, WIDE)
}
