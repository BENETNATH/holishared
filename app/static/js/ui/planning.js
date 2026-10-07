// Page Planning (B021) : sélecteur de jours (mobile), saut à aujourd'hui, feuille d'ajout/édition.
// Les textes viennent des attributs data-* rendus par le serveur ; sans JS, les liens ouvrent le formulaire page entière.
import { openSheet } from 'ui/dialog';

const DESKTOP = '(min-width: 1024px)';
let initialized = false;
let selectedDay = null;

const program = () => document.getElementById('program');
const sections = () => [...program().querySelectorAll('[data-planning-day]')];

function applyDay() {
  const root = program();
  if (!root) return;
  const days = sections().map((s) => s.dataset.planningDay);
  if (!days.includes(selectedDay)) selectedDay = root.dataset.selectedDay;
  root.dataset.selectedDay = selectedDay;
  sections().forEach((section) => {
    const on = section.dataset.planningDay === selectedDay;
    section.classList.toggle('hidden', !on);
    section.classList.toggle('flex', on);
  });
  root.querySelectorAll('[data-planning-day-tab]').forEach((tab) => {
    tab.setAttribute('aria-pressed', tab.dataset.planningDayTab === selectedDay ? 'true' : 'false');
  });
}

function selectDay(day) {
  selectedDay = day;
  applyDay();
  const tab = program().querySelector(`[data-planning-day-tab="${day}"]`);
  if (tab) tab.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
  if (window.matchMedia(DESKTOP).matches) {
    const section = program().querySelector(`[data-planning-day="${day}"]`);
    if (section) section.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }
}

function fill(form, values) {
  Object.entries(values).forEach(([name, value]) => {
    const input = form.elements[name];
    if (input) input.value = value;
  });
}

function openForm(trigger) {
  const sheet = document.getElementById('activity-sheet');
  const form = sheet.querySelector('form');
  const edit = trigger.dataset.fields ? JSON.parse(trigger.dataset.fields) : null;
  form.reset();
  form.action = edit ? trigger.href : form.dataset.createUrl;
  sheet.querySelector('.ui-sheet__title').textContent = edit ? form.dataset.editTitle : form.dataset.createTitle;
  form.querySelector('[data-planning-submit]').textContent = edit ? form.dataset.editSubmit : form.dataset.createSubmit;
  if (edit) {
    fill(form, edit);
  } else {
    fill(form, { date: selectedDay || program().dataset.selectedDay });
  }
  const more = form.querySelector('[data-planning-more]');
  more.open = !!edit && ['end_time', 'location', 'description', 'bring_items'].some((n) => edit[n]) || (edit && edit.min_headcount > 1);
  const menu = trigger.closest('details');
  if (menu) menu.open = false;
  openSheet(sheet, menu ? menu.querySelector('summary') : trigger);
  form.elements.title.focus();
}

export function initPlanning() {
  if (initialized || !program()) return;
  initialized = true;
  selectedDay = program().dataset.selectedDay;
  applyDay();
  document.addEventListener('click', (event) => {
    const tab = event.target.closest('[data-planning-day-tab]');
    if (tab) return selectDay(tab.dataset.planningDayTab);
    const today = event.target.closest('[data-planning-today]');
    if (today) return selectDay(today.dataset.planningToday);
    const opener = event.target.closest('[data-planning-add], [data-planning-edit]');
    if (opener) {
      event.preventDefault();
      openForm(opener);
    }
  });
}
