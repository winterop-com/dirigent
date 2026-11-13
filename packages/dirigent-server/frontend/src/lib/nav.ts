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

import type { RailGroup } from '@winterop-com/sokkel-ui/Rail'

import type { UserRole } from '@/lib/auth'
import { ICONS, type Icon } from '@/lib/icons'
import { LABELS } from '@/lib/labels'

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
    icon: Icon
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
        id: 'dashboard',
        label: null,
        requires: null,
        entries: [
            {
                path: DASHBOARD_PATH,
                label: LABELS.screen.dashboard.name,
                hint: LABELS.screen.dashboard.hint,
                icon: ICONS.dashboard,
            },
        ],
    },
    {
        id: 'operate',
        label: LABELS.screen.operate,
        requires: null,
        entries: [
            {
                path: '/runs',
                label: LABELS.screen.runs.name,
                hint: LABELS.screen.runs.hint,
                icon: ICONS.run,
            },
            {
                path: '/triggers',
                label: LABELS.screen.triggers.name,
                hint: LABELS.screen.triggers.hint,
                icon: ICONS.trigger,
            },
        ],
    },
    {
        id: 'build',
        label: LABELS.screen.build,
        requires: null,
        entries: [
            {
                path: '/pipelines',
                label: LABELS.screen.pipelines.name,
                hint: LABELS.screen.pipelines.hint,
                icon: ICONS.pipeline,
            },
            {
                path: '/connections',
                label: LABELS.screen.connections.name,
                hint: LABELS.screen.connections.hint,
                icon: ICONS.connection,
            },
            {
                path: '/schemas',
                label: LABELS.screen.schemas.name,
                hint: LABELS.screen.schemas.hint,
                icon: ICONS.schema,
            },
        ],
    },
    {
        id: 'reference',
        label: LABELS.screen.reference,
        requires: null,
        entries: [
            {
                path: '/blocks',
                label: LABELS.screen.blocks.name,
                hint: LABELS.screen.blocks.hint,
                icon: ICONS.block,
            },
            {
                path: '/examples',
                label: LABELS.screen.examples.name,
                hint: LABELS.screen.examples.hint,
                icon: ICONS.example,
            },
        ],
    },
    {
        id: 'admin',
        label: LABELS.screen.admin,
        requires: 'admin',
        entries: [
            {
                path: '/admin/users',
                label: LABELS.screen.users.name,
                hint: LABELS.screen.users.hint,
                icon: ICONS.users,
            },
            {
                path: '/admin/workers',
                label: LABELS.screen.workers.name,
                hint: LABELS.screen.workers.hint,
                icon: ICONS.worker,
            },
            {
                path: '/admin/alerting',
                label: LABELS.screen.alerting.name,
                hint: LABELS.screen.alerting.hint,
                icon: ICONS.alerting,
            },
            {
                path: '/admin/audit',
                label: LABELS.screen.audit.name,
                hint: LABELS.screen.audit.hint,
                icon: ICONS.recent,
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

/** Every screen an account is offered, flattened, which is what the palette shelves. */
export function entriesFor(role: UserRole | null): NavEntry[] {
    return sectionsFor(role).flatMap((section) => section.entries)
}

/**
 * Whether an entry is marked only at its own address.
 *
 * An entry with other entries beneath it -- the root, which every address is under -- would
 * otherwise be marked wherever any of them is open, and the rail would say the reader is in two
 * places.
 */
export function marksOnlyItself(path: string): boolean {
    const below = path === '/' ? '/' : `${path}/`
    return NAV.flatMap((section) => section.entries).some(
        (entry) => entry.path !== path && entry.path.startsWith(below),
    )
}

/** Whether the rail marks an entry as the screen at this address. */
export function isActive(entryPath: string, pathname: string): boolean {
    if (pathname === entryPath) return true
    return !marksOnlyItself(entryPath) && pathname.startsWith(`${entryPath}/`)
}

/**
 * The rail's groups for this account at this address: each section a group under its heading, each
 * entry a link with its mark, the one at this address active, and its path a word the palette finds
 * it by.
 */
export function railGroups(role: UserRole | null, pathname: string): RailGroup[] {
    return sectionsFor(role).map((section) => ({
        id: section.id,
        title: section.label ?? undefined,
        entries: section.entries.map((entry) => ({
            id: entry.path,
            label: entry.label,
            href: entry.path,
            icon: entry.icon,
            active: isActive(entry.path, pathname),
        })),
    }))
}

/**
 * The rail entry one address is inside, or null.
 *
 * Longest path first, because an entry may be a prefix of another address it does not own.
 */
export function entryAt(path: string): NavEntry | null {
    const candidates = NAV.flatMap((section) => section.entries)
        .filter((entry) => path === entry.path || path.startsWith(`${entry.path}/`))
        .toSorted((left, right) => right.path.length - left.path.length)
    return candidates[0] ?? null
}

/**
 * The screen a path shows, which is what the scroller's place is kept under: a step chosen on a
 * run or a pipeline, and a row chosen in the connections listing, are the screen they were chosen
 * on, so choosing one leaves the page where it is.
 */
export function screenPath(pathname: string): string {
    const parts = pathname.split('/').filter((part) => part !== '')
    if (parts[0] === 'runs' && parts.length > 2) return `/runs/${parts[1]}`
    if (parts[0] === 'pipelines' && parts.length > 2 && parts[2] !== 'edit') return `/pipelines/${parts[1]}`
    if (parts[0] === 'connections' && parts.length > 1) return '/connections'
    return pathname
}
