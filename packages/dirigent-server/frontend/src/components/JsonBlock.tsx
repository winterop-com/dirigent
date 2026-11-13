import { Code } from '@winterop-com/sokkel-ui/Code'
import { WindowedPane, WindowedPaneButton } from '@winterop-com/sokkel-ui/WindowedPane'
import { CodePane } from '@/components/pipeline/CodePane'
import { copyWords, windowWords } from '@/lib/design-system'
import { LABELS } from '@/lib/labels'
import { cn } from '@/lib/utils'

/**
 * One piece of JSON on a screen: sokkel-ui's `Code`, highlighted as JSON with its copy button,
 * and a window when that is small.
 *
 * The window is the same text a size up, in the read-only editor, with folding and search.
 *
 * IT IS A PREVIEW, SO IT DECLARES A HEIGHT, AND THE HEIGHT IS STATED HERE. Reference material
 * has no length of its own: a block drawn at the height of what it holds pushes whatever acts on
 * it below the fold, so this is a pane of `max-h-72` and the window carries the rest. A surface
 * with less room to give narrows it through `className` and says what it measured; nothing
 * leaves it off.
 *
 * `className` sizes the block. The window button stands beside the copy button in the block's
 * head row, above the text, so no line, scrolled anywhere, runs under either, and a height never
 * cuts them off.
 */
export function JsonBlock({ title, text, className }: { title: string; text: string; className?: string }) {
    return (
        <WindowedPane
            title={<span className="font-mono">{title}</span>}
            keepPane
            button="none"
            words={windowWords(title)}
        >
            {(where) =>
                where === 'pane' ? (
                    <Code
                        value={text}
                        language="json"
                        size="sm"
                        header
                        actions={<WindowedPaneButton size="icon-xs" />}
                        words={copyWords(LABELS.shell.copy_pane(title))}
                        className={cn('max-h-72', className)}
                    />
                ) : (
                    <CodePane
                        value={text}
                        mediaType="application/json"
                        label={LABELS.shell.in_window(title)}
                        readOnly
                        className="min-h-0 flex-1"
                    />
                )
            }
        </WindowedPane>
    )
}
