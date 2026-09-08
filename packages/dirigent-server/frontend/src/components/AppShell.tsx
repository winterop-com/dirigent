import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Outlet, useNavigate } from 'react-router'

import { CommandPalette } from '@/components/CommandPalette'
import { NavDrawer, OPEN_NAV_LABEL } from '@/components/NavDrawer'
import { PanelSheet } from '@/components/PanelSheet'
import { PageState } from '@/components/PageState'
import { warmEditor } from '@/components/pipeline/CodePane'
import { Rail } from '@/components/Rail'
import { RightPanel } from '@/components/RightPanel'
import { panelTabs } from '@/lib/panels'
import { ShortcutsDialog } from '@/components/ShortcutsDialog'
import { StatusBar } from '@/components/StatusBar'
import { ServerStatusButton } from '@/components/ServerStatusButton'
import { useTheme } from 'next-themes'

import { MODES, MODE_LABELS } from '@/components/ThemeToggle'
import { Keyboard, LogOut, Menu, PanelLeft, PanelRight, Settings, Monitor, Moon, Sun } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useAppShortcuts } from '@/hooks/use-app-shortcuts'
import { useStore } from '@/hooks/use-store'
import { ApiError, onUnauthorized, type Problem } from '@/lib/api'
import { authStore, refreshIdentity, signOut } from '@/lib/auth'
import { entriesFor, LOGIN_PATH } from '@/lib/nav'
import { APPEARANCE_GROUP,GO_GROUP,
    paletteOpen,
    registerActions,
    SESSION_GROUP,
    VIEW_GROUP,
    type PaletteAction,
} from '@/lib/palette'
import { railCollapsed, toggleRail, togglePanel } from '@/lib/panels'
import { modifierLabel, applePlatform } from '@/lib/shortcuts'

export const SIGN_OUT_LABEL = 'Sign out'
export const TOGGLE_PANEL_LABEL = 'Show or hide the side panel'
export const OPEN_PALETTE_LABEL = 'Open the command palette'

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

/**
 * The chassis: a rail on the left, the screen in the middle, a panel on the right, and one line
 * along the foot.
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
    const collapsed = useStore(railCollapsed)
    const filled = useStore(panelTabs).length > 0
    const navigate = useNavigate()
    const [shortcutsOpen, setShortcutsOpen] = useState(false)
    const [settingsOpen, setSettingsOpen] = useState(false)
    const { setTheme } = useTheme()
    const [settingsAsked, setSettingsAsked] = useState(false)
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
        setSettingsAsked(true)
        setSettingsOpen(true)
    }, [])

    useAppShortcuts(
        useCallback(() => {
            setShortcutsOpen(true)
        }, []),
    )

    const role = auth.identity?.role ?? null
    const signedIn = auth.status === 'signed-in'

    // THE EDITOR'S CHUNK IS FETCHED BEFORE ANYBODY ASKS FOR IT. Monaco is larger than the rest
    // of this bundle and two screens behind this shell open it, so once there is a session and
    // the browser has nothing else to do, the chunk is pulled. It is idle-time work and it
    // happens once: no screen waits on it, and the login page is outside this shell and asks
    // for nothing.
    useEffect(() => {
        if (signedIn) warmEditor()
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
                title: collapsed ? 'Expand the navigation' : 'Collapse the navigation',
                group: VIEW_GROUP,
                icon: PanelLeft,
                keywords: ['sidebar', 'rail'],
                run: toggleRail,
            },
            {
                id: 'view:panel',
                title: 'Show or hide the side panel',
                group: VIEW_GROUP,
                icon: PanelRight,
                keywords: ['inspector', 'details'],
                run: togglePanel,
            },
            {
                id: 'view:settings',
                title: 'Open settings',
                group: VIEW_GROUP,
                icon: Settings,
                keywords: ['preferences', 'appearance', 'times', 'account', 'password', 'server'],
                run: openSettings,
            },
            {
                id: 'view:shortcuts',
                title: 'Keyboard shortcuts',
                group: VIEW_GROUP,
                icon: Keyboard,
                keywords: ['keys', 'chords', 'help'],
                run: () => {
                    setShortcutsOpen(true)
                },
            },
            ...MODES.map((mode) => ({
                id: `appearance:${mode}`,
                title: MODE_LABELS[mode],
                group: APPEARANCE_GROUP,
                icon: mode === 'light' ? Sun : mode === 'dark' ? Moon : Monitor,
                keywords: ['theme', 'appearance', mode],
                run: () => {
                    setTheme(mode)
                },
            })),
            ...(signedIn
                ? [
                      {
                          id: 'session:sign-out',
                          title: SIGN_OUT_LABEL,
                          group: SESSION_GROUP,
                          icon: LogOut,
                          keywords: ['logout', 'leave'],
                          run: () => {
                              void signOut().then(() => navigate(LOGIN_PATH, { replace: true }))
                          },
                      },
                  ]
                : []),
        ]
    }, [collapsed, navigate, openSettings, role, setTheme, signedIn])

    useEffect(() => registerActions(actions), [actions])

    const modifier = modifierLabel(applePlatform(navigator.userAgent))

    return (
        <div className="flex h-svh flex-col overflow-hidden">
            {/* THE THREE COLUMNS, AND ONE RULE UNDER ALL OF THEM. The rail's head, the topbar
                and the panel's tab strip are each `h-shell-top`, and the line beneath them is
                drawn once across the whole width rather than three times -- three borders
                meeting at two column edges is a rule that can come apart. */}
            <div className="relative flex min-h-0 flex-1">
                <Rail />
                <div className="flex min-h-0 min-w-0 flex-1 flex-col">
                    <header
                        data-shell-strip="top"
                        className="bg-sidebar flex h-shell-top shrink-0 items-center gap-2 px-3"
                    >
                        {/* The rail is not drawn below the breakpoint, so this is the way to it. */}
                        <Button
                            ref={menu}
                            variant="ghost"
                            size="icon-sm"
                            aria-label={OPEN_NAV_LABEL}
                            className="md:hidden"
                            onClick={() => {
                                setDrawerOpen(true)
                            }}
                        >
                            <Menu className="size-4" aria-hidden />
                        </Button>
                        <div className="flex-1" />
                        <ServerStatusButton />
                        <Tooltip>
                            <TooltipTrigger
                                render={
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        className="text-muted-foreground px-2 font-mono text-xs"
                                        onClick={() => {
                                            paletteOpen.set(true)
                                        }}
                                        aria-label={OPEN_PALETTE_LABEL}
                                    >
                                        {modifier}K
                                    </Button>
                                }
                            />
                            <TooltipContent side="bottom">{OPEN_PALETTE_LABEL}</TooltipContent>
                        </Tooltip>
                        {filled && (
                            <Tooltip>
                                <TooltipTrigger
                                    render={
                                        <Button
                                            variant="ghost"
                                            size="icon-sm"
                                            aria-label={TOGGLE_PANEL_LABEL}
                                            className="hidden md:inline-flex"
                                            onClick={togglePanel}
                                        >
                                            <PanelRight className="size-4" aria-hidden />
                                        </Button>
                                    }
                                />
                                <TooltipContent side="bottom">{TOGGLE_PANEL_LABEL}</TooltipContent>
                            </Tooltip>
                        )}
                    </header>

                    <main className="flex min-h-0 w-full flex-1 flex-col overflow-y-auto px-4 py-6 md:px-8">
                        {auth.status === 'unknown' ? (
                            <PageState loading={problem === null} problem={problem} empty={false}>
                                {null}
                            </PageState>
                        ) : (
                            <Outlet />
                        )}
                    </main>

                    <PanelSheet />
                </div>
                <RightPanel />
                <div
                    data-shell-rule="top"
                    className="bg-border-strong pointer-events-none absolute inset-x-0 top-shell-top z-20 h-px"
                    aria-hidden
                />
            </div>

            <StatusBar onSettings={openSettings} />

            <NavDrawer open={drawerOpen} onClose={closeDrawer} onSettings={openSettings} />

            <CommandPalette />
            <ShortcutsDialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
            {settingsAsked && (
                <Suspense fallback={null}>
                    <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
                </Suspense>
            )}
        </div>
    )
}
