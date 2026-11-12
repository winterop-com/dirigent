import { RelativeTime } from '@winterop-com/sokkel-ui/RelativeTime'

import { currentZone } from '@/lib/times'

/** English words in their narrow form, "3m ago", and the exact instant on a 24-hour clock. */
const LOCALE = 'en-u-hc-h23'

/**
 * A moment, as sokkel-ui's `RelativeTime` says it, in the zone `lib/times` is set to: how long ago
 * or how long until on screen, the exact instant on hover and on focus. A moment that is not there
 * is a dash.
 */
export function Instant({ at, className }: { at: string | null | undefined; className?: string }) {
    if (!at) return <span className={className}>--</span>
    return (
        <RelativeTime
            date={at}
            locale={LOCALE}
            timeZone={currentZone()}
            length="narrow"
            className={className}
        />
    )
}
