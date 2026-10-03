import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

// The existing runner owns the isolated, seeded SQL server. These checks only
// read genuine records and navigate the rendered app; API requests are not mocked.


const primaryNavigation = (page, includeHidden = false) => page.getByRole('navigation', { includeHidden })
  .filter({ has: page.locator('a[href="/properties"]') }).filter({ has: page.locator('a[href="/contracts"]') });
const navLink = (navigation, href) => navigation.locator(`a[href="${href}"]`);

async function login(page) {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(url => url.pathname === '/');
  await germanWorkspaceReady(page);
  await expect(page.getByRole('main').getByRole('heading', { level: 1 }).first()).toBeVisible();
  const token = await page.evaluate(() => localStorage.getItem('access_token'));
  expect(token).toBeTruthy();
  return { Authorization: `Bearer ${token}` };
}

async function seededProperty(page, headers) {
  const response = await page.request.get('/api/v1/properties', { headers });
  expect(response.status()).toBe(200);
  const property = (await response.json()).find(item => item.name === 'Schönhauser Allee 78');
  expect(property?.city).toBe('Berlin');
  return property;
}

async function assertViewport(page) {
  const size = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth }));
  expect(size.document, `The page must fit its ${size.width}px viewport`).toBeLessThanOrEqual(size.width);
}

async function attachScreenshot(page, testInfo, name) {
  const path = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path, fullPage: false, animations: 'disabled' });
  await testInfo.attach(name, { path, contentType: 'image/png' });
}

async function menuControl(page) {
  // Follow the control's public ARIA relationship instead of relying on an icon,
  // translated button label, CSS class or a particular sidebar container tag.
  const controls = page.locator('button[aria-controls][aria-expanded]:visible');
  for (const control of await controls.all()) {
    const id = await control.getAttribute('aria-controls');
    const controlled = page.locator(`[id=${JSON.stringify(id)}]`);
    if (await controlled.locator('a[href="/properties"]').count()) return control;
  }
  throw new Error('Mobile navigation requires a visible button controlling its navigation with ARIA');
}

async function menuSurface(page, control) {
  // The public control relationship distinguishes navigation from dashboard
  // asides or other dialogs without prescribing their tags, classes or IDs.
  const id = await control.getAttribute('aria-controls');
  expect(id).toBeTruthy();
  const surface = page.locator(`[id=${JSON.stringify(id)}]`);
  await expect(surface).toHaveCount(1);
  return surface;
}

async function focusIsInside(surface) {
  return surface.evaluate(element => element.contains(document.activeElement));
}

for (const locale of ['de-DE', 'en-US', 'es-ES']) {
  test(`desktop navigation: logical groups, active routes and breadcrumbs (${locale})`, async ({ page }, testInfo) => {
    const headers = await login(page);
    const property = await seededProperty(page, headers);
    const navigation = primaryNavigation(page);
    await expect(navigation).toHaveCount(1);
    const localeName = { 'de-DE': 'Deutsch', 'en-US': 'English', 'es-ES': 'Español' }[locale];
    const localeButton = page.getByRole('button', { name: localeName, exact: true });
    await localeButton.click();
    await expect(localeButton).toHaveAttribute('aria-pressed', 'true');
    await expect.poll(() => page.evaluate(() => localStorage.getItem('locale'))).toBe(locale);
    const translations = await page.request.get(`/i18n/${locale}`);
    expect(translations.status()).toBe(200);
    const dictionary = await translations.json();
    const propertyLabel = dictionary.navigation.main.properties;
    expect(typeof propertyLabel).toBe('string');
    await expect(navLink(navigation, '/properties')).toHaveAccessibleName(propertyLabel);

    // Verify four representative work areas rather than copying the entire menu
    // inventory or binding tests to its group names and visual implementation.
    for (const pair of [['/properties', '/units'], ['/tenants', '/contracts'], ['/accounts', '/bookings'], ['/maintenance', '/tasks']]) {
      const group = await navLink(navigation, pair[0]).evaluate((link, partner) => {
        const nav = link.closest('nav, [role="navigation"]');
        let parent = link.parentElement;
        while (parent && parent !== nav && !parent.querySelector(`a[href="${partner}"]`)) parent = parent.parentElement;
        return { grouped: !!parent && parent !== nav, count: parent?.querySelectorAll('a[href]').length, total: nav?.querySelectorAll('a[href]').length };
      }, pair[1]);
      expect(group.grouped, `${pair.join(' + ')} should belong to one work area`).toBe(true);
      expect(group.count, 'A work area must be more specific than the whole navigation').toBeLessThan(group.total);
    }

    for (const href of ['/properties', '/contracts', '/rent-overview']) {
      const link = navLink(navigation, href);
      await expect(link).toHaveAccessibleName(/\S/);
      await link.click();
      await expect(page).toHaveURL(url => url.pathname === href);
      await expect(navigation.locator('[aria-current="page"]')).toHaveCount(1);
      await expect(link).toHaveAttribute('aria-current', 'page');
      const heading = page.getByRole('main').getByRole('heading', { level: 1 }).first();
      await expect(heading).toBeVisible();
      expect(await heading.innerText()).not.toMatch(/^(navigation|ui|finance|tenantsContracts)\./);
      await assertViewport(page);
    }

    await page.goto(`/properties/${property.id}`);
    await expect.poll(() => page.evaluate(() => localStorage.getItem('locale'))).toBe(locale);
    await expect(page.getByRole('heading', { name: property.name, exact: true })).toBeVisible();
    await expect(navLink(primaryNavigation(page), '/properties')).toHaveAttribute('aria-current', 'page');
    const breadcrumb = page.getByRole('navigation').filter({ has: page.locator('a[href="/properties"]') })
      .filter({ hasNot: page.locator('a[href="/contracts"]') });
    await expect(breadcrumb).toHaveCount(1);
    await expect(breadcrumb.locator('[aria-current="page"]')).toHaveText(/\S/);
    const home = breadcrumb.locator('a[href="/"]');
    await expect(home).toHaveAccessibleName(/\S/);
    await home.focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(url => url.pathname === '/');
    await expect(navLink(primaryNavigation(page), '/')).toHaveAttribute('aria-current', 'page');
    await expect(page.getByRole('main').getByRole('heading', { level: 1 }).first()).toBeVisible();
    await assertViewport(page);
    if (locale === 'de-DE') {
      const collapsed = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/auth/users/me/preferences'
        && response.request().method() === 'PUT');
      await page.getByRole('button', { name: dictionary.sidebar.collapse, exact: true }).click();
      expect((await collapsed).status()).toBe(200);
      const propertyLink = navLink(primaryNavigation(page), '/properties');
      await expect(propertyLink).toHaveAccessibleName(propertyLabel);
      await expect(propertyLink).toHaveAttribute('title', propertyLabel);
      await propertyLink.click();
      await expect(page).toHaveURL(url => url.pathname === '/properties');
      await expect(propertyLink).toHaveAttribute('aria-current', 'page');
      await assertViewport(page);
      await page.reload();
      const savedPreferences = await page.request.get('/api/v1/auth/users/me/preferences', { headers });
      expect(savedPreferences.status()).toBe(200);
      expect((await savedPreferences.json()).sidebar_collapsed).toBe(true);
      await expect(propertyLink).toHaveAccessibleName(propertyLabel);
      await expect(propertyLink).toHaveAttribute('title', propertyLabel);
      const expanded = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/auth/users/me/preferences'
        && response.request().method() === 'PUT');
      await page.getByRole('button', { name: dictionary.sidebar.expand, exact: true }).click();
      expect((await expanded).status()).toBe(200);
      await navLink(primaryNavigation(page), '/').click();
      await expect(page.getByRole('main').getByRole('heading', { level: 1 }).first()).toBeVisible();
      await attachScreenshot(page, testInfo, 'navigation-desktop');
    }
  });
}

test('global search: keyboard reaches real seeded data, Escape and empty results stay usable', async ({ page }) => {
  const headers = await login(page);
  const property = await seededProperty(page, headers);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.goto('/');
    const search = page.getByRole('search');
    const input = search.getByRole('combobox');
    // goto() may complete before React mounts its keyboard shortcut listener.
    await expect(input).toBeVisible();
    await page.keyboard.press('Control+k');
    await expect(input).toBeVisible();
    await expect(input).toBeFocused();
    const response = page.waitForResponse(reply => new URL(reply.url()).pathname === '/api/v1/search/page' && new URL(reply.url()).searchParams.get('q') === property.name);
    await input.fill(property.name);
    const reply = await response;
    expect(reply.status()).toBe(200);
    const hit = (await reply.json()).results.find(result => result.entity_type === 'property' && result.id === property.id);
    expect(hit?.url).toBe(`/properties/${property.id}`);
    const option = search.getByRole('option', { name: `${hit.display}${hit.detail ? ` ${hit.detail}` : ''}`, exact: true });
    await expect(option).toHaveCount(1);
    await input.press('ArrowDown');
    await expect(option).toHaveAttribute('aria-selected', 'true');
    expect(await input.getAttribute('aria-activedescendant')).toBe(await option.getAttribute('id'));
    await input.press('Enter');
    await expect(page).toHaveURL(url => url.pathname === hit.url);
    await expect(page.getByRole('heading', { name: property.name, exact: true })).toBeVisible();

    await page.keyboard.press('Control+k');
    await input.fill(property.name);
    await expect(option).toBeVisible();
    await input.press('Escape');
    await expect(input).toHaveAttribute('aria-expanded', 'false');
    await expect(input).toBeFocused();
    await expect(search.getByRole('listbox')).not.toBeVisible();
    const emptyResponse = page.waitForResponse(reply => new URL(reply.url()).pathname === '/api/v1/search/page' && new URL(reply.url()).searchParams.get('q') === 'navigation-no-match-20261001');
    await input.fill('navigation-no-match-20261001');
    const empty = await emptyResponse;
    expect(empty.status()).toBe(200);
    expect((await empty.json()).results).toEqual([]);
    await expect(search.getByRole('listbox')).toHaveAttribute('aria-busy', 'false');
    await expect(search.getByRole('option')).toHaveCount(0);
    await expect(search.getByRole('status')).toHaveText(/\S/);
    await input.press('Escape');
    await assertViewport(page);
  }
});

for (const width of [390, 320]) {
  test(`mobile navigation: keyboard focus, Escape, backdrop and route selection (${width}px)`, async ({ page }, testInfo) => {
    await login(page);
    await page.setViewportSize({ width, height: 844 });
    const control = await menuControl(page);
    const surface = await menuSurface(page, control);
    const originalOverflow = await page.evaluate(() => document.body.style.overflow);
    await expect(control).toHaveAttribute('aria-expanded', 'false');

    await control.focus();
    await page.keyboard.press('Shift+Tab');
    expect(await focusIsInside(surface), 'Closed navigation must not capture keyboard focus').toBe(false);
    // First opening after responsive resize exercises native inert removal and
    // CSS paint. Check actual focus without modifying RAF or application code.
    await control.focus();
    await control.click();
    await expect(control).toHaveAttribute('aria-expanded', 'true');
    await expect.poll(() => focusIsInside(surface), { message: 'The first pointer opening must focus the menu' }).toBe(true);
    await page.keyboard.press('Escape');
    await expect(control).toHaveAttribute('aria-expanded', 'false');
    await expect(control).toBeFocused();
    await control.focus();
    await page.keyboard.press('Enter');
    await expect(control).toHaveAttribute('aria-expanded', 'true');
    await expect(navLink(primaryNavigation(page), '/properties')).toBeVisible();
    await attachScreenshot(page, testInfo, `navigation-mobile-menu-${width}`);
    try {
      await expect.poll(() => focusIsInside(surface), { message: 'Opening the menu must move focus into it' }).toBe(true);
    } finally {
      await testInfo.attach('mobile-focus-state', { contentType: 'application/json', body: JSON.stringify(await surface.evaluate(element => ({
        active: { tag: document.activeElement?.tagName, id: document.activeElement?.id,
          label: document.activeElement?.getAttribute('aria-label') },
        visibility: getComputedStyle(element).visibility,
        inert: element.inert,
        activeRoute: element.querySelector('a[aria-current="page"]')?.getAttribute('href'),
      })), null, 2) });
    }

    const focusables = surface.locator('a[href]:visible, button:visible:not([disabled]), input:visible:not([disabled]), select:visible:not([disabled]), [tabindex="0"]:visible');
    await focusables.first().focus();
    await page.keyboard.press('Shift+Tab');
    expect(await focusIsInside(surface), 'Tab backwards must remain in the open menu').toBe(true);
    await focusables.last().focus();
    await page.keyboard.press('Tab');
    expect(await focusIsInside(surface), 'Tab forwards must remain in the open menu').toBe(true);
    await page.keyboard.press('Escape');
    await expect(control).toHaveAttribute('aria-expanded', 'false');
    await expect(control).toBeFocused();
    expect(await page.evaluate(() => document.body.style.overflow)).toBe(originalOverflow);

    await control.click();
    await expect(control).toHaveAttribute('aria-expanded', 'true');
    await page.mouse.click(width - 8, 820);
    await expect(control).toHaveAttribute('aria-expanded', 'false');
    await expect(control).toBeFocused();
    await control.click();
    await navLink(primaryNavigation(page), '/properties').click();
    await expect(page).toHaveURL(url => url.pathname === '/properties');
    await expect(control).toHaveAttribute('aria-expanded', 'false');
    await expect(navLink(primaryNavigation(page, true), '/properties')).toHaveAttribute('aria-current', 'page');
    await expect(page.getByRole('main').getByRole('heading', { level: 1 }).first()).toBeVisible();
    await assertViewport(page);
    await control.click();
    await assertViewport(page);
    await page.keyboard.press('Escape');
  });
}
