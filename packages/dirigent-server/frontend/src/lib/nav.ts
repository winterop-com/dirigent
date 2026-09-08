/**
 * The navigation, as data.
 *
 * ONE ARRAY, READ BY THREE THINGS: the rail draws it, the command palette offers every entry as
 * a row, and the router's own table is checked against it. Adding a screen is a route plus an
 * entry here, and nothing else has to learn that the screen exists.
 *
 * THE ADMIN SECTION IS ROLE-GATED, AND THAT IS A COURTESY. The server refuses what an account
 * may not do; hiding the section means nobody is offered a screen that will refuse them.
 * Nothing here is a security boundary, and a reader who types the address still reaches the
 * page and is told by the server what it thinks of them.
 */

import {
    Bell,
    Blocks,
    CalendarClock,
    Cpu,
    FileJson,
    House,
    LayoutDashboard,
    Play,
    Plug,
    Users,
    Workflow,
    type LucideIcon,
} from 'lucide-react'

import type { UserRole } from '@/lib/auth'

/** One entry in the rail: where it goes, what it is called, and the mark beside it. */
export interface NavEntry {
    /** The route path, exactly as the router spells it. */
    path: string
    label: string
    /**
     * The line the command palette carries beside the row, saying what the screen holds.
     *
     * A FRAGMENT, NOT A SENTENCE. It sits on one row of a list being searched, so it takes no
     * full stop and no verb it can do without: what is under Runs is every execution, newest
     * first. The rail does not draw it -- a label that names one of the things this app is
     * made of needs no gloss under it.
     */
    hint: string
    icon: LucideIcon
}

/** A run of entries under one heading. */
export interface NavSection {
    id: string
    /** The heading, or null for the first section, which needs none. */
    label: string | null
    /** The role an account needs before this section is offered at all. */
    requires: UserRole | null
    entries: NavEntry[]
}

/** Where a reader lands with no address of their own, which is a screen rather than a noun. */
export const DASHBOARD_PATH = '/'

/** The login screen, which is where a refused request sends a reader. */
export const LOGIN_PATH = '/login'

/**
 * The editor with no pipeline behind it, which is where a new document is written.
 *
 * It is not a rail entry: writing a pipeline is something done from the listing rather than a
 * screen somebody navigates to and leaves open.
 */
export const NEW_PIPELINE_PATH = '/pipelines/$new'

export const NAV: NavSection[] = [
    {
        id: 'operate',
        label: null,
        requires: null,
        entries: [
            {
                path: DASHBOARD_PATH,
                label: 'Dashboard',
                hint: 'How this instance is doing',
                icon: House,
            },
            {
                path: '/pipelines',
                label: 'Pipelines',
                hint: 'Definitions and their versions',
                icon: Workflow,
            },
            {
                path: '/runs',
                label: 'Runs',
                hint: 'Every execution, newest first',
                icon: Play,
            },
            {
                path: '/triggers',
                label: 'Triggers',
                hint: 'Clocks and inbound endpoints',
                icon: CalendarClock,
            },
            {
                path: '/connections',
                label: 'Connections',
                hint: 'Named credentials and their health',
                icon: Plug,
            },
            {
                path: '/blocks',
                label: 'Blocks',
                hint: 'What the plugins contribute',
                icon: Blocks,
            },
            {
                path: '/schemas',
                label: 'Schemas',
                hint: 'Shapes a payload is checked against',
                icon: FileJson,
            },
        ],
    },
    {
        id: 'admin',
        label: 'Admin',
        requires: 'admin',
        entries: [
            {
                path: '/admin',
                label: 'Overview',
                hint: 'This instance, at a glance',
                icon: LayoutDashboard,
            },
            {
                path: '/admin/users',
                label: 'Users',
                hint: 'Accounts and automation tokens',
                icon: Users,
            },
            {
                path: '/admin/workers',
                label: 'Workers',
                hint: 'The nodes claiming work',
                icon: Cpu,
            },
            {
                path: '/admin/alerting',
                label: 'Alerting',
                hint: 'Rules and the delivery queue',
                icon: Bell,
            },
        ],
    },
]

/**
 * The sections this account is offered.
 *
 * A role of null is somebody whose identity has not been read yet, and they are offered the
 * ungated sections rather than nothing: the rail is drawn once and gains its admin section when
 * the read lands, instead of the whole navigation appearing a frame late.
 */
export function sectionsFor(role: UserRole | null): NavSection[] {
    return NAV.filter((section) => section.requires === null || section.requires === role)
}

/** Every entry an account is offered, flattened, which is what the palette shelves. */
export function entriesFor(role: UserRole | null): NavEntry[] {
    return sectionsFor(role).flatMap((section) => section.entries)
}

/**
 * Whether an entry is marked only at its own address.
 *
 * An entry with other entries beneath it -- the root, which every address is under, and
 * `/admin`, which the three admin screens sit below -- would otherwise be marked wherever any
 * of them is open, and the rail would say the reader is in two places.
 */
export function marksOnlyItself(path: string): boolean {
    const below = path === '/' ? '/' : `${path}/`
    return NAV.flatMap((section) => section.entries).some(
        (entry) => entry.path !== path && entry.path.startsWith(below),
    )
}

/**
 * The entry one address is inside, or null.
 *
 * Longest path first, so `/admin/users` marks Users rather than Overview: `/admin` is a prefix
 * of every admin address, and a rail that marked both would say the reader is in two places.
 */
export function entryAt(path: string): NavEntry | null {
    const candidates = NAV.flatMap((section) => section.entries)
        .filter((entry) => path === entry.path || path.startsWith(`${entry.path}/`))
        .toSorted((left, right) => right.path.length - left.path.length)
    return candidates[0] ?? null
}
