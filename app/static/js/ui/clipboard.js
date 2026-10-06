// Copie dans le presse-papiers : [data-copy="texte"] ou [data-copy-target="#selecteur"].
import { t } from 'ui/strings';
import { toast } from 'ui/toast';

let initialized = false;

export async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      /* repli ci-dessous */
    }
  }
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.top = '-1000px';
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch (e) {
    ok = false;
  }
  area.remove();
  return ok;
}

export function initClipboard() {
  if (initialized) return;
  initialized = true;
  document.addEventListener('click', async (event) => {
    const trigger = event.target.closest('[data-copy], [data-copy-target]');
    if (!trigger) return;
    let text = trigger.dataset.copy;
    let field = null;
    if (text === undefined) {
      const target = document.querySelector(trigger.dataset.copyTarget);
      if (!target) return;
      const isField = target.matches('input, textarea');
      field = isField ? target : null;
      text = isField ? target.value : target.textContent.trim();
    }
    if (await copyText(text)) {
      toast(t('copied'), { tone: 'success' });
      trigger.dataset.state = 'copied';
      setTimeout(() => {
        delete trigger.dataset.state;
      }, 2000);
    } else {
      toast(t('copy_failed'), { tone: 'danger' });
      if (field) {
        field.focus();
        field.select();
      }
    }
  });
}
