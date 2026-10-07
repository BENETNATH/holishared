// Anti double envoi : le deuxième envoi est bloqué, le bouton passe en état « chargement ».
let initialized = false;
const HX_ATTRIBUTES = ['hx-get', 'hx-post', 'hx-put', 'hx-patch', 'hx-delete'];

export function initForms() {
  if (initialized) return;
  initialized = true;
  // Sur `window` (et non `document`) : l'écouteur passe APRÈS ceux des modules qui prennent l'envoi en charge
  // (fetch + preventDefault, ex. repas/listes) ; sinon le formulaire restait verrouillé après le premier envoi.
  window.addEventListener('submit', (event) => {
    if (event.defaultPrevented) return;
    const form = event.target;
    if (form.matches('[data-no-lock]') || form.getAttribute('method') === 'dialog') return;
    if (HX_ATTRIBUTES.some((name) => form.hasAttribute(name))) return;
    if (form.dataset.submitting === '1') {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = '1';
    const submitter = event.submitter;
    if (submitter) {
      // Pas de `disabled` : la valeur name=value du bouton doit rester dans l'envoi.
      submitter.setAttribute('aria-disabled', 'true');
      submitter.setAttribute('aria-busy', 'true');
      submitter.setAttribute('data-loading', 'true');
    }
  });
  // Cohérence des dates : la fin ne peut pas précéder le début (et suit le début si elle est vide).
  document.addEventListener('change', (event) => {
    const start = event.target;
    if (!start.matches('[data-date-start]')) return;
    const end = start.form && start.form.querySelector('[data-date-end]');
    if (!end || !start.value) return;
    end.min = start.value;
    if (!end.value || end.value < start.value) end.value = start.value;
  });
  window.addEventListener('pageshow', (event) => {
    if (!event.persisted) return;
    document.querySelectorAll('form[data-submitting]').forEach((form) => {
      delete form.dataset.submitting;
    });
    document.querySelectorAll('[data-loading="true"]').forEach((button) => {
      button.removeAttribute('aria-disabled');
      button.removeAttribute('aria-busy');
      button.removeAttribute('data-loading');
    });
  });
}
