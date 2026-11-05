import { useEffect, useState } from 'react';

/** Runtime mode comes from this server, never a browser preference or URL. */
export default function useRuntimeInfo() {
  const [runtime, setRuntime] = useState({ demo: false, testversion: false, credentials: null });
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const response = await fetch('/health');
        if (!response?.ok) return;
        const info = await response.json();
        const demo = info?.demo === true;
        const login = info?.demo_login;
        const valid = demo && typeof login?.username === 'string' && login.username.length > 0
          && login.username.length <= 200 && typeof login?.password === 'string'
          && login.password.length > 0 && login.password.length <= 200;
        if (active) setRuntime({ demo, testversion: info?.testversion === true,
          credentials: valid ? { username: login.username, password: login.password } : null });
      } catch { /* The ordinary sign-in remains available if health cannot be read. */ }
    }
    load();
    return () => { active = false; };
  }, []);
  return runtime;
}
