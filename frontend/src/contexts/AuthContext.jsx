/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useCallback } from 'react';

const AuthContext = createContext(null);

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);

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
      isAdmin, isReadonly,
      role: user?.role || null,
    }}>
      {children}
    </AuthContext.Provider>
  );
}
