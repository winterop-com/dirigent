import { Moon, Sun } from 'lucide-react'
import { useTheme } from 'next-themes'

import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
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
 * One click flips the look.
 *
 * The corner is a toggle, not a menu: it shows the appearance in force and a click sets the
 * opposite, as an explicit choice. System lives in the settings dialog's Theme pane --
 * choosing it there hands the switch back to the machine until the next click here.
 */
export function ThemeToggle() {
    const { resolvedTheme, setTheme } = useTheme()
    const dark = resolvedTheme !== 'light'
    const label = dark ? LABELS.shell.switch_to_light : LABELS.shell.switch_to_dark

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={label}
                        onClick={() => {
                            setTheme(dark ? 'light' : 'dark')
                        }}
                    >
                        {dark ? (
                            <Moon className="size-4" aria-hidden />
                        ) : (
                            <Sun className="size-4" aria-hidden />
                        )}
                    </Button>
                }
            />
            <TooltipContent side="bottom">{label}</TooltipContent>
        </Tooltip>
    )
}
