import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import { Chip } from '@winterop-com/sokkel-ui/Chip'
import { ConfirmDialog } from '@winterop-com/sokkel-ui/DialogShell'
import { Question } from '@/components/Question'
import { DialogShell } from '@winterop-com/sokkel-ui/DialogShell'
import { Dot } from '@winterop-com/sokkel-ui/Dot'
import { ItemHeading } from '@winterop-com/sokkel-ui/ItemHeading'
import { DescriptionList } from '@winterop-com/sokkel-ui/DescriptionList'
import { describedBy, Field } from '@winterop-com/sokkel-ui/Field'
import { IconButton } from '@winterop-com/sokkel-ui/IconButton'
import { Callout } from '@winterop-com/sokkel-ui/Callout'
import { Breadcrumb } from '@/components/Breadcrumb'
import { PageHeader } from '@/components/ds/PageHeader'
import { Section, Surface } from '@winterop-com/sokkel-ui/Section'
import { SearchField } from '@winterop-com/sokkel-ui/SearchField'
import { GroupLabel } from '@winterop-com/sokkel-ui/GroupLabel'
import { SwitchField } from '@winterop-com/sokkel-ui/SwitchField'
import { TextLink } from '@winterop-com/sokkel-ui/TextLink'
import { KindChip } from '@/components/KindChip'
import { PageState } from '@/components/PageState'
import { StatusChip } from '@winterop-com/sokkel-ui/StatusChip'
import { CopyButton } from '@winterop-com/sokkel-ui/CopyButton'
import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import { Input } from '@winterop-com/sokkel-ui/primitives/input'
import { SecretReveal } from '@winterop-com/sokkel-ui/SecretReveal'
import { Disclosure } from '@/components/pipeline/Disclosure'
import {
    chipWords,
    copyWords,
    DIALOG_WORDS,
    dotOf,
    FIELD_WORDS,
    GALLERY_INDEX,
    galleryAnchor,
    type GallerySection,
    LINK_WORDS,
    SEARCH_PLACEHOLDER,
    SEARCH_WORDS,
    secretWords,
    type Tone,
} from '@/lib/design-system'
import { ICON_GROUPS, ICONS, type IconGroup, type IconName } from '@/lib/icons'
import { itemOf } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import { RUN_STATUSES } from '@/lib/status'
import { cn } from '@/lib/utils'

const COPY = LABELS.design
const SAMPLE = COPY.sample
const VARIANT = COPY.variant

const TONES: readonly Tone[] = ['good', 'critical', 'warning', 'info', 'quiet', 'unknown']

/** One kind of icon, shut until it is asked for: the vocabulary is too long to read whole. */
function IconShelf({ group }: { group: IconGroup }) {
    const [open, setOpen] = useState(false)
    const concepts: readonly IconName[] = ICON_GROUPS[group]
    return (
        <Disclosure
            title={COPY.icon_group[group]}
            summary={<span className="text-xs text-faint">{concepts.length}</span>}
            open={open}
            onToggle={() => {
                setOpen(!open)
            }}
        >
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3 lg:grid-cols-5">
                {concepts.map((concept) => {
                    const Glyph = ICONS[concept]
                    return (
                        <div key={concept} className="flex min-w-0 items-center gap-2 text-xs">
                            <Glyph className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                            <span className="truncate font-mono">{concept}</span>
                        </div>
                    )
                })}
            </div>
        </Disclosure>
    )
}

/** The gestures that say the reader has moved on from the entry they pressed. */
const RELEASES = ['wheel', 'touchmove', 'keydown'] as const

/** How far under the top of the scroller a section lands when its index entry is pressed. */
const SECTION_GAP = 16

/** The sentence under a heading, for the sections that have one to say. */
const LINES: Partial<Record<GallerySection, string>> = COPY.line

/** One part of the gallery: a section heading, its sentence, and a card of specimens. */
function Shelf({ id, children }: { id: GallerySection; children: ReactNode }) {
    const anchor = galleryAnchor(id)
    const line = LINES[id]
    return (
        <div data-gallery={id}>
            <Section headingId={anchor} title={COPY.section[id]} flush bodyClassName="divide-y divide-border">
                {line !== undefined && <p className="px-4 py-3 text-sm text-muted-foreground">{line}</p>}
                {children}
            </Section>
        </div>
    )
}

/**
 * Which section is being read, kept by what crosses a line just under the top of the window.
 *
 * The last one to cross is the one in front of the reader, so a section too short to reach the line
 * is still reached by pressing its entry.
 */
function useReadingSection(): [GallerySection, (section: GallerySection) => void] {
    const [reading, setReading] = useState<GallerySection>('titles')
    // A section at the foot of the page cannot reach the line, so a pressed entry holds until the
    // reader scrolls for themselves.
    const pressed = useRef(false)
    useEffect(() => {
        const observer = new IntersectionObserver(
            (entries) => {
                if (pressed.current) return
                for (const entry of entries) {
                    if (!entry.isIntersecting) continue
                    const id = entry.target.getAttribute('data-gallery') as GallerySection | null
                    if (id !== null) setReading(id)
                }
            },
            { rootMargin: '-8% 0px -88% 0px' },
        )
        for (const section of document.querySelectorAll('[data-gallery]')) observer.observe(section)
        const release = () => {
            pressed.current = false
        }
        for (const gesture of RELEASES) window.addEventListener(gesture, release, { passive: true })
        return () => {
            observer.disconnect()
            for (const gesture of RELEASES) window.removeEventListener(gesture, release)
        }
    }, [])
    const choose = useCallback((section: GallerySection) => {
        pressed.current = true
        setReading(section)
    }, [])
    return [reading, choose]
}

/** Bring one section to the top of the column the screen scrolls in, and nothing else. */
function toSection(section: GallerySection): void {
    const target = document.getElementById(galleryAnchor(section))
    const scroller = target?.closest('main')
    if (target === null || scroller === null || scroller === undefined) return
    const offset = target.getBoundingClientRect().top - scroller.getBoundingClientRect().top
    scroller.scrollTo({ top: scroller.scrollTop + offset - SECTION_GAP })
}

/** Every section by its plain name: a column beside them on a wide window, a block above on a phone. */
function GalleryIndex({
    reading,
    onChoose,
}: {
    reading: GallerySection
    onChoose: (section: GallerySection) => void
}) {
    return (
        <nav
            aria-label={COPY.index}
            className="mb-6 flex flex-wrap gap-x-6 gap-y-2 lg:sticky lg:top-0 lg:mb-0 lg:max-h-[calc(100vh-8rem)] lg:w-40 lg:shrink-0 lg:flex-col lg:self-start lg:overflow-y-auto"
        >
            {GALLERY_INDEX.map(({ group, sections }) => (
                <div key={group} className="min-w-0 space-y-1">
                    <GroupLabel as="h3" className="px-2">
                        {COPY.group[group]}
                    </GroupLabel>
                    <ul className="flex flex-wrap gap-0.5 lg:flex-col">
                        {sections.map((section) => (
                            <li key={section}>
                                <a
                                    href={`#${galleryAnchor(section)}`}
                                    aria-current={section === reading ? 'true' : undefined}
                                    className={cn(
                                        'control-link block rounded-md px-2 py-1 text-sm',
                                        section === reading
                                            ? 'bg-secondary font-medium text-foreground'
                                            : 'text-muted-foreground hover:bg-secondary hover:text-foreground',
                                    )}
                                    onClick={(event) => {
                                        // The shell clips its own overflow, so a jump the browser
                                        // made would scroll the whole app inside the window.
                                        event.preventDefault()
                                        toSection(section)
                                        onChoose(section)
                                    }}
                                >
                                    {COPY.section[section]}
                                </a>
                            </li>
                        ))}
                    </ul>
                </div>
            ))}
        </nav>
    )
}

/**
 * One variant or state inside a section, under its group heading. `small` sets the row on one small
 * line, so a bare dot and a dot saying its small word stand on the same line.
 */
function Specimen({
    title,
    small = false,
    children,
}: {
    title: string
    small?: boolean
    children: ReactNode
}) {
    return (
        <div className="space-y-3 p-4">
            <GroupLabel as="h3">{title}</GroupLabel>
            <div className={cn('flex min-w-0 flex-wrap items-start gap-3', small && 'text-xs')}>
                {children}
            </div>
        </div>
    )
}

/** The width of a narrow cell, so a specimen shows what it does when space runs out. */
function Narrow({ children }: { children: ReactNode }) {
    return <div className="w-56 min-w-0">{children}</div>
}

/**
 * The design system, drawn: every component in `components/ds` in every variant and state.
 *
 * Reached from the command palette and not from the rail. What a page draws is what this draws.
 *
 * ITS NAMES ARE THE READER'S. A section says what somebody is looking for, and the component behind
 * it keeps its own name in the code; the index is `GALLERY_INDEX` in `lib/design-system`.
 */
export function DesignSystem() {
    const [needle, setNeedle] = useState('')
    const [typed, setTyped] = useState<string>(SAMPLE.search_typed)
    const [chosen, setChosen] = useState<readonly string[]>([SAMPLE.tag_finance, SAMPLE.tag_ops])
    const [follow, setFollow] = useState(true)
    const [asking, setAsking] = useState(false)
    const [telling, setTelling] = useState(false)
    const [confirming, setConfirming] = useState(false)
    const [name, setName] = useState('')
    const [left, setLeft] = useState(false)

    const [reading, setReading] = useReadingSection()

    const pipeline = { code: SAMPLE.pipeline.code, name: SAMPLE.pipeline.name }
    const bare = { code: SAMPLE.bare_code }
    const long = { code: SAMPLE.long.code, name: SAMPLE.long.name }
    const nameError = left && name.trim() === '' ? LABELS.form.refusal.required(LABELS.word.name.label) : null

    return (
        <>
            <PageHeader title={LABELS.screen.design.name} />
            <div className="lg:flex lg:gap-8">
                <GalleryIndex reading={reading} onChoose={setReading} />
                <div className="max-w-5xl min-w-0 flex-1 space-y-8 pb-8">
                    <Shelf id="titles">
                        <Specimen title={VARIANT.row_stacked}>
                            <Narrow>
                                <ItemHeading
                                    {...itemOf(pipeline)}
                                    as="span"
                                    description={SAMPLE.pipeline.description}
                                    chips={<Chip>{SAMPLE.tag_finance}</Chip>}
                                />
                            </Narrow>
                            <Narrow>
                                <ItemHeading {...itemOf(bare)} as="span" />
                            </Narrow>
                            <Narrow>
                                <ItemHeading
                                    {...itemOf(long)}
                                    as="span"
                                    description={SAMPLE.long.description}
                                />
                            </Narrow>
                        </Specimen>
                        <Specimen title={VARIANT.row_inline}>
                            <Narrow>
                                <ItemHeading {...itemOf(pipeline)} variant="inline" as="span" />
                            </Narrow>
                            <Narrow>
                                <ItemHeading
                                    {...itemOf(bare)}
                                    variant="inline"
                                    as="span"
                                    chips={<KindChip kind="cron" />}
                                />
                            </Narrow>
                            <Narrow>
                                <ItemHeading {...itemOf(long)} variant="inline" as="span" />
                            </Narrow>
                        </Specimen>
                        <Specimen title={VARIANT.panel}>
                            <div className="w-80 min-w-0">
                                <ItemHeading
                                    {...itemOf(pipeline)}
                                    as="span"
                                    description={SAMPLE.pipeline.description}
                                    chips={<StatusChip dot status="succeeded" />}
                                />
                            </div>
                            <div className="w-80 min-w-0">
                                <ItemHeading
                                    {...itemOf(long)}
                                    size="dialog"
                                    as="span"
                                    description={SAMPLE.long.description}
                                />
                            </div>
                        </Specimen>
                    </Shelf>

                    <Shelf id="headings">
                        <Specimen title={VARIANT.tiers}>
                            <div className="w-full max-w-xl space-y-4">
                                <GroupLabel as="h3">{SAMPLE.yesterday}</GroupLabel>
                                <Narrow>
                                    <GroupLabel as="h3">{SAMPLE.long.name}</GroupLabel>
                                </Narrow>
                            </div>
                        </Specimen>
                        <Specimen title={VARIANT.listing}>
                            <div className="w-full">
                                <PageHeader
                                    inPlace
                                    title={LABELS.screen.pipelines.name}
                                    count={SAMPLE.pipelines_count}
                                    items={[
                                        {
                                            id: 'refresh',
                                            label: LABELS.action.refresh,
                                            icon: <ICONS.refresh aria-hidden />,
                                            onSelect: () => {},
                                        },
                                    ]}
                                    primary={{
                                        id: 'new',
                                        label: SAMPLE.new_pipeline,
                                        face: LABELS.action.new,
                                        moreLabel: SAMPLE.more_ways,
                                        icon: <ICONS.create aria-hidden />,
                                        onSelect: () => {},
                                        more: [
                                            {
                                                label: SAMPLE.from_starter,
                                                icon: <ICONS.template aria-hidden />,
                                                onSelect: () => {},
                                            },
                                            {
                                                label: SAMPLE.from_file,
                                                icon: <ICONS.upload aria-hidden />,
                                                onSelect: () => {},
                                            },
                                        ],
                                    }}
                                />
                            </div>
                        </Specimen>
                        <Specimen title={VARIANT.shut}>
                            <div className="w-full">
                                <PageHeader
                                    inPlace
                                    title={LABELS.screen.connections.name}
                                    count={SAMPLE.connections_count}
                                    primary={{
                                        id: 'new',
                                        label: LABELS.action.new,
                                        icon: <ICONS.create aria-hidden />,
                                        reason: SAMPLE.why_admin,
                                        onSelect: () => {},
                                    }}
                                />
                            </div>
                        </Specimen>
                        <Specimen title={VARIANT.trail}>
                            <div className="w-full space-y-3">
                                <Breadcrumb
                                    trail={[{ label: LABELS.screen.pipelines.name, to: '/pipelines' }]}
                                    inPlace
                                />
                                <PageHeader
                                    inPlace
                                    title={pipeline.name}
                                    code={pipeline.code}
                                    primary={{
                                        id: 'run',
                                        label: LABELS.action.run,
                                        icon: <ICONS.run aria-hidden />,
                                        onSelect: () => {},
                                    }}
                                />
                            </div>
                        </Specimen>
                    </Shelf>

                    <Shelf id="links">
                        <Specimen title={VARIANT.inline}>
                            <p className="text-sm">
                                {SAMPLE.link_sentence.before}
                                <TextLink variant="inline" href="/runs">
                                    {SAMPLE.link_sentence.link}
                                </TextLink>
                                {SAMPLE.link_sentence.after}
                            </p>
                        </Specimen>
                        <Specimen title={VARIANT.data}>
                            <TextLink variant="data" code href="/runs">
                                {SAMPLE.run_id}
                            </TextLink>
                            <TextLink variant="data" code href="/pipelines">
                                {SAMPLE.pipeline.code}
                            </TextLink>
                        </Specimen>
                        <Specimen title={VARIANT.external}>
                            <TextLink variant="inline" external words={LINK_WORDS} href="/docs">
                                {SAMPLE.api_docs}
                            </TextLink>
                        </Specimen>
                    </Shelf>

                    <Shelf id="labels">
                        <Specimen title={VARIANT.tones}>
                            <Chip>{SAMPLE.word_managed}</Chip>
                            <Chip mono>{SAMPLE.pipeline.code}</Chip>
                            <Chip tone="absent">{SAMPLE.word_none}</Chip>
                            <Chip tone="good">{SAMPLE.word_live}</Chip>
                            <Chip tone="critical">{SAMPLE.word_failing}</Chip>
                            <Chip icon={<ICONS.tag aria-hidden />}>{SAMPLE.tag_finance}</Chip>
                        </Specimen>
                        <Specimen title={VARIANT.selectable}>
                            {[SAMPLE.tag_finance, SAMPLE.tag_ops, SAMPLE.tag_nightly].map((tag) =>
                                chosen.includes(tag) ? (
                                    <Chip
                                        key={tag}
                                        mono
                                        words={chipWords(LABELS.shell.stop_filtering_by_tag)}
                                        onRemove={() => {
                                            setChosen(chosen.filter((one) => one !== tag))
                                        }}
                                    >
                                        {tag}
                                    </Chip>
                                ) : (
                                    <Chip
                                        key={tag}
                                        mono
                                        selectLabel={LABELS.shell.filter_by_tag(tag)}
                                        onSelect={() => {
                                            setChosen([...chosen, tag])
                                        }}
                                    >
                                        {tag}
                                    </Chip>
                                ),
                            )}
                        </Specimen>
                        <Specimen title={VARIANT.long}>
                            <Narrow>
                                <Chip title={SAMPLE.long.code} mono>
                                    {SAMPLE.long.code}
                                </Chip>
                            </Narrow>
                        </Specimen>
                        <Specimen title={VARIANT.kind_status}>
                            <KindChip kind="http" />
                            <KindChip kind="sql" />
                            <KindChip kind="cron" />
                            {RUN_STATUSES.map((status) => (
                                <StatusChip dot key={status} status={status} />
                            ))}
                            <StatusChip dot status="failed" label={SAMPLE.status_override} />
                        </Specimen>
                    </Shelf>

                    <Shelf id="dots">
                        <Specimen title={VARIANT.tone_dots} small>
                            {TONES.map((tone) => (
                                <Dot key={tone} {...dotOf({ tone, label: SAMPLE.tone[tone] })} />
                            ))}
                        </Specimen>
                        <Specimen title={VARIANT.always} small>
                            {TONES.map((tone) => (
                                <Dot key={tone} {...dotOf({ tone, label: SAMPLE.tone[tone] }, 'always')} />
                            ))}
                        </Specimen>
                        <Specimen title={VARIANT.status_dots} small>
                            {RUN_STATUSES.map((status) => (
                                <Dot key={status} {...dotOf({ status })} />
                            ))}
                        </Specimen>
                    </Shelf>

                    <Shelf id="icons">
                        <div className="space-y-1 p-4">
                            {(Object.keys(ICON_GROUPS) as IconGroup[]).map((group) => (
                                <IconShelf key={group} group={group} />
                            ))}
                        </div>
                    </Shelf>

                    <Shelf id="buttons">
                        <Specimen title={VARIANT.text_buttons}>
                            <Button size="sm">{LABELS.action.new}</Button>
                            <Button size="sm" variant="outline">
                                {LABELS.action.edit}
                            </Button>
                            <Button size="sm" variant="ghost">
                                {LABELS.action.cancel}
                            </Button>
                            <Button size="sm" variant="outline" className="destructive-action">
                                {LABELS.action.delete.verb}
                            </Button>
                        </Specimen>
                        <Specimen title={VARIANT.sizes}>
                            <IconButton label={LABELS.action.refresh} size="icon-sm">
                                <ICONS.refresh aria-hidden />
                            </IconButton>
                            <IconButton size="icon" label={LABELS.action.refresh}>
                                <ICONS.refresh aria-hidden />
                            </IconButton>
                            <IconButton label={LABELS.action.edit} variant="outline" size="icon-sm">
                                <ICONS.edit aria-hidden />
                            </IconButton>
                            <IconButton size="icon" label={LABELS.action.edit} variant="outline">
                                <ICONS.edit aria-hidden />
                            </IconButton>
                            <IconButton size="icon" label={LABELS.shell.fit_view}>
                                <ICONS.fit_view aria-hidden />
                            </IconButton>
                            <CopyButton
                                value={SAMPLE.url}
                                size="icon"
                                words={copyWords(LABELS.triggers.source.copy_url)}
                            />
                            <IconButton size="icon" label={LABELS.shell.open_in_window(SAMPLE.pane)}>
                                <ICONS.open_in_window aria-hidden />
                            </IconButton>
                            <IconButton size="icon" label={LABELS.shell.open_palette} shortcut={SAMPLE.chord}>
                                <ICONS.search aria-hidden />
                            </IconButton>
                            <IconButton size="icon" label={LABELS.action.delete.verb} destructive>
                                <ICONS.delete aria-hidden />
                            </IconButton>
                        </Specimen>
                        <Specimen title={VARIANT.shut}>
                            <IconButton
                                size="icon"
                                label={LABELS.action.delete.verb}
                                reason={SAMPLE.why_admin}
                            >
                                <ICONS.delete aria-hidden />
                            </IconButton>
                            <IconButton
                                size="icon"
                                label={LABELS.action.run}
                                variant="outline"
                                reason={SAMPLE.why_paused}
                            >
                                <ICONS.run aria-hidden />
                            </IconButton>
                        </Specimen>
                    </Shelf>

                    <Shelf id="search">
                        <Specimen title={VARIANT.empty}>
                            <SearchField
                                placeholder={SEARCH_PLACEHOLDER}
                                words={SEARCH_WORDS}
                                className="w-64"
                                value={needle}
                                label={SAMPLE.search_label}
                                onChange={setNeedle}
                            />
                        </Specimen>
                        <Specimen title={VARIANT.typed}>
                            <SearchField
                                placeholder={SEARCH_PLACEHOLDER}
                                words={SEARCH_WORDS}
                                className="w-64"
                                value={typed}
                                label={SAMPLE.search_label}
                                onChange={setTyped}
                                shortcut={false}
                            />
                        </Specimen>
                        <Specimen title={VARIANT.disabled}>
                            <SearchField
                                placeholder={SEARCH_PLACEHOLDER}
                                words={SEARCH_WORDS}
                                className="w-64"
                                value=""
                                label={SAMPLE.search_label}
                                onChange={() => {}}
                                disabled
                            />
                        </Specimen>
                    </Shelf>

                    <Shelf id="forms">
                        <Specimen title={VARIANT.prose}>
                            <div className="w-80 min-w-0">
                                <Field
                                    id="ds-name"
                                    label={LABELS.word.name.label}
                                    required
                                    requiredMark="word"
                                    words={FIELD_WORDS}
                                    hint={SAMPLE.name_hint}
                                    help={SAMPLE.name_help}
                                    error={nameError}
                                >
                                    <Input
                                        id="ds-name"
                                        value={name}
                                        aria-required
                                        aria-invalid={nameError !== null || undefined}
                                        aria-describedby={describedBy('ds-name', { help: SAMPLE.name_help })}
                                        onChange={(event) => {
                                            setName(event.target.value)
                                        }}
                                        onBlur={() => {
                                            setLeft(true)
                                        }}
                                    />
                                </Field>
                            </div>
                        </Specimen>
                        <Specimen title={VARIANT.key}>
                            <div className="w-80 min-w-0">
                                <Field
                                    id="ds-base-url"
                                    label={SAMPLE.key_label}
                                    mono
                                    fallback={LABELS.form.default_is(SAMPLE.key_default)}
                                    help={SAMPLE.key_help}
                                >
                                    <Input
                                        id="ds-base-url"
                                        placeholder={SAMPLE.key_default}
                                        aria-describedby={describedBy('ds-base-url', {
                                            help: SAMPLE.key_help,
                                            fallback: SAMPLE.key_default,
                                        })}
                                    />
                                </Field>
                            </div>
                        </Specimen>
                        <Specimen title={VARIANT.error}>
                            <div className="w-80 min-w-0">
                                <Field
                                    id="ds-timeout"
                                    label={SAMPLE.timeout_label}
                                    mono
                                    required
                                    requiredMark="word"
                                    words={FIELD_WORDS}
                                    error={SAMPLE.timeout_error}
                                >
                                    <Input
                                        id="ds-timeout"
                                        aria-required
                                        aria-invalid
                                        defaultValue={SAMPLE.timeout_value}
                                    />
                                </Field>
                            </div>
                        </Specimen>
                    </Shelf>

                    <Shelf id="switches">
                        <div className="p-4">
                            <div className="w-full max-w-96 divide-y divide-border">
                                <SwitchField
                                    id="ds-follow"
                                    label={SAMPLE.switch_label}
                                    explain={SAMPLE.switch_help}
                                    checked={follow}
                                    onCheckedChange={setFollow}
                                />
                                <SwitchField
                                    id="ds-shut"
                                    label={SAMPLE.switch_shut_label}
                                    checked={false}
                                    reason={SAMPLE.why_admin}
                                    onCheckedChange={() => {}}
                                />
                            </div>
                        </div>
                    </Shelf>

                    <Shelf id="notices">
                        <Specimen title={VARIANT.notices}>
                            <div className="w-full max-w-xl space-y-2">
                                <Callout tone="critical" title={SAMPLE.notice_critical_title}>
                                    {SAMPLE.notice_critical_body}
                                </Callout>
                                <Callout tone="warning">{SAMPLE.notice_warning}</Callout>
                                <Callout tone="neutral">{SAMPLE.notice_neutral}</Callout>
                                <Callout tone="neutral" icon={false}>
                                    {SAMPLE.notice_neutral}
                                </Callout>
                            </div>
                        </Specimen>
                        <Specimen title={VARIANT.well}>
                            <Surface
                                tone="well"
                                pad
                                className="w-full max-w-xl text-sm text-muted-foreground"
                            >
                                {SAMPLE.well}
                            </Surface>
                        </Specimen>
                        <Specimen title={VARIANT.inset}>
                            <Surface tone="inset" pad className="w-full max-w-xl font-mono text-xs">
                                {SAMPLE.inset}
                            </Surface>
                        </Specimen>
                        <Specimen title={VARIANT.loading}>
                            <div className="w-full max-w-md">
                                <PageState loading problem={null} empty={false}>
                                    {null}
                                </PageState>
                            </div>
                        </Specimen>
                        <Specimen title={VARIANT.empty}>
                            <div className="w-full max-w-md">
                                <PageState loading={false} problem={null} empty emptyMessage={SAMPLE.empty}>
                                    {null}
                                </PageState>
                            </div>
                        </Specimen>
                    </Shelf>

                    <Shelf id="dialogs">
                        <Specimen title={VARIANT.dialogs}>
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => {
                                    setAsking(true)
                                }}
                            >
                                {VARIANT.asks}
                            </Button>
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => {
                                    setTelling(true)
                                }}
                            >
                                {VARIANT.tells}
                            </Button>
                            <Button
                                variant="outline"
                                size="sm"
                                className="destructive-action"
                                onClick={() => {
                                    setConfirming(true)
                                }}
                            >
                                {VARIANT.confirm}
                            </Button>
                        </Specimen>
                        <Specimen title={VARIANT.secret}>
                            <div className="w-full max-w-lg">
                                <SecretReveal value={SAMPLE.secret} words={secretWords(SAMPLE.secret_name)} />
                            </div>
                        </Specimen>
                    </Shelf>

                    <Shelf id="facts">
                        <Specimen title={VARIANT.grid}>
                            <div className="w-80 min-w-0">
                                <DescriptionList
                                    items={[
                                        { term: LABELS.word.kind.term, value: <KindChip kind="http" /> },
                                        {
                                            term: SAMPLE.fact_owner,
                                            value: SAMPLE.fact_owner_value,
                                            code: true,
                                        },
                                        {
                                            term: SAMPLE.fact_schedule,
                                            value: SAMPLE.fact_schedule_value,
                                            code: true,
                                        },
                                        {
                                            term: SAMPLE.fact_address,
                                            value: SAMPLE.fact_address_value,
                                            code: true,
                                        },
                                        { term: SAMPLE.fact_description, value: SAMPLE.long.description },
                                    ]}
                                />
                            </div>
                        </Specimen>
                        <Specimen title={VARIANT.row}>
                            <DescriptionList
                                layout="row"
                                items={[
                                    { term: LABELS.word.kind.term, value: SAMPLE.fact_kind_value },
                                    { term: SAMPLE.fact_owner, value: SAMPLE.fact_owner_value, code: true },
                                    {
                                        term: SAMPLE.fact_schedule,
                                        value: SAMPLE.fact_schedule_value,
                                        code: true,
                                    },
                                ]}
                            />
                        </Specimen>
                    </Shelf>
                </div>
            </div>

            <DialogShell
                words={DIALOG_WORDS}
                open={asking}
                onOpenChange={setAsking}
                title={SAMPLE.dialog_title}
                description={SAMPLE.dialog_description}
                confirm={{
                    label: LABELS.action.create.verb,
                    why: name.trim() === '' ? SAMPLE.why_name : undefined,
                    onConfirm: () => {
                        setAsking(false)
                    },
                }}
            >
                <Field
                    id="ds-dialog-name"
                    label={LABELS.word.name.label}
                    required
                    requiredMark="word"
                    words={FIELD_WORDS}
                    help={SAMPLE.name_help}
                >
                    <Input
                        id="ds-dialog-name"
                        aria-required
                        value={name}
                        onChange={(event) => {
                            setName(event.target.value)
                        }}
                    />
                </Field>
            </DialogShell>

            <DialogShell
                words={DIALOG_WORDS}
                open={telling}
                onOpenChange={setTelling}
                title={SAMPLE.told_title}
                description={SAMPLE.told_description}
            >
                <SecretReveal value={SAMPLE.secret} words={secretWords(SAMPLE.secret_name)} />
            </DialogShell>

            <ConfirmDialog
                open={confirming}
                onOpenChange={setConfirming}
                question={<Question ask={SAMPLE.confirm_ask} code={SAMPLE.secret_name} />}
                confirm={{
                    label: LABELS.action.revoke,
                    onConfirm: () => {
                        setConfirming(false)
                    },
                    destructive: true,
                }}
                words={DIALOG_WORDS}
            />
        </>
    )
}
