import { test, expect, germanWorkspaceReady } from './demoFixtures.mjs';

async function login(page) {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill('demo');
  await page.getByLabel('Passwort', { exact: true }).fill('Demo1234');
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await germanWorkspaceReady(page);
  await page.goto('/settings');
  await page.getByRole('button', { name: 'System', exact: true }).click();
  await expect(page.getByText('Datenbank erreichbar', { exact: true })).toBeVisible();
}

async function geometry(control) {
  return control.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const clipping = [];
    for (let ancestor = element.parentElement; ancestor; ancestor = ancestor.parentElement) {
      const style = getComputedStyle(ancestor);
      const bounds = ancestor.getBoundingClientRect();
      if (['hidden', 'clip', 'auto', 'scroll'].includes(style.overflowX)
          && (rect.left < bounds.left - 1 || rect.right > bounds.right + 1)) {
        clipping.push({ className: ancestor.className, left: bounds.left, right: bounds.right, overflowX: style.overflowX });
      }
    }
    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    const row = element.closest('.settings-row');
    const panel = element.closest('.panel');
    const rowLabel = row?.querySelector('label');
    return { label: element.getAttribute('aria-label') || element.labels?.[0]?.textContent || element.textContent,
      left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width,
      viewportWidth: innerWidth, viewportHeight: innerHeight, pageWidth: document.documentElement.scrollWidth,
      hit: hit === element || element.contains(hit), clipping, pageScrollX: scrollX,
      panel: panel && { rect: panel.getBoundingClientRect().toJSON(), scrollLeft: panel.scrollLeft,
        scrollWidth: panel.scrollWidth, clientWidth: panel.clientWidth },
      rowLabel: rowLabel && { text: rowLabel.textContent, rect: rowLabel.getBoundingClientRect().toJSON() },
      header: document.querySelector('.top-bar').getBoundingClientRect().toJSON(),
      active: document.activeElement === element,
      skip: { focused: document.activeElement === document.querySelector('.shell-skip-link'),
        rect: document.querySelector('.shell-skip-link').getBoundingClientRect().toJSON() } };
  });
}

async function panelGeometry(page) {
  return page.locator('.settings-grid .panel').evaluateAll(panels => panels.map(panel => {
    const bounds = panel.getBoundingClientRect();
    const clippedText = [...panel.querySelectorAll('.settings-row label, .settings-section > p')]
      .filter(element => element.textContent.trim())
      .map(element => ({ text: element.textContent, rect: element.getBoundingClientRect().toJSON() }))
      .filter(item => item.rect.left < bounds.left || item.rect.right > bounds.right);
    return { title: panel.querySelector('.panel-header')?.textContent,
      left: bounds.left, right: bounds.right, viewportWidth: innerWidth,
      scrollLeft: panel.scrollLeft, scrollWidth: panel.scrollWidth, clientWidth: panel.clientWidth, clippedText };
  }));
}

for (const width of [320, 360]) {
  test(`System controls remain fully readable and keyboard reachable at ${width}px`, async ({ page }, testInfo) => {
    const mutations = [];
    page.on('request', request => {
      if (request.method() === 'POST' && ['/api/v1/data/import', '/api/v1/admin/backup', '/api/v1/updates/apply']
        .includes(new URL(request.url()).pathname)) mutations.push(request.url());
    });
    await login(page);
    if (width === 320) {
      const desktopPanels = await panelGeometry(page);
      expect(desktopPanels.filter(panel => panel.left < 0 || panel.right > panel.viewportWidth
        || panel.scrollWidth > panel.clientWidth + 1 || panel.clippedText.length),
      'Desktop panels must retain readable labels and controls').toEqual([]);
      await page.screenshot({ path: testInfo.outputPath('system-desktop.png') });
    }
    await page.setViewportSize({ width, height: 800 });
    // Load directly at the requested width; resizing the desktop shell animates its margin.
    await page.reload();
    await page.getByRole('button', { name: 'System', exact: true }).click();
    await expect(page.getByText('Datenbank erreichbar', { exact: true })).toBeVisible();
    await expect.poll(() => page.locator('.main-content').evaluate(element => element.getBoundingClientRect().left)).toBe(0);
    await page.evaluate(() => scrollTo(0, 0));
    await page.screenshot({ path: testInfo.outputPath(`system-${width}-top.png`) });
    const panels = await panelGeometry(page);
    await testInfo.attach(`system-${width}-panels`, { body: JSON.stringify(panels, null, 2), contentType: 'application/json' });
    expect(panels.filter(panel => panel.left < 0 || panel.right > width || panel.scrollLeft !== 0
      || panel.scrollWidth > panel.clientWidth + 1 || panel.clippedText.length),
    'Panel text must fit before any browser focus can silently scroll an overflow-hidden panel').toEqual([]);
    const backup = page.locator('.panel').filter({ has: page.getByLabel('Daten importieren', { exact: true }) });
    await backup.evaluate(panel => scrollTo(0, scrollY + panel.getBoundingClientRect().top
      - document.querySelector('.top-bar').getBoundingClientRect().height - 12));
    await page.screenshot({ path: testInfo.outputPath(`system-${width}-backup.png`) });

    const controls = page.locator('.settings-grid button:enabled, .settings-grid input:enabled, .settings-grid select:enabled, .settings-grid [tabindex="0"]');
    const observations = [];
    const keyboardOrder = await controls.all();
    await keyboardOrder[0].focus();
    for (let index = 0; index < keyboardOrder.length; index += 1) {
      const control = keyboardOrder[index];
      if (index) await page.keyboard.press('Tab');
      await expect(control, 'Every displayed system action and the scrollable metrics table must be reachable by Tab').toBeFocused();
      observations.push(await geometry(control));
      if (await control.getAttribute('type') === 'file') {
        await page.screenshot({ path: testInfo.outputPath(`system-${width}-filepicker.png`) });
      }
    }
    await testInfo.attach(`system-${width}-geometry`, { body: JSON.stringify(observations, null, 2), contentType: 'application/json' });
    const clipped = observations.filter(item => item.left < -1 || item.right > width + 1 || item.clipping.length || !item.hit
      || item.pageScrollX !== 0 || item.panel && (item.panel.scrollLeft !== 0
        || item.panel.scrollWidth > item.panel.clientWidth + 1)
      || item.rowLabel && (item.rowLabel.rect.left < 0 || item.rowLabel.rect.right > width));
    expect(clipped, 'Every control must fit its visible panel and viewport, including its complete accessible file input').toEqual([]);
    expect(observations.every(item => item.active)).toBe(true);
    expect(observations.every(item => Math.abs(item.header.top) <= 1)).toBe(true);
    expect(observations.every(item => !item.skip.focused && item.skip.rect.bottom < 0)).toBe(true);

    // Enter genuinely opens the browser file chooser. Cancelling must not import anything.
    const file = page.getByLabel('Daten importieren', { exact: true });
    await file.focus();
    const picker = page.waitForEvent('filechooser');
    await file.press('Enter');
    await (await picker).setFiles([]);
    await expect(file).toHaveValue('');
    const info = page.getByRole('button', { name: 'Info', exact: true });
    await info.focus();
    const infoResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/admin/database-info');
    await info.press('Enter');
    expect((await infoResponse).status()).toBe(200);
    await expect(page.getByText('DB-Details', { exact: true })).toBeVisible();
    expect((await panelGeometry(page)).filter(panel => panel.scrollLeft !== 0 || panel.scrollWidth > panel.clientWidth + 1
      || panel.clippedText.length), 'Read-only database details must wrap without hiding the backup controls').toEqual([]);
    await file.focus();
    await page.screenshot({ path: testInfo.outputPath(`system-${width}-backup-details.png`) });
    expect(mutations, 'Keyboard inspection and cancelling the picker must not run any backup/import/update action').toEqual([]);

    const skip = page.getByRole('link', { name: 'Zum Inhalt springen', exact: true });
    await skip.focus();
    await expect(skip).toBeFocused();
    await expect.poll(() => skip.evaluate(element => element.getBoundingClientRect().top)).toBeGreaterThanOrEqual(0);
    await skip.press('Enter');
    await expect(page.locator('#workspace-content')).toBeFocused();
    await expect.poll(() => skip.evaluate(element => element.getBoundingClientRect().bottom)).toBeLessThan(0);

    const table = page.getByRole('region', { name: 'Anfragen nach Verwaltungsbereich', exact: true });
    await table.focus();
    await table.press('ArrowRight');
    await expect.poll(() => table.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
