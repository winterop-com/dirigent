import { cn } from '@/lib/utils'

/** One option of a segmented control: what it answers with and what it is called. */
export interface Segment<T extends string> {
    value: T
    label: string
}

/**
 * A choice from a fixed set, drawn as one control rather than a menu to open.
 *
 * A MENU IS FOR A LIST; THIS IS FOR A SET SOMEBODY CAN SEE ALL OF. Appearance, the palette, and
 * which clock a schedule keeps are each three words, and a control that hid two of them behind
 * a press would be asking for a click to read what fits on the row.
 *
 * IT WRAPS RATHER THAN FOLDING. Below the breakpoint a form-height control is a grid two cells
 * wide, an odd last option spanning both, and a label too wide for its cell takes a second line.
 */
export function Segmented<T extends string>({
    label,
    value,
    options,
    size = 'sm',
    disabled = false,
    onChoose,
}: {
    /** What the group is called, for whoever is reading the screen rather than seeing it. */
    label: string
    value: T
    options: readonly Segment<T>[]
    /** `sm` is a settings row's control; `md` stands beside a form field at its own height. */
    size?: 'sm' | 'md'
    /** Whether the choice may be answered at all. */
    disabled?: boolean
    onChoose: (value: T) => void
}) {
    return (
        <div
            className={cn(
                'overflow-hidden rounded-md border border-border',
                // What a finger lands on is `--spacing-finger` tall, which is the rule every
                // control here grows to below the breakpoint.
                size === 'md' ? 'grid w-full grid-cols-2 md:flex md:h-8' : 'flex min-h-finger md:min-h-0',
            )}
            role="group"
            aria-label={label}
        >
            {options.map((option) => (
                <button
                    key={option.value}
                    type="button"
                    aria-pressed={option.value === value}
                    disabled={disabled}
                    className={cn(
                        size === 'md'
                            ? 'min-h-finger flex-1 px-3 py-1 text-sm last:odd:col-span-2 md:min-h-0 md:py-0 md:whitespace-nowrap'
                            : 'px-2 py-1 text-xs',
                        option.value === value
                            ? 'bg-primary font-medium text-primary-foreground'
                            : 'text-muted-foreground hover:bg-accent',
                        disabled && 'opacity-50',
                    )}
                    onClick={() => {
                        onChoose(option.value)
                    }}
                >
                    {option.label}
                </button>
            ))}
        </div>
    )
}
