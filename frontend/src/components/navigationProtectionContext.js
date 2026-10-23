import { createContext, useContext } from 'react';

export const NavigationProtectionContext = createContext(null);
export function useNavigationProtection() { return useContext(NavigationProtectionContext); }

export function navigationDiscardLabel(labels, locale, fallback) {
  if (!labels || labels.length < 2) return fallback;
  return { en: 'Discard all listed changes and leave', es: 'Descartar todos los cambios indicados y salir',
    de: 'Alle aufgeführten Änderungen verwerfen und verlassen' }[locale?.slice(0, 2)] || 'Alle aufgeführten Änderungen verwerfen und verlassen';
}
