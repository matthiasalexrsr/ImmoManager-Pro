import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { formatPriceIndex, parsePriceIndex, priceIndexService } from './lettersApi';

const MONTHS = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'];
const monthLabel = value => { const [year, month] = value.split('-'); return `${MONTHS[Number(month) - 1]} ${year}`; };

/** The consumer price index for index rents: entered by hand from the Federal Statistical Office, never fetched. */
export default function PriceIndexSection({ service = priceIndexService }) {
  const id = useId();
  const [data, setData] = useState(null);
  const [text, setText] = useState('');
  const [baseYear, setBaseYear] = useState('2020');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const command = useRef(null);

  const load = useCallback(async () => {
    try {
      const value = await service.view();
      setData(value); setText(formatPriceIndex(value.values)); setBaseYear(String(value.base_year || 2020)); setError('');
    } catch (problem) { setError(problem.message || 'Der Verbraucherpreisindex konnte nicht geladen werden.'); }
  }, [service]);
  useEffect(() => { void load(); }, [load]);

  const save = async event => {
    event.preventDefault();
    if (busy || !data) return;
    const { values, errors } = parsePriceIndex(text);
    if (errors.length) { setError(`Nicht lesbar (Format „JJJJ-MM;Wert“): ${errors.slice(0, 3).join(', ')}${errors.length > 3 ? ' …' : ''}`); return; }
    setBusy(true); setError(''); setNotice('');
    try {
      if (!command.current) command.current = crypto.randomUUID();
      const saved = await service.save({ base_year: Number(baseYear), values, base_revision: data.revision, idempotency_key: command.current });
      command.current = null;
      setData(saved); setText(formatPriceIndex(saved.values));
      setNotice(`${saved.months.length} Monatswerte gespeichert.`);
    } catch (problem) {
      if (problem?.statusCode !== undefined && problem.statusCode < 500) command.current = null;
      setError(problem.message || 'Der Verbraucherpreisindex konnte nicht gespeichert werden.');
    } finally { setBusy(false); }
  };

  const months = data?.months || [];
  const latest = months[months.length - 1];
  return <section className="price-index-section" aria-labelledby={`${id}-title`}>
    <h2 className="letters-heading" id={`${id}-title`}>Verbraucherpreisindex (Indexmiete)</h2>
    <p className="letters-hint">Die Vorlage „Mietanpassung bei Indexmiete“ schlägt die Indexwerte aus dieser Tabelle vor. Die Werte veröffentlicht das Statistische Bundesamt monatlich (Verbraucherpreisindex für Deutschland, Tabelle 61111-0002); das Programm ruft nichts selbst ab.</p>
    {!data && !error && <p role="status">Wird geladen …</p>}
    {data && <p className="letters-hint">{months.length ? `${months.length} Monatswerte hinterlegt, zuletzt ${monthLabel(latest)}: ${String(data.values[latest]).replace('.', ',')} (${data.base_year} = 100).` : 'Noch keine Werte hinterlegt.'}</p>}
    {data && <form className="price-index-form" onSubmit={save}>
      <div className="letters-field"><label htmlFor={`${id}-base`}>Basisjahr (= 100)</label>
        <input id={`${id}-base`} type="number" min="1990" max="2100" step="1" value={baseYear} readOnly={!data.can_edit} onChange={event => setBaseYear(event.target.value)} /></div>
      <div className="letters-field letters-field-wide"><label htmlFor={`${id}-values`}>Monatswerte, je Zeile „JJJJ-MM;Wert“</label>
        <textarea id={`${id}-values`} rows={8} value={text} readOnly={!data.can_edit} onChange={event => { command.current = null; setText(event.target.value); }}
          placeholder={'2025-08;122,3\n2025-09;122,6'} />
        <small>Auch „08/2025 122,3“ oder aus einer Tabelle kopierte Zeilen werden gelesen.</small></div>
      {error && <p className="letters-error" role="alert">{error}</p>}
      {notice && <p className="letters-notice" role="status">{notice}</p>}
      {data.can_edit ? <div className="letters-actions"><button type="submit" className="btn btn-primary" disabled={busy}>{busy ? 'Wird gespeichert …' : 'Indexwerte speichern'}</button></div>
        : <p className="letters-hint">Pflegen dürfen Eigentümer und Verwaltung mit Zugriff auf alle Bestände.</p>}
    </form>}
    {!data && error && <p className="letters-error" role="alert">{error}</p>}
  </section>;
}
