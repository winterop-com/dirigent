import { useCallback, useMemo } from 'react'

import { Description } from '@/components/Description'
import { PageState } from '@/components/PageState'
import { CodePane } from '@/components/pipeline/CodePane'
import { Fact, Section } from '@/components/run/Panel'
import { TagChip } from '@/components/TagChip'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { WindowedPane } from '@/components/WindowedPane'
import { useRead } from '@/hooks/use-read'
import {
    carriesNote,
    readExample,
    requirementsOf,
    type ExampleOut,
    type Holdings,
    type Requirement,
} from '@/lib/examples'
import { headingOf } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import { STARTER_TAG } from '@/lib/starters'
import { cn } from '@/lib/utils'

/** What the source pane is called, which is the window's title and what a test asks for. */
const SOURCE_LABEL = LABELS.examples.source_pane

/** What the button that copies a starter into the editor says, here and in the picker. */
export const USE_AS_STARTER = LABELS.examples.use_as_starter

/** Named here so a kind the catalogue has no word for is a compile error rather than a blank. */
const NOUNS: Readonly<Record<Requirement['kind'], string>> = LABELS.examples.requirement.line

/**
 * One example read beside the listing: what it is, what it needs, and the text a copy copies.
 *
 * THE SOURCE IS THE POINT. A document in the corpus is a thing somebody reads before deciding
 * whether to copy it, comments and all, so the whole text is here in the editor every document
 * in this app is written in -- read-only, because this is the shipped file and not a draft, and
 * with the window every pane holding more than its box does.
 *
 * WHAT IT NEEDS IS CHECKED AGAINST THIS INSTANCE, item by item. The listing's column says how
 * many; this says which, and which of those are not here -- because what a reader does next is
 * create the ones that are missing.
 *
 * THE VERB IS OFFERED ONLY WHERE IT WOULD WORK. A document that did not opt into being copied
 * carries no button: `dg pipeline new` refuses the same code, and a control that opened an
 * editor on something the CLI refuses would be two answers to one question.
 */
export function ExamplePanel({
    example,
    holdings,
    onUse,
}: {
    example: ExampleOut
    holdings: Holdings
    /** Copy this document into the editor. Called only for a starter. */
    onUse: (source: string, code: string) => void
}) {
    const code = example.code
    const detail = useRead(useCallback(() => readExample(code), [code]))

    const heading = headingOf(example)
    const items = useMemo(() => requirementsOf(example.requires, holdings), [example.requires, holdings])
    const carries = carriesNote(example)
    const shown = example.tags.filter((tag) => tag !== STARTER_TAG)
    const source = detail.value?.source ?? ''

    return (
        <div className="flex flex-col gap-4 p-4">
            <div className="space-y-1">
                <h2 className={cn('text-sm font-semibold', !heading.named && 'font-mono')}>
                    {heading.title}
                </h2>
                {heading.code !== null && (
                    <p className="font-mono text-xs text-muted-foreground">{heading.code}</p>
                )}
                {(example.starter || carries !== null) && (
                    <p className="flex flex-wrap items-center gap-2 pt-0.5">
                        {example.starter && <Badge variant="outline">{LABELS.examples.starter_badge}</Badge>}
                        {carries !== null && <span className="text-xs text-muted-foreground">{carries}</span>}
                    </p>
                )}
                <Description text={example.description} />
            </div>

            {/* The badge above says this is a starter, so the chip that says it again is not
                drawn -- the same rule the listing row follows. */}
            {shown.length > 0 && (
                <p className="flex flex-wrap items-center gap-1">
                    {shown.map((tag) => (
                        <TagChip key={tag} tag={tag} />
                    ))}
                </p>
            )}

            <Section title={LABELS.examples.facts}>
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                    <Fact term={LABELS.examples.fact.plugin} detail={example.plugin} />
                    <Fact
                        term={LABELS.examples.fact.shelf}
                        detail={example.shelf === '' ? LABELS.examples.root_shelf : example.shelf}
                    />
                    {detail.value !== null && (
                        <Fact
                            term={LABELS.examples.fact.path}
                            detail={<span className="font-mono break-all">{detail.value.path}</span>}
                        />
                    )}
                </dl>
            </Section>

            <Section title={LABELS.word.requires}>
                {items.length === 0 ? (
                    <p className="text-xs text-muted-foreground">{LABELS.examples.requires_nothing}</p>
                ) : (
                    <ul className="space-y-1 text-xs">
                        {items.map((item) => (
                            <li key={`${item.kind}:${item.name}`} className="flex items-baseline gap-2">
                                <span className="text-faint">{NOUNS[item.kind]}</span>
                                <span className="font-mono break-all">{item.name}</span>
                                <span className={cn('ml-auto shrink-0', inkOf(item))}>{wordOf(item)}</span>
                            </li>
                        ))}
                    </ul>
                )}
            </Section>

            <Section title={LABELS.word.source}>
                {!detail.read || detail.problem !== null ? (
                    <PageState loading={!detail.read} problem={detail.problem} empty={false}>
                        {null}
                    </PageState>
                ) : (
                    <WindowedPane
                        name={SOURCE_LABEL}
                        className="overflow-hidden rounded-md border border-border bg-background"
                        windowed={
                            <CodePane
                                value={source}
                                path={`example-${code}-window`}
                                label={LABELS.examples.source_pane_windowed(SOURCE_LABEL)}
                                className="min-h-0 flex-1"
                                readOnly
                            />
                        }
                    >
                        <CodePane
                            value={source}
                            path={`example-${code}`}
                            label={SOURCE_LABEL}
                            className="h-72 min-h-40"
                            readOnly
                        />
                    </WindowedPane>
                )}
            </Section>

            {example.starter && (
                <Button
                    size="sm"
                    className="self-start"
                    disabled={detail.value === null}
                    onClick={() => {
                        onUse(source, code)
                    }}
                >
                    {USE_AS_STARTER}
                </Button>
            )}
        </div>
    )
}

/** What one requirement's state is called: held, not here, or nothing here can say. */
function wordOf(item: Requirement): string {
    if (item.met === null) return LABELS.examples.requirement.unchecked
    return item.met ? LABELS.examples.requirement.here : LABELS.examples.requirement.missing_word
}

/** The ink that state is read in, which is the one the connections column already uses. */
function inkOf(item: Requirement): string {
    if (item.met === null) return 'text-faint'
    return item.met ? 'text-good' : 'text-critical'
}
