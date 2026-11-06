import { whatsAppNumber } from '../documentShare/documentShare';

export function normalizedChatNumber(value) {
  const text = String(value || '').trim();
  return /^\+?[\d() ./-]+$/.test(text) && !text.startsWith('+0') ? whatsAppNumber(text) : '';
}

export function whatsAppWebLink(phone, text = '') {
  const number = normalizedChatNumber(phone);
  if (!number || text.length > 2000) return '';
  const query = new URLSearchParams({ phone: number, ...(text ? { text } : {}) });
  return `https://web.whatsapp.com/send?${query}`;
}

export function emailClientLink(to, subject = '', body = '') {
  const address = String(to || '').trim();
  if (!/^[^\s@,;<>\r\n]+@[^\s@,;<>\r\n]+\.[^\s@,;<>\r\n]+$/.test(address) || /[\r\n\0]/.test(subject) || body.length > 2000 || subject.length > 200) return '';
  return `mailto:${encodeURIComponent(address)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

export function berlinLocal(value = new Date()) {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Berlin', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(value).replace(' ', 'T');
}

export function reminderDefault(dueDate, days = 7, clock = '09:00', now = new Date()) {
  const current = berlinLocal(now);
  if (/^\d{4}-\d{2}-\d{2}$/.test(dueDate || '')) {
    const day = new Date(`${dueDate}T12:00:00Z`);
    day.setUTCDate(day.getUTCDate() - Number(days || 0));
    const candidate = `${day.toISOString().slice(0, 10)}T${clock}`;
    if (candidate > current) return candidate;
  }
  const day = new Date(`${current.slice(0, 10)}T12:00:00Z`);
  day.setUTCDate(day.getUTCDate() + 1);
  return `${day.toISOString().slice(0, 10)}T${clock}`;
}

export function reminderDate(value) {
  return new Intl.DateTimeFormat('de-DE', { timeZone: 'Europe/Berlin', dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}
