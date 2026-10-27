import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import PdfPreview from '../../components/PdfPreview';
import { LETTERHEAD_FIELDS, letterheadService } from './lettersApi';
import './letters.css';

const ORIGIN = { global: 'Installation', Standard: 'nicht festgelegt', 'Persönlich': 'Ihre persönliche Vorgabe' };

/** The one letterhead of every letter: sender, contact, bank details, footer and logo, with a specimen letter. */
export default function LetterheadSection({ service = letterheadService }) {
  const auth = useAuth();
  const [view, setView] = useState(null);
  const [rules, setRules] = useState({});
  const [form, setForm] = useState({});
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [logoUrl, setLogoUrl] = useState(null);
  const [sampleUrl, setSampleUrl] = useState(null);
  const urls = useRef([]);
  const fileInput = useRef(null);
  const canEdit = Boolean(view?.can_edit && view.logo_rules?.global);

  const remember = url => { urls.current.push(url); return url; };
  useEffect(() => () => urls.current.forEach(url => URL.revokeObjectURL(url)), []);

  const load = useCallback(async () => {
    setError('');
    try {
      const next = await service.view();
      setView(next);
      setForm(Object.fromEntries(LETTERHEAD_FIELDS.map(field => [field.name, next.fields?.[field.name]?.value ?? ''])));
      if (next.can_edit) {
        const catalogue = await service.catalogue();
        setRules(Object.fromEntries((catalogue.items || []).filter(item => item.scope === 'global')
          .map(item => [item.key, item.revision])));
      }
      setLogoUrl(next.logo ? remember(URL.createObjectURL(await service.logo())) : null);
    } catch (problem) { setError(problem.message || 'Der Briefkopf konnte nicht geladen werden.'); }
  }, [service]);
  useEffect(() => { void load(); }, [load]);

  const changed = LETTERHEAD_FIELDS.filter(field => view && (form[field.name] ?? '') !== (view.fields?.[field.name]?.value ?? ''));

  const save = async event => {
    event.preventDefault();
    if (busy || !changed.length) return;
    setBusy('save'); setError(''); setNotice('');
    try {
      for (const field of changed) {
        await service.saveField(field.key, form[field.name].trim(), rules[field.key] ?? 0);
      }
      setNotice('Der Briefkopf ist gespeichert. Er gilt für alle neuen Briefe; archivierte Briefe bleiben unverändert.');
      setSampleUrl(null);
      await load();
    } catch (problem) {
      setError(problem.message || 'Der Briefkopf konnte nicht gespeichert werden.');
      await load();
    } finally { setBusy(''); }
  };

  const upload = async file => {
    if (!file || busy) return;
    setBusy('logo'); setError(''); setNotice('');
    try {
      await service.uploadLogo(file, view.logo_rules.global.revision);
      setNotice('Das Logo ist gespeichert.');
      setSampleUrl(null);
      await load();
    } catch (problem) { setError(problem.message || 'Das Logo konnte nicht gespeichert werden.'); }
    finally { setBusy(''); if (fileInput.current) fileInput.current.value = ''; }
  };

  const removeLogo = async () => {
    if (busy) return;
    setBusy('logo'); setError(''); setNotice('');
    try {
      await service.removeLogo(view.logo_rules.global.revision);
      setNotice('Das Logo wurde entfernt.');
      setSampleUrl(null);
      await load();
    } catch (problem) { setError(problem.message || 'Das Logo konnte nicht entfernt werden.'); }
    finally { setBusy(''); }
  };

  const sample = async () => {
    if (busy) return;
    setBusy('sample'); setError('');
    try { setSampleUrl(remember(URL.createObjectURL(await service.sample()))); }
    catch (problem) { setError(problem.message || 'Der Musterbrief konnte nicht erstellt werden.'); }
    finally { setBusy(''); }
  };

  return (
    <section className="panel letterhead-section settings-panel-full" aria-labelledby="letterhead-title">
      <div className="panel-header" id="letterhead-title">Briefkopf</div>
      <div className="panel-body letterhead-body">
        <p className="letterhead-intro">
          Absender, Logo, Kontakt und Bankverbindung erscheinen auf allen Briefen: auf Briefen aus Vorlagen, Abrechnungsschreiben,
          Mahnungen und Kautionsabrechnungen. Die Anschrift des Mieters steht im Fenster eines Briefumschlags (DIN 5008).
          {' '}<Link to="/letter-templates">Zu den Briefvorlagen</Link>
        </p>
        {error && <p className="letters-error" role="alert">{error}</p>}
        {notice && <p className="letters-notice" role="status">{notice}</p>}
        {!view && !error && <p role="status">Briefkopf wird geladen …</p>}
        {view && <div className="letterhead-columns">
          <form className="letterhead-form" onSubmit={save}>
            {!canEdit && <p className="letters-hint">{auth?.isAdmin
              ? 'Den installationsweiten Briefkopf ändert ein Konto mit Zugriff auf alle Bestände.'
              : 'Den Briefkopf ändern Eigentümer und Verwaltung.'}</p>}
            <fieldset disabled={!canEdit || Boolean(busy)}>
              <legend className="sr-only">Angaben im Briefkopf</legend>
              {LETTERHEAD_FIELDS.map(field => <div key={field.name} className="letters-field">
                <label htmlFor={`letterhead-${field.name}`}>{field.label}</label>
                {field.rows > 1
                  ? <textarea id={`letterhead-${field.name}`} rows={field.rows} value={form[field.name] ?? ''} onChange={event => setForm(old => ({ ...old, [field.name]: event.target.value }))} />
                  : <input id={`letterhead-${field.name}`} value={form[field.name] ?? ''} onChange={event => setForm(old => ({ ...old, [field.name]: event.target.value }))} />}
                <small>{field.hint ? `${field.hint} · ` : ''}Quelle: {ORIGIN[view.fields?.[field.name]?.origin] || view.fields?.[field.name]?.origin}</small>
              </div>)}
              {canEdit && <button type="submit" className="btn btn-primary" disabled={!changed.length || Boolean(busy)}>
                {busy === 'save' ? 'Wird gespeichert …' : changed.length ? `Briefkopf speichern (${changed.length})` : 'Briefkopf gespeichert'}</button>}
            </fieldset>
            <div className="letterhead-logo">
              <h3>Logo</h3>
              {logoUrl ? <img src={logoUrl} alt="Aktuelles Logo im Briefkopf" /> : <p className="letters-hint">Kein Logo hinterlegt.</p>}
              {view.logo && <p className="letters-hint">{view.logo.width} × {view.logo.height} Pixel · {view.logo.filename}</p>}
              {canEdit && <div className="letters-actions">
                <label className="btn btn-secondary btn-sm letterhead-upload">
                  {busy === 'logo' ? 'Wird gespeichert …' : view.logo ? 'Logo ersetzen' : 'Logo hochladen'}
                  <input ref={fileInput} type="file" accept="image/png,image/jpeg" className="sr-only" disabled={Boolean(busy)}
                    onChange={event => upload(event.target.files?.[0])} />
                </label>
                {view.logo && <button type="button" className="btn btn-secondary btn-sm" disabled={Boolean(busy)} onClick={removeLogo}>Logo entfernen</button>}
              </div>}
              <p className="letters-hint">PNG oder JPEG bis 1 MB. Breite Logos wirken am besten; gedruckt wird es höchstens 6 cm breit und 2,2 cm hoch.</p>
            </div>
          </form>
          <section className="letterhead-preview" aria-label="Musterbrief">
            <div className="letters-actions">
              <button type="button" className="btn btn-secondary" disabled={Boolean(busy)} onClick={sample}>
                {busy === 'sample' ? 'Musterbrief wird erstellt …' : sampleUrl ? 'Musterbrief aktualisieren' : 'Musterbrief ansehen'}</button>
            </div>
            {sampleUrl ? <PdfPreview key={sampleUrl} url={sampleUrl} title="Musterbrief" />
              : <p className="letters-hint">Der Musterbrief zeigt den gespeicherten Briefkopf so, wie er gedruckt wird.</p>}
          </section>
        </div>}
      </div>
    </section>
  );
}
