// Feuilles et dialogues : <dialog> natif (focus piégé, Échap), retour du focus, aria-expanded.
let initialized = false;
const openers = new WeakMap();

function resolve(target) {
  return typeof target === 'string' ? document.getElementById(target) : target;
}

export function openSheet(target, opener = document.activeElement) {
  const dialog = resolve(target);
  if (!dialog) return null;
  const other = document.querySelector('dialog[open]');
  if (other && other !== dialog) {
    // La feuille précédente passe la main : son déclencheur est celui à restaurer.
    opener = openers.get(other) || opener;
    openers.delete(other);
    other.close();
  }
  openers.set(dialog, opener);
  dialog.showModal();
  if (opener && opener.hasAttribute && opener.hasAttribute('aria-expanded')) {
    opener.setAttribute('aria-expanded', 'true');
  }
  return dialog;
}

export function closeSheet(dialog, returnValue = '') {
  const el = resolve(dialog);
  if (el && el.open) el.close(returnValue);
}

export function initSheets() {
  if (initialized) return;
  initialized = true;
  document.addEventListener('click', (event) => {
    const opener = event.target.closest('[data-sheet-open]');
    if (opener) {
      openSheet(opener.dataset.sheetOpen, opener);
      return;
    }
    if (event.target.closest('[data-sheet-close]')) {
      closeSheet(event.target.closest('dialog'));
      return;
    }
    const dialog = event.target;
    if (dialog instanceof HTMLDialogElement && dialog.classList.contains('ui-sheet')) {
      closeSheet(dialog);
    }
  });
  // `close` ne remonte pas : écoute en capture.
  document.addEventListener(
    'close',
    (event) => {
      const dialog = event.target;
      if (!(dialog instanceof HTMLDialogElement) || !openers.has(dialog)) return;
      const opener = openers.get(dialog);
      openers.delete(dialog);
      if (opener && opener.hasAttribute && opener.hasAttribute('aria-expanded')) {
        opener.setAttribute('aria-expanded', 'false');
      }
      if (opener && document.contains(opener)) opener.focus();
    },
    true,
  );
}
