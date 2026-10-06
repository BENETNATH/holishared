// Toasts : zone vivante persistante ; un toast émis pendant qu'une feuille est ouverte
// est inséré dans cette feuille (la top layer rend le reste du document inerte).
let initialized = false;
const timers = new WeakMap();
const MAX_TOASTS = 3;
const AUTO_HIDE_MS = 6000;
const LEAVE_MS = 200;

function reducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function zone() {
  const open = [...document.querySelectorAll('dialog[open]')].pop();
  if (!open) return document.getElementById('toast-region');
  let region = open.querySelector(':scope > .ui-toast-region');
  if (!region) {
    region = document.getElementById('toast-region').cloneNode(true);
    region.removeAttribute('id');
    region.removeAttribute('data-testid');
    region.querySelectorAll('.ui-toast-stack').forEach((stack) => stack.replaceChildren());
    open.appendChild(region);
  }
  return region;
}

function closeToast(el) {
  if (el.dataset.state === 'leaving') return;
  el.dataset.state = 'leaving';
  disarm(el);
  setTimeout(() => el.remove(), reducedMotion() ? 0 : LEAVE_MS);
}

function disarm(el) {
  const state = timers.get(el);
  if (state && state.timer) clearTimeout(state.timer);
}

function arm(el, timeout) {
  disarm(el);
  if (timeout === null || timeout === undefined) {
    timers.set(el, { timeout: null, timer: null });
    return;
  }
  timers.set(el, { timeout, timer: setTimeout(() => closeToast(el), timeout) });
}

function defaultTimeout(tone) {
  return tone === 'success' || tone === 'info' ? AUTO_HIDE_MS : null;
}

export function toast(message, { tone = 'info', action = null, timeout } = {}) {
  const template = document.getElementById('ui-toast-template');
  const el = template.content.firstElementChild.cloneNode(true);
  el.dataset.tone = tone;
  el.querySelectorAll('[data-tone-icon]').forEach((icon) => {
    if (icon.dataset.toneIcon !== tone) icon.remove();
  });
  if (action) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'ui-btn ui-btn--ghost ui-btn--sm';
    button.setAttribute('data-toast-action', '');
    button.textContent = action.label;
    button.addEventListener('click', () => action.onClick());
    el.insertBefore(button, el.querySelector('[data-toast-close]'));
  }
  const target = zone();
  const live = tone === 'success' || tone === 'info' ? 'polite' : 'assertive';
  target.querySelector(`[data-toast-live="${live}"]`).appendChild(el);
  const all = target.querySelectorAll('.ui-toast');
  if (all.length > MAX_TOASTS) all[0].remove();
  const message_el = el.querySelector('.ui-toast__message');
  requestAnimationFrame(() => {
    message_el.textContent = message;
  });
  arm(el, timeout === undefined ? defaultTimeout(tone) : timeout);
  return el;
}

function pause(el) {
  disarm(el);
}

function resume(el) {
  const state = timers.get(el);
  if (state && state.timeout !== null) arm(el, AUTO_HIDE_MS);
}

export function initToasts() {
  if (initialized) return;
  initialized = true;
  document.addEventListener('click', (event) => {
    const close = event.target.closest('[data-toast-close]');
    if (close) closeToast(close.closest('.ui-toast'));
  });
  document.addEventListener(
    'pointerenter',
    (event) => {
      if (event.target.matches && event.target.matches('.ui-toast')) pause(event.target);
    },
    true,
  );
  document.addEventListener(
    'pointerleave',
    (event) => {
      if (event.target.matches && event.target.matches('.ui-toast')) resume(event.target);
    },
    true,
  );
  document.addEventListener('focusin', (event) => {
    const el = event.target.closest('.ui-toast');
    if (el) pause(el);
  });
  document.addEventListener('focusout', (event) => {
    const el = event.target.closest('.ui-toast');
    if (el && !el.contains(event.relatedTarget)) resume(el);
  });
  // Toasts rendus par le serveur : minuteur, puis réécriture du message pour l'annonce.
  document.querySelectorAll('.ui-toast[data-testid="toast"]').forEach((el) => {
    const tone = el.dataset.tone;
    arm(el, defaultTimeout(tone));
    const message_el = el.querySelector('.ui-toast__message');
    const text = message_el.textContent;
    message_el.textContent = '';
    requestAnimationFrame(() => {
      message_el.textContent = text;
    });
  });
}
