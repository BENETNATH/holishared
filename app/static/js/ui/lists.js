// Page d'une liste (B023, B032) : panneau « Repas & activités » (colonne repliable sur bureau, tiroir non modal
// à trois états sur mobile), ajout rapide sans rechargement, conservation des zones dépliées après un échange HTMX.
const STORAGE_KEY = 'holishared:list-panel';
const MOBILE_KEY = 'holishared:list-panel-mobile';
const TAP_PX = 8; // en dessous : simple appui
const SWIPE_PX = 40; // glissé lent : seuil de décision
const FLICK = 0.6; // px/ms : un geste rapide compte même court
const CLOSE_PX = 160; // glissé depuis « ouvert » : au-delà, fermeture directe
const FLICK_CLOSE = 1.5;

function read(storage, key) {
  try {
    return window[storage].getItem(key);
  } catch (error) {
    return null;
  }
}

function write(storage, key, value) {
  try {
    window[storage].setItem(key, value);
  } catch (error) {
    // Stockage indisponible : l'état n'est simplement pas mémorisé.
  }
}

// États : « closed » (bouton de l'en-tête seul), « collapsed » (barre compacte, mobile) et « open ».
function initPanel(root) {
  const panel = document.getElementById('list-panel');
  if (!panel) return;
  const toggles = [...document.querySelectorAll('[data-list-panel-toggle]')];
  const chevron = panel.querySelector('[data-list-panel-collapse]');
  const desktop = window.matchMedia('(min-width: 64rem)');
  const state = () => root.dataset.panel;

  function setState(next, { focus = true, remember = true } = {}) {
    const prev = state();
    root.dataset.panel = next;
    toggles.forEach((button) => button.setAttribute('aria-expanded', next === 'closed' ? 'false' : 'true'));
    const open = next === 'open';
    chevron.setAttribute('aria-expanded', open ? 'true' : 'false');
    chevron.setAttribute('aria-label', open ? chevron.dataset.labelCollapse : chevron.dataset.labelExpand);
    if (remember) {
      if (desktop.matches) write('localStorage', STORAGE_KEY, next === 'closed' ? 'closed' : 'open');
      else if (next !== 'closed') write('sessionStorage', MOBILE_KEY, next);
    }
    if (!focus) return;
    if (next === 'closed') {
      if (toggles[0]) toggles[0].focus();
    } else if (prev === 'closed') {
      panel.querySelector('#list-panel-title').focus();
    }
  }

  toggles.forEach((button) =>
    button.addEventListener('click', () => {
      if (state() !== 'closed') return setState('closed');
      const kept = read('sessionStorage', MOBILE_KEY);
      setState(!desktop.matches && kept === 'collapsed' ? 'collapsed' : 'open');
    }),
  );
  chevron.addEventListener('click', () => setState(state() === 'open' ? 'collapsed' : 'open'));
  panel.querySelectorAll('[data-list-panel-close]').forEach((button) => {
    button.addEventListener('click', () => setState('closed'));
  });

  // Échap : ferme le panneau (mobile : depuis n'importe où, sauf boîte de dialogue ; bureau : depuis le panneau).
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || state() === 'closed' || document.querySelector('dialog[open]')) return;
    if (desktop.matches && !panel.contains(document.activeElement)) return;
    setState('closed');
  });

  // Poignée (mobile) : appui = réduit/ouvert ; glissé vers le bas = réduit puis fermé ; vers le haut = ouvert.
  // Le geste est suivi jusqu'au relâchement (capture du pointeur ; `touch-action: none` côté CSS).
  const handle = panel.querySelector('[data-list-panel-handle]');
  let drag = null;
  handle.addEventListener('pointerdown', (event) => {
    if (desktop.matches || event.target.closest('button')) return;
    drag = { id: event.pointerId, y: event.clientY, t: event.timeStamp };
    try {
      handle.setPointerCapture(event.pointerId);
    } catch (error) {
      // Capture impossible : le relâchement sur la poignée suffit.
    }
  });
  handle.addEventListener('pointerup', (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    const dy = event.clientY - drag.y;
    const speed = dy / Math.max(event.timeStamp - drag.t, 1);
    drag = null;
    const current = state();
    if (Math.abs(dy) < TAP_PX) return setState(current === 'open' ? 'collapsed' : 'open');
    if (Math.abs(dy) < SWIPE_PX && Math.abs(speed) < FLICK) return;
    if (dy < 0) return setState('open');
    const fast = dy >= CLOSE_PX || speed >= FLICK_CLOSE;
    setState(current === 'open' && !fast ? 'collapsed' : 'closed');
  });
  handle.addEventListener('pointercancel', () => (drag = null));

  // Passage au bureau : l'état « réduit » n'existe pas (colonne).
  desktop.addEventListener('change', () => {
    if (desktop.matches && state() === 'collapsed') setState('open', { focus: false });
  });

  // Bureau : l'état mémorisé est restauré sans voler le focus ; mobile : le tiroir démarre fermé.
  if (desktop.matches && read('localStorage', STORAGE_KEY) === 'open') {
    setState('open', { focus: false, remember: false });
  }
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
