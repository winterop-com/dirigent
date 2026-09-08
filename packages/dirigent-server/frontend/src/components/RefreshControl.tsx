import { ChevronDown, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useStore } from '@/hooks/use-store'
import { REFRESH_CHOICES, refreshLabel, refreshSeconds, setRefreshSeconds } from '@/lib/refresh'

export const REFRESH_LABEL = 'Refresh'
export const CADENCE_LABEL = 'How often this refreshes on its own'

/**
 * The refresh control: the verb, and how often it happens by itself.
 *
 * A SPLIT BUTTON, the same anatomy as the pipelines listing's New: the primary refreshes
 * now, and the chevron holds the cadence the screen then keeps on its own. The cadence is
 * the app's, not this screen's, so it reads back the same everywhere it is offered.
 */
export function RefreshControl({ onRefresh }: { onRefresh: () => void }) {
    const seconds = useStore(refreshSeconds)
    return (
        <div className="flex items-stretch">
            <Button variant="outline" size="sm" className="rounded-r-none border-r-0" onClick={onRefresh}>
                <RefreshCw aria-hidden />
                {REFRESH_LABEL}
            </Button>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="outline"
                            size="sm"
                            aria-label={CADENCE_LABEL}
                            className="text-muted-foreground rounded-l-none px-2 font-mono text-xs"
                        >
                            {refreshLabel(seconds)}
                            <ChevronDown aria-hidden />
                        </Button>
                    }
                />
                <DropdownMenuContent align="end">
                    <DropdownMenuRadioGroup
                        value={seconds === null ? 'off' : String(seconds)}
                        onValueChange={(value) => {
                            setRefreshSeconds(value === 'off' ? null : Number(value))
                        }}
                    >
                        {REFRESH_CHOICES.map((choice) => (
                            <DropdownMenuRadioItem
                                key={choice === null ? 'off' : String(choice)}
                                value={choice === null ? 'off' : String(choice)}
                                closeOnClick
                            >
                                {refreshLabel(choice)}
                            </DropdownMenuRadioItem>
                        ))}
                    </DropdownMenuRadioGroup>
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}
