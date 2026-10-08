export const ISSUER_ROLES = Object.freeze(['housing_provider', 'authorized_person']);

const isText = value => typeof value === 'string';
const isDate = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value);
const clone = value => typeof structuredClone === 'function'
  ? structuredClone(value)
  : JSON.parse(JSON.stringify(value));

export function personRow(name = '') {
  if (typeof globalThis.crypto?.randomUUID !== 'function') throw new Error('crypto.randomUUID unavailable');
  return { key: `person-${globalThis.crypto.randomUUID()}`, name };
}

export function blankHousingForm() {
  return {
    dwelling_address: '',
    dwelling_label: '',
    housing_provider_name: '',
    housing_provider_address: '',
    owner_relation: '',
    owner_name: '',
    actual_move_in_date: '',
    issue_date: '',
    issuer_name: '',
    issuer_role: '',
    occupants: [personRow()],
    confirmed_actual_move_in: false,
    confirmed_authority: false,
    confirmed_residents: false,
  };
}

export function cloneHousingForm(form) {
  return clone(form);
}

/** Who acts with which rights: a change of user, role or write areas discards private dialog state. */
export function housingActorKey(user, write) {
  if (!user?.id || user.is_active === false) return '';
  return JSON.stringify([user.id, user.role || '', write === null ? null : [...(write || [])].sort()]);
}

export function housingBindingKey(contractId, user, write) {
  const actor = housingActorKey(user, write);
  return contractId && actor ? JSON.stringify([contractId, actor]) : '';
}

export function formSnapshot(form) {
  if (!form) return null;
  return {
    dwelling_address: form.dwelling_address,
    dwelling_label: form.dwelling_label,
    housing_provider_name: form.housing_provider_name,
    housing_provider_address: form.housing_provider_address,
    owner_relation: form.owner_relation,
    owner_name: form.owner_name,
    actual_move_in_date: form.actual_move_in_date,
    issue_date: form.issue_date,
    issuer_name: form.issuer_name,
    issuer_role: form.issuer_role,
    occupants: form.occupants.map(item => item.name),
    confirmed_actual_move_in: Boolean(form.confirmed_actual_move_in),
    confirmed_authority: Boolean(form.confirmed_authority),
    confirmed_residents: Boolean(form.confirmed_residents),
  };
}

export function formSignature(form) {
  return JSON.stringify(formSnapshot(form));
}

export function certificateDataFromForm(form) {
  const value = formSnapshot(form);
  if (!value) throw new Error('missing_form');
  return {
    housing_provider_name: value.housing_provider_name.trim(),
    housing_provider_address: value.housing_provider_address.trim(),
    owner_same_as_provider: value.owner_relation === 'same',
    owner_name: value.owner_relation === 'different' ? value.owner_name.trim() : null,
    move_in_date: value.actual_move_in_date,
    issue_date: value.issue_date,
    apartment_address: value.dwelling_address.trim(),
    apartment_label: value.dwelling_label.trim() || null,
    issuer_name: value.issuer_name.trim(),
    issuer_role: value.issuer_role,
    residents: value.occupants.map(name => name.trim()).filter(Boolean),
  };
}

export function validateHousingForm(form, { forPublish = false } = {}) {
  const data = certificateDataFromForm(form);
  const errors = [];
  if (!data.apartment_address) errors.push('apartment_address');
  if (!data.housing_provider_name) errors.push('housing_provider_name');
  if (!data.housing_provider_address) errors.push('housing_provider_address');
  if (!['same', 'different'].includes(form.owner_relation)) errors.push('owner_relation');
  if (form.owner_relation === 'different' && !data.owner_name) errors.push('owner_name');
  if (!isDate(data.move_in_date)) errors.push('move_in_date');
  if (!isDate(data.issue_date)) errors.push('issue_date');
  if (!data.issuer_name) errors.push('issuer_name');
  if (!ISSUER_ROLES.includes(data.issuer_role)) errors.push('issuer_role');
  if (!data.residents.length) errors.push('residents');
  if (forPublish && !form.confirmed_actual_move_in) errors.push('confirmed_actual_move_in');
  if (forPublish && !form.confirmed_authority) errors.push('confirmed_authority');
  if (forPublish && !form.confirmed_residents) errors.push('confirmed_residents');
  return { valid: errors.length === 0, errors, data };
}

export function addSuggestedOccupant(form, name) {
  if (!isText(name) || !name.trim()) return form;
  return { ...form, occupants: [...form.occupants, personRow(name.trim())] };
}

export function isUnknownOutcome(error) {
  const status = error?.statusCode ?? error?.status;
  return error?.isNetwork === true || (Number.isInteger(status) && status >= 500 && status <= 599);
}

export function isConflictOutcome(error) {
  const status = error?.statusCode ?? error?.status;
  return status === 409 || status === 412;
}

export function isPrivateForgetOutcome(error) {
  const status = error?.statusCode ?? error?.status;
  return status === 401 || status === 403 || status === 404;
}

export function formFromCertificateData(data) {
  const form = blankHousingForm();
  if (!data || typeof data !== 'object') return form;
  return {
    ...form,
    dwelling_address: data.apartment_address || '',
    dwelling_label: data.apartment_label || '',
    housing_provider_name: data.housing_provider_name || '',
    housing_provider_address: data.housing_provider_address || '',
    owner_relation: data.owner_same_as_provider === true ? 'same'
      : data.owner_same_as_provider === false ? 'different' : '',
    owner_name: data.owner_name || '',
    actual_move_in_date: data.move_in_date || '',
    issue_date: data.issue_date || '',
    issuer_name: data.issuer_name || '',
    issuer_role: ISSUER_ROLES.includes(data.issuer_role) ? data.issuer_role : '',
    occupants: Array.isArray(data.residents) && data.residents.length
      ? data.residents.map(name => personRow(String(name)))
      : [personRow()],
    confirmed_actual_move_in: false,
    confirmed_authority: false,
    confirmed_residents: false,
  };
}
