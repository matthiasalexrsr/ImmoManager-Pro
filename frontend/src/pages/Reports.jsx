import FinanceReports from '../features/FinanceReports';
import { ChartNoAxesCombined } from 'lucide-react';

export default function Reports() {
  return <div className="page finance-page"><header className="finance-page-heading"><ChartNoAxesCombined size={24} aria-hidden="true" /><div>
    <h1 className="page-title">Auswertungen</h1><p>Zahlen verstehen, Quellen prüfen und Entscheidungen vorbereiten.</p>
  </div></header><FinanceReports standalone /></div>;
}
