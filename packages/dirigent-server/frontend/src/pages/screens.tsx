import { Stub } from '@/pages/Stub'

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
