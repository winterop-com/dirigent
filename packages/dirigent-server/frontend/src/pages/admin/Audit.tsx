import { useCallback, useEffect, useState } from 'react'

import { ApiChip } from '@/components/ApiChip'
import { AdminOnly } from '@/components/admin/AdminOnly'
import { InlineCode } from '@winterop-com/sokkel-ui/InlineCode'
import { PageHeader } from '@/components/ds/PageHeader'
import { SearchField } from '@winterop-com/sokkel-ui/SearchField'
import { Instant } from '@/components/Instant'
import { Choice } from '@/components/list/Choice'
import { ListTable, type Column } from '@/components/list/ListTable'
import { PageState } from '@/components/PageState'
import { usePaged } from '@/hooks/use-paged'
import {
    actorOf,
    AUDIT_ACTIONS,
    AUDIT_SUBJECTS,
    AUDIT_WINDOWS,
    emptyNote,
    EVERY_CHANGE,
    readAudit,
    subjectOf,
    type AuditEntryOut,
    type AuditFilters,
} from '@/lib/audit'
import { ICONS } from '@/lib/icons'
import { SEARCH_PLACEHOLDER, SEARCH_WORDS } from '@/lib/design-system'
import { LABELS } from '@/lib/labels'
import { ADMIN_GROUP, registerActions } from '@/lib/palette'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'

/** How long a typed code is left alone after a keystroke before it becomes a request. */
const TYPING_MS = 300

const entryId = (entry: AuditEntryOut) => String(entry.id)

/**
 * Every administrative change, newest first: who made it, what it did, to which subject, and the
 * fields an update changed.
 *
 * WHAT IS FILTERED HERE IS WHAT THE SERVER FILTERS. `GET /audit` narrows by subject kind, action,
 * actor, subject code and a window, so the bar offers those and nothing narrows only the rows
 * that happen to have been read.
 *
 * NO VALUE IS EVER ON SCREEN, because none is on the wire: an update names its fields.
 */
export function AdminAudit() {
    return (
        <AdminOnly>
            <Audit />
        </AdminOnly>
    )
}

function Audit() {
    const [filters, setFilters] = useState<AuditFilters>(EVERY_CHANGE)
    const [actor, setActor] = useState('')
    const [subject, setSubject] = useState('')

    // A typed code is filtered on the server, and a keystroke is not a question yet.
    useEffect(() => {
        const timer = setTimeout(() => {
            setFilters((current) =>
                current.actor === actor && current.subject === subject
                    ? current
                    : { ...current, actor, subject },
            )
        }, TYPING_MS)
        return () => {
            clearTimeout(timer)
        }
    }, [actor, subject])

    const read = useCallback((after: string | null) => readAudit(filters, after), [filters])
    const { state, more, reload } = usePaged(read, entryId)

    useEffect(() => {
        setScreenStatus({ note: null, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [])

    useEffect(() => {
        return registerActions([
            {
                id: 'audit:clear',
                title: LABELS.audit.filter_clear,
                group: ADMIN_GROUP,
                screen: true,
                icon: ICONS.clear_filter,
                keywords: ['reset', 'all'],
                run: () => {
                    setActor('')
                    setSubject('')
                    setFilters(EVERY_CHANGE)
                },
            },
            {
                id: 'audit:reload',
                title: LABELS.audit.reload_action,
                group: ADMIN_GROUP,
                screen: true,
                icon: ICONS.refresh,
                keywords: ['refresh', 'reload'],
                run: reload,
            },
        ])
    }, [reload])

    const choose = (key: keyof AuditFilters) => (value: string) => {
        setFilters((current) => ({ ...current, [key]: value }))
    }

    return (
        <>
            <PageHeader title={LABELS.screen.audit.name} lead={<ApiChip tag="audit" />} />

            <div className="mb-4 flex flex-wrap items-center gap-2">
                <SearchField
                    placeholder={SEARCH_PLACEHOLDER}
                    words={SEARCH_WORDS}
                    className="w-64"
                    value={actor}
                    label={LABELS.audit.filter_actor}
                    onChange={setActor}
                />
                <SearchField
                    placeholder={SEARCH_PLACEHOLDER}
                    words={SEARCH_WORDS}
                    className="w-64"
                    value={subject}
                    label={LABELS.audit.filter_subject}
                    onChange={setSubject}
                    shortcut={false}
                />
                <Choice
                    label={LABELS.word.subject}
                    value={filters.subject_kind}
                    options={AUDIT_SUBJECTS.map((kind) => ({
                        value: kind,
                        label: LABELS.audit.subjects[kind],
                    }))}
                    anything={LABELS.audit.any_kind}
                    onChange={choose('subject_kind')}
                />
                <Choice
                    label={LABELS.audit.action}
                    value={filters.action}
                    options={AUDIT_ACTIONS.map((action) => ({
                        value: action,
                        label: LABELS.audit.actions[action],
                    }))}
                    anything={LABELS.audit.any_action}
                    onChange={choose('action')}
                />
                <Choice
                    label={LABELS.word.window.label}
                    value={filters.window}
                    options={AUDIT_WINDOWS.map((window) => ({
                        value: window,
                        label: LABELS.runs.window_option(window),
                    }))}
                    anything={LABELS.runs.any_window}
                    onChange={choose('window')}
                />
            </div>

            <PageState
                loading={!state.read}
                problem={state.problem}
                empty={state.rows.length === 0}
                emptyMessage={emptyNote(filters)}
            >
                <ListTable
                    columns={COLUMNS}
                    rows={state.rows}
                    rowKey={entryId}
                    reading={state.reading}
                    next={state.next}
                    onMore={more}
                    noun={LABELS.audit.count}
                />
            </PageState>
        </>
    )
}

const COLUMNS: Column<AuditEntryOut>[] = [
    {
        id: 'when',
        header: LABELS.audit.when,
        className: 'text-xs',
        cell: (entry) => <Instant at={entry.created_at} className="text-muted-foreground" />,
    },
    {
        id: 'actor',
        header: LABELS.audit.actor,
        kind: 'prose',
        cell: (entry) => {
            const { who, token } = actorOf(entry)
            return (
                <span className="block min-w-0 truncate text-sm" title={entry.actor_label}>
                    {who}
                    {token !== null && (
                        <span
                            className="text-faint"
                            title={
                                entry.actor_token_prefix === null
                                    ? undefined
                                    : LABELS.audit.token_prefix(entry.actor_token_prefix)
                            }
                        >
                            {' · '}
                            {LABELS.audit.through_token(token)}
                        </span>
                    )}
                </span>
            )
        },
    },
    {
        id: 'action',
        header: LABELS.audit.action,
        className: 'text-sm',
        cell: (entry) => <span>{LABELS.audit.actions[entry.action]}</span>,
    },
    {
        id: 'subject',
        header: LABELS.word.subject,
        kind: 'title',
        cell: (entry) => {
            const addressed = subjectOf(entry)
            return (
                <span className="flex min-w-0 items-baseline gap-2">
                    <span className="shrink-0 text-xs text-muted-foreground">
                        {LABELS.audit.subjects[entry.subject_kind]}
                    </span>
                    {addressed !== null && <InlineCode value={addressed} tone="neutral" bare size="xs" />}
                </span>
            )
        },
    },
    {
        id: 'fields',
        header: LABELS.audit.fields,
        kind: 'prose',
        cell: (entry) =>
            entry.fields.length === 0 ? null : (
                <span className="flex min-w-0 flex-wrap gap-x-2">
                    {entry.fields.map((field) => (
                        <InlineCode key={field} value={field} tone="muted" bare size="xs" />
                    ))}
                </span>
            ),
    },
]
