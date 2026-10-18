const keyOf = (owner, kind, identity) => `workspace:${owner}:assistant:${kind}:${identity}`;

function read(owner, kind, identity) {
  if (!owner || !identity) return null;
  try { return JSON.parse(localStorage.getItem(keyOf(owner, kind, identity)) || 'null'); }
  catch { return null; }
}

function write(owner, kind, identity, value) {
  if (!owner || !identity) throw new Error('Die Anmeldung wird noch geprüft.');
  try {
    if (value == null) localStorage.removeItem(keyOf(owner, kind, identity));
    else localStorage.setItem(keyOf(owner, kind, identity), JSON.stringify(value));
  } catch { throw new Error('Der private Wiederanlaufpuffer konnte nicht gespeichert werden. Bitte Browserspeicher prüfen.'); }
}

export function readAssistantDraft(owner, identity) {
  const draft = read(owner, 'draft', identity);
  return draft && typeof draft.body === 'string' && Array.isArray(draft.attachments) && Array.isArray(draft.context)
    ? { ...draft, web_research: draft.web_research === true, report: draft.report || null } : { body: '', attachments: [], context: [], web_research: false, report: null };
}
export const writeAssistantDraft = (owner, identity, draft) => write(owner, 'draft', identity, draft);
export const clearAssistantDraft = (owner, identity) => write(owner, 'draft', identity, null);

export function readAssistantCommand(owner, identity) {
  const command = read(owner, 'command', identity);
  return command && typeof command.idempotency_key === 'string' && command.request && typeof command.request === 'object' ? command : null;
}
export const writeAssistantCommand = (owner, identity, command) => write(owner, 'command', identity, command);
export function clearAssistantCommand(owner, identity, command) {
  if (readAssistantCommand(owner, identity)?.idempotency_key === command.idempotency_key) write(owner, 'command', identity, null);
}
