import { useMemo } from 'react'

import { LogView, type LogLevel, type LogLine } from '@winterop-com/sokkel-ui/LogView'

import { useStore } from '@winterop-com/sokkel-ui/hooks/use-store'
import { formatClock } from '@/lib/format'
import { LABELS } from '@/lib/labels'
import { itemOfEntry } from '@/lib/run-detail'
import { fieldsText } from '@/lib/terminal'
import { followTails } from '@/lib/preferences'
import type { LogEntryOut } from '@/lib/runs'

/**
 * A step's log lines on sokkel-ui's `LogView`, following the tail.
 *
 * THE LINES COME FROM THE RUN'S ONE STREAM, filtered here. There is no second connection for a
 * step's logs: the run's event stream already carries every line the run wrote, and which step
 * wrote one is a field on the line.
 *
 * FOLLOWING STOPS WHEN SOMEBODY SCROLLS UP, and starts again when they scroll back down or take
 * the jump to the newest line.
 *
 * AN EMPTY PANE IS TWO DIFFERENT FACTS. A step that could still write has written nothing yet;
 * one that has settled wrote nothing, and there is no point waiting for a line that is not
 * coming. The caller knows which, because it holds the step's outcome and the run's status.
 *
 * A FAN-OUT ELEMENT'S LABEL MARKS THE LINE'S TEXT. Every element of one step writes the same
 * sentences into this one pane, and without the label there is no telling five copies of
 * "finished" apart. The step is the pane's own, so a line names no source.
 *
 * WHETHER IT FOLLOWS IS A PREFERENCE, held in `lib/preferences` and set in the settings dialog.
 * Turning it off while a pane is open stops that pane too.
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
    const following = useStore(followTails)
    const lines = useMemo<LogLine[]>(
        () =>
            entries.map((entry) => ({
                at: formatClock(entry.created_at),
                level: entry.level as LogLevel,
                item: (items === undefined ? null : itemOfEntry(items, entry.step_attempt_id)) ?? undefined,
                text: entry.message,
                fields: fieldsText(entry.fields) ?? undefined,
            })),
        [entries, items],
    )

    return (
        <LogView
            lines={lines}
            follow={following}
            wrap
            numbered={false}
            words={{ jump: LABELS.terminal.newest }}
            empty={settled === true ? LABELS.terminal.step_empty_settled : LABELS.terminal.step_empty}
            className={className}
        />
    )
}
