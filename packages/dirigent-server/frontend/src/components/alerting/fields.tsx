import { Field } from '@winterop-com/sokkel-ui/Field'
import { Picker } from '@/components/Picker'
import { LABELS } from '@/lib/labels'
import type { PickerOption } from '@/lib/picker'

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
            <Picker
                id={id}
                label={LABELS.word.delivers_through}
                value={value}
                options={options}
                placeholder={LABELS.alerting.target_search}
                onChange={onChange}
            />
        </Field>
    )
}
