import { useAuth } from '../contexts/AuthContext';
import AssistantWorkspace from '../features/assistant/AssistantWorkspace';

export default function Assistant() {
  const owner = useAuth()?.user?.id;
  return owner ? <AssistantWorkspace key={owner} owner={owner} />
    : <div className="page" role="status">Persönlicher KI-Arbeitsbereich wird geladen …</div>;
}
