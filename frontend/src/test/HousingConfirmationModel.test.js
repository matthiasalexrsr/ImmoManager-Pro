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
    occupancy_confirmed: true,
    authority_confirmed: true,
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

  it('has no UI hard cap for household names and keeps duplicate real names', () => {
    let form = blankHousingForm();
    for (let index = 0; index < 45; index += 1) {
      form = addSuggestedOccupant(form, index < 2 ? 'Gleicher Name' : `Person ${index + 1}`);
    }
    expect(form.occupants).toHaveLength(46);
    const data = certificateDataFromForm({
      ...completeForm(),
      occupants: form.occupants.filter(item => item.name),
    });
    expect(data.occupant_names).toHaveLength(45);
    expect(data.occupant_names.slice(0, 2)).toEqual(['Gleicher Name', 'Gleicher Name']);
  });

  it('requires actual occupancy and authority confirmations only for publication', () => {
    const form = { ...completeForm(), occupancy_confirmed: false, authority_confirmed: false };
    expect(validateHousingForm(form).valid).toBe(true);
    const release = validateHousingForm(form, { forPublish: true });
    expect(release.valid).toBe(false);
    expect(release.errors).toEqual(expect.arrayContaining(['occupancy_confirmed', 'authority_confirmed']));
  });

  it('restores a historical certificate as a correction draft without carrying old confirmations', () => {
    const restored = formFromCertificateData(certificateDataFromForm(completeForm()));
    expect(restored.owner_relation).toBe('different');
    expect(restored.owner_name).toBe('Eigentümerin Beispiel');
    expect(restored.occupants.map(item => item.name)).toEqual(['Alex Beispiel']);
    expect(restored.occupancy_confirmed).toBe(false);
    expect(restored.authority_confirmed).toBe(false);
  });
});
