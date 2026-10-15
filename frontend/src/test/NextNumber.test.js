import { expect, it } from 'vitest';
import { nextNumber } from '../utils/nextNumber';

it('increments long numeric contract references exactly without getting stuck', () => {
  expect(nextNumber(['MV-9007199254740992', 'MV-9007199254740993'], 'MV-1')).toBe('MV-9007199254740994');
  expect(nextNumber(['MV-0009007199254740993-A'], 'MV-1')).toBe('MV-0009007199254740994-A');
});
