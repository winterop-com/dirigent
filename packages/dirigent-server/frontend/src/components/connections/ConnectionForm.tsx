import { GroupLabel } from '@winterop-com/sokkel-ui/GroupLabel'
import { TextField } from '@winterop-com/sokkel-ui/TextField'
import { GeneratedForm } from '@/components/schema/GeneratedForm'
import { Refusal } from '@/components/Refusal'
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
            <TextField
                id="connection-name"
                label={LABELS.word.name.label}
                value={form.named}
                onChange={form.setNamed}
            />

            <TextField
                id="connection-description"
                label={LABELS.word.description}
                multiline
                rows={3}
                maxRows={8}
                value={form.description}
                onChange={form.setDescription}
                placeholder={LABELS.connections.description_placeholder}
            />

            <div className="space-y-3">
                <GroupLabel as="h3">{LABELS.connections.settings_heading}</GroupLabel>
                <GeneratedForm form={form.form} />
            </div>

            {form.problem !== null && <Refusal problem={form.problem} />}
        </>
    )
}
