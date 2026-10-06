// Retour d'erreur HTMX : une réponse 4xx/5xx ou une panne réseau n'est pas insérée, elle déclenche un toast.
// Les réponses peuvent aussi demander un toast via l'en-tête HX-Trigger {"ui:toast": {message, tone, timeout, action}} ;
// `action` {label, post, values, target, swap} ajoute un bouton (ex. « Annuler ») qui rejoue une requête HTMX.
import { t } from 'ui/strings';
import { toast } from 'ui/toast';

let initialized = false;

export function initHtmx() {
  if (initialized) return;
  initialized = true;
  const fail = () => toast(t('action_failed'), { tone: 'danger' });
  document.addEventListener('htmx:responseError', fail);
  document.addEventListener('htmx:sendError', fail);
  document.addEventListener('ui:toast', (event) => {
    const { message, tone = 'info', timeout, action } = event.detail || {};
    if (!message) return;
    const options = { tone };
    if (timeout !== undefined) options.timeout = timeout;
    let el = null;
    if (action) {
      options.action = {
        label: action.label,
        onClick: () => {
          if (el) el.querySelector('[data-toast-close]').click();
          window.htmx.ajax('POST', action.post, {
            values: action.values,
            target: action.target,
            swap: action.swap,
          });
        },
      };
    }
    el = toast(message, options);
  });
}
