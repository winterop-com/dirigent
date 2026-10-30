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
 * beside it only when the state is news -- failed, unknown -- unless `say` asks otherwise. `tip`
 * is a sentence the tooltip adds, and `focusable` reaches that tooltip from the keyboard.
 */
export function ToneDot({
    say,
    tip,
    focusable = false,
    className,
    ...dot
}: Dot & { say?: Say; tip?: string | null; focusable?: boolean; className?: string }) {
    const status = 'status' in dot ? dot.status : null
    const label = dot.label ?? (status === null ? '' : statusLabel(status))
    const news = isNews(dot)
    const fill =
        status === null ? { '--chip': TONE_FILL[(dot as { tone: Tone }).tone] } : statusTokens(status)
    const hollow = 'tone' in dot && dot.tone === 'unknown'
    const said = tip === undefined || tip === null || tip === '' ? null : tip
    const tabIndex = focusable ? 0 : undefined
    // Failed is what a reader is looking for; a state nothing has proved is said, but quietly.
    const loud = news && !hollow
    const mark = (
        <span
            className="status-dot"
            data-hollow={hollow || undefined}
            style={fill as CSSProperties}
            aria-hidden
        />
    )
    if (saysWord(news, say)) {
        const word = (
            <>
                {mark}
                <span className={loud ? 'font-medium text-foreground' : 'text-muted-foreground'}>
                    {label}
                </span>
            </>
        )
        const look = cn('inline-flex items-center gap-1.5 text-xs whitespace-nowrap', className)
        if (said === null) return <span className={look}>{word}</span>
        return (
            <Tooltip>
                <TooltipTrigger render={<span tabIndex={tabIndex} className={look} />}>{word}</TooltipTrigger>
                <TooltipContent>{said}</TooltipContent>
            </Tooltip>
        )
    }
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <span
                        role="img"
                        aria-label={label}
                        tabIndex={tabIndex}
                        className={cn('inline-flex size-4 items-center justify-center', className)}
                    />
                }
            >
                {mark}
            </TooltipTrigger>
            <TooltipContent className={said === null ? undefined : 'flex-col items-start gap-1'}>
                <span>{label}</span>
                {said !== null && <span className="opacity-70">{said}</span>}
            </TooltipContent>
        </Tooltip>
    )
}
