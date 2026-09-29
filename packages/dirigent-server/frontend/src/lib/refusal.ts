/**
 * What a refusal is, and which of its parts are worth reading.
 *
 * THE CODE IS WHAT IS READ, AND `detail` IS THE FALLBACK. A refusal arrives with a dotted code,
 * the params its sentence was written out of, and that sentence already rendered into `detail` by
 * whichever process minted it. The code and the params are the translatable pair, so what is drawn
 * is `lib/wording`'s sentence for the code; `detail` is drawn only where neither table holds one.
 * Otherwise a translated interface says translated chrome around an English refusal.
 *
 * `Problem.title` IS THE STATUS PHRASE, NOT A HEADING. The server sets it to what the status
 * says -- "Unprocessable Content" -- so a dialog headed by it says the same thing on every
 * refusal it can make. What a person acts on is the sentence, and the failures behind it are
 * `problems`.
 *
 * A SENTENCE IS SAID ONCE. A validation refusal sets `detail` to its own problems joined with
 * "; ", so drawing both puts the same words on screen twice: where the sentence is the list,
 * the list is what is drawn.
 */

import { ApiError, type Issue, type Problem } from '@/lib/api'
import { LABELS } from '@/lib/labels'
import { sentenceFor } from '@/lib/wording'

/** How the server joins its problems into one sentence. */
const JOIN = '; '

/** A refusal this bundle made itself, in the shape every refusal off the wire takes. */
export function local(detail: string, code = 'client.no_answer'): Problem {
    // No status phrase: nothing refused this over the wire, so the sentence is the whole of it.
    return { status: 0, title: '', detail, code, params: {}, problems: [], instance: null }
}

/** Whatever went wrong, as the one shape a refusal is read in. */
export function refusalOf(error: unknown): Problem {
    if (error instanceof ApiError) return error.problem
    return local(LABELS.refusal.no_answer.sentence)
}

/** What a refusal says here: this interface's sentence for its code, else the one the server sent. */
export function said(problem: Problem): string {
    return sentenceFor(problem.code, problem.params) ?? problem.detail
}

/** One issue as a line, out of whichever sentence it is drawn in. */
function lineOf(issue: Issue, sentence: string): string {
    return issue.location === null ? sentence : `${issue.location}: ${sentence}`
}

/** One issue as a line: its sentence, prefixed by where it is when it names a place. */
export function issueLine(issue: Issue): string {
    return lineOf(issue, sentenceFor(issue.code, issue.params) ?? issue.message)
}

/** What is drawn of a refusal: the sentence, and the failures it does not already spell out. */
export function refusalLines(problem: Problem): { detail: string | null; problems: readonly string[] } {
    const sentence = said(problem)
    const detail = sentence.trim() === '' ? null : sentence
    const listed = problem.problems.map(issueLine)
    if (listed.length === 0) return { detail, problems: [] }
    // The server built `detail` by joining the sentences IT sent, so that is what says whether the
    // sentence is only the list. Comparing it with what is drawn would miss it whenever the
    // re-rendering changed the words -- which is the whole point of re-rendering them.
    const sent = problem.problems.map((issue) => lineOf(issue, issue.message)).join(JOIN)
    if (detail === listed.join(JOIN) || problem.detail === sent) return { detail: null, problems: listed }
    return { detail, problems: listed }
}

/** The one line a refusal is worth where there is no room for a card. */
export function refusalLine(problem: Problem): string {
    const lines = refusalLines(problem)
    return lines.detail ?? lines.problems.join(JOIN)
}
