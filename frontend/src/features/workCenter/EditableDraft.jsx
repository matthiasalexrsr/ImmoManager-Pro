import CustomDraftNotice from '../../components/CustomDraftNotice';
import './editableDraft.css';

export default function EditableDraft({ draft, values, onRestore, beforeRestore, busy, children }) {
  return <><CustomDraftNotice draft={draft} currentValues={values} onRestore={onRestore} beforeRestore={beforeRestore} locked={busy} />
    <fieldset className="editable-draft-fields" disabled={busy || draft.blocked}>{children}</fieldset></>;
}
