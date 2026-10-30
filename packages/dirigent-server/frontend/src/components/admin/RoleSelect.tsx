import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { type UserRole } from '@/lib/auth'
import { ROLE_HINTS, USER_ROLES } from '@/lib/users'

/** The role an account holds: the word in the closed box, and what each may do on its option. */
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
        <Select
            value={value}
            onValueChange={(picked) => {
                onChange(picked as UserRole)
            }}
        >
            <SelectTrigger id={id} className="w-full">
                <SelectValue>{() => value}</SelectValue>
            </SelectTrigger>
            <SelectContent alignItemWithTrigger={false}>
                {USER_ROLES.map((role) => (
                    <SelectItem key={role} value={role}>
                        <span>
                            {role}
                            <span className="block text-xs text-muted-foreground">{ROLE_HINTS[role]}</span>
                        </span>
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
