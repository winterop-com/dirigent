import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import { SplitButton } from '@winterop-com/sokkel-ui/SplitButton'
import type { ToolbarItem } from '@winterop-com/sokkel-ui/Toolbar'

import { TOOLBAR_WORDS } from '@/lib/design-system'

/** A screen's primary verb, said as a `ToolbarItem` is, in the fill or the frame. */
export interface PrimaryItem extends Omit<ToolbarItem, 'destructive' | 'pressed' | 'render' | 'menu'> {
    variant?: 'default' | 'outline'
    /** What the split's chevron is called, where `more` makes it a split button. */
    moreWays?: string
}

/**
 * A screen's primary verb, drawn as sokkel-ui's `Toolbar` draws an item, but filled and beside
 * the items rather than among them, so it never folds into More.
 *
 * Shut with a `reason`, it stays reachable and says why in its tooltip. `face` is the word on the
 * button and `label` its name, which is the title while it is open; `more` makes it a
 * `SplitButton`.
 */
export function PrimaryAction({ item }: { item: PrimaryItem }) {
    const variant = item.variant ?? 'default'
    const shut = item.reason !== undefined && item.reason !== null && item.reason !== false
    const named = item.face !== undefined
    const title = named && !shut ? item.label : undefined
    if (item.more !== undefined) {
        return (
            <SplitButton
                variant={variant}
                size="sm"
                label={named ? item.label : undefined}
                title={title}
                onClick={item.onSelect}
                items={item.more}
                disabled={item.disabled}
                reason={item.reason}
                words={{ more: item.moreWays ?? TOOLBAR_WORDS.moreWays }}
            >
                {item.icon}
                {item.face ?? item.label}
            </SplitButton>
        )
    }
    return (
        <Button
            variant={variant}
            size="sm"
            disabled={item.disabled}
            reason={item.reason}
            aria-label={named ? item.label : undefined}
            title={title}
            onClick={item.onSelect}
        >
            {item.icon}
            {item.face ?? item.label}
        </Button>
    )
}
