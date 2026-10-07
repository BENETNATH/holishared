// Infos pratiques (B025b) : feuille d'ajout/modification ancrée en bas, fermée après l'enregistrement HTMX.
// Sans JS, les liens ouvrent le formulaire page entière.
import { openSheet, closeSheet } from 'ui/dialog';

let initialized = false;

function openForm(trigger) {
  const sheet = document.getElementById('info-sheet');
  const form = sheet.querySelector('form');
  const edit = trigger.dataset.fields ? JSON.parse(trigger.dataset.fields) : null;
  const url = edit ? trigger.href : form.dataset.createUrl;
  form.action = url;
  form.setAttribute('hx-post', url);
  window.htmx?.process(form);
  const values = edit || { title: '', content: '', category: 'general' };
  Object.entries(values).forEach(([name, value]) => {
    if (form.elements[name]) form.elements[name].value = value;
  });
  form.querySelectorAll('.ui-error').forEach((el) => el.remove());
  form.querySelectorAll('[data-invalid]').forEach((el) => el.removeAttribute('data-invalid'));
  form.querySelectorAll('[aria-invalid]').forEach((el) => el.removeAttribute('aria-invalid'));
  sheet.querySelector('.ui-sheet__title').textContent = edit ? form.dataset.editTitle : form.dataset.createTitle;
  const menu = trigger.closest('details');
  if (menu) menu.open = false;
  openSheet(sheet, menu ? menu.querySelector('summary') : trigger);
  form.elements.title.focus();
}

export function initInfos() {
  if (initialized || !document.getElementById('info-sheet')) return;
  initialized = true;
  document.addEventListener('click', (event) => {
    const opener = event.target.closest('[data-info-add], [data-info-edit]');
    if (!opener) return;
    event.preventDefault();
    openForm(opener);
  });
  // La liste n'est remplacée qu'après un enregistrement ou une suppression réussis (une erreur remplace le formulaire).
  document.body.addEventListener('htmx:afterSwap', (event) => {
    if (event.detail.target.id === 'infos-list') closeSheet('info-sheet');
  });
}
