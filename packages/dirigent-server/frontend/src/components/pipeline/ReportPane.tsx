import { useRef } from 'react'

import { CodePane } from '@/components/pipeline/CodePane'
import { Segmented } from '@/components/Segmented'
import { WindowedPane } from '@/components/WindowedPane'
import type { JsonMap } from '@/lib/api'
import { REPORTS_DOCS_URL } from '@/lib/docs'
import { reportIn } from '@/lib/pipeline-document'

/** The media type a report template carries. `TEMPLATE_MEDIA_TYPE` in dirigent_common. */
export const TEMPLATE_MEDIA_TYPE = 'text/x-jinja'

/** Which buffer this pane edits, and what a screen reader and a test call it. */
const TEMPLATE_PATH = 'report/template'
const TEMPLATE_LABEL = 'report.template'

/** What the section asks for, which is the choice the control offers. */
type Choice = 'none' | 'builtin' | 'own'

const CHOICES = [
    { value: 'none' as const, label: 'No report' },
    { value: 'builtin' as const, label: 'Built-in template' },
    { value: 'own' as const, label: 'Own template' },
]

/**
 * The document's report section: whether a run writes one, and the template it writes it from.
 *
 * THREE STATES, ONE CONTROL. No section at all, `report: {}` for the built-in document, and
 * `report: {template: ...}` for the document's own -- three answers from a fixed set, which is
 * a segmented control rather than a menu to open.
 *
 * THE BUILT-IN TEMPLATE IS NOT IN THE DOCUMENT, so there is nothing here to show of it. What
 * stands in its place is the one line saying what a run writes, and the reference beside it.
 *
 * IT WRITES THROUGH THE DOCUMENT MODEL every other pane writes through, so the source pane and
 * the apply dialog see a template as it is typed. A template that does not compile is refused
 * at apply, at `report.template`, which is where the plan lists it.
 */
export function ReportPane({
    document,
    disabled,
    onChange,
}: {
    /** The local document, or null when the pipeline has no version yet. */
    document: JsonMap | null
    /** Why nothing here may be edited, or nothing when it may. */
    disabled?: string
    /** The section as it now stands: which of the three, and the template where there is one. */
    onChange: (choice: Choice, template: string) => void
}) {
    const section = reportIn(document)
    const choice: Choice = !section.declared ? 'none' : section.template === null ? 'builtin' : 'own'
    // What was written survives a trip through the other two choices, which take the template
    // out of the document. Coming back to "own" writes it again rather than opening an empty
    // pane, so the last template is captured as the choice that would drop it is answered.
    const held = useRef('')

    if (document === null) {
        return (
            <p className="text-muted-foreground p-4 text-sm">
                This pipeline has no version, so there is no document to read.
            </p>
        )
    }

    return (
        <div className="flex flex-col gap-4 p-4">
            <div className="space-y-2">
                <Segmented
                    label="What a run of this pipeline reports"
                    size="md"
                    value={choice}
                    options={CHOICES}
                    disabled={disabled !== undefined}
                    onChoose={(chosen) => {
                        if (section.template !== null) held.current = section.template
                        onChange(chosen, held.current)
                    }}
                />
                <p className="text-muted-foreground text-xs">
                    {choice === 'none' ? (
                        'A run of this pipeline writes no report document.'
                    ) : (
                        <>
                            {choice === 'builtin'
                                ? "The built-in document is the run's facts, a table of its steps, and its error. It is not part of this document."
                                : "This template is rendered against the run's facts when the run settles."}{' '}
                            <a
                                className="text-primary-ink hover:underline"
                                href={REPORTS_DOCS_URL}
                                target="_blank"
                                rel="noreferrer"
                            >
                                What a template may read
                            </a>
                        </>
                    )}
                </p>
            </div>

            {disabled !== undefined && (
                <p className="border-warning/40 text-warning rounded-md border p-2 text-xs">{disabled}</p>
            )}

            {choice === 'own' && (
                <WindowedPane
                    name={TEMPLATE_LABEL}
                    className="border-border overflow-hidden rounded-md border"
                    windowed={
                        <CodePane
                            value={section.template ?? ''}
                            mediaType={TEMPLATE_MEDIA_TYPE}
                            path={TEMPLATE_PATH}
                            label={`${TEMPLATE_LABEL}, in a window`}
                            className="min-h-0 flex-1"
                            readOnly={disabled !== undefined}
                            onChange={(text) => {
                                onChange('own', text)
                            }}
                        />
                    }
                >
                    <CodePane
                        value={section.template ?? ''}
                        mediaType={TEMPLATE_MEDIA_TYPE}
                        path={TEMPLATE_PATH}
                        label={TEMPLATE_LABEL}
                        placeholder="# {{ pipeline.code }} {{ run.status }}"
                        className="h-64 min-h-40"
                        readOnly={disabled !== undefined}
                        onChange={(text) => {
                            onChange('own', text)
                        }}
                    />
                </WindowedPane>
            )}
        </div>
    )
}
