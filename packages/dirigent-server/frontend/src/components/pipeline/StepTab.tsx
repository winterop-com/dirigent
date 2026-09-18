import { ChevronRight, X } from 'lucide-react'
import { Fragment, useMemo, useState, type ReactNode } from 'react'

import { KindChip } from '@/components/KindChip'
import { SchemaForm } from '@/components/pipeline/SchemaForm'
import { Section } from '@/components/run/Panel'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { JsonMap, Problem } from '@/lib/api'
import type { BlockEntry } from '@/lib/blocks'
import {
    blockOf,
    changeDocument,
    configOf,
    dependsOn,
    stepHeading,
    stepName,
    stepNames,
} from '@/lib/pipeline-document'
import { fieldsOf, validateFields } from '@/lib/schema-form'
import {
    groupProblems,
    stepGroups,
    type StepGroup,
    type StepGroupId,
    type SummaryPart,
} from '@/lib/step-groups'
import {
    retryFields,
    retryValues,
    stepFields,
    stepKeyValues,
    withRetryKey,
    withStepKey,
} from '@/lib/step-keys'
import { cn } from '@/lib/utils'

export const ADD_DEPENDENCY_LABEL = 'Add a prerequisite'

/**
 * The step in front of somebody: what it runs, what it waits for, and the config it takes.
 *
 * THE CONFIG IS THE QUESTION, AND THE ENGINE IS THE SETTING. What a step does is the block's own
 * config, so that is what the panel opens on; how the engine runs it is five groups under that,
 * each of which says its own state in one line and opens in place. Name is last, because a
 * display string is the least of what a step is.
 *
 * THE FORM IS THE BLOCK'S OWN SCHEMA. `GET /blocks/{id}` publishes a closed schema per block and
 * `lib/schema-form` turns it into fields, so a config key this instance does not take has no box
 * to be typed into and a value outside the schema is refused under the field it was typed in.
 *
 * THE CONFIG OPENS ON WHAT THE STEP NEEDS. A block may publish twenty keys and take two, so the
 * form draws what the schema requires and what this step already sets, and offers the rest behind
 * one link.
 *
 * A SHUT GROUP STILL SAYS WHAT WOULD RUN. Its line carries the values the document sets in body
 * ink and the defaults it leaves alone in muted ink, so a reader sees the whole of the step's
 * behaviour without opening anything -- and `lib/step-groups` is where a group's members and its
 * line are decided, from the same schema the controls are built from.
 *
 * A GROUP WITH SOMETHING WRONG IN IT STANDS OPEN, because a refusal folded away is a refusal
 * nobody can answer. It is the only thing that decides a group's state for it; every other group
 * opens and shuts on its own, and what is open is the panel's own state, so choosing another step
 * -- which is another panel -- starts shut again.
 *
 * THE REFUSAL HERE IS THE CLIENT'S HALF. What this can check is one field against one schema.
 * Whether the document as a whole applies -- its graph, its references, the blocks it names --
 * is the server's, and Validate and Apply are where it is asked.
 *
 * THE GROUPS WRITE THROUGH THE DOCUMENT STORE, because the members they edit have no prop of
 * their own the way `config`, `depends_on` and `name` do; `changeDocument` is the same writer
 * those three reach in the end, and it refuses an edit while the source pane does not parse. A
 * key equal to the definition's default is removed rather than written, and the control still
 * shows that default.
 *
 * THE KEY IS THE STEP AND THE NAME IS NOT. `depends_on`, every attempt and every log line
 * reference the key this step is written under, so the key is not editable here; the name is a
 * display string with nothing pointing at it, which is why it has a box.
 */
export function StepTab({
    step,
    document,
    block,
    blockProblem,
    disabled,
    onConfig,
    onDependsOn,
    onName,
}: {
    step: string
    document: JsonMap
    /** The catalog entry for the block this step runs, or null while it is being read. */
    block: BlockEntry | null
    /** Why the block could not be read, such as a plugin this instance does not have. */
    blockProblem: Problem | null
    /** Why nothing on this form may be edited, or nothing when it may. */
    disabled?: string
    onConfig: (config: JsonMap) => void
    onDependsOn: (names: string[]) => void
    /** The display name was changed, or emptied. */
    onName: (name: string | null) => void
}) {
    const heading = stepHeading(document, step)
    const [named, setNamed] = useState(stepName(document, step) ?? '')
    const config = configOf(document, step)
    const fields = useMemo(() => fieldsOf(block?.config_schema), [block])
    const problems = useMemo(() => validateFields(fields, config), [fields, config])
    const prerequisites = dependsOn(document, step)
    const offered = stepNames(document).filter((name) => name !== step && !prerequisites.includes(name))
    const keys = stepKeyValues(document, step)
    const retry = retryValues(document, step)
    const keyProblems = validateFields(stepFields, keys)
    const retryProblems = validateFields(retryFields, retry)
    const refusals = Object.entries({ ...keyProblems, ...retryProblems, ...problems })
    const groups = stepGroups({ keys, retry, prerequisites, sensor: block?.kind === 'sensor' })
    // Which groups somebody opened. The panel is keyed by step upstream, so this belongs to the
    // step in front of them and choosing another one starts over.
    const [opened, setOpened] = useState<ReadonlySet<StepGroupId>>(() => new Set())

    return (
        <div className="flex flex-col gap-4 p-4">
            <div className="space-y-1">
                <h2 className={heading.named ? 'text-sm font-semibold' : 'font-mono text-sm font-semibold'}>
                    {heading.title}
                </h2>
                <p className="flex items-center gap-2">
                    {heading.code !== null && (
                        <span className="font-mono text-xs text-muted-foreground">{heading.code}</span>
                    )}
                    <span className="font-mono text-xs">{blockOf(document, step) ?? 'no block'}</span>
                    {block !== null && <KindChip kind={block.kind} />}
                </p>
                {block !== null && <p className="text-xs text-muted-foreground">{block.summary}</p>}
            </div>

            {disabled !== undefined && (
                <p className="rounded-md border border-warning/40 p-2 text-xs text-warning">{disabled}</p>
            )}

            <Section title="Config">
                {blockProblem !== null ? (
                    <p className="text-xs text-critical">{blockProblem.detail}</p>
                ) : block === null ? (
                    <p className="text-xs text-muted-foreground">Reading this block's schema.</p>
                ) : (
                    <SchemaForm
                        // Choosing another step is another form, not the same one with new
                        // values in it, so every control starts from what that step carries.
                        key={step}
                        fields={fields}
                        values={config}
                        problems={problems}
                        disabled={disabled}
                        fold
                        onChange={(name, value) => {
                            const next = { ...config }
                            if (value === undefined) delete next[name]
                            else next[name] = value
                            onConfig(next)
                        }}
                    />
                )}
            </Section>

            <div className="flex flex-col">
                {groups.map((group) => {
                    const wrong = groupProblems(group, group.id === 'retry' ? retryProblems : keyProblems)
                    const refused = Object.keys(wrong).length > 0
                    return (
                        <Group
                            key={group.id}
                            group={group}
                            open={refused || opened.has(group.id)}
                            onToggle={
                                refused
                                    ? null
                                    : () => {
                                          setOpened(toggled(opened, group.id))
                                      }
                            }
                        >
                            {group.id === 'depends_on' ? (
                                <Prerequisites
                                    prerequisites={prerequisites}
                                    offered={offered}
                                    disabled={disabled}
                                    onDependsOn={onDependsOn}
                                />
                            ) : group.id === 'retry' ? (
                                <SchemaForm
                                    key={`retry-${step}`}
                                    fields={group.fields}
                                    values={retry}
                                    problems={retryProblems}
                                    disabled={disabled}
                                    onChange={(name, value) => {
                                        changeDocument((current) => withRetryKey(current, step, name, value))
                                    }}
                                />
                            ) : (
                                <SchemaForm
                                    key={`${group.id}-${step}`}
                                    fields={group.fields}
                                    values={keys}
                                    problems={wrong}
                                    disabled={disabled}
                                    onChange={(name, value) => {
                                        changeDocument((current) => withStepKey(current, step, name, value))
                                    }}
                                />
                            )}
                        </Group>
                    )
                })}
            </div>

            <div className="space-y-1.5">
                <Label htmlFor="step-display-name">Name</Label>
                <Input
                    id="step-display-name"
                    value={named}
                    disabled={disabled !== undefined}
                    onChange={(event) => {
                        setNamed(event.target.value)
                        onName(event.target.value)
                    }}
                    placeholder="What to call this step on screen"
                />
                <p className="text-xs text-faint">
                    Display only. Every reference to this step is by its key, {step}.
                </p>
            </div>

            {refusals.length > 0 && (
                <div className="space-y-1 rounded-md border border-critical/40 p-2" role="alert">
                    <p className="text-xs font-medium text-critical">This step will be refused at apply.</p>
                    <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                        {refusals.map(([name, message]) => (
                            <li key={name}>{message}</li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    )
}

/** The open set with one group turned over. */
function toggled(open: ReadonlySet<StepGroupId>, id: StepGroupId): ReadonlySet<StepGroupId> {
    const next = new Set(open)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
}

/**
 * One group: the row that says where it stands, and its form under it while it is open.
 *
 * A group nothing may shut -- one holding a refusal -- has no button, because a control that
 * cannot carry out what it offers is chrome. Its chevron still says which way the group is.
 */
function Group({
    group,
    open,
    onToggle,
    children,
}: {
    group: StepGroup
    open: boolean
    /** How to turn the group over, or nothing where it may not be shut. */
    onToggle: (() => void) | null
    children: ReactNode
}) {
    const row = (
        <>
            <ChevronRight className={cn('size-3 shrink-0 self-center', open && 'rotate-90')} aria-hidden />
            <span className="shrink-0 text-sm font-medium">{group.title}</span>
            {!open && <Summary parts={group.summary} chips={group.chips} />}
        </>
    )
    return (
        <div>
            {onToggle === null ? (
                <div className="flex w-full items-baseline gap-2 py-1.5">{row}</div>
            ) : (
                <button
                    type="button"
                    aria-expanded={open}
                    onClick={onToggle}
                    className="row-hover flex w-full items-baseline gap-2 rounded-sm py-1.5 text-left"
                >
                    {row}
                </button>
            )}
            {open && <div className="my-1 ml-5 border-l border-primary py-1 pl-3">{children}</div>}
        </div>
    )
}

/** What a shut group would run: the document's own values in body ink, the defaults in muted. */
function Summary({ parts, chips }: { parts: SummaryPart[]; chips: boolean }) {
    if (chips) {
        return (
            <span className="ml-auto flex flex-wrap items-center justify-end gap-1">
                {parts.map((part) => (
                    <span
                        key={part.text}
                        className="rounded-sm border border-border bg-secondary px-1.5 py-0.5 font-mono text-xs"
                    >
                        {part.text}
                    </span>
                ))}
            </span>
        )
    }
    return (
        <span className="ml-auto min-w-0 text-right font-mono text-xs break-words">
            {parts.map((part, index) => (
                <Fragment key={part.text}>
                    {index > 0 && <span className="text-faint"> · </span>}
                    <span className={part.set ? 'text-foreground' : 'text-muted-foreground'}>
                        {part.text}
                    </span>
                </Fragment>
            ))}
        </span>
    )
}

/** The steps this one waits for, and the ones it could be told to wait for. */
function Prerequisites({
    prerequisites,
    offered,
    disabled,
    onDependsOn,
}: {
    prerequisites: string[]
    /** Every other step in the document this one does not already wait for. */
    offered: string[]
    disabled?: string
    onDependsOn: (names: string[]) => void
}) {
    return (
        <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-1.5">
                {prerequisites.length === 0 && (
                    <span className="text-xs text-muted-foreground">nothing; this step is a root</span>
                )}
                {prerequisites.map((name) => (
                    <span
                        key={name}
                        className="flex items-center gap-1 rounded-sm border border-border bg-secondary px-1.5 py-0.5 text-xs"
                    >
                        {name}
                        <Button
                            variant="ghost"
                            size="icon-xs"
                            aria-label={`Stop waiting for ${name}`}
                            disabled={disabled !== undefined}
                            onClick={() => {
                                onDependsOn(prerequisites.filter((one) => one !== name))
                            }}
                        >
                            <X className="size-3" aria-hidden />
                        </Button>
                    </span>
                ))}
            </div>
            {offered.length > 0 && (
                <Select
                    value=""
                    disabled={disabled !== undefined}
                    onValueChange={(chosen) => {
                        const name = String(chosen)
                        if (name !== '') onDependsOn([...prerequisites, name])
                    }}
                >
                    <SelectTrigger size="sm" className="w-full" aria-label={ADD_DEPENDENCY_LABEL}>
                        <SelectValue placeholder={ADD_DEPENDENCY_LABEL} />
                    </SelectTrigger>
                    <SelectContent>
                        {offered.map((name) => (
                            <SelectItem key={name} value={name}>
                                {name}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            )}
        </div>
    )
}
