// Thème clair/sombre : data-theme posé avant le rendu par le script de <head>.
let initialized = false;

export function getTheme() {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
}

export function setTheme(theme, { persist = true } = {}) {
  document.documentElement.setAttribute('data-theme', theme);
  const canvas = getComputedStyle(document.documentElement).getPropertyValue('--color-canvas').trim();
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta && canvas) meta.setAttribute('content', canvas);
  document.querySelectorAll('[data-theme-toggle]').forEach((btn) => {
    btn.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
  });
  if (persist) {
    try {
      localStorage.setItem('theme', theme);
    } catch (e) {
      /* stockage indisponible : le thème reste valable pour cette page */
    }
  }
}

function hasStoredTheme() {
  try {
    const stored = localStorage.getItem('theme');
    return stored === 'light' || stored === 'dark';
  } catch (e) {
    return false;
  }
}

export function initTheme() {
  if (initialized) return;
  initialized = true;
  setTheme(getTheme(), { persist: false });
  document.addEventListener('click', (event) => {
    if (event.target.closest('[data-theme-toggle]')) {
      setTheme(getTheme() === 'dark' ? 'light' : 'dark');
    }
  });
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  media.addEventListener('change', (event) => {
    if (!hasStoredTheme()) setTheme(event.matches ? 'dark' : 'light', { persist: false });
  });
}
