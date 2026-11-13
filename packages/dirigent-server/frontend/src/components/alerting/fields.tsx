import type { ReactNode } from 'react'

import { AsyncSelect } from '@winterop-com/sokkel-ui/AsyncSelect'
import { Field } from '@winterop-com/sokkel-ui/Field'
import { Mark } from '@/components/Mark'
import { pickerWords } from '@/lib/library-words'
import { LABELS } from '@/lib/labels'
import { matchesOption, type PickerOption } from '@/lib/picker'

/**
 * Which channel a rule or a test delivers through: the process log, or a credential.
 *
 * ONE PICKER, BECAUSE A TARGET IS ONE THING. The notifier is the chosen connection's kind, so
 * asking for the channel and then for the credential would be asking the same question twice and
 * letting the two answers disagree. Each row wears the kind it implies, so what is chosen says
 * which channel sends it without a second line under the control repeating that.
 */
export function TargetPicker({
    id,
    options,
    value,
    onChange,
}: {
    id: string
    options: readonly PickerOption[]
    value: string
    onChange: (value: string) => void
}) {
    return (
        <Field id={id} label={LABELS.word.delivers_through}>
            <AsyncSelect
                id={id}
                items={options}
                filter={matchesOption}
                itemKey={(option) => option.value}
                itemLabel={(option) => option.label}
                itemMeta={(option) => option.aside}
                monoMeta
                metaInValue
                itemMark={markOf}
                value={options.find((option) => option.value === value) ?? null}
                words={pickerWords(LABELS.alerting.target_search)}
                onValueChange={(picked) => {
                    onChange(picked === null ? '' : picked.value)
                }}
            />
        </Field>
    )
}

/** A target's channel, as the mark its kind wears. */
function markOf(option: PickerOption): ReactNode {
    return option.mark === undefined ? undefined : <Mark glyph={option.mark} />
}
