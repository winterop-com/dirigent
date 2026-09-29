import { LABELS } from '@/lib/labels'
import { Stub } from '@/pages/Stub'

/** An address this app does not answer, said where it was opened rather than redirected away. */
export function NotFound() {
    return (
        <Stub
            title={LABELS.screen.nowhere}
            waiting={LABELS.refusal.nowhere.detail}
            note={LABELS.refusal.nowhere.note}
        />
    )
}
