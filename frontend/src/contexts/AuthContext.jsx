/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { api } from '../api';
import { areaForRoute, mayWrite } from '../utils/permissions';

const AuthContext = createContext(null);

export function useAuth() {
  return useContext(AuthContext);
}

/** Whether the signed-in user may change what the current page lists (hides New/Edit/Delete). */
export function useCanWrite(path) {
  const auth = useContext(AuthContext);
  if (!auth?.user) return true;          // not loaded yet (and in tests): the server decides
  // pages remount on navigation, so the current address is enough (no router needed in tests)
  return mayWrite(auth.write, path || areaForRoute(window.location.pathname));
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  // null = everything; until loaded, the role gives a safe first answer
  const [write, setWrite] = useState(null);

  useEffect(() => {
    if (!user?.id) return;
    setWrite(user.role === 'readonly' ? [] : null);
    api.get('/auth/me/permissions').then(p => setWrite(p?.write ?? null)).catch(() => {});
  }, [user?.id, user?.role]);

  const updateUser = useCallback((userData) => {
    setUser(userData);
  }, []);

  const clearUser = useCallback(() => {
    setUser(null);
  }, []);

  const isAdmin = user?.role === 'eigentuemer' || user?.role === 'verwalter';
  const isReadonly = user?.role === 'readonly';

  return (
    <AuthContext.Provider value={{
      user, updateUser, clearUser,
      isAdmin, isReadonly, write,
      role: user?.role || null,
    }}>
      {children}
    </AuthContext.Provider>
  );
}
