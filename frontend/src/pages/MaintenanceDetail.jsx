import { useParams } from 'react-router-dom';
import MaintenanceProject from '../features/maintenanceProject/MaintenanceProject';

// A new case id starts a new project view (state, open dialogs and requests of the previous one end).
export default function MaintenanceDetail() {
  const { id } = useParams();
  return <MaintenanceProject key={id} caseId={id} />;
}
