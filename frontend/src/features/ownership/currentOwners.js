import { useEffect, useState } from 'react';
import { api } from '../../api';

const EMPTY = { properties: {}, units: {} };

/** "Linda 55 %, Matthias 45 %"; a sole owner without the percent. */
export function ownersLabel(owners) {
  if (!owners?.length) return '';
  if (owners.length === 1 && owners[0].percent >= 100) return owners[0].name;
  return owners.map(owner => `${owner.name} ${Number(owner.percent).toLocaleString('de-DE', { maximumFractionDigits: 4 })}\u00a0%`).join(', ');
}

/** The recorded owners of every property and unit today (backend: /ownership-shares/current). */
export function useCurrentOwners() {
  const [owners, setOwners] = useState(EMPTY);
  useEffect(() => {
    let active = true;
    // the lists stay usable without the owners: a failed read only leaves the column empty
    Promise.resolve().then(() => api.get('/ownership-shares/current'))
      .then(data => { if (active && data?.properties && data?.units) setOwners(data); })
      .catch(() => {});
    return () => { active = false; };
  }, []);
  return owners;
}
