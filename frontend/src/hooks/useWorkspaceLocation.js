import { useContext } from 'react';
import { UNSAFE_LocationContext } from 'react-router-dom';

// During blocked browser Back/Forward, the address bar briefly points at the
// attempted destination while the router still owns the mounted form's route.
// Read that committed location; standalone dialogs retain their browser fallback.
export default function useWorkspaceLocation() {
  const routed = useContext(UNSAFE_LocationContext);
  return routed?.location || (typeof window === 'undefined'
    ? { pathname: '/', search: '', hash: '' }
    : { pathname: window.location.pathname, search: window.location.search, hash: window.location.hash });
}
