import { LoadingBar } from '@winterop-com/sokkel-ui/Loaders'

import { LABELS } from '@/lib/labels'
import { cn } from '@/lib/utils'

/**
 * How far a live wait has come, as a line in the hue of the element it sits in, beneath the text
 * it belongs to. No number is drawn, and nothing at all for no progress.
 */
export function ProgressLine({ progress, className }: { progress: number | null; className?: string }) {
    if (progress === null) return null
    return (
        <LoadingBar
            value={progress * 100}
            tone="current"
            label={LABELS.runs.wait_progress}
            className={cn('mt-1 mb-0.5 text-(--chip)', className)}
        />
    )
}
