import { useCallback, useEffect } from 'react'

import { RefreshCw } from 'lucide-react'

import { ApiChip } from '@/components/ApiChip'
import { AdminOnly } from '@/components/admin/AdminOnly'
import { WorkersTable } from '@/components/admin/WorkersTable'
import { PageHeader } from '@/components/ds/PageHeader'
import { usePaged } from '@/hooks/use-paged'
import { LABELS } from '@/lib/labels'
import { ADMIN_GROUP, registerActions } from '@/lib/palette'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { readWorkers, worstConcern, concernNote, type WorkerOut } from '@/lib/workers'

const workerId = (worker: WorkerOut) => worker.id

/**
 * The whole registry, walked a page at a time.
 *
 * THE STATUS BAR CARRIES THE WORST FACT, along the foot, because somebody who opened the registry
 * has already been told there is something to find and wants to know what.
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
    const note = worst === null ? LABELS.workers.all_answering : concernNote(worst.worker, worst.concern)
    const tone = worst === null ? 'quiet' : 'warn'

    useEffect(() => {
        setScreenStatus({ note, tone, identifier: null })
        return clearScreenStatus
    }, [note, tone])

    useEffect(() => {
        return registerActions([
            {
                id: 'workers:reload',
                title: LABELS.workers.reload_action,
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
            <PageHeader title={LABELS.screen.workers.name} aside={<ApiChip tag="workers" />} />
            <WorkersTable state={workers.state} more={workers.more} empty={LABELS.workers.empty} />
        </>
    )
}
