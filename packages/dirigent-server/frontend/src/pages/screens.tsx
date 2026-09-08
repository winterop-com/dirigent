import { Stub } from '@/pages/Stub'

/**
 * The screens the rail names, each reserved at its address and not yet built.
 *
 * ONE FILE RATHER THAN ONE OF THREE LINES EACH. Each of these is replaced by a screen of its
 * own the moment its design board settles, and until then what they have to say is the same
 * shape: what the screen is for, and that it is not here yet. Splitting them now would be a
 * file each to delete.
 */

/** An address this app does not answer, said where it was opened rather than redirected away. */
export function NotFound() {
    return (
        <Stub
            title="Nothing at this address"
            waiting="This app does not answer for the address in the browser bar."
            note="no screen at this address"
        />
    )
}
