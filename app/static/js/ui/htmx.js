// Retour d'erreur HTMX : une réponse 4xx/5xx ou une panne réseau n'est pas insérée, elle déclenche un toast.
import { t } from 'ui/strings';
import { toast } from 'ui/toast';

let initialized = false;

export function initHtmx() {
  if (initialized) return;
  initialized = true;
  const fail = () => toast(t('action_failed'), { tone: 'danger' });
  document.addEventListener('htmx:responseError', fail);
  document.addEventListener('htmx:sendError', fail);
}
