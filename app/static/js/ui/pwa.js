// Service worker : enregistrement, nettoyage de l'ancien SW, annonce des mises à jour.
import { t } from 'ui/strings';
import { toast } from 'ui/toast';

let initialized = false;

function promptUpdate(worker) {
  toast(t('new_version'), {
    tone: 'info',
    timeout: null,
    action: { label: t('reload'), onClick: () => worker.postMessage({ type: 'SKIP_WAITING' }) },
  });
}

export async function initPwa() {
  if (initialized) return;
  initialized = true;
  if (!('serviceWorker' in navigator) || document.documentElement.dataset.sw !== 'on') return;
  // Ancien service worker (portée /static/js/) : désinscrit.
  const registrations = await navigator.serviceWorker.getRegistrations();
  await Promise.all(
    registrations.filter((r) => r.scope.endsWith('/static/js/')).map((r) => r.unregister()),
  );
  const hadController = !!navigator.serviceWorker.controller;
  const registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
  if (registration.waiting && hadController) promptUpdate(registration.waiting);
  registration.addEventListener('updatefound', () => {
    const worker = registration.installing;
    if (!worker) return;
    worker.addEventListener('statechange', () => {
      if (worker.state === 'installed' && navigator.serviceWorker.controller) promptUpdate(worker);
    });
  });
  let reloaded = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!hadController || reloaded) return;
    reloaded = true;
    location.reload();
  });
}
