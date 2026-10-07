// Média (B026) : envoi multiple fichier par fichier avec progression (XHR, concurrence 2, annuler/réessayer),
// glisser-déposer, rafraîchissement de la grille sans rechargement ; visionneuse (flèches, balayage, Échap).
import { t } from 'ui/strings';
import { toast } from 'ui/toast';
import { closeSheet, openSheet } from 'ui/dialog';

const CONCURRENCY = 2;
let galleryReady = false;
let viewerReady = false;

export function initGallery() {
  const root = document.getElementById('media');
  if (galleryReady || !root) return;
  galleryReady = true;
  const form = document.getElementById('media-upload-form');
  const input = document.getElementById('media-file');
  const caption = document.getElementById('media-caption');
  const queue = document.getElementById('media-queue');
  const send = form.querySelector('[data-testid=media-send]');
  const maxBytes = Number(root.dataset.maxBytes) || 0;
  let jobs = [];
  let running = false;
  let uploaded = 0;

  const setState = (job, state, text) => {
    job.state = state;
    job.li.dataset.state = state;
    job.status.textContent = text;
    job.bar.hidden = state !== 'sending';
    job.retry.hidden = state !== 'error';
    job.cancel.hidden = state === 'done';
    job.cancel.setAttribute('aria-label', state === 'sending' ? t('cancel') : t('media_remove'));
  };

  function add(file) {
    const li = document.createElement('li');
    li.className = 'ui-media-job';
    li.dataset.testid = 'media-upload-item';
    li.innerHTML =
      '<div class="ui-media-job__row"><span class="ui-media-job__name"></span><span class="ui-media-job__status" role="status"></span></div>' +
      '<progress class="ui-progress" max="100" value="0" hidden></progress>' +
      '<div class="ui-media-job__actions"><button type="button" class="ui-btn ui-btn--ghost ui-btn--sm" data-retry hidden></button>' +
      '<button type="button" class="ui-btn ui-btn--ghost ui-btn--icon" data-cancel>✕</button></div>';
    const job = {
      file,
      li,
      state: 'pending',
      xhr: null,
      status: li.querySelector('.ui-media-job__status'),
      bar: li.querySelector('progress'),
      retry: li.querySelector('[data-retry]'),
      cancel: li.querySelector('[data-cancel]'),
    };
    li.querySelector('.ui-media-job__name').textContent = file.name;
    job.bar.setAttribute('aria-label', file.name);
    job.retry.textContent = t('media_retry');
    job.retry.addEventListener('click', () => {
      setState(job, 'pending', t('media_pending'));
      pump();
    });
    job.cancel.addEventListener('click', () => {
      if (job.xhr) job.xhr.abort();
      jobs = jobs.filter((j) => j !== job);
      li.remove();
      sync();
    });
    if (maxBytes && file.size > maxBytes) {
      queue.append(li);
      jobs.push(job);
      setState(job, 'error', root.dataset.msgTooBig);
      return;
    }
    queue.append(li);
    jobs.push(job);
    setState(job, 'pending', t('media_pending'));
  }

  function upload(job) {
    return new Promise((resolve) => {
      const xhr = new XMLHttpRequest();
      job.xhr = xhr;
      setState(job, 'sending', t('media_sending'));
      job.bar.value = 0;
      const body = new FormData(form);
      body.delete('file');
      body.set('file', job.file, job.file.name);
      xhr.open('POST', form.action);
      xhr.setRequestHeader('Accept', 'application/json');
      xhr.upload.addEventListener('progress', (event) => {
        if (event.lengthComputable) job.bar.value = Math.round((event.loaded / event.total) * 100);
      });
      xhr.addEventListener('load', () => {
        let message = '';
        try {
          message = JSON.parse(xhr.responseText).message || '';
        } catch (_e) {
          /* réponse non JSON (429, 413 de proxy…) */
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          uploaded += 1;
          setState(job, 'done', t('media_done'));
        } else if (xhr.status === 429) {
          setState(job, 'error', t('media_rate_limited'));
        } else if (xhr.status === 413) {
          setState(job, 'error', root.dataset.msgTooBig);
        } else {
          setState(job, 'error', message || t('action_failed'));
        }
        resolve();
      });
      xhr.addEventListener('error', () => {
        setState(job, 'error', t('media_network'));
        resolve();
      });
      xhr.addEventListener('abort', resolve);
      xhr.send(body);
    });
  }

  function sync() {
    const pending = jobs.some((j) => j.state === 'pending' || j.state === 'sending');
    send.disabled = running || !jobs.some((j) => j.state === 'pending');
    send.querySelector('span').textContent = running && pending ? t('media_sending') : send.dataset.label;
  }

  async function pump() {
    if (running) return;
    running = true;
    sync();
    const worker = async () => {
      let job;
      while ((job = jobs.find((j) => j.state === 'pending'))) await upload(job);
    };
    await Promise.all(Array.from({ length: CONCURRENCY }, worker));
    running = false;
    sync();
    if (uploaded) await refresh();
    if (jobs.length && jobs.every((j) => j.state === 'done')) {
      toast(t('media_added'), { tone: 'success' });
      closeSheet(document.getElementById('media-upload-sheet'));
      jobs = [];
      queue.replaceChildren();
      caption.value = '';
    }
    uploaded = 0;
  }

  function refresh() {
    return window.htmx.ajax('GET', root.dataset.galleryUrl, { target: '#media-gallery', swap: 'innerHTML' });
  }

  const addAll = (files) => {
    [...files].forEach(add);
    sync();
  };

  form.querySelector('[data-media-pick]').addEventListener('click', () => input.click());
  send.dataset.label = send.querySelector('span').textContent;
  sync();
  input.addEventListener('change', () => {
    addAll(input.files);
    input.value = '';
  });
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    pump();
  });

  // Glisser-déposer (bureau) : sur la feuille ou n'importe où sur la page.
  const drop = (event) => {
    if (!event.dataTransfer || ![...event.dataTransfer.types].includes('Files')) return;
    event.preventDefault();
    if (event.type !== 'drop') return;
    openSheet('media-upload-sheet');
    addAll(event.dataTransfer.files);
  };
  document.addEventListener('dragover', drop);
  document.addEventListener('drop', drop);
}

export function initViewer() {
  const root = document.querySelector('[data-testid=media-viewer]');
  if (viewerReady || !root) return;
  viewerReady = true;
  const go = (rel) => {
    const link = root.querySelector(`a[rel=${rel}]`);
    if (link) window.location.assign(link.href);
  };
  const image = root.querySelector('img[data-original]');
  const full = () => {
    if (image && image.src !== new URL(image.dataset.original, location.href).href) image.src = image.dataset.original;
  };
  if (image) {
    image.addEventListener('error', full, { once: true }); // miniature indisponible : l'original prend le relais
    const link = root.querySelector('[data-original-link]');
    if (link) {
      link.addEventListener('click', (event) => {
        event.preventDefault();
        full();
      });
    }
  }
  document.addEventListener('keydown', (event) => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
    if (document.querySelector('dialog[open]') || event.target.closest('input, textarea, select')) return;
    if (event.key === 'ArrowLeft') go('prev');
    else if (event.key === 'ArrowRight') go('next');
    else if (event.key === 'Escape') window.location.assign(root.dataset.back);
  });
  // Balayage tactile : horizontal franc uniquement, hors commandes de la vidéo.
  const stage = root.querySelector('[data-testid=viewer-stage]');
  let start = null;
  stage.addEventListener('touchstart', (event) => {
    start = event.target.closest('video') || event.touches.length !== 1 ? null : event.touches[0];
  }, { passive: true });
  stage.addEventListener('touchend', (event) => {
    if (!start) return;
    const end = event.changedTouches[0];
    const dx = end.clientX - start.clientX;
    const dy = end.clientY - start.clientY;
    start = null;
    if (Math.abs(dx) > 50 && Math.abs(dx) > 1.5 * Math.abs(dy)) go(dx > 0 ? 'prev' : 'next');
  }, { passive: true });
}
