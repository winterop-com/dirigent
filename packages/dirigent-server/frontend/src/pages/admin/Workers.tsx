import { useCallback, useEffect } from 'react'

import { RefreshCw } from 'lucide-react'

import { ApiChip } from '@/components/ApiChip'
import { AdminOnly } from '@/components/admin/AdminOnly'
import { WorkersTable } from '@/components/admin/WorkersTable'
import { PageHeader } from '@/components/PageState'
import { usePaged } from '@/hooks/use-paged'
import { ADMIN_GROUP, registerActions } from '@/lib/palette'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { readWorkers, worstConcern, concernNote, type WorkerOut } from '@/lib/workers'

const workerId = (worker: WorkerOut) => worker.id

/**
 * The whole registry, walked a page at a time.
 *
 * THE TABLE IS THE DASHBOARD'S. One implementation, drawn small on the overview and whole here,
 * so the two cannot come to disagree about what a stale worker looks like.
 *
 * THE STATUS BAR CARRIES THE WORST FACT. The tile on the dashboard states it because a
 * dashboard is read at a glance; this screen states it along the foot because somebody who
 * opened the registry has already been told there is something to find and wants to know what.
 */
export function AdminWorkers() {
    return (
        <AdminOnly>
            <Workers />
        </AdminOnly>
    )
}

function Workers() {
    const workers = usePaged(
        useCallback((after: string | null) => readWorkers(after), []),
        workerId,
    )

    const { reload } = workers
    const worst = worstConcern(workers.state.rows)

    // Two strings rather than the worker itself: `worstConcern` answers a fresh object every
    // render, and an effect keyed on it would clear and restate the bar on every one of them.
    const note = worst === null ? 'every worker is answering' : concernNote(worst.worker, worst.concern)
    const tone = worst === null ? 'quiet' : 'warn'

    useEffect(() => {
        setScreenStatus({ note, tone, identifier: null })
        return clearScreenStatus
    }, [note, tone])

    useEffect(() => {
        return registerActions([
            {
                id: 'workers:reload',
                title: 'Read the worker registry again',
                group: ADMIN_GROUP,
                screen: true,
                icon: RefreshCw,
                keywords: ['refresh', 'reload'],
                run: reload,
            },
        ])
    }, [reload])

    return (
        <>
            <PageHeader title="Workers" aside={<ApiChip tag="workers" />} />
            <WorkersTable
                state={workers.state}
                more={workers.more}
                empty="No workers. Start one with dg worker; nothing is claimed until one registers."
            />
        </>
    )
}
