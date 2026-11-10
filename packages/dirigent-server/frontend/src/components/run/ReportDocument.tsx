import { WindowedPane } from '@winterop-com/sokkel-ui/WindowedPane'
import { Description } from '@/components/Description'
import { useApiPrefix } from '@/hooks/use-api-prefix'
import { artifactUrl, type ReportDocument } from '@/lib/artifacts'
import { windowWords } from '@/lib/design-system'
import { LABELS } from '@/lib/labels'
import { cn } from '@/lib/utils'

/** What the window is titled and what a saved file is called. */
const DOCUMENT_NAME = 'report.md'

/**
 * How the document is set in the window: prose at a reading measure, tables the whole width.
 *
 * The markdown component draws one flat column of blocks and knows nothing about a measure, so
 * the measure is put on the blocks that are read as sentences. A table is not one of them: it
 * is drawn in its own scrolling box, and what a window buys it is the room not to scroll.
 */
export const READING =
    '[&_p]:mx-auto [&_p]:max-w-[68ch] [&_ul]:mx-auto [&_ul]:max-w-[68ch] [&_ol]:mx-auto [&_ol]:max-w-[68ch] [&_pre]:mx-auto [&_pre]:max-w-[68ch] [&_blockquote]:mx-auto [&_blockquote]:max-w-[68ch]'

/**
 * A run's rendered report: the markdown in place, the same document in a window, and the raw
 * file a link away.
 *
 * `capped` holds the pane to a fixed height that scrolls, for a page where the document stands
 * among other panels; the window is where the whole of it is read.
 */
export function ReportDocumentPane({
    document,
    capped = false,
}: {
    document: ReportDocument
    capped?: boolean
}) {
    const prefix = useApiPrefix()
    return (
        <WindowedPane
            title={<span className="font-mono">{DOCUMENT_NAME}</span>}
            keepPane
            button="sticky"
            className={capped ? undefined : 'p-4'}
            words={windowWords(DOCUMENT_NAME)}
        >
            {(where) =>
                where === 'pane' ? (
                    <div className={cn('flex flex-col gap-3', capped && 'max-h-[28rem] overflow-y-auto p-4')}>
                        <Description text={document.markdown} ink="body" />
                        {prefix !== null && document.id !== null && (
                            <a
                                className="w-fit text-xs text-foreground underline-offset-2 hover:underline"
                                href={artifactUrl(prefix, document.id)}
                                download={DOCUMENT_NAME}
                                rel="noopener"
                            >
                                {LABELS.runs.report_download}
                            </a>
                        )}
                    </div>
                ) : (
                    <div className={cn('w-full', READING)}>
                        <Description text={document.markdown} ink="body" />
                    </div>
                )
            }
        </WindowedPane>
    )
}
