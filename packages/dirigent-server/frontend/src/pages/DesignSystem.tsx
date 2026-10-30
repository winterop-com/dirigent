import { useEffect, useState, type ReactNode } from 'react'

import { Chip } from '@/components/ds/Chip'
import { ConfirmDialog } from '@/components/ds/ConfirmDialog'
import { DialogShell } from '@/components/ds/DialogShell'
import { EntityHeading } from '@/components/ds/EntityHeading'
import { Fact, FactList } from '@/components/ds/FactList'
import { describedBy, FormField } from '@/components/ds/FormField'
import { IconButton } from '@/components/ds/IconButton'
import { Notice } from '@/components/ds/Notice'
import { PageHeader } from '@/components/ds/PageHeader'
import { SearchField } from '@/components/ds/SearchField'
import { SecretReveal } from '@/components/ds/SecretReveal'
import { SectionHeading } from '@/components/ds/SectionHeading'
import { SwitchField } from '@/components/ds/SwitchField'
import { TextLink } from '@/components/ds/TextLink'
import { ToneDot } from '@/components/ds/ToneDot'
import { Well } from '@/components/ds/Well'
import { KindChip } from '@/components/KindChip'
import { PageState } from '@/components/PageState'
import { StatusChip } from '@/components/run/StatusChip'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Disclosure } from '@/components/pipeline/Disclosure'
import { galleryAnchor, GALLERY_INDEX, type GallerySection, type Tone } from '@/lib/design-system'
import { ICON_GROUPS, ICONS, type IconGroup, type IconName } from '@/lib/icons'
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

/** How far under the top of the scroller a section lands when its index entry is pressed. */
const SECTION_GAP = 16

/** The sentence under a heading, for the sections that have one to say. */
const LINES: Partial<Record<GallerySection, string>> = COPY.line

/** One part of the gallery: a section heading, its sentence, and a card of specimens. */
function Section({ id, children }: { id: GallerySection; children: ReactNode }) {
    const anchor = galleryAnchor(id)
    const line = LINES[id]
    return (
        <section data-gallery={id} aria-labelledby={anchor} className="space-y-2">
            <div className="space-y-0.5">
                <SectionHeading id={anchor}>{COPY.section[id]}</SectionHeading>
                {line !== undefined && <p className="text-sm text-muted-foreground">{line}</p>}
            </div>
            <div className="divide-y divide-border rounded-lg border border-border bg-card">{children}</div>
        </section>
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
    useEffect(() => {
        const observer = new IntersectionObserver(
            (entries) => {
                for (const entry of entries) {
                    if (!entry.isIntersecting) continue
                    const id = entry.target.getAttribute('data-gallery') as GallerySection | null
                    if (id !== null) setReading(id)
                }
            },
            { rootMargin: '-8% 0px -88% 0px' },
        )
        for (const section of document.querySelectorAll('[data-gallery]')) observer.observe(section)
        return () => {
            observer.disconnect()
        }
    }, [])
    return [reading, setReading]
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
                    <SectionHeading tier="group" className="px-2">
                        {COPY.group[group]}
                    </SectionHeading>
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

/** One variant or state inside a section, under its group heading. */
function Specimen({ title, children }: { title: string; children: ReactNode }) {
    return (
        <div className="space-y-3 p-4">
            <SectionHeading tier="group">{title}</SectionHeading>
            <div className="flex min-w-0 flex-wrap items-start gap-3">{children}</div>
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
                    <Section id="titles">
                        <Specimen title={VARIANT.row_stacked}>
                            <Narrow>
                                <EntityHeading
                                    thing={pipeline}
                                    description={SAMPLE.pipeline.description}
                                    chips={<Chip>{SAMPLE.tag_finance}</Chip>}
                                />
                            </Narrow>
                            <Narrow>
                                <EntityHeading thing={bare} />
                            </Narrow>
                            <Narrow>
                                <EntityHeading thing={long} description={SAMPLE.long.description} />
                            </Narrow>
                        </Specimen>
                        <Specimen title={VARIANT.row_inline}>
                            <Narrow>
                                <EntityHeading variant="row-inline" thing={pipeline} />
                            </Narrow>
                            <Narrow>
                                <EntityHeading
                                    variant="row-inline"
                                    thing={bare}
                                    chips={<KindChip kind="cron" />}
                                />
                            </Narrow>
                            <Narrow>
                                <EntityHeading variant="row-inline" thing={long} />
                            </Narrow>
                        </Specimen>
                        <Specimen title={VARIANT.panel}>
                            <div className="w-80 min-w-0">
                                <EntityHeading
                                    variant="panel"
                                    thing={pipeline}
                                    description={SAMPLE.pipeline.description}
                                    chips={<StatusChip status="succeeded" />}
                                />
                            </div>
                            <div className="w-80 min-w-0">
                                <EntityHeading
                                    variant="panel"
                                    thing={long}
                                    description={SAMPLE.long.description}
                                />
                            </div>
                        </Specimen>
                    </Section>

                    <Section id="headings">
                        <Specimen title={VARIANT.tiers}>
                            <div className="w-full max-w-xl space-y-4">
                                <SectionHeading
                                    aside={SAMPLE.runs_count}
                                    link={{ to: '/runs', label: SAMPLE.all_runs }}
                                >
                                    {SAMPLE.recent_runs}
                                </SectionHeading>
                                <SectionHeading tier="group" aside={<Chip>{SAMPLE.word_managed}</Chip>}>
                                    {SAMPLE.yesterday}
                                </SectionHeading>
                                <Narrow>
                                    <SectionHeading>{SAMPLE.long.name}</SectionHeading>
                                </Narrow>
                            </div>
                        </Specimen>
                        <Specimen title={VARIANT.listing}>
                            <div className="w-full">
                                <PageHeader
                                    title={LABELS.screen.pipelines.name}
                                    count={SAMPLE.pipelines_count}
                                    actions={[
                                        {
                                            id: 'refresh',
                                            label: LABELS.action.refresh,
                                            icon: ICONS.refresh,
                                            onClick: () => {},
                                        },
                                        {
                                            id: 'new',
                                            label: LABELS.action.new,
                                            icon: ICONS.create,
                                            variant: 'default',
                                            ariaLabel: SAMPLE.new_pipeline,
                                            onClick: () => {},
                                            moreLabel: SAMPLE.more_ways,
                                            more: [
                                                {
                                                    id: 'starter',
                                                    label: SAMPLE.from_starter,
                                                    icon: ICONS.template,
                                                    onClick: () => {},
                                                },
                                                {
                                                    id: 'file',
                                                    label: SAMPLE.from_file,
                                                    icon: ICONS.upload,
                                                    onClick: () => {},
                                                },
                                            ],
                                        },
                                    ]}
                                />
                            </div>
                        </Specimen>
                        <Specimen title={VARIANT.shut}>
                            <div className="w-full">
                                <PageHeader
                                    title={LABELS.screen.connections.name}
                                    count={SAMPLE.connections_count}
                                    actions={[
                                        {
                                            id: 'new',
                                            label: LABELS.action.new,
                                            icon: ICONS.create,
                                            variant: 'default',
                                            disabled: true,
                                            why: SAMPLE.why_admin,
                                            onClick: () => {},
                                        },
                                    ]}
                                />
                            </div>
                        </Specimen>
                        <Specimen title={VARIANT.trail}>
                            <div className="w-full">
                                <PageHeader
                                    title={pipeline.name}
                                    trail={[
                                        { label: LABELS.screen.pipelines.name, to: '/pipelines' },
                                        { label: pipeline.name },
                                    ]}
                                    code={pipeline.code}
                                    actions={[
                                        {
                                            id: 'run',
                                            label: LABELS.action.run,
                                            icon: ICONS.run,
                                            variant: 'default',
                                            onClick: () => {},
                                        },
                                    ]}
                                />
                            </div>
                        </Specimen>
                    </Section>

                    <Section id="links">
                        <Specimen title={VARIANT.inline}>
                            <p className="text-sm">
                                {SAMPLE.link_sentence.before}
                                <TextLink to="/runs">{SAMPLE.link_sentence.link}</TextLink>
                                {SAMPLE.link_sentence.after}
                            </p>
                        </Specimen>
                        <Specimen title={VARIANT.data}>
                            <TextLink variant="data" to="/runs">
                                {SAMPLE.run_id}
                            </TextLink>
                            <TextLink variant="data" to="/pipelines">
                                {SAMPLE.pipeline.code}
                            </TextLink>
                        </Specimen>
                        <Specimen title={VARIANT.external}>
                            <TextLink variant="external" href="/docs">
                                {SAMPLE.api_docs}
                            </TextLink>
                        </Specimen>
                    </Section>

                    <Section id="labels">
                        <Specimen title={VARIANT.tones}>
                            <Chip>{SAMPLE.word_managed}</Chip>
                            <Chip tone="mono">{SAMPLE.pipeline.code}</Chip>
                            <Chip tone="dashed">{SAMPLE.word_none}</Chip>
                            <Chip tone="good">{SAMPLE.word_live}</Chip>
                            <Chip tone="critical">{SAMPLE.word_failing}</Chip>
                            <Chip tone="edit">{SAMPLE.word_edited}</Chip>
                            <Chip icon={ICONS.tag}>{SAMPLE.tag_finance}</Chip>
                        </Specimen>
                        <Specimen title={VARIANT.selectable}>
                            {[SAMPLE.tag_finance, SAMPLE.tag_ops, SAMPLE.tag_nightly].map((tag) =>
                                chosen.includes(tag) ? (
                                    <Chip
                                        key={tag}
                                        tone="mono"
                                        removeLabel={LABELS.shell.stop_filtering_by_tag(tag)}
                                        onRemove={() => {
                                            setChosen(chosen.filter((one) => one !== tag))
                                        }}
                                    >
                                        {tag}
                                    </Chip>
                                ) : (
                                    <Chip
                                        key={tag}
                                        tone="mono"
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
                                <Chip title={SAMPLE.long.code} tone="mono">
                                    {SAMPLE.long.code}
                                </Chip>
                            </Narrow>
                        </Specimen>
                        <Specimen title={VARIANT.kind_status}>
                            <KindChip kind="http" />
                            <KindChip kind="sql" />
                            <KindChip kind="cron" />
                            {RUN_STATUSES.map((status) => (
                                <StatusChip key={status} status={status} />
                            ))}
                            <StatusChip status="failed" label={SAMPLE.status_override} />
                        </Specimen>
                    </Section>

                    <Section id="dots">
                        <Specimen title={VARIANT.tone_dots}>
                            {TONES.map((tone) => (
                                <ToneDot key={tone} tone={tone} label={SAMPLE.tone[tone]} />
                            ))}
                        </Specimen>
                        <Specimen title={VARIANT.always}>
                            {TONES.map((tone) => (
                                <ToneDot key={tone} tone={tone} label={SAMPLE.tone[tone]} say="always" />
                            ))}
                        </Specimen>
                        <Specimen title={VARIANT.status_dots}>
                            {RUN_STATUSES.map((status) => (
                                <ToneDot key={status} status={status} />
                            ))}
                        </Specimen>
                    </Section>

                    <Section id="icons">
                        <div className="space-y-1 p-4">
                            {(Object.keys(ICON_GROUPS) as IconGroup[]).map((group) => (
                                <IconShelf key={group} group={group} />
                            ))}
                        </div>
                    </Section>

                    <Section id="buttons">
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
                            <IconButton icon={ICONS.refresh} label={LABELS.action.refresh} size="sm" />
                            <IconButton icon={ICONS.refresh} label={LABELS.action.refresh} />
                            <IconButton
                                icon={ICONS.edit}
                                label={LABELS.action.edit}
                                variant="outline"
                                size="sm"
                            />
                            <IconButton icon={ICONS.edit} label={LABELS.action.edit} variant="outline" />
                            <IconButton icon={ICONS.fit_view} label={LABELS.shell.fit_view} />
                            <IconButton
                                icon={ICONS.open_in_window}
                                label={LABELS.shell.open_in_window(SAMPLE.pane)}
                            />
                            <IconButton
                                icon={ICONS.search}
                                label={LABELS.shell.open_palette}
                                shortcut={SAMPLE.chord}
                            />
                            <IconButton icon={ICONS.delete} label={LABELS.action.delete.verb} destructive />
                        </Specimen>
                        <Specimen title={VARIANT.shut}>
                            <IconButton
                                icon={ICONS.delete}
                                label={LABELS.action.delete.verb}
                                why={SAMPLE.why_admin}
                            />
                            <IconButton
                                icon={ICONS.run}
                                label={LABELS.action.run}
                                variant="outline"
                                why={SAMPLE.why_paused}
                            />
                        </Specimen>
                    </Section>

                    <Section id="search">
                        <Specimen title={VARIANT.empty}>
                            <SearchField value={needle} label={SAMPLE.search_label} onChange={setNeedle} />
                        </Specimen>
                        <Specimen title={VARIANT.typed}>
                            <SearchField
                                value={typed}
                                label={SAMPLE.search_label}
                                onChange={setTyped}
                                shortcut={false}
                            />
                        </Specimen>
                        <Specimen title={VARIANT.disabled}>
                            <SearchField value="" label={SAMPLE.search_label} onChange={() => {}} disabled />
                        </Specimen>
                    </Section>

                    <Section id="forms">
                        <Specimen title={VARIANT.prose}>
                            <div className="w-80 min-w-0">
                                <FormField
                                    id="ds-name"
                                    label={LABELS.word.name.label}
                                    required
                                    hint={SAMPLE.name_hint}
                                    help={SAMPLE.name_help}
                                    error={nameError}
                                >
                                    <Input
                                        id="ds-name"
                                        value={name}
                                        aria-invalid={nameError !== null || undefined}
                                        aria-describedby={describedBy('ds-name', {
                                            help: SAMPLE.name_help,
                                            error: nameError,
                                        })}
                                        onChange={(event) => {
                                            setName(event.target.value)
                                        }}
                                        onBlur={() => {
                                            setLeft(true)
                                        }}
                                    />
                                </FormField>
                            </div>
                        </Specimen>
                        <Specimen title={VARIANT.key}>
                            <div className="w-80 min-w-0">
                                <FormField
                                    id="ds-base-url"
                                    label={SAMPLE.key_label}
                                    mono
                                    fallback={SAMPLE.key_default}
                                    help={SAMPLE.key_help}
                                >
                                    <Input id="ds-base-url" placeholder={SAMPLE.key_default} />
                                </FormField>
                            </div>
                        </Specimen>
                        <Specimen title={VARIANT.error}>
                            <div className="w-80 min-w-0">
                                <FormField
                                    id="ds-timeout"
                                    label={SAMPLE.timeout_label}
                                    mono
                                    required
                                    error={SAMPLE.timeout_error}
                                >
                                    <Input id="ds-timeout" aria-invalid defaultValue={SAMPLE.timeout_value} />
                                </FormField>
                            </div>
                        </Specimen>
                    </Section>

                    <Section id="switches">
                        <div className="p-4">
                            <div className="w-96 min-w-0 divide-y divide-border">
                                <SwitchField
                                    id="ds-follow"
                                    label={SAMPLE.switch_label}
                                    help={SAMPLE.switch_help}
                                    checked={follow}
                                    onCheckedChange={setFollow}
                                />
                                <SwitchField
                                    id="ds-shut"
                                    label={SAMPLE.switch_shut_label}
                                    checked={false}
                                    why={SAMPLE.why_admin}
                                    onCheckedChange={() => {}}
                                />
                            </div>
                        </div>
                    </Section>

                    <Section id="notices">
                        <Specimen title={VARIANT.notices}>
                            <div className="w-full max-w-xl space-y-2">
                                <Notice tone="critical" title={SAMPLE.notice_critical_title}>
                                    {SAMPLE.notice_critical_body}
                                </Notice>
                                <Notice tone="warning">{SAMPLE.notice_warning}</Notice>
                                <Notice tone="neutral">{SAMPLE.notice_neutral}</Notice>
                                <Notice tone="neutral" icon={false}>
                                    {SAMPLE.notice_neutral}
                                </Notice>
                            </div>
                        </Specimen>
                        <Specimen title={VARIANT.well}>
                            <Well className="w-full max-w-xl text-sm text-muted-foreground">
                                {SAMPLE.well}
                            </Well>
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
                    </Section>

                    <Section id="dialogs">
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
                                <SecretReveal value={SAMPLE.secret} label={SAMPLE.secret_name} />
                            </div>
                        </Specimen>
                    </Section>

                    <Section id="facts">
                        <Specimen title={VARIANT.grid}>
                            <div className="w-80 min-w-0">
                                <FactList>
                                    <Fact term={LABELS.word.kind.term}>
                                        <KindChip kind="http" />
                                    </Fact>
                                    <Fact term={SAMPLE.fact_owner} mono>
                                        {SAMPLE.fact_owner_value}
                                    </Fact>
                                    <Fact term={SAMPLE.fact_schedule} mono>
                                        {SAMPLE.fact_schedule_value}
                                    </Fact>
                                    <Fact
                                        term={SAMPLE.fact_address}
                                        mono
                                        truncate
                                        title={SAMPLE.fact_address_value}
                                    >
                                        {SAMPLE.fact_address_value}
                                    </Fact>
                                    <Fact term={SAMPLE.fact_description}>{SAMPLE.long.description}</Fact>
                                </FactList>
                            </div>
                        </Specimen>
                        <Specimen title={VARIANT.row}>
                            <FactList variant="row">
                                <Fact term={LABELS.word.kind.term}>{SAMPLE.fact_kind_value}</Fact>
                                <Fact term={SAMPLE.fact_owner} mono>
                                    {SAMPLE.fact_owner_value}
                                </Fact>
                                <Fact term={SAMPLE.fact_schedule} mono>
                                    {SAMPLE.fact_schedule_value}
                                </Fact>
                            </FactList>
                        </Specimen>
                    </Section>
                </div>
            </div>

            <DialogShell
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
                <FormField
                    id="ds-dialog-name"
                    label={LABELS.word.name.label}
                    required
                    help={SAMPLE.name_help}
                >
                    <Input
                        id="ds-dialog-name"
                        value={name}
                        onChange={(event) => {
                            setName(event.target.value)
                        }}
                    />
                </FormField>
            </DialogShell>

            <DialogShell
                open={telling}
                onOpenChange={setTelling}
                title={SAMPLE.told_title}
                description={SAMPLE.told_description}
            >
                <SecretReveal value={SAMPLE.secret} label={SAMPLE.secret_name} />
            </DialogShell>

            <ConfirmDialog
                open={confirming}
                onOpenChange={setConfirming}
                title={SAMPLE.confirm_title}
                code={SAMPLE.secret_name}
                consequence={SAMPLE.confirm_consequence}
                verb={LABELS.action.revoke}
                onConfirm={() => {
                    setConfirming(false)
                }}
            />
        </>
    )
}
