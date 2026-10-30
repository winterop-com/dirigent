import { useEffect } from 'react'

import { paletteOpen } from '@/lib/palette'
import { toggleRail } from '@/lib/panels'
import {
    applePlatform,
    focusesSearch,
    opensPalette,
    opensShortcuts,
    togglesRail,
    togglesTerminal,
    type FocusedField,
} from '@/lib/shortcuts'
import { toggleTerminal } from '@/lib/terminal'

/** Whatever has focus in this document, described for `lib/shortcuts`. */
export function focusedField(): FocusedField | null {
    const element = document.activeElement
    if (!(element instanceof HTMLElement)) return null
    return {
        tagName: element.tagName,
        isContentEditable: element.isContentEditable,
        inEditor: element.closest('.monaco-editor') !== null,
    }
}

/**
 * The one place a real `KeyboardEvent` is read.
 *
 * All it does is describe the press and the focused element to `lib/shortcuts`, which decides.
 * Bound on the document rather than on the shell, so a chord works with focus anywhere --
 * inside the palette, inside a dialog, on the page's own body.
 */
export function useAppShortcuts(onShortcuts: () => void): void {
    useEffect(() => {
        const apple = applePlatform(navigator.userAgent)

        function onKeyDown(event: KeyboardEvent): void {
            const press = {
                key: event.key,
                ctrlKey: event.ctrlKey,
                metaKey: event.metaKey,
                altKey: event.altKey,
            }
            if (opensPalette(press)) {
                event.preventDefault()
                paletteOpen.update((open) => !open)
                return
            }
            if (togglesRail(press, focusedField(), apple)) {
                event.preventDefault()
                toggleRail()
                return
            }
            if (togglesTerminal(press, focusedField())) {
                event.preventDefault()
                toggleTerminal()
                return
            }
            if (opensShortcuts(press, focusedField())) {
                event.preventDefault()
                onShortcuts()
                return
            }
            if (focusesSearch(press, focusedField())) {
                // A dialog's own box, where one is open: the page behind it is not what is in front.
                const scope = document.querySelector('[role="dialog"]') ?? document
                const box = scope.querySelector<HTMLInputElement>('[data-search-shortcut]:not(:disabled)')
                if (box === null) return
                event.preventDefault()
                box.focus()
                box.select()
            }
        }

        document.addEventListener('keydown', onKeyDown)
        return () => {
            document.removeEventListener('keydown', onKeyDown)
        }
    }, [onShortcuts])
}
