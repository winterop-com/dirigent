import { Suspense, lazy } from 'react'
import { Route, Routes } from 'react-router'

import { AppShell } from '@/components/AppShell'
import { PageState } from '@/components/PageState'
import { useStore } from '@/hooks/use-store'
import { LOGIN_PATH } from '@/lib/nav'
import { timesMode } from '@/lib/times'
import { Login } from '@/pages/Login'
import { Pipelines } from '@/pages/Pipelines'
import { Runs } from '@/pages/Runs'
import { NotFound } from '@/pages/screens'

/**
 * A screen whose dependencies no other screen has is fetched when somebody opens it.
 *
 * The run detail screen and the pipeline editor draw a graph, and React Flow and elk together
 * are a larger download than the whole of the rest of this bundle. A lazy route is what keeps
 * them out of the entry chunk every reader pays for, and the loading card is the one every read
 * on every screen shows.
 */
/**
 * The front door, which is a screen rather than a redirect.
 *
 * It composes six reads across three resources and nothing else in this app needs any of that
 * composition, so it is a chunk of its own -- and the reader who lands on it is the one reader
 * who has not yet said which screen they want.
 */
const Dashboard = lazy(() => import('@/pages/Dashboard').then((module) => ({ default: module.Dashboard })))

const RunDetail = lazy(() => import('@/pages/RunDetail').then((module) => ({ default: module.RunDetail })))

/**
 * The pipeline editor draws the same graph and adds an editor to it, so it is a lazy route for
 * the same reason -- and Monaco, which only its source pane needs, is a chunk inside that one.
 *
 * It is mounted at two addresses: one pipeline, and `pipelines/$new`, which is the same screen
 * with no pipeline behind it. A static segment outranks a dynamic one, so a document that has
 * not been applied is reached at the address it will keep answering under once it has been.
 */
const PipelineEditor = lazy(() =>
    import('@/pages/PipelineEditor').then((module) => ({ default: module.PipelineEditor })),
)

/**
 * Two more screens that carry what only they use: the form a credential is edited in, the
 * dialogs a trigger is declared in, and the panels their histories are read in. None of it is
 * on the way to a run, so none of it is in the chunk every reader pays for.
 */
const Connections = lazy(() => import('@/pages/Connections').then((module) => ({ default: module.Connections })))
const Schemas = lazy(() => import('@/pages/Schemas').then((module) => ({ default: module.Schemas })))
const Triggers = lazy(() => import('@/pages/Triggers').then((module) => ({ default: module.Triggers })))

/**
 * The block catalog is a reference somebody goes looking for rather than a stop on the way to a
 * run, so it is lazy for the same reason the two above are: nothing on the path to reading a run
 * needs it.
 */
const Blocks = lazy(() => import('@/pages/Blocks').then((module) => ({ default: module.Blocks })))

/**
 * The admin section, which most readers of this app are never offered.
 *
 * Four screens, a users table with two dialogs behind it and a dashboard that composes five
 * listings, all of it behind a role gate. An operator pays nothing for any of it.
 */
const AdminOverview = lazy(() => import('@/pages/admin/Overview').then((module) => ({ default: module.AdminOverview })))
const AdminUsers = lazy(() => import('@/pages/admin/Users').then((module) => ({ default: module.AdminUsers })))
const AdminWorkers = lazy(() => import('@/pages/admin/Workers').then((module) => ({ default: module.AdminWorkers })))
const AdminAlerting = lazy(() => import('@/pages/admin/Alerting').then((module) => ({ default: module.AdminAlerting })))

/** What stands in the content column while a screen's chunk is being fetched. */
function Loading() {
    return (
        <PageState loading problem={null} empty={false}>
            {null}
        </PageState>
    )
}

/**
 * The route table.
 *
 * CLEAN PATHS, NOT HASHES. The server answers a navigation nothing else claimed with the shell,
 * so `/runs/<id>` is a link that can be pasted, bookmarked, and reloaded. `dirigent_server.ui`
 * is where that fallback lives and what decides a navigation from a fetch.
 *
 * TWO LAYOUTS. Everything inside `AppShell` is drawn in the chassis and needs a session; the
 * login screen is outside it, because there is no navigation to draw for somebody who cannot
 * reach any of it.
 *
 * ADDING A SCREEN: a `<Route>` here and an entry in `NAV` (lib/nav). The rail is drawn from that
 * array and the command palette offers every entry in it, so nothing else has to be told.
 *
 * THE ROOT IS THE HOME SCREEN. It answers "how is this instance doing" before anybody has
 * picked a noun, which is a question no listing answers and the one somebody arriving with no
 * address of their own is asking. Every other screen keeps its own address, so a link to one of
 * them is still a link that can be sent.
 */
export default function App() {
    // WHICH CLOCK IS READ HERE AND NOWHERE ELSE. Every instant in this app is rendered by
    // `lib/format`, which asks `lib/times` which zone to use, and no screen subscribes to that
    // store. This does, and it is the route table: a change builds every route element afresh,
    // so the screen in front of somebody repaints rather than keeping the clock it was drawn
    // with. Subscribing in the shell would not do it -- react-router hands the shell the same
    // element object each time, and React skips a subtree whose element has not changed.
    useStore(timesMode)

    return (
        <Routes>
            <Route path={LOGIN_PATH} element={<Login />} />
            <Route element={<AppShell />}>
                <Route
                    index
                    element={
                        <Suspense fallback={<Loading />}>
                            <Dashboard />
                        </Suspense>
                    }
                />
                <Route path="pipelines" element={<Pipelines />} />
                <Route
                    path="pipelines/$new"
                    element={
                        <Suspense fallback={<Loading />}>
                            <PipelineEditor />
                        </Suspense>
                    }
                />
                <Route
                    path="pipelines/:code"
                    element={
                        <Suspense fallback={<Loading />}>
                            <PipelineEditor />
                        </Suspense>
                    }
                />
                <Route path="runs" element={<Runs />} />
                <Route
                    path="runs/:id"
                    element={
                        <Suspense fallback={<Loading />}>
                            <RunDetail />
                        </Suspense>
                    }
                />
                <Route
                    path="triggers"
                    element={
                        <Suspense fallback={<Loading />}>
                            <Triggers />
                        </Suspense>
                    }
                />
                <Route
                    path="connections"
                    element={
                        <Suspense fallback={<Loading />}>
                            <Connections />
                        </Suspense>
                    }
                />
                <Route
                    path="blocks"
                    element={
                        <Suspense fallback={<Loading />}>
                            <Blocks />
                        </Suspense>
                    }
                />
                <Route
                    path="schemas"
                    element={
                        <Suspense fallback={<Loading />}>
                            <Schemas />
                        </Suspense>
                    }
                />
                <Route
                    path="admin"
                    element={
                        <Suspense fallback={<Loading />}>
                            <AdminOverview />
                        </Suspense>
                    }
                />
                <Route
                    path="admin/users"
                    element={
                        <Suspense fallback={<Loading />}>
                            <AdminUsers />
                        </Suspense>
                    }
                />
                <Route
                    path="admin/workers"
                    element={
                        <Suspense fallback={<Loading />}>
                            <AdminWorkers />
                        </Suspense>
                    }
                />
                <Route
                    path="admin/alerting"
                    element={
                        <Suspense fallback={<Loading />}>
                            <AdminAlerting />
                        </Suspense>
                    }
                />
                <Route path="*" element={<NotFound />} />
            </Route>
        </Routes>
    )
}
