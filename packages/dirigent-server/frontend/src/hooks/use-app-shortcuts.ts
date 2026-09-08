import { useEffect } from 'react'

import { paletteOpen } from '@/lib/palette'
import { toggleRail } from '@/lib/panels'
import {
    applePlatform,
    opensPalette,
    opensShortcuts,
    togglesRail,
    togglesTerminal,
    type FocusedField,
} from '@/lib/shortcuts'
import { toggleTerminal } from '@/lib/terminal'

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

        function focused(): FocusedField | null {
            const element = document.activeElement
            if (!(element instanceof HTMLElement)) return null
            return { tagName: element.tagName, isContentEditable: element.isContentEditable }
        }

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
            if (togglesRail(press, focused(), apple)) {
                event.preventDefault()
                toggleRail()
                return
            }
            if (togglesTerminal(press, focused())) {
                event.preventDefault()
                toggleTerminal()
                return
            }
            if (opensShortcuts(press, focused())) {
                event.preventDefault()
                onShortcuts()
            }
        }

        document.addEventListener('keydown', onKeyDown)
        return () => {
            document.removeEventListener('keydown', onKeyDown)
        }
    }, [onShortcuts])
}
