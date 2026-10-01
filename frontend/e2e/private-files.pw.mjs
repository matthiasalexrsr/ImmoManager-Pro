import { randomUUID } from 'node:crypto';
import { test, expect } from '@playwright/test';

const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aO5cAAAAASUVORK5CYII=', 'base64');

function pdf() {
  const stream = 'BT /F1 24 Tf 50 700 Td (Private PDF browser check) Tj ET';
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`,
  ];
  let content = '%PDF-1.4\n';
  const offsets = [0];
  objects.forEach((object, index) => { offsets.push(Buffer.byteLength(content)); content += `${index + 1} 0 obj\n${object}\nendobj\n`; });
  const start = Buffer.byteLength(content);
  content += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${start}\n%%EOF`;
  return Buffer.from(content);
}

async function login(page, username = 'demo', password = 'Demo1234') {
  await page.goto('/login');
  await page.getByLabel('Benutzername', { exact: true }).fill(username);
  await page.getByLabel('Passwort', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  return { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token'))}` };
}

test('private attachments: image/PDF upload, protected viewer and unit photo survive new login', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const errors = [];
  const directUploads = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/uploads/')) directUploads.push(request.url()); });
  await page.addInitScript(() => { if (window === window.top) localStorage.setItem('locale', 'de-DE'); });
  const headers = await login(page);
  const unique = randomUUID();
  const documents = [];
  for (const file of [{ name: 'private-image.png', mimeType: 'image/png', buffer: image }, { name: 'private-pdf.pdf', mimeType: 'application/pdf', buffer: pdf() }, { name: 'spoofed-pdf.pdf', mimeType: 'application/pdf', buffer: Buffer.from('<html><script>window.top.privateFileXss = true</script></html>') }]) {
    await page.goto('/documents');
    const uploaded = page.waitForResponse(response => response.url().includes('/files/upload?') && response.request().method() === 'POST');
    await page.locator('input[type=file]').setInputFiles(file);
    const response = await uploaded;
    expect(response.status()).toBe(200);
    const data = await response.json();
    const created = await page.request.post('/api/v1/documents', { headers, data: { title: `${unique} ${file.name}`, file_url: data.file_url } });
    expect(created.status()).toBe(201);
    documents.push(await created.json());
    expect((await page.request.get(data.file_url)).status()).toBe(401);
    expect((await page.request.get(data.file_url, { headers })).status()).toBe(200);
  }

  await page.goto('/documents');
  await page.getByRole('row').filter({ hasText: documents[0].title }).click();
  const viewer = page.getByRole('dialog', { name: 'Dateiansicht' });
  const picture = viewer.getByAltText('Dokument');
  await expect(picture).toHaveAttribute('src', /^blob:/);
  await expect.poll(() => picture.evaluate(element => element.naturalWidth)).toBe(1);
  const download = page.waitForEvent('download');
  await viewer.getByRole('link', { name: 'Herunterladen', exact: true }).click();
  expect((await download).suggestedFilename()).toMatch(/\.png$/);
  await viewer.getByRole('button', { name: 'Schließen' }).click();
  await page.getByRole('row').filter({ hasText: documents[1].title }).click();
  const frame = viewer.getByTitle('PDF Viewer');
  await expect(frame).toHaveAttribute('src', /^blob:/);
  await expect(frame).not.toHaveAttribute('sandbox');
  // Chromium's native PDF viewer embeds the PDF plug-in in its protected frame.
  await expect.poll(async () => {
    const content = await frame.contentFrame();
    return content.locator('embed[type="application/pdf"]').count();
  }).toBe(1);
  // Native plug-ins do not expose a DOM paint-ready event. Wait for their
  // document/network load and allow rendering before capturing visual evidence.
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1500);
  const screenshot = testInfo.outputPath('private-pdf-viewer.png');
  await page.screenshot({ path: screenshot, fullPage: true });
  await testInfo.attach('private-pdf-viewer', { path: screenshot, contentType: 'image/png' });
  await viewer.getByRole('button', { name: 'Schließen' }).click();

  await page.getByRole('row').filter({ hasText: documents[2].title }).click();
  await expect(viewer.getByRole('alert')).toHaveText('Dateiinhalt passt nicht zum Dateityp. Die Datei kann nur heruntergeladen werden.');
  await expect(viewer.locator('iframe')).toHaveCount(0);
  await expect(viewer.getByRole('link', { name: 'Herunterladen', exact: true })).toHaveAttribute('download', /\.pdf$/);
  expect(await page.evaluate(() => window.privateFileXss)).toBeUndefined();
  await viewer.getByRole('button', { name: 'Schließen' }).click();

  const unitsResponse = await page.request.get('/api/v1/units', { headers });
  const unit = (await unitsResponse.json())[0];
  await page.goto(`/units/${unit.id}`);
  const uploadedPhoto = page.waitForResponse(response => response.url().includes('/photos/upload?') && response.request().method() === 'POST');
  await page.getByLabel('Fotos hochladen').setInputFiles({ name: 'private-photo.png', mimeType: 'image/png', buffer: image });
  expect((await uploadedPhoto).status()).toBe(201);
  const photo = page.locator('.photo-grid img').last();
  await expect(photo).toHaveAttribute('src', /^blob:/);
  await expect.poll(() => photo.evaluate(element => element.naturalWidth)).toBe(1);
  await page.reload();
  await expect(photo).toHaveAttribute('src', /^blob:/);

  const reader = `reader-${unique}`;
  expect((await page.request.post('/api/v1/auth/users', { headers, data: { username: reader, email: `${reader}@example.com`, full_name: 'Private File Reader', password: 'Strong123', role: 'readonly' } })).status()).toBe(201);
  await page.evaluate(() => localStorage.clear());
  await login(page, reader, 'Strong123');
  await page.goto(`/units/${unit.id}`);
  await expect(photo).toHaveAttribute('src', /^blob:/);
  await expect.poll(() => photo.evaluate(element => element.naturalWidth)).toBe(1);
  await page.goto('/documents');
  await page.getByRole('row').filter({ hasText: documents[0].title }).click();
  await expect(picture).toHaveAttribute('src', /^blob:/);
  await expect.poll(() => picture.evaluate(element => element.naturalWidth)).toBe(1);
  expect(directUploads, 'Image and viewer requests use protected downloads, never public uploads URLs').toEqual([]);
  expect(errors).toEqual([]);
});
