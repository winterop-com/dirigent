import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { Surface } from '@winterop-com/sokkel-ui/Section'
import { SchemeChoice } from '@winterop-com/sokkel-ui/SchemeChoice'
import { SettingsDialog as LibrarySettingsDialog } from '@winterop-com/sokkel-ui/SettingsDialog'
import { ThemeCards } from '@winterop-com/sokkel-ui/ThemeCards'
import { Refusal } from '@/components/Refusal'
import { FIELD_WORDS, LINK_WORDS, SCHEME_WORDS, SETTINGS_WORDS, THEME_CARDS_WORDS } from '@/lib/design-system'
import { Segmented } from '@winterop-com/sokkel-ui/Segmented'
import { Dot } from '@winterop-com/sokkel-ui/Dot'
import { STATUS_CSS } from '@winterop-com/sokkel-ui/lib/status'
import { useAppearance } from '@winterop-com/sokkel-ui/hooks/use-appearance'
import { Chip } from '@winterop-com/sokkel-ui/Chip'
import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import { Kbd, KbdGroup } from '@winterop-com/sokkel-ui/primitives/kbd'
import { useRead, type Reading } from '@/hooks/use-read'
import { useStore } from '@winterop-com/sokkel-ui/hooks/use-store'
import { type Problem } from '@/lib/api'
import { authStore, signOut } from '@/lib/auth'
import { MIN_PASSWORD_LENGTH } from '@/lib/users'
import { API_DOCS_URL, DOCS_URL } from '@/lib/docs'
import { formatInstant, formatRelative } from '@/lib/format'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'
import { LOGIN_PATH } from '@/lib/nav'
import { changePassword, formProblem, NO_PASSWORD, refusalOf, type PasswordForm } from '@/lib/password'
import { followTails, highlightLine, setFollowTails, setHighlightLine } from '@/lib/preferences'
import { checkServer, SERVER_STATES, serverStatus } from '@/lib/server-status'
import {
    FIRST_CATEGORY,
    settingsGroups,
    settingsRows,
    type RowControl,
    type SettingsRow,
} from '@/lib/settings'
import { applePlatform, shortcuts } from '@/lib/shortcuts'
import { readSystemInfo, type SystemInfo } from '@/lib/system'
import { APPEARANCE_DEFAULTS, APPEARANCE_OFFER, PALETTES } from '@/lib/theme'
import { chooseTimes, TIMES_LABELS, TIMES_MODES, timesMode } from '@/lib/times'
import { cn } from '@/lib/utils'
import { TextField } from '@winterop-com/sokkel-ui/TextField'
import { TextLink } from '@winterop-com/sokkel-ui/TextLink'

export const SETTINGS_TITLE = LABELS.settings.title

/**
 * sokkel-ui's settings dialog over the rows `lib/settings` holds, each with the control this file
 * puts on it by the row's id. Every control writes a store the screens read: the Theme rows write
 * sokkel-ui's appearance, Timezone writes `lib/times`, the log and editor rows `lib/preferences`.
 */
export function SettingsDialog({
    open,
    startAt = null,
    onOpenChange,
}: {
    open: boolean
    /** The category it opens on, where the thing that opened it is about one. */
    startAt?: string | null
    onOpenChange: (open: boolean) => void
}) {
    const apple = applePlatform(navigator.userAgent)
    const [search, setSearch] = useState('')
    const [active, setActive] = useState(startAt ?? FIRST_CATEGORY)
    const [changing, setChanging] = useState(false)
    const info = useRead(useCallback(() => readSystemInfo(), []))

    const rows = useMemo(() => settingsRows(apple), [apple])
    const keys = useMemo(
        () => new Map(shortcuts(apple).map((one) => [`shortcuts:${one.id}`, one.keys])),
        [apple],
    )
    const groups = settingsGroups(
        rows,
        (row) => controlOf(row, { keys, info, changing, setChanging }),
        (category) => {
            if (category === 'shortcuts') return { lead: <Quiet>{LABELS.settings.shortcuts_apply}</Quiet> }
            if (category === 'server' && info.problem !== null)
                return { foot: <Refusal problem={info.problem} /> }
            return {}
        },
    )

    return (
        <LibrarySettingsDialog
            open={open}
            onOpenChange={onOpenChange}
            groups={groups}
            active={active}
            onActiveChange={setActive}
            search={search}
            onSearchChange={setSearch}
            phoneStart={startAt === null ? 'list' : 'section'}
            words={SETTINGS_WORDS}
        />
    )
}

interface Context {
    keys: Map<string, readonly string[]>
    info: Reading<SystemInfo>
    changing: boolean
    setChanging: (changing: boolean) => void
}

/** The control one row carries, and where it sits. */
function controlOf(row: SettingsRow, context: Context): RowControl {
    switch (row.id) {
        case 'theme:appearance':
            return { control: <ModeControl /> }
        case 'theme:palette':
            return { control: <PaletteCards />, layout: 'below' }
        case 'general:times':
            return { control: <TimesControl /> }
        case 'general:tails':
            return { control: <TailsControl />, layout: 'trailing' }
        case 'general:highlight':
            return { control: <HighlightControl />, layout: 'trailing' }
        case 'account:identity':
            return { control: <IdentityControl />, layout: 'trailing' }
        case 'account:password':
            return context.changing
                ? {
                      control: (
                          <ChangePassword
                              onDone={() => {
                                  context.setChanging(false)
                              }}
                          />
                      ),
                      layout: 'below',
                  }
                : {
                      control: (
                          <Button
                              variant="outline"
                              size="sm"
                              onClick={() => {
                                  context.setChanging(true)
                              }}
                          >
                              {LABELS.action.change}
                          </Button>
                      ),
                      layout: 'trailing',
                  }
        case 'account:sign-out':
            return { control: <SignOutButton />, layout: 'trailing' }
        case 'server:health':
            return { control: <HealthControl /> }
        case 'server:reference':
            return { control: <ReferenceLinks />, layout: 'trailing' }
        default:
            if (row.category === 'shortcuts') {
                return {
                    control: (
                        <KbdGroup>
                            {(context.keys.get(row.id) ?? []).map((key) => (
                                <Kbd key={key}>{key}</Kbd>
                            ))}
                        </KbdGroup>
                    ),
                    layout: 'trailing',
                }
            }
            return factControl(row.id, context.info)
    }
}

function ModeControl() {
    const { settings, setSettings } = useAppearance(APPEARANCE_DEFAULTS, APPEARANCE_OFFER)
    return (
        <SchemeChoice
            value={settings.scheme}
            onValueChange={(scheme) => {
                setSettings({ ...settings, scheme })
            }}
            words={SCHEME_WORDS}
        />
    )
}

/** One card per palette, each a small page in that palette's own tokens. */
function PaletteCards() {
    const { settings, setSettings } = useAppearance(APPEARANCE_DEFAULTS, APPEARANCE_OFFER)
    return (
        <ThemeCards
            value={settings.theme}
            onValueChange={(theme) => {
                setSettings({ ...settings, theme })
            }}
            themes={PALETTES.map((palette) => ({
                value: palette.name,
                label: palette.label,
            }))}
            words={THEME_CARDS_WORDS}
        />
    )
}

function TimesControl() {
    const times = useStore(timesMode)
    return (
        <Segmented
            label={LABELS.settings.times_control}
            value={times}
            options={TIMES_MODES.map((one) => ({
                value: one,
                label: TIMES_LABELS[one],
            }))}
            onValueChange={chooseTimes}
        />
    )
}

function TailsControl() {
    const tails = useStore(followTails)
    return (
        <Toggle
            on={tails}
            onChange={setFollowTails}
            label={tails ? LABELS.settings.following : LABELS.settings.not_following}
        />
    )
}

function HighlightControl() {
    const highlight = useStore(highlightLine)
    return (
        <Toggle
            on={highlight}
            onChange={setHighlightLine}
            label={highlight ? LABELS.settings.highlighted : LABELS.settings.not_highlighted}
        />
    )
}

/** A two-way preference as a pressed button that says the state it is in. */
function Toggle({ on, onChange, label }: { on: boolean; onChange: (on: boolean) => void; label: string }) {
    return (
        <Button
            variant={on ? 'secondary' : 'outline'}
            size="sm"
            aria-pressed={on}
            onClick={() => {
                onChange(!on)
            }}
        >
            {label}
        </Button>
    )
}

function IdentityControl() {
    const auth = useStore(authStore)
    return (
        <span className="flex items-center gap-1">
            <span className="font-mono text-sm">{auth.identity?.username ?? LABELS.settings.nobody}</span>
            {auth.identity !== null && <Chip tone="outline">{auth.identity.role}</Chip>}
        </span>
    )
}

function SignOutButton() {
    const navigate = useNavigate()
    const [busy, setBusy] = useState(false)
    return (
        <Button
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => {
                setBusy(true)
                void signOut().then(() => navigate(LOGIN_PATH, { replace: true }))
            }}
        >
            {LABELS.action.sign_out}
        </Button>
    )
}

/**
 * Change this account's password, under the row that offered to: the two fields on one line, the
 * refusal beside them, and Cancel beside the verb.
 */
function ChangePassword({ onDone }: { onDone: () => void }) {
    const [form, setForm] = useState<PasswordForm>(NO_PASSWORD)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)
    // Which boxes have been left once, so a required one says so only after somebody was there.
    const [left, setLeft] = useState({ current: false, next: false })
    const currentIssue = left.current && form.current === '' ? LABELS.refusal.password.current_missing : null
    const nextIssue =
        left.next && form.next.length < MIN_PASSWORD_LENGTH
            ? LABELS.refusal.password.too_short(String(MIN_PASSWORD_LENGTH))
            : null

    const send = () => {
        const local = formProblem(form)
        if (local !== null) {
            setProblem(local)
            return
        }
        setBusy(true)
        setProblem(null)
        void changePassword(form)
            .then(
                () => {
                    setForm(NO_PASSWORD)
                    toast.success(LABELS.settings.password_changed)
                    onDone()
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
        <Surface tone="well" pad className="w-full space-y-3">
            <div className="flex flex-col gap-3 md:flex-row">
                <TextField
                    id="password-current"
                    label={LABELS.settings.current_password}
                    required
                    requiredMark="word"
                    words={FIELD_WORDS}
                    error={currentIssue}
                    className="flex-1"
                    type="password"
                    autoComplete="current-password"
                    value={form.current}
                    onChange={(current) => {
                        setForm((was) => ({ ...was, current }))
                    }}
                    onBlur={() => {
                        setLeft((was) => ({ ...was, current: true }))
                    }}
                />
                <TextField
                    id="password-new"
                    label={LABELS.settings.new_password}
                    required
                    requiredMark="word"
                    words={FIELD_WORDS}
                    error={nextIssue}
                    className="flex-1"
                    type="password"
                    autoComplete="new-password"
                    value={form.next}
                    onChange={(next) => {
                        setForm((was) => ({ ...was, next }))
                    }}
                    onBlur={() => {
                        setLeft((was) => ({ ...was, next: true }))
                    }}
                />
            </div>

            {problem !== null && <Refusal problem={problem} />}

            <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={onDone}>
                    {LABELS.action.cancel}
                </Button>
                <Button size="sm" disabled={busy} onClick={send}>
                    {LABELS.settings.change_password}
                </Button>
            </div>
        </Surface>
    )
}

/**
 * Whether this instance is ready, from the store the top bar's dot paints from; Recheck is that
 * store's one reader.
 */
function HealthControl() {
    const status = useStore(serverStatus)
    const [rechecking, setRechecking] = useState(false)

    const recheck = () => {
        setRechecking(true)
        void checkServer().finally(() => {
            setRechecking(false)
        })
    }

    return (
        <span className="flex flex-wrap items-center gap-1">
            <Dot
                color={STATUS_CSS[SERVER_STATES[status.state].color]}
                className={cn(status.state === 'unknown' && 'animate-pulse')}
            />
            <span className="text-sm">
                {LABELS.state.server[status.state === 'unknown' ? 'asking' : status.state]}
            </span>
            {status.checkedAt !== null && (
                <span
                    className="ml-1 text-xs text-faint"
                    title={formatInstant(new Date(status.checkedAt).toISOString())}
                >
                    {LABELS.settings.checked(formatRelative(new Date(status.checkedAt).toISOString()))}
                </span>
            )}
            <Button variant="outline" size="sm" className="ml-2" disabled={rechecking} onClick={recheck}>
                <ICONS.recheck aria-hidden />
                {LABELS.action.recheck}
            </Button>
        </span>
    )
}

function ReferenceLinks() {
    return (
        <span className="flex gap-4 text-sm">
            <TextLink variant="inline" external words={LINK_WORDS} href={DOCS_URL}>
                {LABELS.settings.documentation}
            </TextLink>
            <TextLink variant="inline" href={API_DOCS_URL}>
                {LABELS.settings.api_reference}
            </TextLink>
        </span>
    )
}

/**
 * A row stating one fact of `GET /system/info`: one value, or the codes of a list, each on one
 * line. A refused read is stated once, under the pane's rows.
 */
function factControl(id: string, info: Reading<SystemInfo>): RowControl {
    if (info.value !== null) {
        return {
            control: (
                <span className="flex min-w-0 flex-wrap justify-end gap-x-2 font-mono text-xs">
                    {factOf(id, info.value).map((one) => (
                        <span key={one} className="whitespace-nowrap">
                            {one}
                        </span>
                    ))}
                </span>
            ),
            layout: 'trailing',
        }
    }
    return { control: <Quiet>{LABELS.shell.reading}</Quiet>, layout: 'trailing' }
}

function Quiet({ children }: { children: ReactNode }) {
    return <span className="text-xs text-faint">{children}</span>
}

function factOf(id: string, info: SystemInfo): string[] {
    switch (id) {
        case 'server:version':
            return [info.version]
        case 'server:environment':
            return [info.environment]
        case 'server:database':
            return [info.database]
        case 'server:blocks':
            return [String(info.blocks)]
        case 'server:storage':
            return info.storage_schemes.length === 0 ? [LABELS.word.none] : info.storage_schemes
        default:
            return info.plugins.length === 0 ? [LABELS.word.none] : info.plugins
    }
}
