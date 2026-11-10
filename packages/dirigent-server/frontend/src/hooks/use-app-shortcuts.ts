import { useEffect } from 'react'

import { toggleRail } from '@/lib/panels'
import { applePlatform, togglesRail, togglesTerminal, type FocusedField } from '@/lib/shortcuts'
import { toggleTerminal } from '@/lib/terminal'

/** Whatever has focus in this document, described for `lib/shortcuts`. */
export function focusedField(): FocusedField | null {
    const element = document.activeElement
    if (!(element instanceof HTMLElement)) return null
    return {
        tagName: element.tagName,
        isContentEditable: element.isContentEditable,
        inEditor: element.closest('.cm-editor') !== null,
    }
}

/**
 * The one place a real `KeyboardEvent` is read for the keys this app answers itself: the rail's
 * chord and the terminal's letter. The palette's chord and `?` are the shell's.
 *
 * All it does is describe the press and the focused element to `lib/shortcuts`, which decides.
 * Bound on the document rather than on the shell, so a chord works with focus anywhere.
 */
export function useAppShortcuts(): void {
    useEffect(() => {
        const apple = applePlatform(navigator.userAgent)

        function onKeyDown(event: KeyboardEvent): void {
            const press = {
                key: event.key,
                ctrlKey: event.ctrlKey,
                metaKey: event.metaKey,
                altKey: event.altKey,
            }
            if (togglesRail(press, focusedField(), apple)) {
                event.preventDefault()
                toggleRail()
                return
            }
            if (togglesTerminal(press, focusedField())) {
                event.preventDefault()
                toggleTerminal()
            }
        }

        document.addEventListener('keydown', onKeyDown)
        return () => {
            document.removeEventListener('keydown', onKeyDown)
        }
    }, [])
}
