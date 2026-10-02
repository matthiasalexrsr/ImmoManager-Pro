/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { api } from '../api';
import useWriteAccess from '../hooks/useWriteAccess';

const DevModeContext = createContext(null);

export function useDevMode() {
  return useContext(DevModeContext);
}

export function DevModeProvider({ children }) {
  const [requested, setEnabled] = useState(() => {
    return localStorage.getItem('dev_mode') === 'true';
  });
  const [notes, setNotes] = useState([]);
  const [annotating, setAnnotating] = useState(false);

  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/dev-notes', () => { setEnabled(false); setAnnotating(false); setNotes([]); });
  const enabled = requested && canWrite;

  const fetchNotes = useCallback(async () => {
    if (!isAllowed()) return;
    try {
      const data = await api.get('/dev-notes');
      if (!isAllowed()) return;
      setNotes(data || []);
    } catch (err) {
      console.warn('[DevMode] Failed to load notes:', err.message);
    }
  }, [isAllowed]);

  // Persist toggle
  useEffect(() => {
    localStorage.setItem('dev_mode', String(enabled));
  }, [enabled]);

  // Load notes when dev mode is enabled
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    api.get('/dev-notes')
      .then((data) => {
        if (!cancelled) setNotes(data || []);
      })
      .catch((err) => {
        console.warn('[DevMode] Failed to load notes:', err.message);
      });

    return () => {
      cancelled = true;
    };
  }, [enabled]);

  // Keyboard shortcut: Ctrl+Shift+D to toggle dev mode
  useEffect(() => {
    const handler = (e) => {
      if (isAllowed() && e.ctrlKey && e.shiftKey && e.key === 'D') {
        e.preventDefault();
        setEnabled(prev => !prev);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isAllowed]);

  const createNote = useCallback(async (noteData) => {
    requireWrite();
    try {
      const note = await api.post('/dev-notes', noteData);
      if (isAllowed()) setNotes(prev => [...prev, note]);
      return note;
    } catch (err) {
      console.warn('[DevMode] Failed to create note:', err.message);
      throw err;
    }
  }, [requireWrite, isAllowed]);

  const updateNote = useCallback(async (noteId, updates) => {
    requireWrite();
    try {
      const updated = await api.patch(`/dev-notes/${noteId}`, updates);
      if (isAllowed()) setNotes(prev => prev.map(n => n.id === noteId ? updated : n));
      return updated;
    } catch (err) {
      console.warn('[DevMode] Failed to update note:', err.message);
      throw err;
    }
  }, [requireWrite, isAllowed]);

  const deleteNote = useCallback(async (noteId) => {
    requireWrite();
    try {
      await api.del(`/dev-notes/${noteId}`);
      if (isAllowed()) setNotes(prev => prev.filter(n => n.id !== noteId));
    } catch (err) {
      console.warn('[DevMode] Failed to delete note:', err.message);
      throw err;
    }
  }, [requireWrite, isAllowed]);

  const resolveNote = useCallback(async (noteId) => {
    requireWrite();
    try {
      const updated = await api.post(`/dev-notes/${noteId}/resolve`);
      if (isAllowed()) setNotes(prev => prev.map(n => n.id === noteId ? updated : n));
      return updated;
    } catch (err) {
      console.warn('[DevMode] Failed to resolve note:', err.message);
      throw err;
    }
  }, [requireWrite, isAllowed]);

  const exportLog = useCallback(async () => {
    if (!isAllowed()) return;
    try {
      const data = await api.get('/dev-notes/log-content');
      return data?.content || '';
    } catch (err) {
      console.warn('[DevMode] Failed to export log:', err.message);
      return '';
    }
  }, [isAllowed]);

  const toggle = useCallback(() => { if (isAllowed()) setEnabled(prev => !prev); }, [isAllowed]);
  const startAnnotating = useCallback(() => { if (isAllowed()) setAnnotating(true); }, [isAllowed]);
  const stopAnnotating = useCallback(() => setAnnotating(false), []);

  return (
    <DevModeContext.Provider value={{
      enabled, toggle, notes, annotating,
      startAnnotating, stopAnnotating,
      fetchNotes, createNote, updateNote, deleteNote, resolveNote, exportLog,
    }}>
      {children}
    </DevModeContext.Provider>
  );
}
