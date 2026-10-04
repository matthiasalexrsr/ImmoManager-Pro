export const INBOX_PAGE_SIZE = 10;

const isObject = value => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const isString = value => typeof value === 'string' && value.length > 0;
const optionalString = value => value == null || typeof value === 'string';
const nonNegativeInteger = value => Number.isSafeInteger(value) && value >= 0;
const ISO = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})?$/;

export function notificationPrincipalKey(user) {
  if (!user?.id || user.is_active === false) return '';
  return JSON.stringify([
    user.id,
    user.role || '',
    user.portfolio_access || '',
    user.portfolio_access_origin || '',
    [...(user.portfolio_ids || [])].sort(),
    [...(user.write_permissions || [])].sort(),
  ]);
}

export function parseInboxUtcMicros(value) {
  if (!isString(value)) throw new Error('invalid_notification_timestamp');
  const match = ISO.exec(value);
  if (!match) throw new Error('invalid_notification_timestamp');
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, fraction = '', zone = ''] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  if (month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59 || second > 59) {
    throw new Error('invalid_notification_timestamp');
  }
  const check = new Date(0);
  check.setUTCFullYear(year, month - 1, day);
  check.setUTCHours(hour, minute, second, 0);
  const utcMs = check.getTime();
  if (!Number.isFinite(utcMs)
      || check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1
      || check.getUTCDate() !== day || check.getUTCHours() !== hour
      || check.getUTCMinutes() !== minute || check.getUTCSeconds() !== second) {
    throw new Error('invalid_notification_timestamp');
  }
  let micros = BigInt(utcMs) * 1000n + BigInt(fraction.padEnd(6, '0'));
  if (zone && zone !== 'Z') {
    const offsetHours = Number(zone.slice(1, 3));
    const offsetMinutePart = Number(zone.slice(4, 6));
    if (offsetHours > 23 || offsetMinutePart > 59) {
      throw new Error('invalid_notification_timestamp');
    }
    const sign = zone[0] === '+' ? 1n : -1n;
    const offsetMinutes = BigInt(offsetHours * 60 + offsetMinutePart);
    micros -= sign * offsetMinutes * 60n * 1000000n;
  }
  return micros;
}

export function inboxUtcDate(value) {
  if (value == null) return null;
  const micros = parseInboxUtcMicros(value);
  let milliseconds = micros / 1000n;
  if (micros % 1000n < 0n) milliseconds -= 1n;
  const parsed = new Date(Number(milliseconds));
  if (!Number.isFinite(parsed.getTime())) throw new Error('invalid_notification_timestamp');
  return parsed;
}

function compareUtf8(left, right) {
  const encoder = new TextEncoder();
  const a = encoder.encode(left);
  const b = encoder.encode(right);
  const length = Math.min(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    if (a[index] !== b[index]) return a[index] < b[index] ? -1 : 1;
  }
  return a.length === b.length ? 0 : a.length < b.length ? -1 : 1;
}

export function compareInboxItems(left, right) {
  const leftTime = left.created_at == null ? null : parseInboxUtcMicros(left.created_at);
  const rightTime = right.created_at == null ? null : parseInboxUtcMicros(right.created_at);
  if (leftTime == null && rightTime != null) return 1;
  if (leftTime != null && rightTime == null) return -1;
  if (leftTime != null && rightTime != null && leftTime !== rightTime) {
    return leftTime > rightTime ? -1 : 1;
  }
  return -compareUtf8(left.id, right.id);
}

function ordered(items, previousLastItem = null) {
  let previous = previousLastItem;
  for (const item of items) {
    if (previous && compareInboxItems(previous, item) >= 0) return false;
    previous = item;
  }
  return true;
}

export function validateAuthorityUser(value) {
  if (!isObject(value)
      || !isString(value.id)
      || !isString(value.role)
      || value.is_active !== true
      || !['all', 'selected'].includes(value.portfolio_access)
      || !isString(value.portfolio_access_origin)
      || !Array.isArray(value.portfolio_ids)
      || !value.portfolio_ids.every(isString)
      || !Array.isArray(value.write_permissions)
      || !value.write_permissions.every(isString)) {
    throw new Error('invalid_notification_authority');
  }
  return value;
}

export function validateInboxItem(value) {
  if (!isObject(value)
      || !isString(value.id)
      || !isString(value.notification_type)
      || !isString(value.title)
      || typeof value.content !== 'string'
      || !isString(value.severity)
      || !optionalString(value.entity_type)
      || !optionalString(value.entity_id)
      || !(value.created_at == null || isString(value.created_at))
      || !(value.read_at == null || isString(value.read_at))
      || !isObject(value.actions)
      || typeof value.actions.mark_read !== 'boolean') {
    throw new Error('invalid_notification_inbox_item');
  }
  if (value.created_at != null) parseInboxUtcMicros(value.created_at);
  if (value.read_at != null) parseInboxUtcMicros(value.read_at);
  return value;
}

export function validateInboxPage(
  value,
  {
    status = 'unread',
    expectedConsistency = 'live',
    previousLastItem = null,
  } = {},
) {
  if (!isObject(value)
      || !Array.isArray(value.items)
      || !nonNegativeInteger(value.full_count)
      || !nonNegativeInteger(value.unread_count)
      || typeof value.has_more !== 'boolean'
      || !(value.next_cursor == null || isString(value.next_cursor))
      || value.snapshot_token !== null
      || value.consistency !== expectedConsistency
      || !isObject(value.actions)
      || value.actions.mark_all_read !== false) {
    throw new Error('invalid_notification_inbox_page');
  }

  const items = value.items.map(validateInboxItem);
  if (new Set(items.map(item => item.id)).size !== items.length
      || items.length > value.full_count
      || value.has_more !== Boolean(value.next_cursor)
      || !ordered(items, previousLastItem)) {
    throw new Error('invalid_notification_inbox_page');
  }

  if (status === 'unread') {
    if (value.full_count !== value.unread_count || items.some(item => item.read_at != null)) {
      throw new Error('invalid_notification_inbox_page');
    }
  } else if (status === 'read') {
    if (items.some(item => item.read_at == null)) throw new Error('invalid_notification_inbox_page');
  } else if (status === 'all') {
    if (value.unread_count > value.full_count) throw new Error('invalid_notification_inbox_page');
  } else {
    throw new Error('invalid_notification_inbox_page');
  }

  return { ...value, items };
}

export function validateMarkReadResponse(value, expectedId) {
  if (!isObject(value)
      || value.notification_id !== expectedId
      || !isString(value.read_at)) {
    throw new Error('invalid_notification_read_response');
  }
  parseInboxUtcMicros(value.read_at);
  return value;
}

export function notificationErrorKind(error) {
  if ([401, 403, 404].includes(error?.statusCode)) return 'access';
  if (error?.statusCode === 409) return 'changed';
  if (error?.message?.startsWith('invalid_notification_')) return 'invalid';
  if (error?.isNetwork || error?.statusCode >= 500) return 'unavailable';
  return 'request';
}

export function emptyInboxState(principal = '', service = null, phase = 'idle') {
  return {
    principal,
    service,
    phase,
    items: [],
    fullCount: null,
    unreadCount: null,
    hasMore: false,
    nextCursor: null,
    consistency: 'live',
    error: null,
    errorKind: null,
  };
}
