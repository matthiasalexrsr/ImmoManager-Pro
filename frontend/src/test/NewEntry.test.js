import { afterEach, expect, it } from 'vitest';
import { dropNewEntry, holdNewEntry, takeNewEntry } from '../utils/newEntry';

afterEach(() => dropNewEntry('/unrelated'));

it('does not let a new page consume the previous page pending form before shell cleanup', () => {
  holdNewEntry('/units', { property_id: 'p1' });
  expect(takeNewEntry('/bookings')).toBeNull();
  expect(takeNewEntry('/units')).toEqual({ prefill: { property_id: 'p1' } });
  expect(takeNewEntry('/units')).toBeNull();
});
