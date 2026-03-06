import { useState, useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { useDevMode } from '../contexts/DevModeContext';
import { useTranslation } from '../i18n';

const CATEGORIES = [
  { value: 'improvement', label: 'Improvement', color: '#06b6d4' },
  { value: 'bug', label: 'Bug', color: '#ef4444' },
  { value: 'idea', label: 'Idea', color: '#8b5cf6' },
  { value: 'todo', label: 'Todo', color: '#f59e0b' },
  { value: 'question', label: 'Question', color: '#10b981' },
];

const PRIORITIES = ['low', 'medium', 'high', 'critical'];

const PRIORITY_COLORS = {
  low: '#9ca3af',
  medium: '#f59e0b',
  high: '#f97316',
  critical: '#ef4444',
};

function categoryColor(cat) {
  return CATEGORIES.find(c => c.value === cat)?.color || '#6b7280';
}

// ---------------------------------------------------------------------------
// Note Form (used when creating a new annotation)
// ---------------------------------------------------------------------------

function NoteForm({ onSubmit, onCancel, initialPage }) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('improvement');
  const [priority, setPriority] = useState('medium');
  const [component, setComponent] = useState('');
  const titleRef = useRef(null);

  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!title.trim()) return;
    onSubmit({
      page: initialPage,
      component: component || null,
      selector: null,
      category,
      priority,
      title: title.trim(),
      description: description.trim() || null,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="dev-note-form">
      <div className="dev-note-form-row">
        <input
          ref={titleRef}
          type="text"
          placeholder="Title / Summary..."
          value={title}
          onChange={e => setTitle(e.target.value)}
          className="dev-note-input"
          required
        />
      </div>
      <div className="dev-note-form-row">
        <input
          type="text"
          placeholder="Component / Section (optional)"
          value={component}
          onChange={e => setComponent(e.target.value)}
          className="dev-note-input"
        />
      </div>
      <div className="dev-note-form-row">
        <textarea
          placeholder="Detailed description (optional)..."
          value={description}
          onChange={e => setDescription(e.target.value)}
          className="dev-note-textarea"
          rows={3}
        />
      </div>
      <div className="dev-note-form-row dev-note-form-selects">
        <select value={category} onChange={e => setCategory(e.target.value)} className="dev-note-select">
          {CATEGORIES.map(c => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>
        <select value={priority} onChange={e => setPriority(e.target.value)} className="dev-note-select">
          {PRIORITIES.map(p => (
            <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
          ))}
        </select>
      </div>
      <div className="dev-note-form-actions">
        <button type="submit" className="dev-btn dev-btn-primary">Add Note</button>
        <button type="button" className="dev-btn dev-btn-secondary" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Notes List Panel
// ---------------------------------------------------------------------------

function NotesList({ notes, onResolve, onDelete, filterPage }) {
  const [filter, setFilter] = useState(filterPage ? 'page' : 'all');
  const [showResolved, setShowResolved] = useState(false);

  const filtered = notes.filter(n => {
    if (!showResolved && n.resolved) return false;
    if (filter === 'page' && n.page !== filterPage) return false;
    return true;
  });

  const priorityOrder = { critical: 0, high: 1, medium: 2, low: 3 };
  filtered.sort((a, b) => (priorityOrder[a.priority] || 2) - (priorityOrder[b.priority] || 2));

  return (
    <div className="dev-notes-list">
      <div className="dev-notes-list-header">
        <div className="dev-notes-filter-row">
          <button
            className={`dev-btn dev-btn-xs ${filter === 'all' ? 'dev-btn-primary' : 'dev-btn-ghost'}`}
            onClick={() => setFilter('all')}
          >All ({notes.filter(n => showResolved || !n.resolved).length})</button>
          <button
            className={`dev-btn dev-btn-xs ${filter === 'page' ? 'dev-btn-primary' : 'dev-btn-ghost'}`}
            onClick={() => setFilter('page')}
          >This Page</button>
          <label className="dev-checkbox-label">
            <input type="checkbox" checked={showResolved} onChange={e => setShowResolved(e.target.checked)} />
            Resolved
          </label>
        </div>
      </div>
      {filtered.length === 0 && (
        <div className="dev-notes-empty">No notes yet</div>
      )}
      {filtered.map(note => (
        <div key={note.id} className={`dev-note-item ${note.resolved ? 'dev-note-resolved' : ''}`}>
          <div className="dev-note-item-header">
            <span className="dev-note-badge" style={{ background: categoryColor(note.category) }}>
              {note.category}
            </span>
            <span className="dev-note-badge" style={{ background: PRIORITY_COLORS[note.priority] }}>
              {note.priority}
            </span>
          </div>
          <div className="dev-note-item-title">{note.title}</div>
          <div className="dev-note-item-location">{note.page}{note.component ? ` > ${note.component}` : ''}</div>
          {note.description && <div className="dev-note-item-desc">{note.description}</div>}
          <div className="dev-note-item-actions">
            {!note.resolved && (
              <button className="dev-btn dev-btn-xs dev-btn-ghost" onClick={() => onResolve(note.id)}>Resolve</button>
            )}
            <button className="dev-btn dev-btn-xs dev-btn-danger" onClick={() => onDelete(note.id)}>Delete</button>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Log Preview Panel
// ---------------------------------------------------------------------------

function LogPreview({ onClose }) {
  const { exportLog } = useDevMode();
  const [content, setContent] = useState('Loading...');

  useEffect(() => {
    exportLog().then(c => setContent(c || '(empty)'));
  }, [exportLog]);

  const handleCopy = () => {
    navigator.clipboard.writeText(content).catch(() => {});
  };

  const handleDownload = () => {
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'dev_notes.log';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="dev-log-preview">
      <div className="dev-log-preview-header">
        <span>Dev Notes Log</span>
        <div>
          <button className="dev-btn dev-btn-xs dev-btn-ghost" onClick={handleCopy}>Copy</button>
          <button className="dev-btn dev-btn-xs dev-btn-ghost" onClick={handleDownload}>Download</button>
          <button className="dev-btn dev-btn-xs dev-btn-ghost" onClick={onClose}>Close</button>
        </div>
      </div>
      <pre className="dev-log-preview-content">{content}</pre>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Overlay
// ---------------------------------------------------------------------------

export default function DevModeOverlay() {
  const { enabled, notes, annotating, startAnnotating, stopAnnotating, createNote, resolveNote, deleteNote, toggle } = useDevMode();
  const location = useLocation();
  const [showPanel, setShowPanel] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [showLog, setShowLog] = useState(false);

  // Count unresolved notes for current page
  const currentPath = location.pathname;
  const pageNotes = notes.filter(n => n.page === currentPath && !n.resolved);
  const unresolvedCount = notes.filter(n => !n.resolved).length;

  if (!enabled) return null;

  const handleCreateNote = async (data) => {
    await createNote(data);
    setShowForm(false);
    stopAnnotating();
  };

  const handleNewNote = () => {
    setShowForm(true);
    setShowPanel(false);
    setShowLog(false);
    startAnnotating();
  };

  const handleShowPanel = () => {
    setShowPanel(!showPanel);
    setShowForm(false);
    setShowLog(false);
    stopAnnotating();
  };

  const handleShowLog = () => {
    setShowLog(!showLog);
    setShowPanel(false);
    setShowForm(false);
    stopAnnotating();
  };

  return (
    <>
      {/* Dev Mode Indicator Bar */}
      <div className="dev-mode-bar">
        <div className="dev-mode-bar-left">
          <span className="dev-mode-indicator">DEV MODE</span>
          <span className="dev-mode-page">{currentPath}</span>
          {pageNotes.length > 0 && (
            <span className="dev-mode-page-count">{pageNotes.length} note{pageNotes.length !== 1 ? 's' : ''} on this page</span>
          )}
        </div>
        <div className="dev-mode-bar-right">
          <button className="dev-btn dev-btn-sm dev-btn-accent" onClick={handleNewNote}>
            + Add Note
          </button>
          <button className="dev-btn dev-btn-sm dev-btn-ghost" onClick={handleShowPanel}>
            Notes ({unresolvedCount})
          </button>
          <button className="dev-btn dev-btn-sm dev-btn-ghost" onClick={handleShowLog}>
            Export Log
          </button>
          <button className="dev-btn dev-btn-sm dev-btn-ghost" onClick={toggle} title="Ctrl+Shift+D">
            Exit
          </button>
        </div>
      </div>

      {/* Annotation Form */}
      {showForm && (
        <div className="dev-panel dev-panel-form">
          <div className="dev-panel-title">New Developer Note — {currentPath}</div>
          <NoteForm
            initialPage={currentPath}
            onSubmit={handleCreateNote}
            onCancel={() => { setShowForm(false); stopAnnotating(); }}
          />
        </div>
      )}

      {/* Notes List Panel */}
      {showPanel && (
        <div className="dev-panel dev-panel-list">
          <div className="dev-panel-title">Developer Notes</div>
          <NotesList
            notes={notes}
            filterPage={currentPath}
            onResolve={resolveNote}
            onDelete={deleteNote}
          />
        </div>
      )}

      {/* Log Preview */}
      {showLog && (
        <div className="dev-panel dev-panel-log">
          <LogPreview onClose={() => setShowLog(false)} />
        </div>
      )}

      {/* Page note indicators — small badges on the page showing note count */}
      {pageNotes.length > 0 && !showPanel && !showForm && !showLog && (
        <div className="dev-page-indicators">
          {pageNotes.map(note => (
            <div
              key={note.id}
              className="dev-page-indicator"
              style={{ borderLeftColor: categoryColor(note.category) }}
              title={`${note.title}\n${note.component || ''}`}
              onClick={handleShowPanel}
            >
              <span className="dev-indicator-priority" style={{ color: PRIORITY_COLORS[note.priority] }}>●</span>
              <span className="dev-indicator-text">{note.title}</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
