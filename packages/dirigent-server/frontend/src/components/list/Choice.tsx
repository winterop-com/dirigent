import { ChevronDown } from 'lucide-react'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

/** What every filter menu calls its own "no filter" row. */
export const ANY = ''

/** One option a filter offers, and the drawing the rest of the app gives its value. */
export interface ChoiceOption {
    value: string
    label: string
    /** How this value is drawn everywhere else: a status chip, a tag chip, a kind chip. */
    mark?: ReactNode
}

/**
 * One filter that is a choice from a fixed set, with a row that is no filter at all.
 *
 * AN OPTION WEARS WHAT ITS VALUE WEARS EVERYWHERE ELSE. A status filter's rows are the same
 * chips the listing draws, and a tag filter's rows are the same tag chips, so choosing one is
 * recognising it rather than reading a word in a second costume -- and the trigger shows the
 * chip it chose. An option never wraps: the menu grows to its longest row instead of folding
 * "completed with errors" in half.
 *
 * A CHOICE CLOSES ON THE CHOICE. One row is the whole answer, so the menu goes away with it; a
 * set of checkboxes is the case that stays open, because choosing one is not the answer yet.
 */
export function Choice({
    label,
    value,
    options,
    anything,
    onChange,
}: {
    label: string
    value: string
    options: ChoiceOption[]
    /** What the row that clears this filter is called. */
    anything: string
    onChange: (value: string) => void
}) {
    const chosen = options.find((option) => option.value === value)
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button variant="outline" size="sm" aria-label={`${label}: ${chosen?.label ?? anything}`}>
                        {chosen === undefined ? anything : (chosen.mark ?? chosen.label)}
                        <ChevronDown aria-hidden />
                    </Button>
                }
            />
            <DropdownMenuContent align="start" className="min-w-56">
                <DropdownMenuRadioGroup value={value} onValueChange={onChange}>
                    <DropdownMenuRadioItem value={ANY} closeOnClick className="whitespace-nowrap">
                        {anything}
                    </DropdownMenuRadioItem>
                    {options.map((option) => (
                        <DropdownMenuRadioItem
                            key={option.value}
                            value={option.value}
                            closeOnClick
                            className="whitespace-nowrap"
                        >
                            {option.mark ?? option.label}
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
