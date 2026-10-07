// Frais (B024) : le taux de change n'apparaît que pour une devise différente de la devise de base.
import { openSheet } from 'ui/dialog';

let initialized = false;

function sync(select) {
  const field = select.closest('form')?.querySelector('[data-rate-field]');
  if (!field) return;
  const hidden = select.value === select.dataset.baseCurrency;
  field.hidden = hidden;
  const input = field.querySelector('input');
  if (input) input.required = !hidden;
}

export function initCosts() {
  if (initialized) return;
  initialized = true;
  document.addEventListener('change', (event) => {
    if (event.target.matches('[data-currency-select]')) sync(event.target);
  });
  document.querySelectorAll('[data-currency-select]').forEach(sync);
  // Après une erreur de validation, le serveur demande de rouvrir la feuille concernée.
  const marker = document.querySelector('[data-costs-open-sheet]');
  if (marker) openSheet(JSON.parse(marker.textContent), null);
}
