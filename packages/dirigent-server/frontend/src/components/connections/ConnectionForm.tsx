import { GroupLabel } from '@winterop-com/sokkel-ui/GroupLabel'
import { Field } from '@winterop-com/sokkel-ui/Field'
import { GeneratedForm } from '@/components/schema/GeneratedForm'
import { Refusal } from '@/components/Refusal'
import { Input } from '@winterop-com/sokkel-ui/primitives/input'
import { Textarea } from '@winterop-com/sokkel-ui/primitives/textarea'
import { type ConnectionEdit } from '@/hooks/use-connection-edit'
import { LABELS } from '@/lib/labels'

/**
 * The boxes a connection's dialog holds in its edit state.
 *
 * THE KIND AND THE CODE ARE FIXED. `PATCH /connections/{code}` changes the name, the description
 * and the config, and nothing else: a connection of a different kind is a different connection,
 * and one addressed by a different code is a different connection too.
 */
export function ConnectionForm({ form }: { form: ConnectionEdit }) {
    return (
        <>
            <Field id="connection-name" label={LABELS.word.name.label}>
                <Input
                    id="connection-name"
                    value={form.named}
                    onChange={(event) => {
                        form.setNamed(event.target.value)
                    }}
                />
            </Field>

            <Field id="connection-description" label={LABELS.word.description}>
                <Textarea
                    id="connection-description"
                    className="h-20"
                    value={form.description}
                    onChange={(event) => {
                        form.setDescription(event.target.value)
                    }}
                    placeholder={LABELS.connections.description_placeholder}
                />
            </Field>

            <div className="space-y-3">
                <GroupLabel as="h3">{LABELS.connections.settings_heading}</GroupLabel>
                <GeneratedForm form={form.form} />
            </div>

            {form.problem !== null && <Refusal problem={form.problem} />}
        </>
    )
}
