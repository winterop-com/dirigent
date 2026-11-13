import { useState } from 'react'

import { InlineCode } from '@winterop-com/sokkel-ui/InlineCode'
import { ConfirmDialog } from '@winterop-com/sokkel-ui/DialogShell'
import { ProblemLine } from '@winterop-com/sokkel-ui/Problem'
import { Surface } from '@winterop-com/sokkel-ui/Section'
import { Question } from '@/components/Question'
import { DescriptionList } from '@winterop-com/sokkel-ui/DescriptionList'
import { DialogShell } from '@winterop-com/sokkel-ui/DialogShell'
import { Refusable } from '@/components/Refusable'
import { CopyButton } from '@winterop-com/sokkel-ui/CopyButton'
import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import { SecretReveal } from '@winterop-com/sokkel-ui/SecretReveal'
import { useMayWrite } from '@/hooks/use-may-write'
import type { Problem } from '@/lib/api'
import { copyWords, DIALOG_WORDS, secretWords } from '@/lib/library-words'
import { LABELS } from '@/lib/labels'
import { refusalLine, refusalOf } from '@/lib/refusal'
import {
    authLine,
    curlLine,
    endpointUrl,
    listensTo,
    rotatable,
    rotateSourceToken,
    type SourceOut,
    type SourceTokenOut,
} from '@/lib/sources'

/** The origin this bundle was served from, which is the instance a caller reaches. */
function origin(): string {
    return window.location.origin
}

/**
 * Where a received source is called: its methods and the full URL, in mono, with a copy button.
 * Nothing for a source no request reaches.
 */
export function EndpointAddress({ source }: { source: Pick<SourceOut, 'methods' | 'url_path'> }) {
    const url = endpointUrl(origin(), source)
    if (url === null || source.methods.length === 0) return null
    return (
        <span className="flex min-w-0 items-start gap-2" data-testid="endpoint-address">
            <InlineCode
                value={source.methods.join(', ')}
                className="shrink-0 leading-6"
                tone="neutral"
                bare
                size="xs"
            />
            {/* The URL wraps rather than truncates, so all of it is on screen. */}
            <code className="min-w-0 flex-1 font-mono text-xs leading-6 break-all">{url}</code>
            <CopyButton value={url} size="icon-xs" words={copyWords(LABELS.triggers.source.copy_url)} />
        </span>
    )
}

/**
 * What a source listens to and how its caller authenticates, as facts, and the verb that
 * replaces its credential where it has one.
 */
export function SourceFacts({
    source,
    body,
    onReplaced,
}: {
    source: SourceOut
    body: unknown
    onReplaced?: (row: SourceOut) => void
}) {
    const listens = listensTo(source)
    const auth = authLine(source)
    return (
        <div className="space-y-3">
            <DescriptionList
                termWidth="auto"
                size="sm"
                items={[
                    ...(listens === null
                        ? []
                        : [
                              {
                                  term: LABELS.triggers.source.listens,
                                  value:
                                      source.url_path === null ? (
                                          <span className="font-mono break-all">{listens}</span>
                                      ) : (
                                          <EndpointAddress source={source} />
                                      ),
                              },
                          ]),
                    ...(auth === null ? [] : [{ term: LABELS.triggers.source.auth, value: auth }]),
                ]}
            />
            <NewToken source={source} body={body} onReplaced={onReplaced} />
        </div>
    )
}

/**
 * `New token`, or `New secret` on a signed source: the question first, then the credential the
 * instance made, shown once.
 *
 * `body` is what the curl line in the answer sends, the source's sample body where it has one.
 * `onReplaced` is told the row as it now stands, so the prefix beside the verb moves at once.
 */
export function NewToken({
    source,
    body,
    onReplaced,
}: {
    source: SourceOut
    body: unknown
    onReplaced?: (row: SourceOut) => void
}) {
    const write = useMayWrite()
    const [asking, setAsking] = useState(false)
    const [busy, setBusy] = useState(false)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [minted, setMinted] = useState<SourceTokenOut | null>(null)
    if (!rotatable(source)) return null
    const signed = source.auth === 'hmac'
    const words = LABELS.triggers.replace

    const replace = () => {
        setBusy(true)
        setProblem(null)
        void rotateSourceToken(source.pipeline, source.code).then(
            (token) => {
                setBusy(false)
                setAsking(false)
                setMinted(token)
                onReplaced?.({ ...source, token_prefix: token.prefix, secret_fingerprint: token.fingerprint })
            },
            (error: unknown) => {
                setBusy(false)
                setProblem(refusalOf(error))
            },
        )
    }

    return (
        <>
            <Refusable why={write.why}>
                <Button
                    variant="outline"
                    size="sm"
                    disabled={!write.may}
                    title={write.why}
                    onClick={() => {
                        setProblem(null)
                        setAsking(true)
                    }}
                >
                    {signed ? words.secret : words.token}
                </Button>
            </Refusable>
            <ConfirmDialog
                open={asking}
                onOpenChange={setAsking}
                question={<Question ask={signed ? words.ask_secret : words.ask_token} code={source.code} />}
                detail={words.note}
                confirm={{
                    label: words.verb,
                    onConfirm: replace,
                    destructive: true,
                    busy: busy,
                    busyLabel: words.busy,
                }}
                words={DIALOG_WORDS}
                status={problem === null ? undefined : <ProblemLine>{refusalLine(problem)}</ProblemLine>}
            />
            {minted !== null && (
                <MintedToken
                    token={minted}
                    methods={source.methods}
                    body={body}
                    onClose={() => {
                        setMinted(null)
                    }}
                />
            )}
        </>
    )
}

/**
 * A token or a signing secret, the one time it is readable.
 *
 * There is no read that answers this again: closing this dialog is the moment it stops being
 * available to anybody who did not copy it, and the only way back is another, which invalidates
 * this one. Beside it is where to call and how a caller presents it, and for a bearer token a
 * curl line that makes one call with it.
 */
export function MintedToken({
    token,
    methods,
    body,
    onClose,
}: {
    token: SourceTokenOut
    /** The methods the source answers, the first of which the curl line calls with. */
    methods: readonly string[]
    body: unknown
    onClose: () => void
}) {
    const signed = token.auth === 'hmac'
    const url = endpointUrl(origin(), token) ?? token.url_path
    const curl =
        token.auth === 'token'
            ? curlLine({ url, method: methods[0] ?? 'POST', token: token.token, body })
            : null
    const words = LABELS.triggers.token
    return (
        <DialogShell
            words={DIALOG_WORDS}
            open
            onOpenChange={(next) => {
                if (!next) onClose()
            }}
            width="lg"
            title={signed ? words.secret_title(token.code) : words.title(token.code)}
            description={words.lost(signed ? LABELS.triggers.replace.secret : LABELS.triggers.replace.token)}
        >
            <div className="space-y-4">
                <SecretReveal
                    value={token.token}
                    words={secretWords(signed ? words.secret_noun : words.token_noun)}
                    autoFocus
                />

                <div className="space-y-1">
                    <p className="text-xs text-muted-foreground">{words.url}</p>
                    <span className="flex min-w-0 items-center gap-2">
                        <code className="min-w-0 flex-1 font-mono text-xs break-all">{url}</code>
                        <CopyButton
                            value={url}
                            size="icon-xs"
                            words={copyWords(LABELS.triggers.source.copy_url)}
                        />
                    </span>
                </div>

                <div className="space-y-1">
                    <p className="text-xs text-muted-foreground">{words.how}</p>
                    {signed && token.header !== null ? (
                        <>
                            <p className="font-mono text-xs break-all">{words.signed_header(token.header)}</p>
                            <p className="text-xs text-muted-foreground">{words.signed_note}</p>
                        </>
                    ) : (
                        <p className="font-mono text-xs break-all">{words.bearer}</p>
                    )}
                </div>

                {curl !== null && (
                    <div className="space-y-1">
                        <p className="text-xs text-muted-foreground">{words.try_it}</p>
                        <Surface tone="inset" className="flex min-w-0 items-start gap-2 p-2">
                            <code className="min-w-0 flex-1 font-mono text-xs break-all select-all">
                                {curl}
                            </code>
                            <CopyButton
                                value={curl}
                                size="icon-xs"
                                words={copyWords(LABELS.shell.copy_secret(words.curl_noun))}
                            />
                        </Surface>
                    </div>
                )}
            </div>
        </DialogShell>
    )
}
