/**
 * What a refusal is, and which of its parts are worth reading.
 *
 * `Problem.title` IS THE STATUS PHRASE, NOT A HEADING. The server sets it to what the status
 * says -- "Unprocessable Content" -- so a dialog headed by it says the same thing on every
 * refusal it can make. What a person acts on is `detail`, and the failures behind it are
 * `problems`.
 *
 * A SENTENCE IS SAID ONCE. A validation refusal sets `detail` to its own problems joined with
 * "; ", so drawing both puts the same words on screen twice: where the sentence is the list,
 * the list is what is drawn.
 */

import { ApiError, type Problem } from '@/lib/api'

/** How the server joins its problems into one sentence. */
const JOIN = '; '

/** A refusal this bundle made itself, in the shape every refusal off the wire takes. */
export function local(detail: string): Problem {
    // No status phrase: nothing refused this over the wire, so the sentence is the whole of it.
    return { status: 0, title: '', detail, problems: [], instance: null }
}

/** Whatever went wrong, as the one shape a refusal is read in. */
export function refusalOf(error: unknown): Problem {
    if (error instanceof ApiError) return error.problem
    return local('The server did not answer.')
}

/** What is drawn of a refusal: the sentence, and the failures it does not already spell out. */
export function refusalLines(problem: Problem): { detail: string | null; problems: readonly string[] } {
    const detail = problem.detail.trim() === '' ? null : problem.detail
    if (problem.problems.length === 0) return { detail, problems: [] }
    if (detail === problem.problems.join(JOIN)) return { detail: null, problems: problem.problems }
    return { detail, problems: problem.problems }
}

/** The one line a refusal is worth where there is no room for a card. */
export function refusalLine(problem: Problem): string {
    const lines = refusalLines(problem)
    return lines.detail ?? lines.problems.join(JOIN)
}
