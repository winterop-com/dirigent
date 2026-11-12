import { RelativeTime } from '@winterop-com/sokkel-ui/RelativeTime'

import { exactInstant, RELATIVE } from '@/lib/format'

const { now: nowWord, ...relative } = RELATIVE

/**
 * A moment, as sokkel-ui's `RelativeTime` says it with this app's `RELATIVE` reading: how long
 * ago or how long until on screen, `formatInstant`'s spelling on hover and on focus. Inside a row
 * that is already a link or a button, `focusable={false}` drops its own tab stop and the exact
 * instant becomes its title. A moment that is not there is a dash.
 */
export function Instant({
    at,
    focusable = true,
    className,
}: {
    at: string | null | undefined
    focusable?: boolean
    className?: string
}) {
    if (!at) return <span className={className}>--</span>
    return (
        <RelativeTime
            date={at}
            {...relative}
            words={{ now: nowWord }}
            exact={exactInstant}
            focusable={focusable}
            className={className}
        />
    )
}
