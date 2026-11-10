import { useEffect, type ReactNode } from 'react'
import { useLocation } from 'react-router'

import { PageHeader } from '@/components/ds/PageHeader'
import { PageState } from '@/components/PageState'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'

/**
 * A screen with a heading and one sentence and nothing to read: the address nothing answers.
 *
 * DELIBERATELY THE SAME THREE STATES A REAL SCREEN HAS, built on `PageState`, so a screen that
 * starts here is finished by giving it a read.
 *
 * Its identifier in the top strip is the address it was opened at, which is the one fact the
 * heading and the sentence do not already say.
 */
export function Stub({ title, waiting, aside }: { title: string; waiting: string; aside?: ReactNode }) {
    const { pathname } = useLocation()
    useEffect(() => {
        setScreenStatus({ note: null, tone: 'quiet', identifier: pathname })
        return clearScreenStatus
    }, [pathname])

    return (
        <>
            <PageHeader title={title} lead={aside} />
            <PageState loading={false} problem={null} empty emptyMessage={waiting}>
                {null}
            </PageState>
        </>
    )
}
