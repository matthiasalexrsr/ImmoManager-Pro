import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Archive, Copy, FilePlus2, Pencil } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { mayWrite } from '../utils/permissions';
import { templatesService } from '../features/letters/lettersApi';
import '../features/letters/letters.css';

const TEXTS = [
  { key: 'subject', label: 'Betreff', rows: 1 },
  { key: 'salutation', label: 'Anrede', rows: 1 },
  { key: 'body', label: 'Text', rows: 16 },
  { key: 'closing', label: 'Schlussformel', rows: 2 },
  { key: 'appendix', label: 'Anhang nach der Unterschrift (z. B. Zustimmungserklärung)', rows: 5 },
];

const blank = kind => ({ kind, name: '', subject: '', salutation: 'Guten Tag {{mieter.name}},', body: '', closing: 'Mit freundlichen Grüßen', appendix: '' });

/** Built-in and own letter templates; own ones are edited against their revision. */
export default function LetterTemplates({ service = templatesService }) {
  const auth = useAuth();
  const canEdit = Boolean(auth?.user && auth.user.role !== 'readonly' && mayWrite(auth?.write ?? null, '/letter-templates'));
  const [data, setData] = useState(null);
  const [archived, setArchived] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [editor, setEditor] = useState(null);
  const [busy, setBusy] = useState(false);
  const focused = useRef({ key: 'body', element: null });
  const command = useRef(null);

  const load = useCallback(async () => {
    try { setData(await service.list(archived)); setError(''); }
    catch (problem) { setError(problem.message || 'Die Briefvorlagen konnten nicht geladen werden.'); }
  }, [service, archived]);
  useEffect(() => { void load(); }, [load]);

  const kinds = Object.fromEntries((data?.kinds || []).map(kind => [kind.kind, kind]));
  const open = (template, copy = false) => {
    command.current = null; setNotice(''); setError('');
    if (!template) { setEditor({ mode: 'new', values: blank('free') }); return; }
    const values = Object.fromEntries(['kind', 'name', ...TEXTS.map(text => text.key)].map(key => [key, template[key] ?? '']));
    if (copy) setEditor({ mode: 'new', values: { ...values, name: `${template.name} (eigene Fassung)` }, basedOn: template.builtin ? template.id : null });
    else setEditor({ mode: template.builtin ? 'view' : 'edit', values, id: template.id, revision: template.revision, archived: template.archived });
  };
  const change = (key, value) => { command.current = null; setEditor(old => ({ ...old, values: { ...old.values, [key]: value } })); };
  const insert = token => {
    if (!editor || editor.mode === 'view') return;
    const { key, element } = focused.current;
    const current = editor.values[key] ?? '';
    const start = element?.selectionStart ?? current.length;
    const end = element?.selectionEnd ?? current.length;
    const block = token.startsWith('{{tabelle.');
    const before = current.slice(0, start);
    const text = block ? `${before && !before.endsWith('\n') ? '\n' : ''}${token}\n` : token;
    change(key, before + text + current.slice(end));
    requestAnimationFrame(() => { element?.focus(); const position = (before + text).length; element?.setSelectionRange?.(position, position); });
  };
  const save = async (archive = null) => {
    if (busy || !editor) return;
    setBusy(true); setError(''); setNotice('');
    const values = { ...editor.values };
    try {
      if (!command.current) command.current = crypto.randomUUID();
      if (editor.mode === 'new') {
        const saved = await service.create({ ...values, based_on: editor.basedOn || null, idempotency_key: command.current });
        setNotice(`Vorlage „${saved.name}“ angelegt.`);
      } else {
        const { kind: _kind, ...texts } = values;
        const saved = await service.update(editor.id, { ...texts, archived: archive ?? Boolean(editor.archived), base_revision: editor.revision, idempotency_key: command.current });
        setNotice(archive ? `Vorlage „${saved.name}“ archiviert.` : archive === false ? `Vorlage „${saved.name}“ wiederhergestellt.` : `Vorlage „${saved.name}“ gespeichert.`);
      }
      command.current = null; setEditor(null); await load();
    } catch (problem) {
      if (problem?.statusCode !== undefined && problem.statusCode < 500) command.current = null;
      setError(problem.message || 'Die Vorlage konnte nicht gespeichert werden.');
    } finally { setBusy(false); }
  };

  const builtin = (data?.items || []).filter(item => item.builtin);
  const own = (data?.items || []).filter(item => !item.builtin);
  const kind = editor ? kinds[editor.values.kind] : null;
  const readOnly = !editor || editor.mode === 'view' || !canEdit;

  const card = template => <li key={template.id} className={`letter-template-card${template.archived ? ' is-archived' : ''}`}>
    <div><strong>{template.name}</strong>{!template.builtin && <span>{kinds[template.kind]?.label || template.kind}{template.archived ? ' · archiviert' : ''}</span>}</div>
    <div className="letters-actions">
      {template.builtin ? <>
        <button type="button" className="btn btn-sm btn-secondary" onClick={() => open(template)}>Ansehen</button>
        {canEdit && <button type="button" className="btn btn-sm btn-secondary" onClick={() => open(template, true)}><Copy size={14} aria-hidden="true" /> Als eigene Vorlage kopieren</button>}
      </> : <>
        <button type="button" className="btn btn-sm btn-secondary" onClick={() => open(template)}><Pencil size={14} aria-hidden="true" /> {canEdit ? 'Bearbeiten' : 'Ansehen'}</button>
        {canEdit && <button type="button" className="btn btn-sm btn-secondary" onClick={() => open(template, true)}><Copy size={14} aria-hidden="true" /> Kopieren</button>}
      </>}
    </div>
  </li>;

  return (
    <div className="page letter-templates-page">
      <div className="page-header-row">
        <h1 className="page-title">Briefvorlagen</h1>
        {canEdit && <button type="button" className="btn btn-primary" onClick={() => open(null)}><FilePlus2 size={16} aria-hidden="true" /> Neue Vorlage</button>}
      </div>
      <p className="letters-intro">Briefe schreiben Sie am Vertrag oder in der Parteiakte („Brief schreiben“). Platzhalter wie <code>{'{{mieter.name}}'}</code> füllt das Programm aus dem Vertrag. Die mitgelieferten Vorlagen prüfen Fristen und Grenzen, zum Beispiel die Kappungsgrenze bei der Mieterhöhung. Den Briefkopf legen Sie unter <Link to="/settings?section=letterhead">Einstellungen → Briefkopf</Link> fest.</p>
      {error && <p className="letters-error" role="alert">{error}</p>}
      {notice && <p className="letters-notice" role="status">{notice}</p>}
      {!data && !error && <p role="status">Briefvorlagen werden geladen …</p>}
      {data && !editor && <>
        <h2 className="letters-heading">Mitgelieferte Vorlagen</h2>
        <ul className="letter-template-list">{builtin.map(card)}</ul>
        <div className="letters-heading-row"><h2 className="letters-heading">Eigene Vorlagen</h2>
          <label className="letters-check"><input type="checkbox" checked={archived} onChange={event => setArchived(event.target.checked)} /> Archivierte zeigen</label></div>
        {own.length ? <ul className="letter-template-list">{own.map(card)}</ul>
          : <p className="letters-hint">Noch keine eigenen Vorlagen. Kopieren Sie eine mitgelieferte Vorlage, um ihren Text anzupassen; Prüfungen und Angaben bleiben erhalten.</p>}
      </>}
      {editor && <div className="letter-template-editor">
        <form className="letter-template-form" onSubmit={event => { event.preventDefault(); void save(); }}>
          <h2 className="letters-heading">{editor.mode === 'new' ? 'Neue Vorlage' : editor.mode === 'view' ? 'Mitgelieferte Vorlage (nur lesen)' : 'Vorlage bearbeiten'}</h2>
          <div className="letters-field"><label htmlFor="template-kind">Art</label>
            <select id="template-kind" value={editor.values.kind} disabled={editor.mode !== 'new' || Boolean(editor.basedOn)} onChange={event => change('kind', event.target.value)}>
              {(data?.kinds || []).map(item => <option key={item.kind} value={item.kind}>{item.label}</option>)}
            </select>
            <small>{kind?.description}{editor.mode === 'new' ? ' Die Art bestimmt Angaben und Prüfungen und lässt sich später nicht ändern.' : ''}</small></div>
          <div className="letters-field"><label htmlFor="template-name">Name</label>
            <input id="template-name" value={editor.values.name} readOnly={readOnly} required maxLength={120} onChange={event => change('name', event.target.value)} /></div>
          {TEXTS.map(text => <div key={text.key} className="letters-field"><label htmlFor={`template-${text.key}`}>{text.label}</label>
            {text.rows > 1
              ? <textarea id={`template-${text.key}`} rows={text.rows} value={editor.values[text.key]} readOnly={readOnly} onFocus={event => { focused.current = { key: text.key, element: event.target }; }} onChange={event => change(text.key, event.target.value)} />
              : <input id={`template-${text.key}`} value={editor.values[text.key]} readOnly={readOnly} required={text.key === 'subject'} onFocus={event => { focused.current = { key: text.key, element: event.target }; }} onChange={event => change(text.key, event.target.value)} />}
          </div>)}
          <p className="letters-hint">Absätze trennt eine Leerzeile. Zeilen mit „- “ werden Aufzählungen, <code>**Text**</code> wird fett. Tabellen-Platzhalter stehen allein in einer Zeile.</p>
          <div className="letters-actions">
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => { setEditor(null); setError(''); }}>{readOnly ? 'Schließen' : 'Abbrechen'}</button>
            {editor.mode === 'edit' && canEdit && <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => save(!editor.archived)}><Archive size={15} aria-hidden="true" /> {editor.archived ? 'Wiederherstellen' : 'Archivieren'}</button>}
            {!readOnly && <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? 'Wird gespeichert …' : 'Vorlage speichern'}</button>}
          </div>
        </form>
        <aside className="letter-placeholders" aria-label="Platzhalter">
          <h3>Platzhalter</h3>
          <p className="letters-hint">{readOnly ? 'Diese Platzhalter füllt das Programm aus.' : 'Klicken fügt den Platzhalter an der Cursorposition ein.'}</p>
          <ul>{(kind?.placeholders || []).map(item => <li key={item.name}><button type="button" disabled={readOnly} onClick={() => insert(`{{${item.name}}}`)}><code>{`{{${item.name}}}`}</code><span>{item.label}</span></button></li>)}</ul>
          <h3>Tabellen</h3>
          <ul>{(kind?.blocks || []).map(item => <li key={item.name}><button type="button" disabled={readOnly} onClick={() => insert(`{{${item.name}}}`)}><code>{`{{${item.name}}}`}</code><span>{item.label}</span></button></li>)}</ul>
        </aside>
      </div>}
    </div>
  );
}
