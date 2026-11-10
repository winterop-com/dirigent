import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import type { ToolbarItem } from '@winterop-com/sokkel-ui/Toolbar'

/**
 * A strip's `primary`, drawn in the frame rather than the fill while `quiet`, by its word alone:
 * the verb that would do nothing now stands beside the others rather than over them.
 */
export function quietPrimary(quiet: boolean, item: ToolbarItem): ToolbarItem {
    if (!quiet) return item
    const named = item.face !== undefined
    return {
        ...item,
        render: (
            <Button
                variant="outline"
                size="sm"
                disabled={item.disabled}
                reason={item.reason}
                aria-label={named ? item.label : undefined}
                onClick={item.onSelect}
            >
                {item.face ?? item.label}
            </Button>
        ),
    }
}
