import { test as base, expect } from '@playwright/test';

// All normal suites share one SQL server, while browser contexts are fresh.
// Reset the actual account before mounting React: localStorage alone cannot
// override the account preferences fetched after login. Never use this in the
// empty-installation suite, which deliberately has no demo account.
export const test = base.extend({
  page: async ({ page }, use) => {
    const login = await page.request.post('/api/v1/auth/login', {
      data: { username: 'demo', password: 'Demo1234' },
    });
    expect(login.status(), 'The isolated runner must seed the demo owner').toBe(200);
    const { access_token: token } = await login.json();
    const preferences = await page.request.put('/api/v1/auth/users/me/preferences', {
      headers: { Authorization: `Bearer ${token}` },
      data: { locale: 'de-DE', theme: 'light', sidebar_collapsed: false },
    });
    expect(preferences.status(), 'Test prerequisites must persist before UI login').toBe(200);
    expect(await preferences.json()).toMatchObject({ locale: 'de-DE', theme: 'light', sidebar_collapsed: false });
    await page.addInitScript(() => localStorage.setItem('locale', 'de-DE'));
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await use(page);
    expect(errors, 'The browser must not emit uncaught JavaScript errors').toEqual([]);
  },
});

export { expect };

export async function germanWorkspaceReady(page) {
  await expect(page.getByRole('button', { name: 'Deutsch', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect.poll(() => page.evaluate(() => localStorage.getItem('locale'))).toBe('de-DE');
  // This cache is written after the real protected preference GET completes.
  await expect.poll(() => page.evaluate(() => Object.entries(localStorage).some(([key, value]) => {
    if (!key.startsWith('user_preferences:')) return false;
    try { return JSON.parse(value).locale === 'de-DE'; } catch { return false; }
  }))).toBe(true);
}
