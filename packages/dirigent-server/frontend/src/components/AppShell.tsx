import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Outlet, useNavigate } from 'react-router'

import { crumbSlot } from '@/components/Breadcrumb'
import { headSlot } from '@/components/PageHead'
import { CommandPalette } from '@/components/CommandPalette'
import { NavDrawer, OPEN_NAV_LABEL } from '@/components/NavDrawer'
import { PanelSheet } from '@/components/PanelSheet'
import { PageState } from '@/components/PageState'
import { warmLayout } from '@/components/graph/elk'
import { warmEditor } from '@/components/pipeline/CodePane'
import { Rail } from '@/components/Rail'
import { RightPanel } from '@/components/RightPanel'
import { panelTabs } from '@/lib/panels'
import { ShortcutsDialog } from '@/components/ShortcutsDialog'
import { ServerStatusButton } from '@/components/ServerStatusButton'
import { useScheme } from '@winterop-com/sokkel-ui/hooks/use-scheme'

import { InlineCode } from '@winterop-com/sokkel-ui/InlineCode'
import { IconButton } from '@winterop-com/sokkel-ui/IconButton'

import { useAppShortcuts } from '@/hooks/use-app-shortcuts'
import { useStore } from '@/hooks/use-store'
import { ApiError, onUnauthorized, type Problem } from '@/lib/api'
import { authStore, refreshIdentity, signOut } from '@/lib/auth'
import { LABELS } from '@/lib/labels'
import { loadKindMarks } from '@/lib/marks'
import { loadContributedWording } from '@/lib/wording'
import { ICONS } from '@/lib/icons'
import { DESIGN_PATH, entriesFor, LOGIN_PATH } from '@/lib/nav'
import {
    APPEARANCE_GROUP,
    GO_GROUP,
    paletteOpen,
    registerActions,
    SESSION_GROUP,
    VIEW_GROUP,
    type PaletteAction,
} from '@/lib/palette'
import { panelOpen, railHidden, toggleRail, togglePanel } from '@/lib/panels'
import { screenStatus, type StatusTone } from '@/lib/screen-status'
import { modifierLabel, applePlatform } from '@/lib/shortcuts'
import { MODE_ICONS, MODES, MODE_LABELS } from '@/lib/theme'
import { cn } from '@/lib/utils'

export const SIGN_OUT_LABEL = LABELS.action.sign_out
export const TOGGLE_PANEL_LABEL = LABELS.shell.toggle_panel
export const OPEN_PALETTE_LABEL = LABELS.shell.open_palette

/** The settings pane the top bar's dot opens on. */
const SERVER_PANE = 'server'

/**
 * The settings dialog is fetched the first time somebody asks for it.
 *
 * It carries five panes, two reads of its own and a form, and most sessions never open it. It
 * is mounted only once it has been opened, so its chunk is not in the entry bundle and the
 * closing animation still has something to animate.
 */
const SettingsDialog = lazy(() =>
    import('@/components/settings/SettingsDialog').then((module) => ({ default: module.SettingsDialog })),
)

/** How each tone of the screen's note is inked. A live stream is information, not a warning. */
const TONE: Record<StatusTone, string> = {
    live: 'text-info-ink',
    quiet: 'text-muted-foreground',
    warn: 'text-warning-ink',
}

/**
 * The chassis: the rail on the left, the screen in the middle under its top strip, and a panel
 * on the right where the screen fills one.
 *
 * `h-svh` rather than `min-h-svh`. The shell claims the viewport and the content column is the
 * one thing that scrolls, so there is exactly one scrollbar on every screen -- and a screen that
 * wants to fill the height it was given can be told how much that is.
 *
 * NO SCREEN IS DRAWN UNTIL THE IDENTITY IS KNOWN. A screen that rendered first would fire its
 * reads first, and every one of them would be a request the server answers 401 to. So the shell
 * renders its own frame and waits, which takes one round trip.
 */
export function AppShell() {
    const auth = useStore(authStore)
    const hidden = useStore(railHidden)
    const filled = useStore(panelTabs).length > 0
    const panelShown = useStore(panelOpen)
    const navigate = useNavigate()
    const [shortcutsOpen, setShortcutsOpen] = useState(false)
    const [settingsOpen, setSettingsOpen] = useState(false)
    const { setScheme } = useScheme()
    const [settingsAsked, setSettingsAsked] = useState(false)
    const [settingsPane, setSettingsPane] = useState<string | null>(null)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [drawerOpen, setDrawerOpen] = useState(false)
    const menu = useRef<HTMLButtonElement | null>(null)
    const wasOpen = useRef(false)
    useEffect(() => {
        wasOpen.current = drawerOpen
    }, [drawerOpen])

    // The focus goes back where it came from: the button that raised the drawer. Only when the
    // drawer was actually standing -- a navigation closes it whether or not it was open, and
    // taking the focus off what somebody just clicked is not a close.
    const closeDrawer = useCallback(() => {
        if (!wasOpen.current) return
        setDrawerOpen(false)
        menu.current?.focus()
    }, [])

    // A refusal for want of a session is the shell's, not a screen's: the session expired, and
    // the answer is the login page rather than a refusal card on whatever was open.
    useEffect(() => {
        onUnauthorized(() => {
            void navigate(LOGIN_PATH, { replace: true })
        })
        return () => {
            onUnauthorized(null)
        }
    }, [navigate])

    useEffect(() => {
        void refreshIdentity().catch((error: unknown) => {
            setProblem(error instanceof ApiError ? error.problem : null)
        })
    }, [])

    // A read that answers "nobody" sends the reader to the login page rather than leaving them
    // on a screen whose every request is about to be refused.
    const signedOut = auth.status === 'signed-out'
    useEffect(() => {
        if (signedOut) void navigate(LOGIN_PATH, { replace: true })
    }, [navigate, signedOut])

    const openSettings = useCallback(() => {
        setSettingsPane(null)
        setSettingsAsked(true)
        setSettingsOpen(true)
    }, [])

    const openServerPane = useCallback(() => {
        setSettingsPane(SERVER_PANE)
        setSettingsAsked(true)
        setSettingsOpen(true)
    }, [])

    const openShortcuts = useCallback(() => {
        setShortcutsOpen(true)
    }, [])

    useAppShortcuts(openShortcuts)

    const role = auth.identity?.role ?? null
    const signedIn = auth.status === 'signed-in'

    // THE TWO BIG CHUNKS ARE FETCHED BEFORE ANYBODY ASKS FOR THEM. Monaco and elk are each
    // larger than the rest of this bundle and the screens behind this shell open both, so once
    // there is a session and the browser has nothing else to do, the chunks are pulled. It is
    // idle-time work and it happens once: no screen waits on either, and the login page is
    // outside this shell and asks for nothing.
    useEffect(() => {
        if (!signedIn) return
        warmEditor()
        warmLayout()
    }, [signedIn])

    // WHAT THE PACKS DRAW THEMSELVES WITH IS READ ONCE, for the same reason and at the same
    // moment: every screen that names a connection kind draws its mark, every screen can draw a
    // pack's refusal, and what a pack declares does not change while the process is up.
    useEffect(() => {
        if (signedIn) {
            loadKindMarks()
            loadContributedWording()
        }
    }, [signedIn])

    const actions = useMemo<PaletteAction[]>(() => {
        const pages: PaletteAction[] = entriesFor(role).map((entry) => ({
            id: `go:${entry.path}`,
            title: entry.label,
            group: GO_GROUP,
            hint: entry.hint,
            icon: entry.icon,
            keywords: [entry.path],
            run: () => {
                void navigate(entry.path)
            },
        }))
        return [
            ...pages,
            {
                id: 'view:rail',
                title: hidden ? LABELS.shell.show_nav : LABELS.shell.hide_nav,
                group: VIEW_GROUP,
                icon: ICONS.sidebar,
                keywords: ['sidebar', 'rail'],
                run: toggleRail,
            },
            {
                id: 'view:panel',
                title: TOGGLE_PANEL_LABEL,
                group: VIEW_GROUP,
                icon: ICONS.panel,
                keywords: ['inspector', 'details'],
                run: togglePanel,
            },
            {
                id: 'view:settings',
                title: LABELS.shell.open_settings,
                group: VIEW_GROUP,
                icon: ICONS.settings,
                keywords: ['preferences', 'appearance', 'times', 'account', 'password', 'server'],
                run: openSettings,
            },
            {
                id: 'view:shortcuts',
                title: LABELS.shell.shortcuts,
                group: VIEW_GROUP,
                icon: ICONS.shortcuts,
                keywords: ['keys', 'chords', 'help'],
                run: () => {
                    setShortcutsOpen(true)
                },
            },
            {
                id: 'view:design',
                title: LABELS.screen.design.name,
                group: VIEW_GROUP,
                icon: ICONS.design,
                keywords: ['components', 'gallery', 'tokens', DESIGN_PATH],
                run: () => {
                    void navigate(DESIGN_PATH)
                },
            },
            ...MODES.map((mode) => ({
                id: `appearance:${mode}`,
                title: MODE_LABELS[mode],
                group: APPEARANCE_GROUP,
                icon: MODE_ICONS[mode],
                keywords: ['theme', 'appearance', mode],
                run: () => {
                    setScheme(mode)
                },
            })),
            ...(signedIn
                ? [
                      {
                          id: 'session:sign-out',
                          title: SIGN_OUT_LABEL,
                          group: SESSION_GROUP,
                          icon: ICONS.sign_out,
                          keywords: ['logout', 'leave'],
                          run: () => {
                              void signOut().then(() => navigate(LOGIN_PATH, { replace: true }))
                          },
                      },
                  ]
                : []),
        ]
    }, [hidden, navigate, openSettings, role, setScheme, signedIn])

    useEffect(() => registerActions(actions), [actions])

    const modifier = modifierLabel(applePlatform(navigator.userAgent))
    const setSlot = useCallback((element: HTMLDivElement | null) => {
        crumbSlot.set(element)
    }, [])
    const setHead = useCallback((element: HTMLDivElement | null) => {
        headSlot.set(element)
    }, [])

    return (
        <div className="flex h-svh overflow-hidden">
            <Rail onSettings={openSettings} onShortcuts={openShortcuts} />
            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
                <header
                    data-shell-strip="top"
                    className="flex h-shell-top shrink-0 items-center gap-2 px-4 md:px-8"
                >
                    {/* The rail is not drawn below the breakpoint, so this is the way to it. */}
                    <IconButton
                        ref={menu}
                        label={OPEN_NAV_LABEL}
                        size="icon-sm"
                        className="-ml-2 md:hidden"
                        onClick={() => {
                            setDrawerOpen(true)
                        }}
                    >
                        <ICONS.menu aria-hidden />
                    </IconButton>
                    {hidden && (
                        <IconButton
                            label={LABELS.shell.show_nav}
                            size="icon-sm"
                            className="-ml-2 hidden text-muted-foreground md:inline-flex"
                            onClick={toggleRail}
                        >
                            <ICONS.sidebar aria-hidden />
                        </IconButton>
                    )}
                    <div ref={setSlot} data-shell-crumb className="flex min-w-0 items-center" />
                    <div className="flex-1" />
                    <ScreenFacts />
                    <IconButton
                        label={OPEN_PALETTE_LABEL}
                        shortcut={LABELS.shell.palette_chord(modifier)}
                        size="icon-sm"
                        className="text-muted-foreground"
                        onClick={() => {
                            paletteOpen.set(true)
                        }}
                    >
                        <ICONS.search aria-hidden />
                    </IconButton>
                    <ServerStatusButton onOpen={openServerPane} />
                    {filled && !panelShown && (
                        <IconButton
                            label={TOGGLE_PANEL_LABEL}
                            size="icon-sm"
                            className="-mr-2 hidden text-muted-foreground md:inline-flex"
                            onClick={togglePanel}
                        >
                            <ICONS.panel aria-hidden />
                        </IconButton>
                    )}
                </header>

                <main className="flex min-h-0 w-full flex-1 flex-col">
                    <div ref={setHead} data-page-head className="shrink-0 px-4 pt-1 md:px-8" />
                    <div data-page-scroller className="dg-scroller flex min-h-0 flex-1 flex-col pt-px">
                        {auth.status === 'unknown' ? (
                            <PageState loading={problem === null} problem={problem} empty={false}>
                                {null}
                            </PageState>
                        ) : (
                            <Outlet />
                        )}
                    </div>
                </main>

                <PanelSheet />
            </div>
            <RightPanel />

            <NavDrawer
                open={drawerOpen}
                onClose={closeDrawer}
                onSettings={openSettings}
                onShortcuts={openShortcuts}
            />

            <CommandPalette />
            <ShortcutsDialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
            {settingsAsked && (
                <Suspense fallback={null}>
                    <SettingsDialog
                        key={settingsPane}
                        startAt={settingsPane}
                        open={settingsOpen}
                        onOpenChange={setSettingsOpen}
                    />
                </Suspense>
            )}
        </div>
    )
}

/** What the screen in front of somebody is doing: its note, and its identifier in mono. */
function ScreenFacts() {
    const status = useStore(screenStatus)
    if (status.note === null && status.identifier === null) return null
    return (
        <div data-screen-facts className="flex min-w-0 items-center gap-3 pr-2">
            {status.note !== null && (
                <span className={cn('min-w-0 truncate text-xs', TONE[status.tone])}>{status.note}</span>
            )}
            {status.identifier !== null && (
                <InlineCode value={status.identifier} tone="muted" bare size="xs" />
            )}
        </div>
    )
}
