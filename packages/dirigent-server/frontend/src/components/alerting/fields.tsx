import { useEffect, useState, type ReactNode } from 'react'

import { Picker } from '@/components/Picker'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { LOG_NOTIFIER } from '@/lib/alerting'
import { readConnections, type ConnectionOut } from '@/lib/connections'
import { headingOf } from '@/lib/identity'
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
            {hint !== undefined && <p className="text-faint text-xs">{hint}</p>}
        </div>
    )
}

/** Which channel a rule or a test goes through: the notifiers this instance has installed. */
export function NotifierPicker({
    id,
    notifiers,
    value,
    onChange,
}: {
    id: string
    notifiers: readonly string[]
    value: string
    onChange: (value: string) => void
}) {
    return (
        <div className="space-y-2">
            <Label htmlFor={id}>Notifier</Label>
            <Picker
                id={id}
                label="Notifier"
                value={value}
                options={notifiers.map((one) => ({ value: one, label: one, aside: '' }))}
                placeholder="Search the installed channels"
                onChange={onChange}
            />
        </div>
    )
}

/** The credential a channel delivers through: the connections of that notifier's own kind. */
export function ConnectionPicker({
    id,
    kind,
    value,
    onChange,
}: {
    id: string
    kind: string
    value: string
    onChange: (value: string) => void
}) {
    const options = useConnections(kind)
    return (
        <div className="space-y-2">
            <Label htmlFor={id}>Connection</Label>
            <Picker
                id={id}
                label="Connection"
                value={value}
                options={options}
                placeholder={options.length === 0 ? `No ${kind} connection yet` : 'Search by name or code'}
                onChange={onChange}
            />
        </div>
    )
}

/**
 * The connections one channel may deliver through, read once per kind.
 *
 * A CHANNEL'S CREDENTIAL IS A CONNECTION OF ITS OWN KIND. `slack` delivers through a `slack`
 * connection and nothing else, so the picker offers the kind rather than every credential the
 * instance holds -- there is no server-side filter on the listing, so the narrowing is here.
 */
function useConnections(kind: string): PickerOption[] {
    const [rows, setRows] = useState<ConnectionOut[]>([])

    useEffect(() => {
        if (kind === '' || kind === LOG_NOTIFIER) return
        let live = true
        void readConnections().then(
            (page) => {
                if (live) setRows(page.items)
            },
            () => {
                // The picker offers nothing rather than the screen refusing: the box beside it
                // still takes a code, and the server is what refuses one it does not have.
                if (live) setRows([])
            },
        )
        return () => {
            live = false
        }
    }, [kind])

    return rows
        .filter((row) => row.kind === kind)
        .map((row) => {
            const heading = headingOf(row)
            return { value: row.code, label: heading.title, aside: heading.code ?? '' }
        })
}
