// Page d'une liste (B023) : panneau « Repas & activités » (colonne repliable sur bureau, tiroir non modal
// sur mobile), ajout rapide sans rechargement, conservation des zones dépliées après un échange HTMX.
const STORAGE_KEY = 'holishared:list-panel';
const SWIPE_CLOSE_PX = 60;

function readStored() {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch (error) {
    return null;
  }
}

function writeStored(value) {
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch (error) {
    // Stockage indisponible : l'état n'est simplement pas mémorisé.
  }
}

function initPanel(root) {
  const panel = document.getElementById('list-panel');
  if (!panel) return;
  const toggles = [...document.querySelectorAll('[data-list-panel-toggle]')];
  const desktop = window.matchMedia('(min-width: 64rem)');
  const isOpen = () => root.dataset.panel === 'open';

  function setOpen(open, { focus = true, remember = true } = {}) {
    root.dataset.panel = open ? 'open' : 'closed';
    toggles.forEach((button) => button.setAttribute('aria-expanded', open ? 'true' : 'false'));
    if (remember && desktop.matches) writeStored(open ? 'open' : 'closed');
    if (!focus) return;
    if (open) panel.querySelector('#list-panel-title').focus();
    else if (toggles[0]) toggles[0].focus();
  }

  toggles.forEach((button) => button.addEventListener('click', () => setOpen(!isOpen())));
  panel.querySelectorAll('[data-list-panel-close]').forEach((button) => {
    button.addEventListener('click', () => setOpen(false));
  });

  // Échap : ferme le panneau (mobile : depuis n'importe où, sauf boîte de dialogue ; bureau : depuis le panneau).
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || !isOpen() || document.querySelector('dialog[open]')) return;
    if (desktop.matches && !panel.contains(document.activeElement)) return;
    setOpen(false);
  });

  // Glissé vers le bas sur l'en-tête du tiroir (mobile) : fermeture.
  const handle = panel.querySelector('[data-list-panel-handle]');
  let startY = null;
  handle.addEventListener('pointerdown', (event) => {
    if (desktop.matches || event.target.closest('button')) return;
    startY = event.clientY;
  });
  handle.addEventListener('pointermove', (event) => {
    if (startY !== null && event.clientY - startY > SWIPE_CLOSE_PX) {
      startY = null;
      setOpen(false);
    }
  });
  ['pointerup', 'pointercancel'].forEach((name) => handle.addEventListener(name, () => (startY = null)));

  // Bureau : l'état mémorisé est restauré sans voler le focus ; mobile : le tiroir démarre fermé.
  if (desktop.matches && readStored() === 'open') setOpen(true, { focus: false, remember: false });
}

// Après un échange HTMX, les <details> repliables gardent l'état qu'ils avaient (clé data-keep-open).
function initKeepOpen() {
  let states = new Map();
  document.body.addEventListener('htmx:beforeSwap', () => {
    states = new Map(
      [...document.querySelectorAll('details[data-keep-open]')].map((el) => [el.dataset.keepOpen, el.open]),
    );
  });
  document.body.addEventListener('htmx:afterSwap', () => {
    document.querySelectorAll('details[data-keep-open]').forEach((el) => {
      if (states.has(el.dataset.keepOpen)) el.open = states.get(el.dataset.keepOpen);
    });
  });
}

// Ajout rapide : le champ est vidé et garde le focus (saisie en rafale) sauf erreur de validation (toast).
function initAddForm() {
  document.body.addEventListener('htmx:afterRequest', (event) => {
    const form = event.target;
    if (!form.matches || !form.matches('[data-list-add]') || !event.detail.successful) return;
    if (event.detail.xhr.getResponseHeader('HX-Reswap') === 'none') return;
    form.reset();
    form.querySelector('[name="name"]').focus();
  });
}

export function initLists() {
  const root = document.querySelector('[data-list-layout]');
  if (!root) return;
  initPanel(root);
  initKeepOpen();
  initAddForm();
}
