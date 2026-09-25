import {
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
    useComboboxAnchor,
} from '@/components/ui/combobox'
import { Mark } from '@/components/Mark'
import { InputGroupAddon, InputGroupButton } from '@/components/ui/input-group'
import { matchesOption, type PickerOption } from '@/lib/picker'

/**
 * One value out of a set too long to read: typed into, walked with the arrows, chosen with Enter.
 *
 * A CHOICE FROM A LIST THIS LONG IS NOT A BOX TO TYPE A KEY INTO. A pipeline is addressed by a
 * code and titled by a name, and asking somebody to remember the code is asking them to leave
 * the screen to look it up -- so what is offered is the list, headed the way every listing in
 * this app heads a thing: the title, and the code beside it in mono.
 *
 * WHAT IT NARROWS BY IS `lib/picker`, which is the same every-term rule the command palette
 * filters by, over both halves of the row.
 *
 * A ROW MAY LEAD WITH A MARK, which is what a row naming a kind carries -- a channel's glyph --
 * and a row that names none simply has none.
 */
export function Picker({
    id,
    value,
    options,
    placeholder,
    label,
    onChange,
}: {
    id: string
    /** The chosen value, or the empty string when nothing has been chosen. */
    value: string
    options: readonly PickerOption[]
    placeholder: string
    /** What the control is called, for whoever is reading the screen rather than seeing it. */
    label: string
    onChange: (value: string) => void
}) {
    const chosen = options.find((option) => option.value === value) ?? null
    // The list hangs off the whole box rather than off the bare input inside it, which is a
    // control's worth of marks and asides narrower.
    const field = useComboboxAnchor()

    return (
        <Combobox
            items={options as PickerOption[]}
            value={chosen}
            itemToStringLabel={(option: PickerOption) => option.label}
            filter={(option: PickerOption, query: string) => matchesOption(option, query)}
            onValueChange={(picked: PickerOption | null) => {
                onChange(picked === null ? '' : picked.value)
            }}
        >
            {/* The same ground every other box on a form sits on, in both modes: an input
                group's own is a rung off, and two field grounds on one form read as two kinds
                of box. */}
            <div ref={field}>
                <ComboboxInput
                    id={id}
                    aria-label={label}
                    placeholder={placeholder}
                    className="bg-field dark:bg-field"
                    showTrigger={false}
                >
                    {/* What was chosen wears its kind's mark in the closed box the way it wore it
                        in the list, so the row somebody picked is the row they are looking at. */}
                    {chosen?.mark !== undefined && (
                        <InputGroupAddon align="inline-start">
                            <Mark glyph={chosen.mark} />
                        </InputGroupAddon>
                    )}
                    {/* The machine's half of the chosen row stands in the closed box as well as in
                        the list: a picker that showed only the title would take the code off the
                        screen the moment somebody chose one. */}
                    <InputGroupAddon align="inline-end">
                        {chosen !== null && chosen.aside !== '' && (
                            <span className="font-mono text-xs text-muted-foreground">{chosen.aside}</span>
                        )}
                        <InputGroupButton size="icon-xs" variant="ghost" render={<ComboboxTrigger />} />
                    </InputGroupAddon>
                </ComboboxInput>
            </div>
            <ComboboxContent anchor={field}>
                <ComboboxEmpty>No match.</ComboboxEmpty>
                <ComboboxList>
                    {(option: PickerOption) => (
                        <ComboboxItem key={option.value} value={option}>
                            {option.mark !== undefined && <Mark glyph={option.mark} />}
                            <span className="truncate">{option.label}</span>
                            {option.aside !== '' && (
                                <span className="ml-auto font-mono text-xs whitespace-nowrap text-muted-foreground">
                                    {option.aside}
                                </span>
                            )}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
