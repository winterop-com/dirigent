import { formatInstant, formatRelative } from '@/lib/format'

/**
 * A moment, said the one way this app says one.
 *
 * HOW LONG AGO ON SCREEN, THE EXACT INSTANT ON HOVER. What a reader asks of a timestamp is how
 * recent it is, and the wall clock is what they need only once they are asking something else --
 * so the coarse reading is the text and `formatInstant` is the title, in the zone `lib/times` is
 * set to. A panel that spelled the wall clock out where a listing beside it said "2m ago" would
 * be two answers to one question on two halves of one screen.
 *
 * A FUTURE INSTANT IS ONE OF THESE TOO. `formatRelative` measures either side of now, so a
 * schedule's next firing reads "in 2h" here and spells the wall clock on hover like the rest.
 */
export function Instant({ at, className }: { at: string | null | undefined; className?: string }) {
    return (
        <span className={className} title={at ? formatInstant(at) : undefined}>
            {formatRelative(at)}
        </span>
    )
}
