import type { ReactNode } from 'react'
import { toast } from 'sonner'

import { Callout } from '@winterop-com/sokkel-ui/Callout'
import type { DataTableWords } from '@winterop-com/sokkel-ui/DataTable'
import type { PageStateWords, ReadOutcome } from '@winterop-com/sokkel-ui/PageState'
import type { Problem } from '@/lib/api'
import { TABLE_WORDS } from '@/lib/design-system'
import { LABELS } from '@/lib/labels'
import { refusalLine, refusalLines, refusalOf } from '@/lib/refusal'

/**
 * The words of a refusal: the sentence, and under it the failures it does not already spell out.
 *
 * A FAILURE IS A SENTENCE, NOT AN IDENTIFIER. The server writes each one for a person to act on,
 * so the list is set in the prose face and wraps on spaces.
 */
function RefusalWords({ problem }: { problem: Problem }) {
    const lines = refusalLines(problem)
    if (lines.problems.length === 0) return <>{lines.detail}</>
    return (
        <>
            {lines.detail}
            <ul className="list-disc space-y-0.5 pl-4">
                {lines.problems.map((one) => (
                    <li key={one} className="break-words">
                        {one}
                    </li>
                ))}
            </ul>
        </>
    )
}

/**
 * A refusal inside something already on screen: a dialog, a form, a panel, as the library's
 * critical `Callout`.
 *
 * IT IS NOT HEADED BY THE STATUS PHRASE. `Problem.title` is what the status says rather than
 * what happened, so every refusal a dialog can make would be headed "Unprocessable Content".
 * What the server wrote for a person to act on leads instead.
 */
export function Refusal({ problem }: { problem: Problem }) {
    return (
        <Callout tone="critical">
            <RefusalWords problem={problem} />
        </Callout>
    )
}

/** What the library's `PageState` says while a read is on its way, and over one that never came back. */
export const READ_WORDS: Partial<PageStateWords> = {
    loading: LABELS.shell.reading,
    unreachable: LABELS.refusal.no_answer.title,
}

/**
 * A refused read as the library's `PageState` takes it: the refusal's sentence as the diagnostic
 * and its failures listed under it, how the read came back, and the status phrase as the heading
 * over a refusal and an absence.
 */
export function refusedRead(problem: Problem | null): {
    error: ReactNode
    problems: readonly ReactNode[] | undefined
    status: ReadOutcome | undefined
    words: Partial<PageStateWords>
} {
    if (problem === null)
        return { error: undefined, problems: undefined, status: undefined, words: READ_WORDS }
    const lines = refusalLines(problem)
    return {
        // An empty diagnostic still draws the failure, with the list as all it says.
        error: lines.detail ?? '',
        problems: lines.problems,
        status: problem.status === 0 ? 'unreachable' : problem.status,
        words: { ...READ_WORDS, refused: problem.title, missing: problem.title },
    }
}

/**
 * A refused read as the library's `DataTable` draws it in place of its rows: `refusedRead`'s
 * diagnostic, failures and outcome, the table's own `words` headed with the status phrase, and
 * Try again where the read can simply be asked again.
 */
export function refusedTable(
    problem: Problem | null,
    onRetry?: () => void,
    words: Partial<DataTableWords> = TABLE_WORDS,
): {
    error: ReactNode
    problems: readonly ReactNode[] | undefined
    status: ReadOutcome | undefined
    onRetry: (() => void) | undefined
    words: Partial<DataTableWords>
} {
    const read = refusedRead(problem)
    return {
        error: read.error,
        problems: read.problems,
        status: read.status,
        onRetry,
        words: problem === null ? words : { ...words, refused: problem.title, missing: problem.title },
    }
}

/**
 * Say a refusal where the thing refused has nowhere to put one.
 *
 * A row's button and a panel's verb are pressed against a listing, and there is no card beside
 * either -- so the refusal is a toast, which is the one place in this app that says something
 * about a request nothing on screen is waiting for.
 */
export function sayRefusal(error: unknown): void {
    toast.error(refusalLine(refusalOf(error)))
}
