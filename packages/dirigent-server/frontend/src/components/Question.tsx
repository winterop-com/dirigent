/** A confirm's question around the code of the thing it is about: "Delete ", the code in mono, "?". */
export function Question({ ask, code }: { ask: { before: string; after: string }; code: string }) {
    return (
        <>
            {ask.before}
            <span className="font-mono break-all">{code}</span>
            {ask.after}
        </>
    )
}
