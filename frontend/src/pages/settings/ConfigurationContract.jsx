import { useEffect, useState } from 'react';
import { api } from '../../api';

export default function ConfigurationContract() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true; const same = api.captureSession();
    api.get('/auth/users/me/settings/configuration-contract').then(result => { same(); if (live) setData(result); }).catch(failure => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, [attempt]);
  return <section aria-label="API und Erweiterungen"><h3>API und Erweiterungen</h3>
    {data && <><p>{data.api.base} · <a href={data.api.schema}>Dokumentierter API-Vertrag</a></p><p>{data.api.authorization}</p><p>{data.api.commands}</p><p>{data.api.secret_policy}</p>
      <p>{data.plugin_policy}</p>{data.plugins.length ? <ul>{data.plugins.map(plugin => <li key={plugin.name}>{plugin.name} · Version {plugin.version} · {plugin.description}</li>)}</ul> : <p>Keine Pythonplugins im laufenden Prozess geladen.</p>}</>}
    {error && <p role="alert">{error}<button onClick={() => setAttempt(n => n + 1)}>Erneut laden</button></p>}
    {!data && !error && <p role="status">API- und Pluginstatus werden geladen …</p>}
  </section>;
}
