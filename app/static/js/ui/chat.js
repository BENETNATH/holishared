// Chat (B025b) : composeur (Entrée envoie, Maj+Entrée saute une ligne, champ extensible), envoi sans rechargement,
// récupération incrémentale (?after=<id>&ts=<iso>), défilement respectueux, « Nouveaux messages », historique à la demande.
import { t } from 'ui/strings';
import { toast } from 'ui/toast';

let initialized = false;
const GROUP_MS = 300000;

export function initChat() {
  const root = document.getElementById('chat');
  if (initialized || !root) return;
  initialized = true;
  const list = document.getElementById('chat-list');
  const composer = root.querySelector('[data-testid=chat-composer]');
  const input = document.getElementById('chat-input');
  const pill = document.getElementById('chat-new');
  const pollMs = Number(root.dataset.pollMs) || 5000;
  const hiddenMs = Number(root.dataset.pollHiddenMs) || 30000;
  const messages = () => [...list.querySelectorAll('[data-message-id]')];
  const headers = { 'HX-Request': 'true' };
  let timer = null;
  let inflight = false;

  const cursor = () => {
    const last = messages().pop();
    return last ? { after: last.dataset.messageId, ts: last.dataset.created } : { after: '', ts: '' };
  };
  const atBottom = () => {
    const doc = document.documentElement;
    return doc.scrollHeight - (window.scrollY + window.innerHeight) < 120;
  };
  const toBottom = () => window.scrollTo({ top: document.documentElement.scrollHeight });
  const nodesOf = (html) => {
    const tpl = document.createElement('template');
    tpl.innerHTML = html;
    return [...tpl.content.children];
  };
  const fresh = (nodes) => {
    const known = new Set(messages().map((li) => li.dataset.messageId));
    return nodes.filter((n) => !n.dataset.messageId || !known.has(n.dataset.messageId));
  };

  // Groupes par auteur et séparateurs de date, recalculés après tout ajout ou retrait.
  function regroup() {
    let last = null;
    let chain = null;
    [...list.children].forEach((li) => {
      if (li.dataset.testid === 'chat-date') {
        if (last && last.dataset.day === li.dataset.day) li.remove();
        else chain = null;
        return;
      }
      const near = chain && Math.abs(Date.parse(li.dataset.created + 'Z') - Date.parse(chain.dataset.created + 'Z')) <= GROUP_MS;
      const continued = !!(near && chain.dataset.author === li.dataset.author && chain.dataset.day === li.dataset.day);
      if (li.dataset.continued !== String(continued)) li.dataset.continued = String(continued);
      chain = li;
      last = li;
    });
  }
  new MutationObserver(regroup).observe(list, { childList: true });

  function append(html, { stick = false } = {}) {
    const nodes = fresh(nodesOf(html));
    const added = nodes.filter((n) => n.dataset.messageId);
    if (!added.length) return 0;
    const follow = stick || atBottom();
    const empty = document.getElementById('chat-empty');
    if (empty) empty.remove();
    nodes.forEach((n) => list.appendChild(n));
    if (window.htmx) nodes.forEach((n) => window.htmx.process(n));
    regroup();
    if (follow) toBottom();
    else pill.hidden = false;
    return added.length;
  }

  async function poll() {
    if (inflight) return;
    inflight = true;
    try {
      const { after, ts } = cursor();
      const url = `${root.dataset.url}?after=${encodeURIComponent(after)}&ts=${encodeURIComponent(ts)}`;
      const response = await fetch(url, { headers, credentials: 'same-origin' });
      if (response.status === 200) append(await response.text());
    } catch (error) {
      /* réseau indisponible : le prochain cycle réessaie */
    } finally {
      inflight = false;
    }
  }
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      await poll();
      schedule();
    }, document.hidden ? hiddenMs : pollMs);
  }
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) poll();
    schedule();
  });
  window.addEventListener('pagehide', () => clearTimeout(timer));
  if (messages().length) toBottom();
  schedule();

  // Nouveaux messages
  pill.addEventListener('click', () => {
    toBottom();
    pill.hidden = true;
    input.focus({ preventScroll: true });
  });
  window.addEventListener('scroll', () => {
    if (!pill.hidden && atBottom()) pill.hidden = true;
  }, { passive: true });

  // Composeur
  const grow = () => {
    input.style.height = 'auto';
    input.style.height = `${input.scrollHeight}px`;
  };
  input.addEventListener('input', grow);
  input.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
    if (!window.matchMedia('(pointer: fine)').matches) return;
    event.preventDefault();
    if (input.value.trim()) composer.requestSubmit();
  });
  composer.addEventListener('htmx:configRequest', (event) => {
    Object.assign(event.detail.parameters, cursor());
  });
  composer.addEventListener('htmx:beforeRequest', () => {
    composer.querySelector('[data-testid=chat-send]').disabled = true;
  });
  composer.addEventListener('htmx:afterRequest', (event) => {
    composer.querySelector('[data-testid=chat-send]').disabled = false;
    if (!event.detail.successful) return;
    append(event.detail.xhr.responseText, { stick: true });
    input.value = '';
    grow();
    input.focus({ preventScroll: true });
  });

  // Historique
  const older = document.getElementById('chat-older');
  if (older) {
    older.addEventListener('click', async (event) => {
      event.preventDefault();
      if (older.getAttribute('aria-busy') === 'true') return;
      older.setAttribute('aria-busy', 'true');
      const label = older.querySelector('span');
      const text = label.textContent;
      label.textContent = t('loading');
      try {
        const response = await fetch(`${root.dataset.url}?before=${encodeURIComponent(older.dataset.before)}`, {
          headers,
          credentials: 'same-origin',
        });
        if (response.status !== 200) throw new Error(String(response.status));
        const nodes = fresh(nodesOf(await response.text()));
        const doc = document.documentElement;
        const before = doc.scrollHeight;
        const y = window.scrollY;
        const first = list.firstElementChild;
        nodes.forEach((n) => list.insertBefore(n, first));
        regroup();
        window.scrollTo(0, y + doc.scrollHeight - before);
        const top = messages()[0];
        if (top) older.dataset.before = top.dataset.messageId;
        if (response.headers.get('X-Chat-Has-More') !== 'true') older.remove();
      } catch (error) {
        toast(t('action_failed'), { tone: 'danger' });
      } finally {
        label.textContent = text;
        older.removeAttribute('aria-busy');
      }
    });
  }
}
