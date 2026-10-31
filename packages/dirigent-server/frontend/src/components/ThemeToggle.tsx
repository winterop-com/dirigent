import { useTheme } from 'next-themes'

import { IconButton } from '@/components/ds/IconButton'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'

/** The three settings of the mode axis; the settings dialog offers all of them. */
export const MODES = ['light', 'dark', 'system'] as const

export type Mode = (typeof MODES)[number]

/** What each setting is called: on the Theme pane's segmented control, and in the palette. */
export const MODE_LABELS: Record<Mode, string> = {
    light: LABELS.shell.mode.light,
    dark: LABELS.shell.mode.dark,
    system: LABELS.shell.mode.system,
}

/**
 * One click flips the look: the top strip's corner shows the appearance in force and a click
 * sets the opposite, as an explicit choice. System is the settings dialog's Theme pane.
 */
export function ThemeToggle() {
    const { resolvedTheme, setTheme } = useTheme()
    const dark = resolvedTheme !== 'light'
    return (
        <IconButton
            icon={dark ? ICONS.dark : ICONS.light}
            label={dark ? LABELS.shell.switch_to_light : LABELS.shell.switch_to_dark}
            size="sm"
            className="text-muted-foreground"
            onClick={() => {
                setTheme(dark ? 'light' : 'dark')
            }}
        />
    )
}
