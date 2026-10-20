import { describe, expect, it } from 'vitest';
import { expiryState } from '../utils/documentExpiry';

describe('document expiry state', () => {
  const today = new Date(2026, 9, 20);
  it('follows the reminder window of the daily job', () => {
    expect(expiryState({}, today)).toBeNull();
    expect(expiryState({ valid_until: '2026-10-19' }, today)).toBe('expired');
    expect(expiryState({ valid_until: '2026-10-20' }, today)).toBe('due');
    expect(expiryState({ valid_until: '2026-11-19' }, today)).toBe('due');        // 30 days by default
    expect(expiryState({ valid_until: '2026-11-20' }, today)).toBe('valid');
    expect(expiryState({ valid_until: '2027-01-01', reminder_days: 90 }, today)).toBe('due');
    expect(expiryState({ valid_until: '2026-10-25', reminder_days: 0 }, today)).toBe('valid');
  });
});
