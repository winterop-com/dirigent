import { Check, RefreshCw } from 'lucide-react'
import { useTheme } from 'next-themes'
import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { Refusal } from '@/components/Refusal'
import { Segmented } from '@/components/Segmented'
import { Dot, TONE } from '@/components/ServerStatusButton'
import { MODE_LABELS, MODES, type Mode } from '@/components/ThemeToggle'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Kbd, KbdGroup } from '@/components/ui/kbd'
import { Label } from '@/components/ui/label'
import { useRead } from '@/hooks/use-read'
import { useStore } from '@/hooks/use-store'
import { type Problem } from '@/lib/api'
import { authStore, signOut } from '@/lib/auth'
import { API_DOCS_URL, DOCS_URL } from '@/lib/docs'
import { formatRelative } from '@/lib/format'
import { LOGIN_PATH } from '@/lib/nav'
import { changePassword, formProblem, NO_PASSWORD, refusalOf, type PasswordForm } from '@/lib/password'
import { followTails, setFollowTails } from '@/lib/preferences'
import { checkServer, serverStatus } from '@/lib/server-status'
import {
    categoriesWith,
    FIRST_CATEGORY,
    filterSettings,
    rowsOf,
    SETTINGS_GROUPS,
    settingsRows,
    type SettingsRow,
} from '@/lib/settings'
import { applePlatform, shortcuts } from '@/lib/shortcuts'
import { readSystemInfo, type SystemInfo } from '@/lib/system'
import { choosePalette, paletteAfter, PALETTES, paletteStore, type PaletteName } from '@/lib/theme'
import { chooseTimes, TIMES_LABELS, TIMES_MODES, timesMode } from '@/lib/times'
import { cn } from '@/lib/utils'

export const SETTINGS_TITLE = 'Settings'

/**
 * Two panes: what there is on the left, one category of it on the right.
 *
 * THE ROWS ARE DATA AND THE SEARCH IS A PURE FUNCTION OVER THEM. `lib/settings` holds every row
 * as a record -- what it is called, what else it can be found by -- so filtering across every
 * category is one function with a test, and not a traversal of markup. What a row puts on its
 * right edge is this file's, keyed by the row's id.
 *
 * NOTHING HERE IS A COPY OF A SETTING. Appearance writes next-themes, which is the same store
 * the toggle in the header writes; times writes `lib/times`, which the formatters consult; the
 * log preference writes `lib/preferences`, which the log pane reads. A dialog that held its own
 * copy of a setting would be a second answer to the same question.
 *
 * SIGN OUT IS STILL IN THE HEADER. This adds a second way to reach it rather than moving it:
 * somebody who knows where it is should keep finding it there.
 */
export function SettingsDialog({
    open,
    onOpenChange,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
}) {
    const apple = applePlatform(navigator.userAgent)
    const [query, setQuery] = useState('')
    const [chosen, setChosen] = useState(FIRST_CATEGORY)

    const rows = useMemo(() => settingsRows(apple), [apple])
    const shown = useMemo(() => filterSettings(rows, query), [query, rows])
    const categories = useMemo(() => categoriesWith(shown), [shown])
    const active = categories.some((category) => category.id === chosen)
        ? chosen
        : (categories[0]?.id ?? null)
    const heading = categories.find((category) => category.id === active) ?? null

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="flex h-[32rem] flex-col gap-0 p-0 sm:max-w-3xl">
                <DialogHeader className="shrink-0 gap-1 border-b border-border px-4 py-3">
                    <DialogTitle>{SETTINGS_TITLE}</DialogTitle>
                </DialogHeader>

                <div className="flex min-h-0 flex-1">
                    <nav className="flex w-36 shrink-0 flex-col gap-1 overflow-y-auto border-r border-border bg-sidebar p-2 md:w-52">
                        <Input
                            value={query}
                            aria-label="Search the settings"
                            placeholder="Search"
                            className="mb-1"
                            onChange={(event) => {
                                setQuery(event.target.value)
                            }}
                        />
                        {SETTINGS_GROUPS.map((group) => {
                            const inGroup = categories.filter((category) => category.group === group.id)
                            if (inGroup.length === 0) return null
                            return (
                                <div key={group.id} className="mb-1">
                                    <p className="px-2 py-1 text-xs text-faint">{group.label}</p>
                                    {inGroup.map((category) => (
                                        <button
                                            key={category.id}
                                            type="button"
                                            aria-current={category.id === active}
                                            className={cn(
                                                'block w-full rounded-md px-2 py-1 text-left text-sm',
                                                category.id === active
                                                    ? 'bg-primary/15 font-medium text-foreground'
                                                    : 'text-muted-foreground hover:bg-accent',
                                            )}
                                            onClick={() => {
                                                setChosen(category.id)
                                            }}
                                        >
                                            {category.label}
                                        </button>
                                    ))}
                                </div>
                            )
                        })}
                    </nav>

                    <div className="min-h-0 flex-1 overflow-y-auto p-4">
                        {heading === null ? (
                            <p className="text-sm text-muted-foreground">Nothing matches that.</p>
                        ) : (
                            <>
                                <h2 className="mb-3 text-sm font-semibold">{heading.label}</h2>
                                <Pane category={heading.id} rows={rowsOf(shown, heading.id)} apple={apple} />
                            </>
                        )}
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    )
}

/** Which pane one category is. Each holds its own reads, so a closed pane reads nothing. */
function Pane({ category, rows, apple }: { category: string; rows: SettingsRow[]; apple: boolean }) {
    if (rows.length === 0) return <p className="text-sm text-muted-foreground">Nothing matches that.</p>
    switch (category) {
        case 'general':
            return <GeneralPane rows={rows} />
        case 'theme':
            return <ThemePane rows={rows} />
        case 'account':
            return <AccountPane rows={rows} />
        case 'shortcuts':
            return <ShortcutsPane rows={rows} apple={apple} />
        default:
            return <ServerPane rows={rows} />
    }
}

/**
 * One row: what it is called, the control on its right edge, and whatever it expands into.
 *
 * The description is the row's own and is usually absent: a line restating the label is a line
 * that says nothing, so only a row with a fact the control cannot show carries one.
 */
function Row({ row, children, under }: { row: SettingsRow; children?: ReactNode; under?: ReactNode }) {
    return (
        <div className="row-hover -mx-2 border-b border-border px-2 py-3 last:border-b-0">
            {/* Below the breakpoint the control sits under what it is called: a label column
                and a control column on a 390px screen is two words a line. */}
            <div className="flex flex-col items-start gap-2 md:flex-row md:items-start md:justify-between md:gap-4">
                <div className="min-w-0 space-y-0.5">
                    <p className="text-sm font-medium">{row.label}</p>
                    {row.description !== undefined && (
                        <p className="text-xs text-muted-foreground">{row.description}</p>
                    )}
                </div>
                {children !== undefined && <div className="flex shrink-0 items-center gap-1">{children}</div>}
            </div>
            {under !== undefined && <div className="mt-3">{under}</div>}
        </div>
    )
}

/** The look: the two axes, one row each. */
function ThemePane({ rows }: { rows: SettingsRow[] }) {
    const { theme, setTheme } = useTheme()
    const mode = (theme ?? 'system') as Mode
    const palette = useStore(paletteStore)

    return (
        <div>
            {rows.map((row) => {
                if (row.id === 'theme:appearance') {
                    return (
                        <Row key={row.id} row={row}>
                            <Segmented
                                label="Appearance"
                                value={mode}
                                options={MODES.map((one) => ({ value: one, label: MODE_LABELS[one] }))}
                                onChoose={setTheme}
                            />
                        </Row>
                    )
                }
                return (
                    <Row
                        key={row.id}
                        row={row}
                        under={
                            <PaletteSwatches
                                value={palette}
                                onChoose={(name) => {
                                    choosePalette(name)
                                }}
                            />
                        }
                    />
                )
            })}
        </div>
    )
}

/** The tokens a swatch shows, ground first and accent last: the ladder plus the two inks. */
const SWATCH_STRIPS = ['bg-background', 'bg-card', 'bg-border', 'bg-foreground', 'bg-primary']

/**
 * One card per palette, and the card is the radio.
 *
 * WHAT A PALETTE LOOKS LIKE IS THE SWATCH, NOT A SENTENCE. Each card scopes itself with
 * `data-palette`, which index.css hangs that palette's own token block off, so the five strips
 * are the real ground, surface, line, ink and accent -- in the appearance in force, and right
 * without anybody copying a colour when a token moves.
 *
 * A RADIOGROUP, WITH THE ARROWS CHOOSING. One tab stop for the group, the arrows move and
 * choose, Space and Enter choose what has focus. That is the stock behaviour of a radio group,
 * and a palette applies the moment it is chosen, so moving through them is trying them on.
 */
function PaletteSwatches({ value, onChoose }: { value: PaletteName; onChoose: (name: PaletteName) => void }) {
    const cards = useRef<(HTMLButtonElement | null)[]>([])
    const at = Math.max(
        0,
        PALETTES.findIndex((one) => one.name === value),
    )

    const move = (key: string) => {
        const next = paletteAfter(value, key)
        if (next === null) return false
        onChoose(next)
        cards.current[PALETTES.findIndex((one) => one.name === next)]?.focus()
        return true
    }

    return (
        <div role="radiogroup" aria-label="Palette" className="flex gap-2">
            {PALETTES.map((palette, index) => {
                const chosen = palette.name === value
                return (
                    <button
                        key={palette.name}
                        ref={(element) => {
                            cards.current[index] = element
                        }}
                        type="button"
                        role="radio"
                        aria-checked={chosen}
                        tabIndex={index === at ? 0 : -1}
                        className={cn(
                            'flex max-w-32 min-w-0 flex-1 flex-col gap-1.5 rounded-md border p-1.5 text-left',
                            'focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                            chosen ? 'border-primary ring-2 ring-primary' : 'border-border hover:bg-accent',
                        )}
                        onClick={() => {
                            onChoose(palette.name)
                        }}
                        onKeyDown={(event) => {
                            if (move(event.key)) {
                                event.preventDefault()
                            } else if (event.key === ' ' || event.key === 'Enter') {
                                event.preventDefault()
                                onChoose(palette.name)
                            }
                        }}
                    >
                        <span
                            data-palette={palette.name}
                            className="flex h-8 overflow-hidden rounded-sm border border-border"
                        >
                            {SWATCH_STRIPS.map((strip) => (
                                <span key={strip} className={cn('flex-1', strip)} />
                            ))}
                        </span>
                        <span className="flex items-center gap-1 text-xs">
                            {palette.label}
                            {chosen && <Check className="size-3 text-primary" aria-hidden />}
                        </span>
                    </button>
                )
            })}
        </div>
    )
}

function GeneralPane({ rows }: { rows: SettingsRow[] }) {
    const times = useStore(timesMode)
    const tails = useStore(followTails)

    return (
        <div>
            {rows.map((row) => {
                if (row.id === 'general:times') {
                    return (
                        <Row key={row.id} row={row}>
                            <Segmented
                                label="Times"
                                value={times}
                                options={TIMES_MODES.map((one) => ({ value: one, label: TIMES_LABELS[one] }))}
                                onChoose={chooseTimes}
                            />
                        </Row>
                    )
                }
                return (
                    <Row key={row.id} row={row}>
                        <Button
                            variant={tails ? 'secondary' : 'outline'}
                            size="sm"
                            aria-pressed={tails}
                            onClick={() => {
                                setFollowTails(!tails)
                            }}
                        >
                            {tails ? 'Following' : 'Not following'}
                        </Button>
                    </Row>
                )
            })}
        </div>
    )
}

function AccountPane({ rows }: { rows: SettingsRow[] }) {
    const auth = useStore(authStore)
    const [changing, setChanging] = useState(false)

    return (
        <div>
            {rows.map((row) => {
                if (row.id === 'account:identity') {
                    return (
                        <Row key={row.id} row={row}>
                            <span className="font-mono text-sm">{auth.identity?.username ?? 'nobody'}</span>
                            {auth.identity !== null && <Badge variant="outline">{auth.identity.role}</Badge>}
                        </Row>
                    )
                }
                if (row.id === 'account:password') {
                    return (
                        <Row
                            key={row.id}
                            row={row}
                            under={
                                changing ? (
                                    <ChangePassword
                                        onDone={() => {
                                            setChanging(false)
                                        }}
                                    />
                                ) : undefined
                            }
                        >
                            {changing ? undefined : (
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => {
                                        setChanging(true)
                                    }}
                                >
                                    Change
                                </Button>
                            )}
                        </Row>
                    )
                }
                return (
                    <Row key={row.id} row={row}>
                        <SignOutRow />
                    </Row>
                )
            })}
        </div>
    )
}

/** Sign out from the dialog. The header keeps its own button; this is a second way in. */
function SignOutRow() {
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
            Sign out
        </Button>
    )
}

/**
 * Change this account's password, in the row that offered to.
 *
 * IT EXPANDS UNDER THE ROW RATHER THAN OPENING A SECOND DIALOG. What is being changed is on
 * screen, and a dialog over a dialog puts a scrim over the thing it is about. The refusal is
 * `Refusal` beside the fields, because there is room for it here, and nothing closes on one.
 */
function ChangePassword({ onDone }: { onDone: () => void }) {
    const [form, setForm] = useState<PasswordForm>(NO_PASSWORD)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)

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
                    toast.success('Password changed. Every other session of this account is signed out.')
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
        <div className="space-y-3 rounded-lg border border-border bg-secondary/30 p-3">
            <div className="flex flex-col gap-3 md:flex-row">
                <div className="min-w-0 flex-1 space-y-1">
                    <Label htmlFor="password-current">Current password</Label>
                    <Input
                        id="password-current"
                        type="password"
                        autoComplete="current-password"
                        value={form.current}
                        onChange={(event) => {
                            setForm((current) => ({ ...current, current: event.target.value }))
                        }}
                    />
                </div>
                <div className="min-w-0 flex-1 space-y-1">
                    <Label htmlFor="password-new">New password</Label>
                    <Input
                        id="password-new"
                        type="password"
                        autoComplete="new-password"
                        value={form.next}
                        onChange={(event) => {
                            setForm((current) => ({ ...current, next: event.target.value }))
                        }}
                    />
                </div>
            </div>

            {problem !== null && <Refusal problem={problem} />}

            <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={onDone}>
                    Cancel
                </Button>
                <Button size="sm" disabled={busy} onClick={send}>
                    Change password
                </Button>
            </div>
        </div>
    )
}

function ShortcutsPane({ rows, apple }: { rows: SettingsRow[]; apple: boolean }) {
    const keys = useMemo(
        () => new Map(shortcuts(apple).map((one) => [`shortcuts:${one.id}`, one.keys])),
        [apple],
    )
    return (
        <div>
            {rows.map((row) => (
                <div
                    key={row.id}
                    className="row-hover -mx-2 flex min-h-10 items-center justify-between gap-4 border-b border-border px-2 last:border-b-0"
                >
                    <p className="min-w-0 text-sm font-medium">{row.label}</p>
                    <KbdGroup>
                        {(keys.get(row.id) ?? []).map((key) => (
                            <Kbd key={key}>{key}</Kbd>
                        ))}
                    </KbdGroup>
                </div>
            ))}
            <p className="mt-3 text-xs text-faint">Anywhere but inside a text box.</p>
        </div>
    )
}

/**
 * What this instance is, and whether it is well.
 *
 * THE HEALTH HALF IS THE CORNER DOT'S. `lib/server-status` holds the one reader of
 * `/health/ready` and the store the dot in the topbar paints from; this pane reads that store
 * and its Recheck button is that reader, so the pane and the dot cannot say different things
 * about the same instance at the same moment. Which check said what is the popover behind that
 * dot, and is not repeated here. What is installed is a different question, and
 * `GET /system/info` is where this pane asks it.
 */
function ServerPane({ rows }: { rows: SettingsRow[] }) {
    const info = useRead(useCallback(() => readSystemInfo(), []))
    const status = useStore(serverStatus)
    const [rechecking, setRechecking] = useState(false)
    const value = info.value

    const recheck = () => {
        setRechecking(true)
        void checkServer().finally(() => {
            setRechecking(false)
        })
    }

    return (
        <div>
            {info.problem !== null && <Refusal problem={info.problem} />}
            {rows.map((row) => {
                if (row.id === 'server:health') {
                    return (
                        <Row key={row.id} row={row}>
                            <Dot state={status.state} wide />
                            <span className="text-sm">{TONE[status.state].word}</span>
                            {status.checkedAt !== null && (
                                <span className="ml-1 text-xs text-faint">
                                    checked {formatRelative(new Date(status.checkedAt).toISOString())}
                                </span>
                            )}
                            <Button
                                variant="outline"
                                size="sm"
                                className="ml-2"
                                disabled={rechecking}
                                onClick={recheck}
                            >
                                <RefreshCw aria-hidden />
                                Recheck
                            </Button>
                        </Row>
                    )
                }
                return (
                    <Row key={row.id} row={row}>
                        {value === null ? (
                            <span className="text-xs text-faint">Reading</span>
                        ) : (
                            <span className="font-mono text-xs">{factOf(row.id, value)}</span>
                        )}
                    </Row>
                )
            })}
            <p className="mt-3 flex gap-4 text-sm">
                <a
                    className="text-primary-ink hover:underline"
                    href={DOCS_URL}
                    target="_blank"
                    rel="noreferrer"
                >
                    Documentation
                </a>
                <a className="text-primary-ink hover:underline" href={API_DOCS_URL}>
                    API reference
                </a>
            </p>
        </div>
    )
}

/** What one server row states, out of the one document that carries all of them. */
function factOf(id: string, info: SystemInfo): string {
    switch (id) {
        case 'server:version':
            return info.version
        case 'server:environment':
            return info.environment
        case 'server:database':
            return info.database
        case 'server:blocks':
            return String(info.blocks)
        case 'server:storage':
            return info.storage_schemes.length === 0 ? 'none' : info.storage_schemes.join(', ')
        default:
            return info.plugins.length === 0 ? 'none' : info.plugins.join(', ')
    }
}
