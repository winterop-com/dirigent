import { cn } from '@/lib/utils'

/** One option of a segmented control: what it answers with and what it is called. */
export interface Segment<T extends string> {
    value: T
    label: string
}

/**
 * A choice from a fixed set of two or three, drawn as one control rather than a menu to open.
 *
 * A MENU IS FOR A LIST; THIS IS FOR A SET SOMEBODY CAN SEE ALL OF. Appearance, the palette, and
 * which clock a schedule keeps are each three words, and a control that hid two of them behind
 * a press would be asking for a click to read what fits on the row.
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
                'flex overflow-hidden rounded-md border border-border',
                // What a finger lands on is 40px tall, which is the rule every control here
                // grows to below the breakpoint.
                size === 'md' ? 'h-10 w-full md:h-8' : 'min-h-10 md:min-h-0',
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
                        size === 'md' ? 'flex-1 px-3 text-sm whitespace-nowrap' : 'px-2 py-1 text-xs',
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
