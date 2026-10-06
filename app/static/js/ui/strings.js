// Chaînes JS : registre unique rendu par le serveur dans #ui-strings (app/ui.py JS_STRINGS).
let cache = null;

export function t(key) {
  if (cache === null) {
    const el = document.getElementById('ui-strings');
    cache = el ? JSON.parse(el.textContent) : {};
  }
  if (!(key in cache)) {
    console.error('ui-strings: clé manquante ' + key);
    return key;
  }
  return cache[key];
}
