import { cn } from '@/lib/utils'

/**
 * How far a live wait has come, as a line in the hue of the element it sits in.
 *
 * `foot` runs along the bottom edge of a positioned box, inside its border; `under` is a line in
 * the flow, beneath the text it belongs to. No number is drawn, and nothing at all for no progress.
 */
export function ProgressLine({
    progress,
    placement,
    className,
}: {
    progress: number | null
    placement: 'foot' | 'under'
    className?: string
}) {
    if (progress === null) return null
    return (
        <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress * 100)}
            className={cn('progress-line', `progress-line-${placement}`, className)}
        >
            <div className="progress-line-fill" style={{ width: `${String(progress * 100)}%` }} />
        </div>
    )
}
