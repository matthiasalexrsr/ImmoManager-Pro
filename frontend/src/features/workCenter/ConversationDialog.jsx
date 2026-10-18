import { useRef } from 'react';
import FormModal from '../../components/FormModal';
import { api } from '../../api';
import { workspace } from '../../utils/workspaceClient';

export default function ConversationDialog({ entityType, entityId, entityRevision, title, initial, onClose, onSaved }) {
  const command = useRef(workspace.command());
  const payloadRef = useRef(null);
  const revision = useRef(entityRevision);
  const fields = [
    { key: 'conversation_kind', label: 'Art', type: 'select', default: 'note', required: true, options: [
      { value: 'note', label: 'Notiz' }, { value: 'phone', label: 'Telefonat' }, { value: 'email', label: 'E-Mail' }, { value: 'meeting', label: 'Besprechung' },
    ] },
    { key: 'body', label: 'Gesprächsnotiz', type: 'textarea', required: true },
    { section: 'Wiedervorlage (optional)', key: 'follow_up_title', label: 'Aufgabe' },
    { section: 'Wiedervorlage (optional)', key: 'follow_up_due', label: 'Fällig am', type: 'date' },
    { section: 'Wiedervorlage (optional)', key: 'follow_up_assignee', label: 'Zuständig' },
    { section: 'Wiedervorlage (optional)', key: 'follow_up_priority', label: 'Priorität', type: 'select', default: 'medium', options: [
      { value: 'low', label: 'Niedrig' }, { value: 'medium', label: 'Mittel' }, { value: 'high', label: 'Hoch' },
    ] },
  ];
  const save = async values => {
    if (!values.body?.trim()) throw new Error('Bitte eine Gesprächsnotiz eingeben.');
    if (!values.follow_up_title?.trim() && (values.follow_up_due || values.follow_up_assignee)) throw new Error('Bitte eine Aufgabe für die Wiedervorlage benennen.');
    const payload = { entity_type: entityType, entity_id: entityId, base_revision: revision.current,
      body: values.body.trim(), conversation_kind: values.conversation_kind,
      ...(values.follow_up_title?.trim() ? { follow_up: { title: values.follow_up_title.trim(), due_date: values.follow_up_due || null,
        assignee: values.follow_up_assignee || null, priority: values.follow_up_priority || 'medium' } } : {}) };
    const serialized = JSON.stringify(payload);
    // A retry after an unknown network outcome repeats the same command. An edited
    // payload is a new command, so it cannot replay another conversation by accident.
    if (payloadRef.current !== null && payloadRef.current !== serialized) command.current = workspace.command();
    payloadRef.current = serialized;
    const result = await api.post('/work-center/notes', { ...payload, idempotency_key: command.current });
    onSaved?.(result);
  };
  return <FormModal title={`Gespräch / Wiedervorlage · ${title || 'Vorgang'}`} fields={fields} initial={initial} onSave={save} onClose={onClose}
    draftContext="conversation-note" draftAnchor={{ kind: entityType, id: entityId }}
    onDraftRebase={source => { revision.current = source.revision; }} />;
}
