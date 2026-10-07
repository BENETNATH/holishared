// Sondages (B025) : feuille de création rapide, champs selon le type, sélection d'activités.
// Sans JS, le lien « Nouveau sondage » ouvre le formulaire page entière et tous les champs restent visibles.
import { openSheet } from 'ui/dialog';

let initialized = false;

function syncKind(form, { fromUser = false } = {}) {
  const kind = form.querySelector('input[name="kind"]:checked');
  const activities = !!kind && kind.value === 'activities';
  form.querySelectorAll('[data-poll-panel="activities"]').forEach((panel) => {
    panel.hidden = !activities;
  });
  const label = form.querySelector('[data-poll-options-label]');
  const help = form.querySelector('[data-poll-options-help]');
  const key = activities ? 'activities' : 'free';
  if (label) label.textContent = label.dataset[key];
  if (help) help.textContent = help.dataset[key];
  if (!fromUser) return;
  const question = form.elements.question;
  const suggestion = form.dataset.defaultQuestion;
  if (activities && !question.value.trim()) {
    question.value = suggestion;
    form.dataset.autoQuestion = '1';
  } else if (!activities && form.dataset.autoQuestion === '1' && question.value === suggestion) {
    question.value = '';
    delete form.dataset.autoQuestion;
  }
}

function filterDay(select) {
  const day = select.value;
  select.closest('fieldset').querySelectorAll('[data-poll-activity-day]').forEach((item) => {
    const checked = item.querySelector('input').checked;
    item.hidden = !!day && item.dataset.pollActivityDay !== day && !checked;
  });
}

export function initVoting() {
  if (initialized) return;
  initialized = true;
  document.querySelectorAll('[data-poll-fields]').forEach((form) => syncKind(form));
  document.addEventListener('change', (event) => {
    const form = event.target.closest('[data-poll-fields]');
    if (!form) return;
    if (event.target.name === 'kind') syncKind(form, { fromUser: true });
    if (event.target.matches('[data-poll-day-filter]')) filterDay(event.target);
  });
  document.addEventListener('input', (event) => {
    const form = event.target.closest('[data-poll-fields]');
    if (form && event.target.name === 'question') delete form.dataset.autoQuestion;
  });
  document.addEventListener('click', (event) => {
    const opener = event.target.closest('[data-poll-add]');
    if (!opener) return;
    const sheet = document.getElementById('poll-sheet');
    if (!sheet) return;
    event.preventDefault();
    const form = sheet.querySelector('form');
    form.reset();
    delete form.dataset.autoQuestion;
    syncKind(form);
    form.querySelectorAll('[data-poll-activity-day]').forEach((item) => (item.hidden = false));
    openSheet(sheet, opener);
    form.elements.question.focus();
  });
}
