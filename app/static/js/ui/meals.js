// Page Repas (B022) : feuille d'un repas, actions par fetch (le fragment de grille remplace l'ancien),
// déplacement aux pointer events (souris + tactile). Aucune bibliothèque.
import { t } from 'ui/strings';
import { toast } from 'ui/toast';
import { closeSheet } from 'ui/dialog';

const CELL = '[data-testid="meal-cell"]';
const DRAG_THRESHOLD = 6;
const EDGE = 72;
const TAB_SWITCH_MS = 450;

let initialized = false;
let selectedDay = null;
let current = null; // id du repas affiché dans la feuille
let busy = false;
let focusAfter = null; // { mealId } ou { date, slot }

const grid = () => document.getElementById('meal-grid');
const sheet = () => document.getElementById('meal-sheet');
const moveForm = () => sheet().querySelector('[data-testid="meal-move-form"]');

// --- Jour affiché (mobile) -------------------------------------------------

function applyDay() {
  const root = grid();
  if (!root) return;
  const days = [...root.querySelectorAll('[data-meal-day]')].map((s) => s.dataset.mealDay);
  if (!days.includes(selectedDay)) selectedDay = root.dataset.selectedDay;
  root.dataset.selectedDay = selectedDay;
  root.querySelectorAll('[data-meal-day]').forEach((section) => {
    const on = section.dataset.mealDay === selectedDay;
    section.classList.toggle('hidden', !on);
    section.classList.toggle('flex', on);
  });
  root.querySelectorAll('[data-meal-day-tab]').forEach((tab) => {
    tab.setAttribute('aria-pressed', tab.dataset.mealDayTab === selectedDay ? 'true' : 'false');
  });
}

function selectDay(day, { reveal = true } = {}) {
  selectedDay = day;
  applyDay();
  if (reveal) {
    const tab = grid().querySelector(`[data-meal-day-tab="${day}"]`);
    if (tab) tab.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
  }
}

function shiftDay(step) {
  const days = [...grid().querySelectorAll('[data-meal-day]')].map((s) => s.dataset.mealDay);
  const next = days[days.indexOf(selectedDay) + step];
  if (next) selectDay(next);
}

// --- Envoi et remplacement de la grille -------------------------------------

function notify(header) {
  if (!header) return;
  try {
    const payload = JSON.parse(header)['meals:message'];
    if (payload) toast(payload.message, { tone: payload.tone });
  } catch {
    // en-tête illisible : aucun message plutôt qu'un message faux
  }
}

function restoreFocus() {
  const root = grid();
  const target = focusAfter;
  focusAfter = null;
  if (!root || !target) return;
  let el = null;
  if (target.mealId) el = root.querySelector(`[data-meal-id="${target.mealId}"] [data-meal-open]`);
  if (!el && target.date) {
    el = root.querySelector(`[data-meal-add][data-date="${target.date}"][data-slot="${target.slot}"]`);
  }
  if (el && !el.disabled) el.focus({ preventScroll: true });
}

function swapGrid(html) {
  const template = document.createElement('template');
  template.innerHTML = html.trim();
  const next = template.content.firstElementChild;
  if (!next || next.id !== 'meal-grid') return false;
  grid().replaceWith(next);
  applyDay();
  return true;
}

async function send(url, params, { focus = null } = {}) {
  if (busy) return false;
  busy = true;
  grid().setAttribute('aria-busy', 'true');
  focusAfter = focus;
  try {
    const response = await fetch(url, {
      method: 'POST',
      body: new URLSearchParams(params),
      headers: { 'HX-Request': 'true' },
      credentials: 'same-origin',
    });
    const redirect = response.headers.get('HX-Redirect');
    if (redirect) {
      window.location.assign(redirect);
      return false;
    }
    if ((response.status === 200 || response.status === 422) && swapGrid(await response.text())) {
      notify(response.headers.get('HX-Trigger'));
      restoreFocus();
      return response.ok;
    }
    toast(t('action_failed'), { tone: 'danger' });
    return false;
  } catch {
    toast(t('action_failed'), { tone: 'danger' });
    return false;
  } finally {
    busy = false;
    const root = grid();
    if (root) root.removeAttribute('aria-busy');
  }
}

function moveParams(card, cell, before) {
  return {
    csrf_token: sheet().querySelector('input[name="csrf_token"]').value,
    meal_id: card.dataset.mealId,
    date: cell.dataset.date,
    slot: cell.dataset.slot,
    before_id: before ? before.dataset.mealId : '',
  };
}

// --- Feuille d'un repas ------------------------------------------------------

const cardById = (id) => grid().querySelector(`[data-meal-id="${id}"]`);

function fillSheet(card) {
  const dialog = sheet();
  const cell = card.closest(CELL);
  const editable = card.dataset.editable === '1';
  current = card.dataset.mealId;
  dialog.querySelector('#meal-sheet-title').textContent = card.dataset.title;
  dialog.querySelector('[data-meal-sheet-cell]').textContent = cell.dataset.header;
  dialog.querySelector('[data-meal-readonly]').hidden = editable;
  dialog.querySelector('[data-meal-actions]').hidden = !editable;
  if (!editable) return;
  const edit = dialog.querySelector('[data-meal-edit-form]');
  edit.action = card.dataset.editUrl;
  edit.elements.title.value = card.dataset.title;
  dialog.querySelector('[data-meal-delete-form]').action = card.dataset.deleteUrl;
  dialog.querySelectorAll('input[name="meal_id"]').forEach((input) => {
    input.value = current;
  });
  const move = moveForm();
  move.elements.date.value = cell.dataset.date;
  move.elements.slot.value = cell.dataset.slot;

  const select = dialog.querySelector('#meal-swap-other');
  select.replaceChildren();
  grid()
    .querySelectorAll('[data-meal-id][data-editable="1"]')
    .forEach((other) => {
      if (other.dataset.mealId === current) return;
      const option = document.createElement('option');
      option.value = other.dataset.mealId;
      option.textContent = `${other.closest(CELL).dataset.header} — ${other.dataset.title}`;
      select.appendChild(option);
    });
  const none = select.options.length === 0;
  const swapForm = dialog.querySelector('[data-testid="meal-swap-form"]');
  swapForm.querySelector('[data-meal-swap-empty]').hidden = !none;
  select.closest('.ui-field').hidden = none;
  swapForm.querySelector('button[type="submit"]').disabled = none;

  const siblings = [...card.parentElement.children];
  const index = siblings.indexOf(card);
  dialog.querySelector('[data-meal-reorder="up"]').disabled = index === 0;
  dialog.querySelector('[data-meal-reorder="down"]').disabled = index === siblings.length - 1;
}

async function reorder(direction) {
  const card = current && cardById(current);
  if (!card) return;
  let before = null;
  if (direction === 'up') before = card.previousElementSibling;
  else if (card.nextElementSibling) before = card.nextElementSibling.nextElementSibling;
  await send(moveForm().action, moveParams(card, card.closest(CELL), before), {
    focus: { mealId: current },
  });
  const next = current && cardById(current);
  if (next && sheet().open) {
    fillSheet(next);
    const button = sheet().querySelector(`[data-meal-reorder="${direction}"]`);
    (button.disabled ? sheet().querySelector('[data-meal-reorder]:not(:disabled)') : button)?.focus();
  }
}

function onClick(event) {
  const target = event.target;
  const tab = target.closest('[data-meal-day-tab]');
  if (tab) {
    selectDay(tab.dataset.mealDayTab);
    return;
  }
  const open = target.closest('[data-meal-open]');
  if (open) {
    fillSheet(open.closest('[data-meal-id]'));
    return;
  }
  const add = target.closest('[data-meal-add]');
  if (add) {
    const dialog = document.getElementById('meal-add-sheet');
    const form = dialog.querySelector('form');
    form.elements.date.value = add.dataset.date;
    form.elements.slot.value = add.dataset.slot;
    form.elements.title.value = '';
    dialog.querySelector('[data-meal-add-target]').textContent = add.dataset.header;
    return;
  }
  const reorderButton = target.closest('[data-meal-reorder]');
  if (reorderButton) reorder(reorderButton.dataset.mealReorder);
}

async function onSubmit(event) {
  const form = event.target.closest?.('[data-meal-form]');
  if (!form || event.defaultPrevented) return;
  event.preventDefault();
  const data = Object.fromEntries(new FormData(form));
  let focus = { mealId: data.meal_id || current };
  if (form.matches('[data-testid="meal-add-form"]')) {
    focus = { date: data.date, slot: data.slot };
  } else if (form.matches('[data-meal-delete-form]')) {
    const cell = cardById(current).closest(CELL);
    focus = { date: cell.dataset.date, slot: cell.dataset.slot };
  }
  const ok = await send(form.action, data, { focus });
  if (ok) closeSheet(form.closest('dialog'));
}

// --- Glisser aux pointer events ----------------------------------------------

let drag = null;

function clearTarget() {
  if (!drag) return;
  if (drag.cell) drag.cell.classList.remove('ring-2', 'ring-primary-strong');
  if (drag.indicator) drag.indicator.remove();
  drag.cell = null;
  drag.before = null;
}

function updateTarget() {
  const el = document.elementFromPoint(drag.x, drag.y);
  const tab = el && el.closest('[data-meal-day-tab]');
  const cell = el && el.closest(CELL);
  if (tab) {
    clearTarget();
    if (tab.dataset.mealDayTab !== selectedDay && drag.tabTimer === null) {
      drag.tabTimer = setTimeout(() => {
        selectDay(tab.dataset.mealDayTab, { reveal: false });
        drag.tabTimer = null;
      }, TAB_SWITCH_MS);
    }
    return;
  }
  clearTimeout(drag.tabTimer);
  drag.tabTimer = null;
  if (!cell) {
    clearTarget();
    return;
  }
  if (cell !== drag.cell) {
    clearTarget();
    drag.cell = cell;
    cell.classList.add('ring-2', 'ring-primary-strong');
  }
  const list = cell.querySelector('[data-meal-list]');
  const cards = [...list.querySelectorAll('[data-meal-id]')].filter((c) => c !== drag.card);
  drag.before =
    cards.find((c) => {
      const box = c.getBoundingClientRect();
      return drag.y < box.top + box.height / 2;
    }) || null;
  if (!drag.indicator) {
    drag.indicator = document.createElement('li');
    drag.indicator.setAttribute('aria-hidden', 'true');
    drag.indicator.dataset.mealDropIndicator = '';
    drag.indicator.className = 'h-1 rounded-full bg-primary-strong';
  }
  list.insertBefore(drag.indicator, drag.before);
}

function moveGhost() {
  drag.ghost.style.transform = `translate(${drag.x - drag.offsetX}px, ${drag.y - drag.offsetY}px)`;
}

function scrollLoop() {
  if (!drag || !drag.active) return;
  let step = 0;
  if (drag.y < EDGE) step = -Math.ceil((EDGE - drag.y) / 4);
  else if (drag.y > window.innerHeight - EDGE) {
    step = Math.ceil((drag.y - (window.innerHeight - EDGE)) / 4);
  }
  if (step) {
    window.scrollBy(0, step);
    updateTarget();
  }
  drag.raf = requestAnimationFrame(scrollLoop);
}

function activateDrag() {
  const box = drag.card.getBoundingClientRect();
  drag.active = true;
  drag.offsetX = drag.startX - box.left;
  drag.offsetY = drag.startY - box.top;
  drag.ghost = drag.card.cloneNode(true);
  drag.ghost.removeAttribute('data-testid');
  drag.ghost.removeAttribute('data-meal-id');
  drag.ghost.setAttribute('aria-hidden', 'true');
  drag.ghost.className += ' pointer-events-none fixed left-0 top-0 z-50 opacity-90';
  drag.ghost.style.width = `${box.width}px`;
  document.body.appendChild(drag.ghost);
  drag.card.classList.add('opacity-40');
  document.body.classList.add('select-none');
  grid().dataset.dragging = 'true';
  moveGhost();
  drag.raf = requestAnimationFrame(scrollLoop);
}

function endDrag() {
  if (!drag) return;
  clearTimeout(drag.tabTimer);
  cancelAnimationFrame(drag.raf);
  clearTarget();
  if (drag.ghost) drag.ghost.remove();
  drag.card.classList.remove('opacity-40');
  document.body.classList.remove('select-none');
  const root = grid();
  if (root) delete root.dataset.dragging;
  document.removeEventListener('pointermove', onPointerMove);
  document.removeEventListener('pointerup', onPointerUp);
  document.removeEventListener('pointercancel', endDrag);
  document.removeEventListener('keydown', onDragKey, true);
  drag = null;
}

function onPointerDown(event) {
  const handle = event.target.closest?.('[data-meal-handle]');
  if (!handle || drag || busy || (event.pointerType === 'mouse' && event.button !== 0)) return;
  drag = {
    card: handle.closest('[data-meal-id]'),
    startX: event.clientX,
    startY: event.clientY,
    x: event.clientX,
    y: event.clientY,
    active: false,
    tabTimer: null,
    cell: null,
    before: null,
    indicator: null,
  };
  try {
    handle.setPointerCapture(event.pointerId);
  } catch {
    // capture refusée : les écouteurs du document suffisent
  }
  event.preventDefault();
  document.addEventListener('pointermove', onPointerMove);
  document.addEventListener('pointerup', onPointerUp);
  document.addEventListener('pointercancel', endDrag);
  document.addEventListener('keydown', onDragKey, true);
}

function onPointerMove(event) {
  if (!drag) return;
  drag.x = event.clientX;
  drag.y = event.clientY;
  if (!drag.active) {
    if (Math.hypot(drag.x - drag.startX, drag.y - drag.startY) < DRAG_THRESHOLD) return;
    activateDrag();
  }
  moveGhost();
  updateTarget();
}

function onPointerUp() {
  if (!drag) return;
  const { card, active, cell, before } = drag;
  endDrag();
  if (!active || !cell) return;
  if (card.closest(CELL) === cell) {
    // Même case : rien à envoyer si la carte reste à sa place.
    const next = card.nextElementSibling;
    if (before === next || (before === null && next === null)) return;
  }
  send(moveForm().action, moveParams(card, cell, before), { focus: { mealId: card.dataset.mealId } });
}

function onDragKey(event) {
  if (event.key !== 'Escape') return;
  event.stopPropagation();
  const active = drag && drag.active;
  endDrag();
  if (active) toast(t('meal_drag_cancelled'), { tone: 'info' });
}

// --- Balayage (mobile) ---------------------------------------------------------

function initSwipe() {
  let start = null;
  document.addEventListener(
    'touchstart',
    (event) => {
      const root = grid();
      const inside = root && root.contains(event.target);
      const blocked = event.target.closest('[data-meal-tabs], [data-meal-handle]');
      start =
        inside && !blocked && event.touches.length === 1
          ? { x: event.touches[0].clientX, y: event.touches[0].clientY }
          : null;
    },
    { passive: true },
  );
  document.addEventListener(
    'touchend',
    (event) => {
      if (!start || window.matchMedia('(min-width: 1024px)').matches) return;
      const touch = event.changedTouches[0];
      const dx = touch.clientX - start.x;
      const dy = touch.clientY - start.y;
      start = null;
      if (Math.abs(dx) > 70 && Math.abs(dy) < 40) shiftDay(dx < 0 ? 1 : -1);
    },
    { passive: true },
  );
}

export function initMeals() {
  if (initialized || !grid()) return;
  initialized = true;
  selectedDay = grid().dataset.selectedDay;
  applyDay();
  document.addEventListener('click', onClick);
  document.addEventListener('submit', onSubmit);
  document.addEventListener('pointerdown', onPointerDown);
  document.addEventListener('contextmenu', (event) => {
    if (event.target.closest?.('[data-meal-handle]')) event.preventDefault();
  });
  initSwipe();
}
