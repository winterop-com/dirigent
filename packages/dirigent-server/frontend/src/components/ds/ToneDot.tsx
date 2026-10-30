import type { CSSProperties } from 'react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { isNews, saysWord, TONE_FILL, type Say, type Tone } from '@/lib/design-system'
import { statusLabel, statusTokens } from '@/lib/status'
import { cn } from '@/lib/utils'

type Dot = { tone: Tone; label: string } | { status: string; label?: string }

/**
 * One dot for every state: a tone from `lib/design-system`, or a run or attempt status.
 *
 * The dot is the answer and its word is its accessible name and its tooltip. The word is drawn
 * beside it only when the state is news -- failed, unknown -- unless `say` asks otherwise.
 */
export function ToneDot({ say, className, ...dot }: Dot & { say?: Say; className?: string }) {
    const status = 'status' in dot ? dot.status : null
    const label = dot.label ?? (status === null ? '' : statusLabel(status))
    const news = isNews(dot)
    const fill =
        status === null ? { '--chip': TONE_FILL[(dot as { tone: Tone }).tone] } : statusTokens(status)
    const hollow = 'tone' in dot && dot.tone === 'unknown'
    const mark = (
        <span
            className="status-dot"
            data-hollow={hollow || undefined}
            style={fill as CSSProperties}
            aria-hidden
        />
    )
    if (saysWord(news, say)) {
        return (
            <span className={cn('inline-flex items-center gap-1.5 text-xs', className)}>
                {mark}
                <span className={news ? 'font-medium text-foreground' : 'text-muted-foreground'}>
                    {label}
                </span>
            </span>
        )
    }
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <span
                        role="img"
                        aria-label={label}
                        className={cn('inline-flex size-4 items-center justify-center', className)}
                    />
                }
            >
                {mark}
            </TooltipTrigger>
            <TooltipContent>{label}</TooltipContent>
        </Tooltip>
    )
}
