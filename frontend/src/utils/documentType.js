// Document types the program sets itself (and short keys of imported data) are stored as stable keys; people see a name.
import { codeLabel } from './codeLabels';

export function documentTypeLabel(type) {
  return codeLabel(type);
}
