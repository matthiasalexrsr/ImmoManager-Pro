import { api } from '../../api';
import {
  INBOX_PAGE_SIZE,
  validateAuthorityUser,
  validateInboxPage,
  validateMarkReadResponse,
} from './notificationInboxModel';

const encode = value => encodeURIComponent(String(value));

function query(values) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  }
  const suffix = params.toString();
  return suffix ? `?${suffix}` : '';
}

export const notificationInboxService = {
  async loadAuthority({ signal } = {}) {
    return validateAuthorityUser(await api.get('/auth/me', { signal }));
  },

  async listInbox({
    status = 'unread',
    after = null,
    limit = INBOX_PAGE_SIZE,
    signal,
  } = {}) {
    const value = await api.get(
      `/notifications/inbox${query({ status, after, limit })}`,
      { signal },
    );
    return validateInboxPage(value, { status });
  },

  async markRead(id, { signal } = {}) {
    const value = await api.post(
      `/notifications/inbox/${encode(id)}/read`,
      {},
      { signal },
    );
    return validateMarkReadResponse(value, id);
  },
};
