import { useEffect, type ReactNode } from 'react'

import { PageHeader, PageState } from '@/components/PageState'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'

/**
 * A screen this milestone reserved the address for and did not build.
 *
 * DELIBERATELY THE SAME THREE STATES A REAL SCREEN HAS. A stub that rendered a bare sentence
 * would be thrown away wholesale later; one built on `PageState` is finished by giving it a
 * read, and the empty state it already states is the empty state it keeps.
 *
 * IT STATES ITS FACT ALONG THE FOOT LIKE ANY OTHER SCREEN, so the bar says something true
 * about what is in front of somebody rather than holding whatever the last screen left there.
 */
export function Stub({
    title,
    description,
    waiting,
    note,
    aside,
}: {
    title: string
    /** The line under the title; a screen whose title says the whole thing carries none. */
    description?: string
    waiting: string
    /** The one fact the status bar states while this screen is open. */
    note: string
    aside?: ReactNode
}) {
    useEffect(() => {
        setScreenStatus({ note, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [note])

    return (
        <>
            <PageHeader title={title} description={description} aside={aside} />
            <PageState loading={false} problem={null} empty emptyMessage={waiting}>
                {null}
            </PageState>
        </>
    )
}
