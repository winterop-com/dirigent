import { useStore } from '@/hooks/use-store'
import { authStore } from '@/lib/auth'
import { whyShut, type Gate } from '@/lib/roles'

/**
 * Whether this account may make the write a control would make, and why not when it may not.
 *
 * Every write control in the app asks here rather than reading the role itself, so a screen
 * cannot have its own idea of what a viewer may press. `why` is the sentence a shut control
 * wears as its title, which is the only way a disabled button says anything.
 */
export function useMayWrite(gate: Gate = 'operator'): { may: boolean; why: string | undefined } {
    const role = useStore(authStore).identity?.role ?? null
    const why = whyShut(role, gate)
    return { may: why === undefined, why }
}
