import { CornerDownLeft, Dot } from 'lucide-react'
import { useMemo, useState } from 'react'

import {
    Command,
    CommandDialog,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
    CommandShortcut,
} from '@/components/ui/command'
import { Kbd, KbdGroup } from '@/components/ui/kbd'
import { useStore } from '@/hooks/use-store'
import { filterActions, paletteActions, paletteOpen, shelve, type PaletteAction } from '@/lib/palette'

export const PALETTE_TITLE = 'Command palette'
export const PALETTE_DESCRIPTION = 'Every place this app can go, and everything it can do from here'
export const PALETTE_PLACEHOLDER = 'Go to a screen, or run something'
export const PALETTE_EMPTY = 'Nothing here answers to that'

/**
 * The palette: a renderer over the registered actions, and nothing more.
 *
 * THE FILTERING IS NOT cmdk's. cmdk scores by its own fuzzy match over the rendered text, which
 * ranks a screen's own name below whichever row happens to share more letters with the query.
 * `filterActions` is this app's rule, it is a pure function, and it has a test -- so `shouldFilter`
 * is off here and the list handed to cmdk is already the answer, in order.
 *
 * THE SCREEN'S OWN SHELF LEADS, which `shelve` decides and this only draws. Somebody who opened
 * the palette while reading a run wants something to do with that run more often than they want
 * a navigation row, and the shelf's heading names what it is scoped to.
 *
 * CHOOSING CLOSES FIRST, THEN RUNS. An action that navigates while its own dialog is still on
 * screen leaves the new page under a modal for a frame.
 */
export function CommandPalette() {
    const open = useStore(paletteOpen)
    const actions = useStore(paletteActions)
    const [query, setQuery] = useState('')

    const shown = useMemo(() => filterActions(actions, query), [actions, query])
    const shelves = useMemo(() => shelve(shown), [shown])

    function choose(action: PaletteAction): void {
        paletteOpen.set(false)
        setQuery('')
        action.run()
    }

    return (
        <CommandDialog
            open={open}
            onOpenChange={(next) => {
                paletteOpen.set(next)
                if (!next) setQuery('')
            }}
            title={PALETTE_TITLE}
            description={PALETTE_DESCRIPTION}
            className="top-[15vh] w-full p-0 shadow-2xl sm:max-w-[768px]"
        >
            <Command shouldFilter={false} label={PALETTE_TITLE} className="dg-palette p-0">
                <CommandInput
                    placeholder={PALETTE_PLACEHOLDER}
                    value={query}
                    onValueChange={setQuery}
                    autoFocus
                    className="text-base"
                />
                <CommandList className="max-h-[26rem] p-2">
                    <CommandEmpty>{PALETTE_EMPTY}</CommandEmpty>
                    {shelves.map((shelf) => (
                        <CommandGroup key={shelf.label} heading={shelf.label} className="p-0 pb-1">
                            {shelf.rows.map((action) => (
                                <Row
                                    key={action.id}
                                    action={action}
                                    onChoose={() => {
                                        choose(action)
                                    }}
                                />
                            ))}
                        </CommandGroup>
                    ))}
                </CommandList>
                <div className="border-border text-faint flex h-11 shrink-0 items-center justify-between gap-3 border-t px-3">
                    <KbdGroup>
                        <Kbd>↑↓</Kbd>
                        <span className="text-xs">choose</span>
                        <Kbd className="ml-2">↵</Kbd>
                        <span className="text-xs">run it</span>
                    </KbdGroup>
                </div>
            </Command>
        </CommandDialog>
    )
}

/**
 * One row: its mark and what it is called.
 *
 * A ROW IS ITS TITLE. What an action says about itself stays in the search -- typing `cron`
 * still finds Triggers -- but drawn beside every title it is a column of glosses saying what
 * the titles already say.
 *
 * A ROW WITHOUT AN ICON GETS THE NEUTRAL GLYPH rather than an empty tile, so the titles stay on
 * one line down the list however many of them an author has given a mark to.
 */
function Row({ action, onChoose }: { action: PaletteAction; onChoose: () => void }) {
    const Icon = action.icon ?? Dot
    return (
        <CommandItem value={action.id} onSelect={onChoose} className="h-11 gap-3 rounded-md px-2">
            <span className="bg-muted text-muted-foreground flex size-7 shrink-0 items-center justify-center rounded-md">
                <Icon className="size-4" aria-hidden />
            </span>
            <span className="truncate text-sm">{action.title}</span>
            <CommandShortcut className="ml-auto">
                <Kbd className="opacity-0 group-data-selected/command-item:opacity-100">
                    <CornerDownLeft aria-hidden />
                </Kbd>
            </CommandShortcut>
        </CommandItem>
    )
}
