import { TextLink } from '@winterop-com/sokkel-ui/TextLink'
import { WindowedPane } from '@winterop-com/sokkel-ui/WindowedPane'
import { Description } from '@/components/Description'
import { useApiPrefix } from '@/hooks/use-api-prefix'
import { artifactUrl, type ReportDocument } from '@/lib/artifacts'
import { windowWords } from '@/lib/library-words'
import { LABELS } from '@/lib/labels'
import { cn } from '@/lib/utils'

/** What the window is titled and what a saved file is called. */
const DOCUMENT_NAME = 'report.md'

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
                            <TextLink
                                variant="inline"
                                href={artifactUrl(prefix, document.id)}
                                download={DOCUMENT_NAME}
                                className="w-fit text-xs"
                            >
                                {LABELS.runs.report_download}
                            </TextLink>
                        )}
                    </div>
                ) : (
                    <Description text={document.markdown} ink="body" measure />
                )
            }
        </WindowedPane>
    )
}
