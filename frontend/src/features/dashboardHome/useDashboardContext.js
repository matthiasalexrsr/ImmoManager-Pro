import { useEffect, useState } from 'react';
import { api } from '../../api';
import { accessDenied, day, text } from './dashboardModel';

const paths = { task: '/tasks', contract: '/contracts' };
const fail = () => { throw new Error('dashboard_summary_invalid'); };
const reference = value => value === null || text(value);
export async function readContext(selection, signal) {
  const get = async path => {
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    const value = await api.get(path, { signal });
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    return value;
  };
  const entity = await get(`${paths[selection.type]}/${encodeURIComponent(selection.id)}`);
  if (entity?.id !== selection.id || typeof entity.status !== 'string'
    || !reference(entity.unit_id) || !reference(entity.property_id)) fail();
  const isContract = selection.type === 'contract';
  if (isContract ? !text(entity.contract_number) || !text(entity.unit_id) || !text(entity.property_id) || !day(entity.start_date) || !(entity.end_date === null || day(entity.end_date))
    : typeof entity.title !== 'string' || !(entity.due_date === null || day(entity.due_date))) fail();
  let unit = null; let property = null;
  if (entity.unit_id) {
    const value = await get(`/units/${encodeURIComponent(entity.unit_id)}`);
    if (value?.id !== entity.unit_id || typeof value.label !== 'string' || !text(value.property_id)
      || (entity.property_id && value.property_id !== entity.property_id)) fail();
    unit = { id: value.id, label: value.label, property_id: value.property_id };
  }
  const propertyId = entity.property_id || unit?.property_id;
  if (propertyId) {
    const value = await get(`/properties/${encodeURIComponent(propertyId)}`);
    if (value?.id !== propertyId || typeof value.name !== 'string' || !text(value.portfolio_id)) fail();
    property = { id: value.id, name: value.name };
  }
  return { title: isContract ? entity.contract_number : entity.title, status: entity.status,
    date: isContract ? entity.end_date : entity.due_date, unit, property };
}

export default function useDashboardContext(selection, principal, onDenied) {
  const [state, setState] = useState({ key: null }); const [attempt, setAttempt] = useState(0);
  const key = JSON.stringify([principal, selection?.type, selection?.id, selection?.source, attempt]);
  useEffect(() => {
    if (!principal || !selection || !paths[selection.type]) return undefined;
    const controller = new AbortController();
    readContext(selection, controller.signal).then(data => {
      if (!controller.signal.aborted) setState({ key, status: 'ready', data, error: null });
    }).catch(error => {
      if (controller.signal.aborted) return;
      setState({ key, status: 'error', data: null, error });
      if (accessDenied(error)) onDenied?.(error);
    });
    return () => controller.abort();
  }, [key, principal, selection, attempt, onDenied]);
  return { ...(state.key === key ? state : { status: 'loading', data: null, error: null }), retry: () => setAttempt(value => value + 1) };
}
