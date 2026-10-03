import { describe, expect, it } from 'vitest';
import {
  addSuggestedOccupant,
  blankHousingForm,
  certificateDataFromForm,
  formFromCertificateData,
  validateHousingForm,
} from '../features/housingConfirmation/housingConfirmationModel';

function completeForm() {
  const form = blankHousingForm();
  return {
    ...form,
    dwelling_address: 'Musterstraße 1\n12345 Berlin',
    housing_provider_name: 'Wohnungsgeber GmbH',
    housing_provider_address: 'Verwaltungsweg 2\n12345 Berlin',
    owner_relation: 'different',
    owner_name: 'Eigentümerin Beispiel',
    actual_move_in_date: '2026-10-15',
    issue_date: '2026-10-16',
    issuer_name: 'Beauftragte Person',
    issuer_role: 'authorized_person',
    occupants: [{ key: 'one', name: 'Alex Beispiel' }],
    confirmed_actual_move_in: true,
    confirmed_authority: true,
    confirmed_residents: true,
  };
}

describe('housing confirmation form model', () => {
  it('does not infer tenant names or move-in dates', () => {
    const form = blankHousingForm();
    expect(form.actual_move_in_date).toBe('');
    expect(form.issue_date).toBe('');
    expect(form.occupants).toHaveLength(1);
    expect(form.occupants[0].name).toBe('');

    const suggested = addSuggestedOccupant(form, 'Hauptmieter Beispiel');
    expect(form.occupants[0].name).toBe('');
    expect(suggested.occupants.at(-1).name).toBe('Hauptmieter Beispiel');
  });

  it('projects exactly the backend CertificateData field names and keeps duplicate real names', () => {
    let form = blankHousingForm();
    for (let index = 0; index < 45; index += 1) {
      form = addSuggestedOccupant(form, index < 2 ? 'Gleicher Name' : `Person ${index + 1}`);
    }
    const data = certificateDataFromForm({
      ...completeForm(),
      occupants: form.occupants.filter(item => item.name),
    });

    expect(Object.keys(data).sort()).toEqual([
      'apartment_address', 'apartment_label', 'housing_provider_address',
      'housing_provider_name', 'issue_date', 'issuer_name', 'issuer_role',
      'move_in_date', 'owner_name', 'owner_same_as_provider', 'residents',
    ].sort());
    expect(data.residents).toHaveLength(45);
    expect(data.residents.slice(0, 2)).toEqual(['Gleicher Name', 'Gleicher Name']);
    expect(data.move_in_date).toBe('2026-10-15');
  });

  it('requires all three SaveRequest confirmations only for publication', () => {
    const form = {
      ...completeForm(),
      confirmed_actual_move_in: false,
      confirmed_authority: false,
      confirmed_residents: false,
    };
    expect(validateHousingForm(form).valid).toBe(true);
    const release = validateHousingForm(form, { forPublish: true });
    expect(release.valid).toBe(false);
    expect(release.errors).toEqual(expect.arrayContaining([
      'confirmed_actual_move_in',
      'confirmed_authority',
      'confirmed_residents',
    ]));
  });

  it('restores backend CertificateData as a correction draft without old confirmations', () => {
    const restored = formFromCertificateData(certificateDataFromForm(completeForm()));
    expect(restored.owner_relation).toBe('different');
    expect(restored.owner_name).toBe('Eigentümerin Beispiel');
    expect(restored.occupants.map(item => item.name)).toEqual(['Alex Beispiel']);
    expect(restored.actual_move_in_date).toBe('2026-10-15');
    expect(restored.confirmed_actual_move_in).toBe(false);
    expect(restored.confirmed_authority).toBe(false);
    expect(restored.confirmed_residents).toBe(false);
  });
});
