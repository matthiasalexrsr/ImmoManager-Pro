import { useState } from 'react';
import { useTranslation } from '../../i18n';
import { RECURRENCE_PRESETS, RECURRENCE_FREQUENCIES, recurrenceConfig, recurrencePreset, recurrenceRule } from './taskRecurrence';
import './taskRecurrence.css';

export default function TaskRecurrenceField({ id, value = '', onChange, disabled, ...accessibility }) {
  const { t } = useTranslation();
  // The rule itself lives in FormModal, including incomplete edits and recovery.
  // This local value only keeps the custom controls open for a basic frequency.
  const [customFor, setCustomFor] = useState(null);
  const config = recurrenceConfig(value);
  const selected = customFor === value ? 'custom' : recurrencePreset(value);
  const changeConfig = patch => {
    const next = recurrenceRule({ ...config, ...patch });
    setCustomFor(next);
    onChange(next);
  };
  const hintId = `${id}-semantics`;
  return <div className="task-recurrence">
    <select id={id} value={selected} disabled={disabled} {...accessibility}
      aria-describedby={[accessibility['aria-describedby'], value && hintId].filter(Boolean).join(' ') || undefined}
      onChange={event => {
        const preset = event.target.value;
        if (preset === 'custom') {
          const next = value || 'FREQ=WEEKLY;INTERVAL=1';
          setCustomFor(next);
          if (next !== value) onChange(next);
        } else {
          setCustomFor(null);
          onChange(preset === 'none' ? '' : `FREQ=${RECURRENCE_PRESETS[preset][0]}${RECURRENCE_PRESETS[preset][1] === '1' ? '' : `;INTERVAL=${RECURRENCE_PRESETS[preset][1]}`}`);
        }
      }}>
      {['none', ...Object.keys(RECURRENCE_PRESETS), 'custom'].map(key => <option key={key} value={key}>{t(`pages.tasks.recurrence.${key}`)}</option>)}
    </select>
    {selected === 'custom' && <>
      {config ? <fieldset className="task-recurrence-controls" disabled={disabled}>
        <legend>{t('pages.tasks.recurrence.configure')}</legend>
        <div className="task-recurrence-grid">
          <label htmlFor={`${id}-frequency`}>{t('pages.tasks.recurrence.frequency')}
            <select id={`${id}-frequency`} value={config.frequency} onChange={event => changeConfig({ frequency: event.target.value })}>
              {RECURRENCE_FREQUENCIES.map(freq => <option key={freq} value={freq}>{t(`pages.tasks.recurrence.frequencies.${freq}`)}</option>)}
            </select>
          </label>
          <label htmlFor={`${id}-interval`}>{t('pages.tasks.recurrence.interval')}
            <input id={`${id}-interval`} type="number" min="1" step="1" required value={config.interval}
              onChange={event => changeConfig({ interval: event.target.value })} />
          </label>
          <label htmlFor={`${id}-end`}>{t('pages.tasks.recurrence.end')}
            <select id={`${id}-end`} value={config.end} onChange={event => changeConfig({ end: event.target.value })}>
              {['never', 'count', 'until', 'both'].map(end => <option key={end} value={end}>{t(`pages.tasks.recurrence.ends.${end}`)}</option>)}
            </select>
          </label>
          {['count', 'both'].includes(config.end) && <label htmlFor={`${id}-count`}>{t('pages.tasks.recurrence.countLabel')}
            <input id={`${id}-count`} type="number" min="1" step="1" required value={config.count}
              onChange={event => changeConfig({ count: event.target.value })} />
          </label>}
          {['until', 'both'].includes(config.end) && <label htmlFor={`${id}-until`}>{t('pages.tasks.recurrence.untilLabel')}
            <input id={`${id}-until`} type="date" required value={config.until}
              onChange={event => changeConfig({ until: event.target.value })} />
          </label>}
        </div>
      </fieldset> : <p role="note">{t('pages.tasks.recurrence.retainedRule')}</p>}
      <details open={!config || undefined} className="task-recurrence-expert">
        <summary>{t('pages.tasks.recurrence.expert')}</summary>
        <label htmlFor={`${id}-raw`}>{t('pages.tasks.recurrence.rawRule')}
          <input id={`${id}-raw`} type="text" value={value} disabled={disabled}
            onChange={event => { setCustomFor(event.target.value || null); onChange(event.target.value); }} />
        </label>
        <small>{t('pages.tasks.recurrence.supported')}</small>
      </details>
    </>}
    {value && <small id={hintId} className="form-hint">{t('pages.tasks.recurrence.semantics')}</small>}
  </div>;
}
