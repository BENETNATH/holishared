// Masquage d'un secret : bouton [data-reveal][aria-controls] bascule data-masked sur [data-secret].
import { t } from 'ui/strings';

let initialized = false;

export function initReveal() {
  if (initialized) return;
  initialized = true;
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-reveal]');
    if (!button) return;
    const target = document.getElementById(button.getAttribute('aria-controls'));
    if (!target) return;
    const masked = target.dataset.masked === 'true';
    target.dataset.masked = masked ? 'false' : 'true';
    button.setAttribute('aria-pressed', masked ? 'true' : 'false');
    const label = button.querySelector('[data-reveal-label]');
    if (label) label.textContent = masked ? t('hide') : t('show');
  });
}
