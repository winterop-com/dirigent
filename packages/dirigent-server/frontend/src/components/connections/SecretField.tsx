import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

/**
 * One field a connection kind declares secret, written and never read.
 *
 * A password box starts empty and stays empty: no read anywhere returns a credential, so there
 * is nothing to put in it. Typing into it is the only way one is ever set, and what an empty
 * box means is the caller's -- keep the stored credential where there is one, set none where
 * there is not.
 */
export function SecretField({
    id,
    name,
    stored,
    value,
    onChange,
}: {
    /** The control's own id, so two forms open at once do not share one. */
    id: string
    name: string
    /** Whether the instance already holds a credential for this field. */
    stored: boolean
    value: string
    onChange: (typed: string) => void
}) {
    return (
        <div className="space-y-1.5">
            <Label htmlFor={id} className="font-mono text-sm font-medium">
                {name}
            </Label>
            <Input
                id={id}
                type="password"
                autoComplete="new-password"
                value={value}
                onChange={(event) => {
                    onChange(event.target.value)
                }}
                placeholder={stored ? 'stored — typing replaces it, blank keeps it' : 'not set — type to set one'}
            />
        </div>
    )
}
