import { useEffect, useState } from 'react';
import { api } from '../api';
import { usePreferences } from '../contexts/PreferencesContext';

export default function useEffectiveSettings(propertyId) {
  const preferences = usePreferences();
  const [value, setValue] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true; setValue(null); setError(null);
    if (!propertyId) return;
    const same = api.captureSession();
    api.get(`/auth/users/me/settings/effective?property_id=${encodeURIComponent(propertyId)}`).then(data => {
      same(); if (live) setValue({ propertyId, data });
    }).catch(failure => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, [propertyId, preferences?.prefs?._revision]);
  return { prefs: propertyId ? value?.propertyId === propertyId ? value.data : null : preferences?.prefs, error };
}
