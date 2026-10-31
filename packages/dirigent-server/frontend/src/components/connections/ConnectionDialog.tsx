import { useCallback, useMemo, useRef, useState } from 'react'

import { Description } from '@/components/Description'
import { Instant } from '@/components/Instant'
import { Code } from '@/components/ds/Code'
import { Mark } from '@/components/Mark'
import { Refusable } from '@/components/Refusable'
import { ConnectionForm } from '@/components/connections/ConnectionForm'
import { HealthSaid } from '@/components/connections/Health'
import { ConfirmDialog } from '@/components/ds/ConfirmDialog'
import { DialogShell } from '@/components/ds/DialogShell'
import { EntityHeading } from '@/components/ds/EntityHeading'
import { Fact, FactList } from '@/components/ds/FactList'
import { TextLink } from '@/components/ds/TextLink'
import { Button } from '@/components/ui/button'
import { useConnectionEdit } from '@/hooks/use-connection-edit'
import { useMayWrite } from '@/hooks/use-may-write'
import { useRead } from '@/hooks/use-read'
import { useStore } from '@/hooks/use-store'
import { type JsonMap, type Problem } from '@/lib/api'
import {
    deleteConnection,
    healthOf,
    isUsed,
    readConnection,
    settingFacts,
    usersSaid,
    type ConnectionOut,
    type ConnectionUsers,
} from '@/lib/connections'
import { separatelyUpdated } from '@/lib/format'
import { kindGlyph } from '@/lib/glyphs'
import { ICONS } from '@/lib/icons'
import { counted, LABELS } from '@/lib/labels'
import { kindMarks } from '@/lib/marks'
import { refusalOf } from '@/lib/refusal'
import { cn } from '@/lib/utils'

/**
 * One connection, shown first and edited second, in one dialog over the listing.
 *
 * Pressing Edit does not raise anything: the same surface turns into its form, and Cancel, Escape
 * and a saved edit turn it back. The screen keys this on the connection's code, so another
 * connection is another form rather than a half-typed edit carried onto it.
 */
export function ConnectionDialog({
    connection,
    schema,
    checking,
    onCheck,
    onSaved,
    onDeleted,
    onClose,
}: {
    connection: ConnectionOut
    /** The kind's published config schema, or nothing when the catalog does not carry one. */
    schema: JsonMap | null
    checking: boolean
    onCheck: (row: ConnectionOut) => void
    /** Called with what the server answered, so the row behind updates without a re-read. */
    onSaved: (row: ConnectionOut) => void
    onDeleted: () => void
    onClose: () => void
}) {
    const marks = useStore(kindMarks)
    const write = useMayWrite('admin')
    const form = useConnectionEdit(connection, schema)
    const [editing, setEditing] = useState(false)
    const [deleting, setDeleting] = useState(false)
    const [removing, setRemoving] = useState(false)
    const [refused, setRefused] = useState<Problem | null>(null)
    const editButton = useRef<HTMLButtonElement>(null)

    // Read as the dialog opens and again as the question does. A read that fails leaves the server
    // to say.
    const asking = useRead(useCallback(() => readConnection(connection.code), [connection.code]))
    const { again: askAgain } = asking
    const usedBy = asking.value?.used_by ?? null
    const used = usedBy !== null && isUsed(usedBy)

    const heading = (
        <EntityHeading
            variant="dialog"
            thing={connection}
            lead={editing ? LABELS.action.edit : undefined}
            glyph={<Mark glyph={kindGlyph(connection.kind, marks)} />}
            chips={<Code value={connection.kind} />}
        />
    )

    const remove = () => {
        setRemoving(true)
        setRefused(null)
        void deleteConnection(connection.code)
            .then(onDeleted, (error: unknown) => {
                setRefused(refusalOf(error))
            })
            .finally(() => {
                setRemoving(false)
            })
    }

    return (
        <>
            {editing ? (
                <DialogShell
                    open
                    width="lg"
                    keepOnOutsidePress
                    onOpenChange={(next) => {
                        if (!next) setEditing(false)
                    }}
                    title={heading}
                    footer={
                        <span className="text-xs text-muted-foreground">
                            {LABELS.connections.save_checks}
                        </span>
                    }
                    confirm={{
                        label: LABELS.action.save.verb,
                        busy: form.busy,
                        busyLabel: LABELS.action.save.busy,
                        why: form.shut,
                        onConfirm: () => {
                            form.save((row) => {
                                setEditing(false)
                                if (row === null) return
                                onSaved(row)
                                onCheck(row)
                            })
                        },
                    }}
                >
                    <ConnectionForm connection={connection} form={form} />
                </DialogShell>
            ) : (
                <DialogShell
                    open
                    width="lg"
                    onOpenChange={(next) => {
                        if (!next) onClose()
                    }}
                    initialFocus={write.may ? editButton : undefined}
                    title={heading}
                    footer={
                        <Refusable why={write.why}>
                            <Button
                                variant="outline"
                                size="sm"
                                className="destructive-action"
                                disabled={!write.may}
                                title={write.why}
                                onClick={() => {
                                    setRefused(null)
                                    askAgain()
                                    setDeleting(true)
                                }}
                            >
                                <ICONS.delete aria-hidden />
                                {LABELS.action.delete.verb}
                            </Button>
                        </Refusable>
                    }
                    verbs={
                        <>
                            <Refusable why={write.why}>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    disabled={checking || !write.may}
                                    title={write.why}
                                    onClick={() => {
                                        onCheck(connection)
                                    }}
                                >
                                    <ICONS.recheck className={cn(checking && 'animate-pulse')} aria-hidden />
                                    {LABELS.action.check}
                                </Button>
                            </Refusable>
                            <Refusable why={write.why}>
                                <Button
                                    ref={editButton}
                                    size="sm"
                                    disabled={!write.may}
                                    title={write.why}
                                    onClick={() => {
                                        form.reset()
                                        setEditing(true)
                                    }}
                                >
                                    <ICONS.edit aria-hidden />
                                    {LABELS.action.edit}
                                </Button>
                            </Refusable>
                        </>
                    }
                >
                    <ConnectionFacts connection={connection} schema={schema} users={usedBy} />
                </DialogShell>
            )}

            <ConfirmDialog
                open={deleting}
                onOpenChange={setDeleting}
                ask={LABELS.connections.delete_ask}
                code={connection.code}
                note={used ? LABELS.connections.used_by(usersSaid(usedBy)) : undefined}
                why={used ? LABELS.connections.in_use : asking.reading ? LABELS.shell.reading : undefined}
                verb={LABELS.action.delete.verb}
                busy={removing}
                busyVerb={LABELS.action.delete.busy}
                problem={refused}
                onConfirm={remove}
            />
        </>
    )
}

/** What the dialog reads first: what it says about itself, how it is, and what it holds. */
function ConnectionFacts({
    connection,
    schema,
    users,
}: {
    connection: ConnectionOut
    schema: JsonMap | null
    /** What uses it, or nothing until that has been read. */
    users: ConnectionUsers | null
}) {
    const view = healthOf(connection)
    const facts = useMemo(() => settingFacts(connection, schema), [connection, schema])
    return (
        <>
            <Description text={connection.description} />
            <FactList>
                <Fact term={LABELS.word.health}>
                    <span className="flex min-w-0 flex-col gap-1">
                        <span className="flex items-center gap-2">
                            <HealthSaid view={view} />
                            {view.checkedAt !== null && (
                                <span className="text-xs text-muted-foreground">
                                    {LABELS.word.checked.term} <Instant at={view.checkedAt} />
                                </span>
                            )}
                        </span>
                        {view.detail !== null && (
                            <span className="text-xs break-words text-muted-foreground">{view.detail}</span>
                        )}
                    </span>
                </Fact>
                {facts.map((fact) => (
                    <Fact key={fact.name} term={fact.name} termMono mono={fact.value !== null}>
                        {fact.value === null ? (
                            <span className="text-faint">{LABELS.connections.secret_not_set}</span>
                        ) : (
                            <span className="text-xs break-all">{fact.value}</span>
                        )}
                    </Fact>
                ))}
                {users !== null && isUsed(users) && (
                    <Fact term={LABELS.connections.used_by_term}>
                        <UsedBy users={users} />
                    </Fact>
                )}
                <Fact term={LABELS.word.created.label}>
                    <Instant at={connection.created_at} />
                </Fact>
                {separatelyUpdated(connection.created_at, connection.updated_at) && (
                    <Fact term={LABELS.word.updated.label}>
                        <Instant at={connection.updated_at} />
                    </Fact>
                )}
            </FactList>
        </>
    )
}

/** One line per thing using the credential: its code, a link where it has a screen, and what it is. */
function UsedBy({ users }: { users: ConnectionUsers }) {
    const said = LABELS.connections.users
    return (
        <ul className="flex min-w-0 flex-col gap-1 text-xs">
            {users.pipelines.map((one) => (
                <li key={one.pipeline} className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                    <TextLink variant="data" to={`/pipelines/${encodeURIComponent(one.pipeline)}`}>
                        {one.pipeline}
                    </TextLink>
                    <span className="text-muted-foreground">{counted(1, said.pipeline)}</span>
                    <span className="min-w-0 font-mono break-words text-muted-foreground">
                        {[...one.steps, ...one.sources].join(', ')}
                    </span>
                </li>
            ))}
            {users.alert_rules.map((code) => (
                <li key={code} className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                    <TextLink variant="data" to="/admin/alerting">
                        {code}
                    </TextLink>
                    <span className="text-muted-foreground">{counted(1, said.alert_rule)}</span>
                </li>
            ))}
            {users.storage_schemes.map((scheme) => (
                <li key={scheme} className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                    <span className="font-mono">{scheme}</span>
                    <span className="text-muted-foreground">{counted(1, said.storage_scheme)}</span>
                </li>
            ))}
        </ul>
    )
}
