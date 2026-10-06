// Anti double envoi : le deuxième envoi est bloqué, le bouton passe en état « chargement ».
let initialized = false;
const HX_ATTRIBUTES = ['hx-get', 'hx-post', 'hx-put', 'hx-patch', 'hx-delete'];

export function initForms() {
  if (initialized) return;
  initialized = true;
  document.addEventListener('submit', (event) => {
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
