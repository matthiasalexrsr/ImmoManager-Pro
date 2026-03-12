/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { api } from '../api';

const DevModeContext = createContext(null);

export function useDevMode() {
  return useContext(DevModeContext);
}

export function DevModeProvider({ children }) {
  const [enabled, setEnabled] = useState(() => {
    return localStorage.getItem('dev_mode') === 'true';
  });
  const [notes, setNotes] = useState([]);
  const [annotating, setAnnotating] = useState(false);

  const fetchNotes = useCallback(async () => {
    try {
      const data = await api.get('/dev-notes');
      setNotes(data || []);
    } catch (err) {
      console.warn('[DevMode] Failed to load notes:', err.message);
    }
  }, []);

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
      if (e.ctrlKey && e.shiftKey && e.key === 'D') {
        e.preventDefault();
        setEnabled(prev => !prev);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const createNote = useCallback(async (noteData) => {
    try {
      const note = await api.post('/dev-notes', noteData);
      setNotes(prev => [...prev, note]);
      return note;
    } catch (err) {
      console.warn('[DevMode] Failed to create note:', err.message);
      throw err;
    }
  }, []);

  const updateNote = useCallback(async (noteId, updates) => {
    try {
      const updated = await api.patch(`/dev-notes/${noteId}`, updates);
      setNotes(prev => prev.map(n => n.id === noteId ? updated : n));
      return updated;
    } catch (err) {
      console.warn('[DevMode] Failed to update note:', err.message);
      throw err;
    }
  }, []);

  const deleteNote = useCallback(async (noteId) => {
    try {
      await api.del(`/dev-notes/${noteId}`);
      setNotes(prev => prev.filter(n => n.id !== noteId));
    } catch (err) {
      console.warn('[DevMode] Failed to delete note:', err.message);
      throw err;
    }
  }, []);

  const resolveNote = useCallback(async (noteId) => {
    try {
      const updated = await api.post(`/dev-notes/${noteId}/resolve`);
      setNotes(prev => prev.map(n => n.id === noteId ? updated : n));
      return updated;
    } catch (err) {
      console.warn('[DevMode] Failed to resolve note:', err.message);
      throw err;
    }
  }, []);

  const exportLog = useCallback(async () => {
    try {
      const data = await api.get('/dev-notes/log-content');
      return data?.content || '';
    } catch (err) {
      console.warn('[DevMode] Failed to export log:', err.message);
      return '';
    }
  }, []);

  const toggle = useCallback(() => setEnabled(prev => !prev), []);
  const startAnnotating = useCallback(() => setAnnotating(true), []);
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
