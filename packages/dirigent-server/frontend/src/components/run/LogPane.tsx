import { useEffect, useRef, useState } from 'react'

import { useStore } from '@/hooks/use-store'
import { formatClock } from '@/lib/format'
import { itemOfEntry } from '@/lib/run-detail'
import { fieldsText } from '@/lib/terminal'
import { followTails } from '@/lib/preferences'
import type { LogEntryOut } from '@/lib/runs'
import { cn } from '@/lib/utils'

/** How far off the bottom counts as having scrolled away, in pixels of slack. */
const TAIL_SLACK = 24

/** How each level is inked. Two of the four are the semantic aliases; the rest are prose. */
const LEVEL: Record<string, string> = {
    debug: 'text-faint',
    info: 'text-muted-foreground',
    warning: 'text-warning',
    error: 'text-critical',
}

/**
 * A step's log lines, following the tail.
 *
 * THE LINES COME FROM THE RUN'S ONE STREAM, filtered here. There is no second connection for a
 * step's logs: the run's event stream already carries every line the run wrote, and which step
 * wrote one is a field on the line.
 *
 * FOLLOWING STOPS WHEN SOMEBODY SCROLLS UP, and starts again when they scroll back down. A pane
 * that jumped to the bottom while somebody was reading what failed would be unreadable during
 * exactly the run that matters.
 *
 * AN EMPTY PANE IS TWO DIFFERENT FACTS. A step that could still write has written nothing yet;
 * one that has settled wrote nothing, and there is no point waiting for a line that is not
 * coming. The caller knows which, because it holds the step's outcome and the run's status.
 *
 * A FAN-OUT ELEMENT'S LABEL SITS AT THE FRONT OF THE LINE. Every element of one step writes the
 * same sentences into this one pane, and without the label there is no telling five copies of
 * "finished" apart. A step that fans out to nothing carries none and the line starts at its time.
 *
 * WHETHER IT FOLLOWS TO BEGIN WITH IS A PREFERENCE, held in `lib/preferences` and set in the
 * settings dialog. Turning it off while a pane is open stops that pane too: the reader has just
 * said they do not want to be moved, and waiting for the next mount to honour it would be
 * ignoring them for exactly as long as they are looking.
 */
export function LogPane({
    entries,
    items,
    settled,
    className,
}: {
    entries: LogEntryOut[]
    /** The fan-out element each attempt ran for, by attempt id, from `itemLabels`. */
    items?: ReadonlyMap<string, string>
    /** Whether nothing more will be written here, which is what decides the tense. */
    settled?: boolean
    className?: string
}) {
    const pane = useRef<HTMLDivElement>(null)
    const wanted = useStore(followTails)
    // What the reader did to this pane, and what they set for every pane: following is both.
    const [scrolledAway, setScrolledAway] = useState(false)
    const following = wanted && !scrolledAway

    useEffect(() => {
        const element = pane.current
        if (element === null || !following || entries.length === 0) return
        element.scrollTop = element.scrollHeight
    }, [entries, following])

    return (
        <div
            ref={pane}
            onScroll={(event) => {
                const element = event.currentTarget
                const room = element.scrollHeight - element.scrollTop - element.clientHeight
                setScrolledAway(room > TAIL_SLACK)
            }}
            className={cn(
                'overflow-y-auto rounded-lg border border-border bg-background p-2 font-mono',
                className,
            )}
        >
            {entries.length === 0 ? (
                <p className="text-xs text-faint">
                    {settled === true ? 'This step wrote nothing.' : 'This step has written nothing.'}
                </p>
            ) : (
                entries.map((entry) => {
                    // The fields are half the line: a settlement's error and error_class live
                    // there, and a pane that dropped them said only "failed".
                    const fields = fieldsText(entry.fields)
                    const item = items === undefined ? null : itemOfEntry(items, entry.step_attempt_id)
                    return (
                        <p key={entry.id} className="text-xs break-words whitespace-pre-wrap">
                            <span className="text-faint">{formatClock(entry.created_at)} </span>
                            {item !== null && <span className="text-faint">[{item}] </span>}
                            <span className={LEVEL[entry.level] ?? 'text-muted-foreground'}>
                                {entry.message}
                            </span>
                            {fields !== null && <span className="text-faint"> {fields}</span>}
                        </p>
                    )
                })
            )}
        </div>
    )
}
