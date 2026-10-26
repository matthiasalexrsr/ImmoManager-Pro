import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { saveBlob } from '../documentShare/documentShare';

const BASE = '/data/portability-exports';
export default function CustomerExports() {
  const [page, setPage] = useState(null);
  const [skip, setSkip] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const command = useRef(crypto.randomUUID());
  useEffect(() => {
    const controller = new AbortController();
    let timer;
    const load = async () => {
      try {
        const result = await api.get(`${BASE}?skip=${skip}&limit=25`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setPage(result);
        if (result.items.some(row => row.state === 'queued')) timer = setTimeout(load, 3000);
      } catch (failure) { if (!controller.signal.aborted) setError(failure.message); }
    };
    load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [skip, refresh]);
  const act = async action => {
    if (busy) return;
    setBusy(true); setError('');
    try { await action(); } catch (failure) { setError(failure.message); } finally { setBusy(false); }
  };
  return <section className="panel data-transfer" aria-labelledby="customer-exports"><div className="panel-body">
    <h2 id="customer-exports">Kundenexport</h2>
    <p>Geschäftsdaten, Beziehungen, Originalversionen und Fachnachweise als prüfbares ZIP-Archiv. Zugangskonten, Schlüssel und private Mitarbeitereinstellungen werden ausgeschlossen. Eine vollständige Betriebssicherung bleibt zusätzlich erforderlich.</p>
    <p>Das ZIP kann über die Datenübernahme auf dieser Seite mit Vorschau wieder eingelesen werden. Frühere Zahlungsfreigaben werden als historische Nachweise übernommen; neue Zahlungen brauchen eine neue Freigabe.</p>
    {error && <p className="alert-error" role="alert">{error} <button className="btn btn-secondary" onClick={() => { setError(''); setRefresh(value => value + 1); }}>Status erneut laden</button></p>}
    <button type="button" className="btn btn-primary" disabled={busy} onClick={() => act(async () => {
      await api.post(BASE, { idempotency_key: command.current }); command.current = crypto.randomUUID(); setSkip(0); setRefresh(value => value + 1);
    })}>Kundenexport erstellen</button>
    {!page ? <p role="status">Exportaufträge werden geladen …</p> : <>
      <ul className="transfer-list">{page.items.map(row => <li key={row.id}>
        <strong>{new Date(row.created_at).toLocaleString('de-DE')}</strong> · {row.state === 'ready' ? 'Bereit' : row.state === 'failed' ? 'Fehlgeschlagen' : 'Hintergrundauftrag ausstehend'}
        {row.error && <p role="alert">{row.error}</p>}
        {row.state === 'ready' && <>
          {!!row.manifest.external_links_without_original?.length && <p role="status">{row.manifest.external_links_without_original.length} externe Dateiverweise sind als Verweise enthalten; ihre Originaldateien liegen nicht in diesem Paket. Einzelheiten stehen im Manifest.</p>}
          <p>{row.manifest.originals_count} Originalversionen · {row.size_bytes} Bytes<br />SHA-256: <code>{row.sha256}</code></p>
          <button className="btn btn-secondary" type="button" disabled={busy} onClick={() => act(async () => {
            const current = api.captureSession(); const blob = await api.getBlob(`${BASE}/${row.id}/download`); current(); saveBlob(blob, `ImmoManager-Kundenexport-${row.id}.zip`);
          })}>Exportpaket herunterladen</button>
          <details><summary>Mengen und Beträge dieses Exports</summary><pre>{JSON.stringify(row.manifest.controls, null, 2)}</pre></details>
        </>}
      </li>)}</ul>
      {!page.items.length && <p>Noch kein Kundenexport angefordert.</p>}
      <nav aria-label="Seiten der Kundenexporte"><button type="button" className="btn btn-secondary" disabled={busy || skip === 0} onClick={() => setSkip(Math.max(0, skip - 25))}>Zurück</button>
        <span> {page.total} Exportaufträge </span><button type="button" className="btn btn-secondary" disabled={busy || skip + 25 >= page.total} onClick={() => setSkip(skip + 25)}>Weiter</button></nav>
    </>}
  </div></section>;
}
