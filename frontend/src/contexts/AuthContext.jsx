/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useCallback } from 'react';
import { mayWrite, writePermissions } from '../utils/writeAccess';

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

  const isAdmin = mayWrite(user, '/admin');
  const isReadonly = user?.role === 'readonly';
  const canWrite = useCallback(endpoint => mayWrite(user, endpoint), [user]);

  return (
    <AuthContext.Provider value={{
      user, updateUser, clearUser,
      isAdmin, isReadonly,
      role: user?.role || null,
      writePermissions: writePermissions(user), canWrite,
    }}>
      {children}
    </AuthContext.Provider>
  );
}
