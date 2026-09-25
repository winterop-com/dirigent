import { type ReactNode } from 'react'

import { Picker } from '@/components/Picker'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { PickerOption } from '@/lib/picker'

/** One labelled box, which is what every field on these dialogs is. */
export function Field({
    id,
    label,
    value,
    onChange,
    placeholder,
    mono,
    hint,
}: {
    id: string
    label: string
    value: string
    onChange: (value: string) => void
    placeholder: string
    mono?: boolean
    hint?: ReactNode
}) {
    return (
        <div className="space-y-2">
            <Label htmlFor={id}>{label}</Label>
            <Input
                id={id}
                className={mono === true ? 'font-mono' : undefined}
                spellCheck={false}
                autoComplete="off"
                value={value}
                placeholder={placeholder}
                onChange={(event) => {
                    onChange(event.target.value)
                }}
            />
            {hint !== undefined && <p className="text-xs text-faint">{hint}</p>}
        </div>
    )
}

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
        <div className="space-y-2">
            <Label htmlFor={id}>Deliver through</Label>
            <Picker
                id={id}
                label="Deliver through"
                value={value}
                options={options}
                placeholder="Search by name, kind or code"
                onChange={onChange}
            />
        </div>
    )
}
