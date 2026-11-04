import { useEffect, useState } from 'react';
import { api } from '../../api';

export default function ConfigurationContract() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    async function load() {
      try {
        const same = api.captureSession();
        const result = await api.get('/auth/users/me/settings/configuration-contract'); same(); if (live) { setData(result); setError(null); }
      } catch (failure) {
        if (!live) return;
        if (failure.code === 'SESSION_CHANGED') { setData(null); setError('Die Sitzung wurde geändert. Bitte erneut anmelden.'); }
        else setError(failure.message);
      }
    }
    load();
    return () => { live = false; };
  }, [attempt]);
  return <details className="settings-technical"><summary>API und Erweiterungen</summary><section aria-label="API und Erweiterungen">
    {data && <><p>{data.api.base} · {data.api.schema ? <a href={data.api.schema}>Dokumentierter API-Vertrag</a>
      : 'Die API-Dokumentation ist in dieser Installation aus (API_DOCS_ENABLED=true schaltet sie ein).'}</p><p>{data.api.authorization}</p><p>{data.api.commands}</p><p>{data.api.secret_policy}</p>
      <p>{data.plugin_policy}</p>{data.plugins.length ? <ul>{data.plugins.map(plugin => <li key={plugin.name}>{plugin.name} · Version {plugin.version} · {plugin.description}</li>)}</ul> : <p>Keine Pythonplugins im laufenden Prozess geladen.</p>}</>}
    {error && <p role="alert">{error}<button onClick={() => setAttempt(n => n + 1)}>Erneut laden</button></p>}
    {!data && !error && <p role="status">API- und Pluginstatus werden geladen …</p>}
  </section></details>;
}
