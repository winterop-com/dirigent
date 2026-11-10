import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router'

import { AccountMenu } from '@winterop-com/sokkel-ui/AccountMenu'
import type { PaletteSearch } from '@winterop-com/sokkel-ui/CommandPalette'
import { IconButton } from '@winterop-com/sokkel-ui/IconButton'
import { Rail } from '@winterop-com/sokkel-ui/Rail'
import { Shell, useShell, type ShortcutGroup } from '@winterop-com/sokkel-ui/Shell'
import { StatusItem, StatusLine } from '@winterop-com/sokkel-ui/StatusLine'
import { useScheme } from '@winterop-com/sokkel-ui/hooks/use-scheme'

import { crumbSlot } from '@/components/Breadcrumb'
import { headSlot } from '@/components/PageHead'
import { PageState } from '@/components/PageState'
import { PanelBar } from '@/components/PanelBar'
import { RightPanel } from '@/components/RightPanel'
import { ServerStatusButton } from '@/components/ServerStatusButton'
import { warmLayout } from '@/components/graph/elk'
import { useAppShortcuts } from '@/hooks/use-app-shortcuts'
import { useSmallScreen } from '@/hooks/use-small-screen'
import { useStore } from '@/hooks/use-store'
import { ApiError, onUnauthorized, type Problem } from '@/lib/api'
import { authStore, refreshIdentity, signOut } from '@/lib/auth'
import { accountWords, PALETTE_WORDS, RAIL_WORDS, SHELL_WORDS, SHORTCUTS_WORDS } from '@/lib/design-system'
import { ICONS } from '@/lib/icons'
import { addressOfId, idResults } from '@/lib/id-jump'
import { LABELS } from '@/lib/labels'
import { loadKindMarks } from '@/lib/marks'
import { DASHBOARD_PATH, DESIGN_PATH, entriesFor, LOGIN_PATH, railGroups } from '@/lib/nav'
import {
    APPEARANCE_GROUP,
    GO_GROUP,
    paletteActions,
    paletteGroups,
    registerActions,
    SESSION_GROUP,
    VIEW_GROUP,
    type PaletteAction,
} from '@/lib/palette'
import {
    RAIL_MAX_WIDTH,
    RAIL_MIN_WIDTH,
    RAIL_WIDTH,
    panelOpen,
    panelSheet,
    panelTabs,
    railCollapsed,
    railHidden,
    railWidth,
    setRailCollapsed,
    setRailWidth,
    toggleRail,
    togglePanel,
} from '@/lib/panels'
import { screenStatus } from '@/lib/screen-status'
import { identityLine, serverStatus } from '@/lib/server-status'
import { applePlatform, modifierLabel, shortcuts } from '@/lib/shortcuts'
import { MODE_ICONS, MODES, MODE_LABELS } from '@/lib/theme'
import { loadContributedWording } from '@/lib/wording'
import { warmEditor } from '@/components/pipeline/CodePane'

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

/** The keys this app answers itself, listed in the shell's shortcuts dialog after the shell's own. */
const SHORTCUT_GROUPS: readonly ShortcutGroup[] = [
    { title: LABELS.shell.shortcuts_general, shortcuts: shortcuts(applePlatform(navigator.userAgent)) },
]

/**
 * The chassis, sokkel-ui's `Shell`: the rail on the left with the account at its foot, the
 * screen in the middle under the top bar, the screen's status along the foot, and the side panel
 * on the right where the screen fills one.
 *
 * NO SCREEN IS DRAWN UNTIL THE IDENTITY IS KNOWN. A screen that rendered first would fire its
 * reads first, and every one of them would be a request the server answers 401 to. So the shell
 * renders its own frame and waits, which takes one round trip.
 */
export function AppShell() {
    const auth = useStore(authStore)
    const hidden = useStore(railHidden)
    const collapsed = useStore(railCollapsed)
    const width = useStore(railWidth)
    const tabs = useStore(panelTabs)
    const small = useSmallScreen()
    const open = useStore(small ? panelSheet : panelOpen)
    const actions = useStore(paletteActions)
    const server = useStore(serverStatus)
    const { pathname } = useLocation()
    const navigate = useNavigate()
    const { scheme, setScheme } = useScheme()
    const [shortcutsOpen, setShortcutsOpen] = useState(false)
    const [settingsOpen, setSettingsOpen] = useState(false)
    const [settingsAsked, setSettingsAsked] = useState(false)
    const [settingsPane, setSettingsPane] = useState<string | null>(null)
    const [problem, setProblem] = useState<Problem | null>(null)

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

    const leave = useCallback(() => {
        void signOut().then(() => navigate(LOGIN_PATH, { replace: true }))
    }, [navigate])

    useAppShortcuts()

    const role = auth.identity?.role ?? null
    const signedIn = auth.status === 'signed-in'

    // THE TWO BIG CHUNKS ARE FETCHED BEFORE ANYBODY ASKS FOR THEM. The editor and elk are each
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

    const shellActions = useMemo<PaletteAction[]>(() => {
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
                title: LABELS.shell.toggle_panel,
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
                          title: LABELS.action.sign_out,
                          group: SESSION_GROUP,
                          icon: ICONS.sign_out,
                          keywords: ['logout', 'leave'],
                          run: leave,
                      },
                  ]
                : []),
        ]
    }, [hidden, leave, navigate, openSettings, role, setScheme, signedIn])

    useEffect(() => registerActions(shellActions), [shellActions])

    const palette = useMemo(() => paletteGroups(actions), [actions])
    const paletteSearch = useMemo<PaletteSearch>(
        () => ({
            search: idResults,
            onOpen: (result) => {
                void addressOfId(result.id).then((path) => navigate(path))
            },
            debounce: 0,
        }),
        [navigate],
    )

    const setHead = useCallback((element: HTMLDivElement | null) => {
        headSlot.set(element)
    }, [])

    const panel = tabs.length === 0 ? undefined : <RightPanel />

    const identity = auth.identity
    return (
        <Shell
            rail={
                <Rail
                    mark={<ICONS.brand className="size-4" aria-hidden />}
                    name={LABELS.shell.wordmark}
                    markHref={DASHBOARD_PATH}
                    groups={railGroups(role, pathname)}
                    collapsed={collapsed}
                    onCollapsedChange={setRailCollapsed}
                    size={width}
                    onSizeChange={setRailWidth}
                    minSize={RAIL_MIN_WIDTH}
                    maxSize={RAIL_MAX_WIDTH}
                    defaultSize={RAIL_WIDTH}
                    words={RAIL_WORDS}
                    foot={
                        identity === null ? undefined : (
                            <AccountMenu
                                name={identity.username}
                                where={identityLine(server)}
                                onSettings={openSettings}
                                scheme={scheme}
                                onSchemeChange={setScheme}
                                onSignOut={leave}
                                words={accountWords(identity.username)}
                            />
                        )
                    }
                />
            }
            railMode={hidden ? 'hidden' : undefined}
            route={pathname}
            top={<TopStrip onServer={openServerPane} />}
            foot={<ScreenStatusLine version={server.version} />}
            bottom={small ? <PanelBar /> : undefined}
            panel={panel}
            panelOpen={open}
            onPanelOpenChange={(next) => {
                if (small) panelSheet.set(next)
                else if (next !== panelOpen.get()) togglePanel()
            }}
            palette={palette}
            paletteFilter="terms"
            paletteSearch={paletteSearch}
            paletteWords={PALETTE_WORDS}
            paletteFoot={{
                mark: <ICONS.brand className="size-4" aria-hidden />,
                name: LABELS.shell.wordmark,
            }}
            shortcuts={SHORTCUT_GROUPS}
            shortcutsOpen={shortcutsOpen}
            onShortcutsOpenChange={setShortcutsOpen}
            shortcutsWords={SHORTCUTS_WORDS}
            words={SHELL_WORDS}
        >
            <div className="flex h-full min-h-0 flex-col">
                <div ref={setHead} data-page-head className="shrink-0 px-4 pt-3 md:px-8" />
                <div data-page-scroller className="dg-scroller flex min-h-0 flex-1 flex-col pt-px">
                    {auth.status === 'unknown' ? (
                        <PageState loading={problem === null} problem={problem} empty={false}>
                            {null}
                        </PageState>
                    ) : (
                        <Outlet />
                    )}
                </div>
            </div>
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
        </Shell>
    )
}

/**
 * The top bar: the screen's crumb at its left, drawn there by `Breadcrumb`, then the palette's
 * button, which is the search glyph with the chord on its tooltip, and the instance's dot, last.
 */
function TopStrip({ onServer }: { onServer: () => void }) {
    const { openPalette } = useShell()
    const setSlot = useCallback((element: HTMLDivElement | null) => {
        crumbSlot.set(element)
    }, [])
    const modifier = modifierLabel(applePlatform(navigator.userAgent))
    return (
        <>
            <div ref={setSlot} data-shell-crumb className="flex min-w-0 items-center" />
            <div className="flex-1" />
            <IconButton
                label={LABELS.shell.open_palette}
                shortcut={LABELS.shell.palette_chord(modifier)}
                size="icon-sm"
                className="text-muted-foreground"
                onClick={openPalette}
            >
                <ICONS.search aria-hidden />
            </IconButton>
            <ServerStatusButton onOpen={onServer} />
        </>
    )
}

/** The foot: what the screen is doing, its identifier in mono, and the version the instance runs. */
function ScreenStatusLine({ version }: { version: string | null }) {
    const status = useStore(screenStatus)
    return (
        <StatusLine note={status.note ?? undefined} tone={status.tone} live={status.tone === 'live'}>
            {status.identifier !== null && <StatusItem code>{status.identifier}</StatusItem>}
            {version !== null && (
                <StatusItem label={LABELS.word.version.term} code>
                    {version}
                </StatusItem>
            )}
        </StatusLine>
    )
}
