import { useRef, useState } from 'react'

import { Input } from '@/components/ui/input'
import { Kbd } from '@/components/ui/kbd'
import { clearShown, escapeFrom } from '@/lib/design-system'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'
import { SEARCH_KEY } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

/** What a search box says while it is empty, wherever one is drawn. */
export const SEARCH_PLACEHOLDER = LABELS.shell.search

/**
 * The box that narrows what is on the screen.
 *
 * A search glyph leads, a clear button trails once there is text, and Escape clears it too.
 * While it is empty and unfocused it shows the `/` key cap: `useAppShortcuts` moves the caret
 * into the first box marked `data-search-shortcut` when `/` is pressed outside any field and
 * outside the editor. `shortcut={false}` takes a box out of that, for a second box on a screen.
 *
 * The placeholder names nothing. The noun is on `label`, the accessible name, which is read
 * without the heading beside it.
 */
export function SearchField({
    value,
    label,
    onChange,
    className,
    shortcut = true,
    disabled = false,
}: {
    value: string
    /** What the box is called, and what it matches on, for whoever is not seeing the screen. */
    label: string
    onChange: (typed: string) => void
    className?: string
    shortcut?: boolean
    disabled?: boolean
}) {
    const box = useRef<HTMLInputElement>(null)
    const [focused, setFocused] = useState(false)
    return (
        <div
            data-slot="search-field"
            className={cn('relative flex h-8 w-64 min-w-0 items-center', disabled && 'opacity-50', className)}
        >
            <ICONS.search className="pointer-events-none absolute left-2.5 size-4 text-faint" aria-hidden />
            <Input
                ref={box}
                type="search"
                value={value}
                disabled={disabled}
                aria-label={label}
                placeholder={SEARCH_PLACEHOLDER}
                data-search-shortcut={shortcut || undefined}
                className="h-8 pr-8 pl-8 text-sm"
                onFocus={() => {
                    setFocused(true)
                }}
                onBlur={() => {
                    setFocused(false)
                }}
                onKeyDown={(event) => {
                    if (event.key !== 'Escape') return
                    if (escapeFrom(value) === 'clear') {
                        event.preventDefault()
                        event.stopPropagation()
                        onChange('')
                    } else {
                        box.current?.blur()
                    }
                }}
                onChange={(event) => {
                    onChange(event.target.value)
                }}
            />
            {clearShown(value) ? (
                <button
                    type="button"
                    aria-label={LABELS.shell.clear_search}
                    title={LABELS.shell.clear_search}
                    disabled={disabled}
                    className="absolute right-1.5 inline-flex size-5 items-center justify-center rounded-sm text-faint outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                    onClick={() => {
                        onChange('')
                        box.current?.focus()
                    }}
                >
                    <ICONS.clear className="size-3.5" aria-hidden />
                </button>
            ) : (
                shortcut &&
                !focused &&
                !disabled && (
                    <Kbd
                        className="absolute right-1.5 border border-border bg-transparent font-mono"
                        aria-hidden
                    >
                        {SEARCH_KEY}
                    </Kbd>
                )
            )}
        </div>
    )
}
