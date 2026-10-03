export const KNOWN_MEDIA = Object.freeze({
  cold_water: 'Kaltwasser',
  hot_water: 'Warmwasser',
  heating: 'Heizwärme / Heizung',
  electricity: 'Strom',
  gas: 'Gas',
});

export const KNOWN_UNITS = Object.freeze({
  'm³': 'Kubikmeter (m³)',
  m3: 'Kubikmeter (m3)',
  kWh: 'Kilowattstunden (kWh)',
  MWh: 'Megawattstunden (MWh)',
  Wh: 'Wattstunden (Wh)',
  GJ: 'Gigajoule (GJ)',
  l: 'Liter (l)',
  L: 'Liter (L)',
});

export function billingPrincipalKey(authOrUser) {
  const user = authOrUser?.user || authOrUser;
  const role = user?.role || authOrUser?.role || '';
  const id = user?.id || (role ? `legacy-role:${role}` : '');
  if (!id || user?.is_active === false) return '';
  return JSON.stringify([
    id,
    role,
    [...(user?.write_permissions || [])].sort(),
    user?.portfolio_access || '',
    [...(user?.portfolio_ids || [])].sort(),
  ]);
}

export function dimensionPresentation(value, kind, { required = false } = {}) {
  const normalized = typeof value === 'string' ? value : null;
  if (!normalized) {
    return {
      text: required ? 'Pflichtangabe fehlt' : 'Ungeklärt',
      state: required ? 'missing' : 'unknown',
      raw: null,
    };
  }
  const known = kind === 'medium' ? KNOWN_MEDIA[normalized] : KNOWN_UNITS[normalized];
  return {
    text: known || `Individuell: ${normalized}`,
    state: known ? 'known' : 'custom',
    raw: normalized,
  };
}

export function normalizeOptionalDimension(value) {
  if (value == null) return null;
  const normalized = String(value).trim();
  return normalized || null;
}

export function allocationKeyPayload(data) {
  const payload = {
    ...data,
    consumption_medium: normalizeOptionalDimension(data.consumption_medium),
    consumption_unit: normalizeOptionalDimension(data.consumption_unit),
  };
  if (payload.key_type === 'consumption') {
    const missing = [];
    if (!payload.consumption_medium) missing.push('Verbrauchsmedium');
    if (!payload.consumption_unit) missing.push('Maßeinheit');
    if (missing.length) {
      throw new Error(
        `Für einen Verbrauchsschlüssel sind ${missing.join(' und ')} erforderlich. `
        + 'Leer bedeutet ungeklärt; bitte die tatsächliche Zuordnung ausdrücklich eintragen.',
      );
    }
  }
  return payload;
}

export function meterPayload(data) {
  return {
    ...data,
    measurement_unit: normalizeOptionalDimension(data.measurement_unit),
  };
}

export const DIMENSION_HINTS = Object.freeze({
  medium: 'Bekannte Werte: cold_water (Kaltwasser), hot_water (Warmwasser), heating (Heizung), electricity (Strom), gas (Gas). Andere vorhandene fachliche Werte können unverändert eingegeben werden.',
  allocationUnit: 'Tatsächliche Verbrauchseinheit, z. B. m³, kWh, MWh oder GJ. Sie muss für die Abrechnung exakt zur Zählereinheit passen; es erfolgt keine automatische Umrechnung.',
  meterUnit: 'Tatsächliche Einheit dieses Zählers, z. B. m³ oder kWh. Leer bleibt ausdrücklich ungeklärt; der Wert wird nicht aus dem Zählertyp geraten.',
});
