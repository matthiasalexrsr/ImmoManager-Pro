import { useState, useEffect } from 'react';

export default function FormModal({ title, fields, initial, onSave, onClose }) {
  const [values, setValues] = useState({});
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const init = {};
    fields.forEach(f => {
      init[f.key] = initial?.[f.key] ?? f.default ?? '';
    });
    setValues(init);
  }, [initial, fields]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const cleaned = {};
      fields.forEach(f => {
        let v = values[f.key];
        if (f.type === 'number' && v !== '' && v !== null) v = Number(v);
        if (v === '') v = f.required ? v : null;
        cleaned[f.key] = v;
      });
      await onSave(cleaned);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{title}</h3>
          <button onClick={onClose} className="btn-close">&times;</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {error && <div className="alert alert-error">{error}</div>}
            {fields.map(f => (
              <div key={f.key} className="form-group">
                <label>{f.label}{f.required && ' *'}</label>
                {f.type === 'select' ? (
                  <select
                    value={values[f.key] || ''}
                    onChange={e => setValues({ ...values, [f.key]: e.target.value })}
                    required={f.required}
                  >
                    <option value="">— Auswählen —</option>
                    {f.options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                ) : f.type === 'textarea' ? (
                  <textarea
                    value={values[f.key] || ''}
                    onChange={e => setValues({ ...values, [f.key]: e.target.value })}
                    required={f.required}
                    rows={3}
                  />
                ) : (
                  <input
                    type={f.type || 'text'}
                    value={values[f.key] ?? ''}
                    onChange={e => setValues({ ...values, [f.key]: e.target.value })}
                    required={f.required}
                    step={f.type === 'number' ? '0.01' : undefined}
                    placeholder={f.placeholder}
                  />
                )}
              </div>
            ))}
          </div>
          <div className="modal-footer">
            <button type="button" onClick={onClose} className="btn">Abbrechen</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? 'Speichern...' : 'Speichern'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
