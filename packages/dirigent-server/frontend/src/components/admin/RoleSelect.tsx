import { SelectField } from '@winterop-com/sokkel-ui/SelectField'
import { type UserRole } from '@/lib/auth'
import { LABELS } from '@/lib/labels'
import { ROLE_HINTS, USER_ROLES } from '@/lib/users'

const OPTIONS = USER_ROLES.map((role) => ({ value: role, label: role, detail: ROLE_HINTS[role] }))

/** The role an account holds: the word in the closed box, and what each may do under its option. */
export function RoleSelect({
    id,
    value,
    onChange,
}: {
    id: string
    value: UserRole
    onChange: (role: UserRole) => void
}) {
    return (
        <SelectField
            id={id}
            label={LABELS.word.role}
            options={OPTIONS}
            detailPlacement="below"
            value={value}
            onChange={(picked) => {
                onChange(picked as UserRole)
            }}
        />
    )
}
