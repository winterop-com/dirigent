import { X } from 'lucide-react'
import { useMemo, useState } from 'react'

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
    retryFields,
    retryValues,
    stepFields,
    stepKeyValues,
    withRetryKey,
    withStepKey,
} from '@/lib/step-keys'

export const ADD_DEPENDENCY_LABEL = 'Add a prerequisite'

/**
 * The step in front of somebody: what it runs, what it waits for, and the config it takes.
 *
 * THE FORM IS THE BLOCK'S OWN SCHEMA. `GET /blocks/{id}` publishes a closed schema per block and
 * `lib/schema-form` turns it into fields, so a config key this instance does not take has no box
 * to be typed into and a value outside the schema is refused under the field it was typed in.
 *
 * THE CONFIG OPENS ON WHAT THE STEP NEEDS. A block may publish twenty keys and take two, so the
 * form draws what the schema requires and what this step already sets, and offers the rest behind
 * one link.
 *
 * THE REFUSAL HERE IS THE CLIENT'S HALF. What this can check is one field against one schema.
 * Whether the document as a whole applies -- its graph, its references, the blocks it names --
 * is the server's, and Validate and Apply are where it is asked.
 *
 * THE STEP SECTION IS THE ENGINE'S HALF. `for_each`, `rule`, `items`, `retry` and the timings are
 * what the engine does with the block, so they are read as a form the same way a config is, from
 * the shapes in `lib/step-keys`. A key equal to the definition's default is removed rather than
 * written, and the control still shows that default.
 *
 * THE STEP SECTION WRITES THROUGH THE DOCUMENT STORE, because the members it edits have no prop
 * of their own the way `config`, `depends_on` and `name` do; `changeDocument` is the same writer
 * those three reach in the end, and it refuses an edit while the source pane does not parse.
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

            {disabled !== undefined && (
                <p className="rounded-md border border-warning/40 p-2 text-xs text-warning">{disabled}</p>
            )}

            <Section title="Waits for">
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
            </Section>

            <Section title="Step">
                <SchemaForm
                    key={`step-${step}`}
                    fields={stepFields}
                    values={keys}
                    problems={keyProblems}
                    disabled={disabled}
                    onChange={(name, value) => {
                        changeDocument((current) => withStepKey(current, step, name, value))
                    }}
                />
                <div className="space-y-4 border-l border-border pl-3">
                    <p className="font-mono text-sm font-medium">retry</p>
                    <SchemaForm
                        key={`retry-${step}`}
                        fields={retryFields}
                        values={retry}
                        problems={retryProblems}
                        disabled={disabled}
                        onChange={(name, value) => {
                            changeDocument((current) => withRetryKey(current, step, name, value))
                        }}
                    />
                </div>
            </Section>

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
