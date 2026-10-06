// Confirmation des actions destructives : [data-confirm="message"] sur un formulaire ou un bouton.
let initialized = false;

export function confirmAction({ message, confirmLabel, tone = 'danger' }) {
  const template = document.getElementById('ui-confirm-template');
  const dialog = template.content.firstElementChild.cloneNode(true);
  dialog.querySelector('[data-confirm-message]').textContent = message;
  const accept = dialog.querySelector('[data-confirm-accept]');
  if (confirmLabel) accept.textContent = confirmLabel;
  if (tone === 'primary') {
    accept.classList.remove('ui-btn--danger');
    accept.classList.add('ui-btn--primary');
  }
  const opener = document.activeElement;
  document.body.appendChild(dialog);
  return new Promise((resolve) => {
    dialog.addEventListener('close', () => {
      const accepted = dialog.returnValue === 'accept';
      dialog.remove();
      if (opener && document.contains(opener)) opener.focus();
      resolve(accepted);
    });
    dialog.showModal();
  });
}

export function initConfirm() {
  if (initialized) return;
  initialized = true;
  document.addEventListener('submit', async (event) => {
    const form = event.target;
    const source = (event.submitter && event.submitter.closest('[data-confirm]')) ||
      (form.matches('[data-confirm]') ? form : null);
    if (!source) return;
    if (form.dataset.confirmed === '1') {
      delete form.dataset.confirmed;
      return;
    }
    event.preventDefault();
    const accepted = await confirmAction({
      message: source.dataset.confirm,
      confirmLabel: source.dataset.confirmLabel,
      tone: source.dataset.confirmTone,
    });
    if (accepted) {
      form.dataset.confirmed = '1';
      form.requestSubmit(event.submitter ?? undefined);
    }
  });
}
