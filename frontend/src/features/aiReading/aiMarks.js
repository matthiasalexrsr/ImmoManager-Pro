import { useState } from 'react';

export const AI_CONFIDENCE = { high: 'sicher erkannt', medium: 'wahrscheinlich', low: 'unsicher – bitte genau prüfen' };
export const AI_MARK = { filled: 'KI', confirmed: 'KI ✓', pending: 'KI – prüfen', changed: 'geändert', added: 'neu' };

/**
 * The marks of values a reading put into a form (`aiMarks`: { fields: {key: {value, evidence, confidence}}, mode, document, label }):
 * a read value is pending until confirmed (mode "confirm") or just marked ("mark"); a value changed by hand is
 * "changed", one the person entered into an empty field "added". `start` holds the form's first values.
 */
export function useAiMarks(aiMarks, values, start) {
  const [confirmed, setConfirmed] = useState(() => new Set());
  const state = key => {
    if (!aiMarks) return null;
    const mark = aiMarks.fields?.[key];
    const current = String(values?.[key] ?? '');
    if (mark) {
      if (current !== String(mark.value ?? '')) return 'changed';
      if (aiMarks.mode === 'confirm') return confirmed.has(key) ? 'confirmed' : 'pending';
      return 'filled';
    }
    if (current !== '' && String(start?.[key] ?? '') === '') return 'added';
    return null;
  };
  return {
    state,
    pending: keys => (aiMarks?.mode === 'confirm' ? keys.filter(key => state(key) === 'pending') : []),
    filled: keys => keys.filter(key => aiMarks?.fields?.[key]).length,
    confirm: keys => setConfirmed(current => new Set([...current, ...keys])),
    mark: key => aiMarks?.fields?.[key] || null,
  };
}

/** The class a form group gets for its mark. */
export const aiGroupClass = state => (state === 'added' ? ' ai-added' : state ? ` ai-field is-${state}` : '');

export const pendingMessage = labels => `Bitte die von der KI eingetragenen Werte prüfen und bestätigen: ${labels.join(', ')}.`;
