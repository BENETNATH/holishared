// Notifications Web Push (B027) : section « Notifications » de Mon profil et invitation de l'accueil.
// La permission du navigateur n'est demandée qu'au geste de l'utilisateur (interrupteur), jamais au chargement.
import { t } from 'ui/strings';
import { toast } from 'ui/toast';

const DISMISS_KEY = 'hs-push-invite-dismissed';
let initialized = false;
let dismissedInMemory = false;

const isIos = () =>
  /iphone|ipad|ipod/i.test(navigator.userAgent) ||
  (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const isStandalone = () =>
  window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
const hasPush = () =>
  'serviceWorker' in navigator &&
  'PushManager' in window &&
  'Notification' in window &&
  document.documentElement.dataset.sw === 'on';

// 'ok' | 'install' (iOS hors écran d'accueil) | 'unsupported' | 'denied'
export function supportState() {
  if (!hasPush()) return isIos() && !isStandalone() ? 'install' : 'unsupported';
  return Notification.permission === 'denied' ? 'denied' : 'ok';
}

function keyToBytes(key) {
  const raw = atob((key + '='.repeat((4 - (key.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

async function post(card, name, body) {
  const response = await fetch(card.dataset['url' + name], {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': card.dataset.csrf },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error('push ' + name + ' ' + response.status);
  return response.json();
}

async function currentSubscription() {
  const registration = await navigator.serviceWorker.ready;
  return registration.pushManager.getSubscription();
}

function showPrefs(card, prefs) {
  const box = card.querySelector('[data-push-prefs]');
  box.hidden = !prefs;
  card.querySelector('[data-push-state="granted"]').hidden = !prefs;
  card.querySelector('[data-push-toggle]').checked = !!prefs;
  if (!prefs) return;
  card.querySelectorAll('[data-pref]').forEach((input) => {
    input.checked = prefs[input.dataset.pref] !== false;
  });
}

// Le service worker « actif » peut être une ancienne version, sans gestionnaire push, tant que la nouvelle
// attend la confirmation de la bannière de mise à jour : on active la dernière avant de s'abonner,
// sinon le navigateur affiche seulement « ce site a été mis à jour » au lieu du message.
async function latestRegistration() {
  const registration = await navigator.serviceWorker.ready;
  try {
    await registration.update();
  } catch (error) {
    // Hors ligne : on garde le worker actif.
  }
  const worker = registration.installing || registration.waiting;
  if (!worker) return registration;
  if (worker.state !== 'installed') {
    await new Promise((resolve) => {
      const done = () => {
        if (worker.state !== 'installed' && worker.state !== 'redundant') return;
        worker.removeEventListener('statechange', done);
        resolve();
      };
      worker.addEventListener('statechange', done);
      done();
    });
  }
  if (!registration.waiting) return registration;
  toast(t('update_applying'), { tone: 'info' });
  registration.waiting.postMessage({ type: 'SKIP_WAITING' }); // la page se recharge (ui/pwa)
  return null;
}

async function enable(card) {
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return initCardState(card);
  const registration = await latestRegistration();
  if (!registration) return undefined;
  const subscription =
    (await registration.pushManager.getSubscription()) ||
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyToBytes(card.dataset.vapidKey),
    }));
  const json = subscription.toJSON();
  const result = await post(card, 'Subscribe', {
    endpoint: json.endpoint,
    keys: json.keys,
    lang: (navigator.language || 'fr').slice(0, 2),
  });
  showPrefs(card, result.prefs);
  toast(t('push_on'), { tone: 'success' });
}

async function disable(card, all) {
  const subscription = await currentSubscription();
  await post(card, 'Unsubscribe', all ? { all: true } : { endpoint: subscription && subscription.endpoint });
  if (subscription) await subscription.unsubscribe();
  showPrefs(card, null);
  toast(t('push_off'), { tone: 'info' });
}

function initCardState(card) {
  const state = supportState();
  card.querySelectorAll('[data-push-state]').forEach((el) => {
    if (el.dataset.pushState !== 'granted') el.hidden = el.dataset.pushState !== state;
  });
  card.querySelector('[data-push-controls]').hidden = state !== 'ok';
  return state;
}

async function initCard(card) {
  if (initCardState(card) !== 'ok') return;
  const toggle = card.querySelector('[data-push-toggle]');
  const guarded = (action) => async (event) => {
    const target = event.target;
    target.disabled = true;
    try {
      await action(target);
    } catch (error) {
      if (target.type === 'checkbox') target.checked = !target.checked;
      toast(t('push_error'), { tone: 'danger' });
    } finally {
      target.disabled = false;
    }
  };
  toggle.addEventListener('change', guarded((el) => (el.checked ? enable(card) : disable(card, false))));
  card.querySelectorAll('[data-pref]').forEach((input) => {
    input.addEventListener(
      'change',
      guarded(async (el) => {
        const subscription = await currentSubscription();
        await post(card, 'Prefs', { endpoint: subscription.endpoint, [el.dataset.pref]: el.checked });
      }),
    );
  });
  card.querySelector('[data-push-disable-all]').addEventListener(
    'click',
    guarded(() => disable(card, true)),
  );
  if (Notification.permission !== 'granted') return;
  const subscription = await currentSubscription();
  if (!subscription) return;
  const status = await post(card, 'Status', { endpoint: subscription.endpoint });
  if (status.subscribed) showPrefs(card, status.prefs);
}

function isDismissed() {
  try {
    return localStorage.getItem(DISMISS_KEY) === '1' || dismissedInMemory;
  } catch (error) {
    return dismissedInMemory;
  }
}

function initInvite(invite) {
  if (supportState() === 'ok' && Notification.permission === 'default' && !isDismissed()) invite.hidden = false;
  else if (supportState() === 'install' && !isDismissed()) invite.hidden = false;
  invite.querySelector('[data-push-dismiss]').addEventListener('click', () => {
    dismissedInMemory = true;
    try {
      localStorage.setItem(DISMISS_KEY, '1');
    } catch (error) {
      // Stockage indisponible : l'invitation reste masquée jusqu'au prochain chargement.
    }
    invite.hidden = true;
  });
}

export function initPush() {
  if (initialized) return;
  initialized = true;
  document.querySelectorAll('[data-push]').forEach((card) => initCard(card).catch(() => {}));
  document.querySelectorAll('[data-push-invite]').forEach(initInvite);
}
