import { useState } from 'react'

import { SecretField } from '@/components/connections/SecretField'
import { Mark } from '@/components/Mark'
import { Refusable } from '@/components/Refusable'
import { Refusal } from '@/components/Refusal'
import { SchemaForm } from '@/components/pipeline/SchemaForm'
import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useMayWrite } from '@/hooks/use-may-write'
import { useStore } from '@/hooks/use-store'
import { type JsonMap, type Problem } from '@/lib/api'
import {
    createConnection,
    mintedConfig,
    settingFields,
    type ConnectionOut,
    type SurfaceEntry,
} from '@/lib/connections'
import { kindGlyph } from '@/lib/glyphs'
import { kindMarks } from '@/lib/marks'
import { refusalOf } from '@/lib/refusal'
import { firstShut } from '@/lib/roles'
import { maySubmit, validateFields, withUnreadable } from '@/lib/schema-form'

/**
 * Mint one connection of a kind this instance has installed.
 *
 * THE KIND IS CHOSEN FROM THE CATALOG, not typed. `GET /blocks` answers every contributed
 * surface, connection kinds among them, and that list is the whole of what this instance can
 * seal a credential for -- so the kind is a select over it, and a kind nothing installed is not
 * a thing this dialog can ask for.
 *
 * THE CONFIG IS THE KIND'S SCHEMA, the same form the panel builds beside the listing: the kind
 * is chosen first, so what a control is for is known before one is drawn. Choosing another kind
 * is choosing another config, and what was typed for the last one goes with it.
 *
 * A SECRET IS NOT A SCHEMA FIELD HERE. The schema says a secret is a string, and rendering it as
 * one would put a credential in a text box. Every field the kind declares secret is taken out of
 * the generated form and drawn below it as a write-only password box, and one left empty mints a
 * connection with no credential for it rather than one with an empty password.
 *
 * A REFUSAL IS THE SERVER'S. A code already taken, a config the kind's own model does not
 * accept: each arrives as a problem document and is rendered as one, because the server's
 * sentence names the field and this dialog could only paraphrase it.
 */
export function NewConnection({
    open,
    kinds,
    startKind = '',
    onOpenChange,
    onCreated,
}: {
    open: boolean
    /** What this instance has installed, from the catalog the screen read. */
    kinds: SurfaceEntry[]
    /** The kind the dialog opens on, for a link that already knows which one is wanted. */
    startKind?: string
    onOpenChange: (open: boolean) => void
    /** Called with what was minted, so the listing behind reads itself again. */
    onCreated: (row: ConnectionOut) => void
}) {
    const [code, setCode] = useState('')
    const [named, setNamed] = useState('')
    const [kind, setKind] = useState(startKind)
    const [description, setDescription] = useState('')
    const [values, setValues] = useState<JsonMap>({})
    const [secrets, setSecrets] = useState<Record<string, string>>({})
    const [touched, setTouched] = useState<ReadonlySet<string>>(() => new Set())
    const [unreadable, setUnreadable] = useState<ReadonlySet<string>>(() => new Set())
    const [asked, setAsked] = useState(false)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)

    const chosen = kinds.find((one) => one.id === kind) ?? null
    const fields = settingFields(chosen?.config_schema ?? null, chosen?.secret_fields ?? [])
    const problems = validateFields(fields, values)
    // A required field is not a complaint until somebody has been there or asked to create.
    const stated = asked ? undefined : touched
    const write = useMayWrite('admin')
    const shut = firstShut(write.why, unready(code, kind, problems, unreadable))

    const send = () => {
        setAsked(true)
        setBusy(true)
        setProblem(null)
        void createConnection({
            code: code.trim(),
            name: given(named),
            kind,
            description: given(description),
            config: mintedConfig(values, secrets),
        })
            .then(
                (row) => {
                    onCreated(row)
                    setCode('')
                    setNamed('')
                    setDescription('')
                    setKind(startKind)
                    setValues({})
                    setSecrets({})
                    setTouched(new Set())
                    setUnreadable(new Set())
                    setAsked(false)
                    onOpenChange(false)
                },
                (error: unknown) => {
                    setProblem(refusalOf(error))
                },
            )
            .finally(() => {
                setBusy(false)
            })
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-xl" showCloseButton={false}>
                <DialogHeader>
                    <DialogTitle>New connection</DialogTitle>
                    <DialogDescription>
                        Secret fields are sealed on the way in and never read back out.
                    </DialogDescription>
                </DialogHeader>

                <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-2">
                        <Label htmlFor="connection-code">Code</Label>
                        <Input
                            id="connection-code"
                            className="font-mono"
                            value={code}
                            onChange={(event) => {
                                setCode(event.target.value)
                            }}
                            placeholder="postman-echo"
                        />
                    </div>
                    <div className="space-y-2">
                        <Label htmlFor="connection-kind">Kind</Label>
                        <Select
                            value={kind}
                            onValueChange={(picked) => {
                                setKind(String(picked))
                                // A config belongs to its kind, so another kind starts its own form empty.
                                setValues({})
                                setSecrets({})
                                setTouched(new Set())
                                setUnreadable(new Set())
                                setAsked(false)
                            }}
                        >
                            <SelectTrigger id="connection-kind" className="w-full font-mono">
                                {/* The chosen row keeps its mark in the closed box, so the row
                                    somebody picked is the row they are looking at. Nothing
                                    chosen draws the placeholder, which names no kind and so
                                    wears no mark. */}
                                <SelectValue placeholder="Choose a kind">
                                    {chosen === null ? undefined : () => <KindRow kind={chosen.id} />}
                                </SelectValue>
                            </SelectTrigger>
                            <SelectContent>
                                {kinds.map((one) => (
                                    <SelectItem key={one.id} value={one.id} className="font-mono">
                                        <KindRow kind={one.id} />
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                </div>

                <div className="space-y-2">
                    <Label htmlFor="connection-name-new">Name</Label>
                    <Input
                        id="connection-name-new"
                        value={named}
                        onChange={(event) => {
                            setNamed(event.target.value)
                        }}
                        placeholder="What to call it on screen. Optional; nothing references it."
                    />
                </div>

                <div className="space-y-2">
                    <Label htmlFor="connection-description-new">Description</Label>
                    <Textarea
                        id="connection-description-new"
                        className="h-24"
                        value={description}
                        onChange={(event) => {
                            setDescription(event.target.value)
                        }}
                        placeholder="What this credential is for. Markdown is rendered."
                    />
                </div>

                {chosen !== null && (
                    <div className="space-y-3">
                        <p className="text-xs font-semibold tracking-wide text-faint uppercase">Settings</p>
                        <div className="max-h-[40vh] space-y-3 overflow-y-auto pr-1">
                            <SchemaForm
                                fields={fields}
                                values={values}
                                problems={problems}
                                stated={stated}
                                onChange={(name, value) => {
                                    setValues((current) => {
                                        const next = { ...current }
                                        if (value === undefined) delete next[name]
                                        else next[name] = value
                                        return next
                                    })
                                }}
                                onTouch={(name) => {
                                    setTouched((current) =>
                                        current.has(name) ? current : new Set(current).add(name),
                                    )
                                }}
                                onUnreadable={(name, message) => {
                                    setUnreadable((current) => withUnreadable(current, name, message))
                                }}
                            />
                            {chosen.secret_fields.map((name) => (
                                <SecretField
                                    key={name}
                                    id={`new-secret-${name}`}
                                    name={name}
                                    stored={false}
                                    value={secrets[name] ?? ''}
                                    onChange={(typed) => {
                                        setSecrets((current) => ({ ...current, [name]: typed }))
                                    }}
                                />
                            ))}
                        </div>
                    </div>
                )}

                {problem !== null && <Refusal problem={problem} />}

                <DialogFooter>
                    <DialogClose render={<Button variant="ghost" />}>Close</DialogClose>
                    <Refusable why={shut}>
                        <Button disabled={busy || shut !== undefined} title={shut} onClick={send}>
                            {busy ? 'Creating' : 'Create'}
                        </Button>
                    </Refusable>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

/**
 * One kind as the dialog offers it: the mark, and the code it is chosen by.
 *
 * The kind is written as well as marked, because a mark cannot be typed and the code is what a
 * document names the kind by.
 */
function KindRow({ kind }: { kind: string }) {
    const marks = useStore(kindMarks)
    return (
        <span className="flex items-center gap-2">
            <Mark glyph={kindGlyph(kind, marks)} />
            {kind}
        </span>
    )
}

/** Why Create is shut, which is what the button carries as its title. */
function unready(
    code: string,
    kind: string,
    problems: Record<string, string>,
    unreadable: ReadonlySet<string>,
): string | undefined {
    if (code.trim() === '') return 'A connection is addressed by its code, and this one has none.'
    if (kind === '') return 'No kind is chosen, and a connection is a credential of one kind.'
    if (unreadable.size > 0) return 'A setting below holds text that is not a value.'
    if (!maySubmit(problems, unreadable)) return 'A setting below is not what its kind accepts.'
    return undefined
}

/** A box that was emptied is that member cleared, not a member set to "". */
function given(text: string): string | null {
    const trimmed = text.trim()
    return trimmed === '' ? null : trimmed
}
