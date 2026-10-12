# B017 — Socle Tailwind, shell mobile & outillage UI

- **Lot** : B017 · **Branche** : `ui/tailwind-refonte` · **Statut** : spec corrigée après audit (`specs/audits/B017-spec.md`, 28 constats : suivi en §14)
- **Références** : `AUDIT_UI.md` N1–N9, I3, V10, F20 (+ F20 suite : portée du service worker), F31 (flash de thème), F33 (partiel : fondations), F04 (publication de la page Participants, créateur seul), §11.4 (inventaire JS) ; `TASKS.md` B017 (17.1 → 17.7).
- **Lecteurs** : agent de tests (étape 3), agent de codage au contexte vierge (étape 4), agent d'audit (étape 6). Tout ce qui est nécessaire est ici : ne rien deviner, ne rien ajouter.

---

## 1. Contexte, objectifs, périmètre

### 1.1 Contexte

L'interface repose sur un `main.css` de 5 391 lignes empilées par lots, un `base.html` qui contient ≈ 180 lignes de JS inline, une barre du bas à 4 onglets absente hors événement, un service worker inopérant (portée `/static/js/`) et aucun filet de test visuel. Le programme B017 → B028 migre l'interface vers Tailwind CSS v4 en « big-bang » sur la branche ; B017 pose **le socle** sur lequel chaque lot suivant réécrit ses pages.

### 1.2 Objectifs (résultats vérifiables)

1. Build Tailwind v4 local (Node 22, sans CDN), CSS compilé commité, CI qui refuse un CSS périmé.
2. Design tokens (couleurs clair/sombre AA mesurées, typo, espacements, rayons, ombres, z-index, hauteurs) et thème sans flash.
3. Shell responsive : en-tête sobre, barre du bas 5 destinations + « Plus » (feuille ancrée en bas) dans un événement, navigation sobre hors événement, barre latérale sur bureau, états actifs fiables (y compris pages de « Plus »).
4. Kit de composants `ui-*` + macros Jinja + jeu d'icônes SVG unique ; page catalogue `/_ui` (dev uniquement).
5. JS partagé en modules ES (copie, thème, feuilles, toasts, confirmation, formulaires, PWA) ; fin du JS inline de `base.html` et des duplications copie/confirmation.
6. Service worker servi à la racine, cache versionné par empreinte, page hors ligne, mise à jour annoncée.
7. Outillage `scripts/ui/` : graine de démo, serveur de démo jetable, runner de captures, garde `npm run ui:check`.

### 1.3 Dans le périmètre

- Tout le contenu des sections 2 à 9 ci-dessous.
- Adaptation **minimale** de gabarits existants pour retirer le JS dupliqué (copie, masquage de code, `confirm()`) : `events/dashboard.html`, `events/members.html`, `events/invite.html`, `costs/index.html` (détail §7.12).
- **Correctif de sécurité** de `events/members.html` : les codes personnels des participants (et leurs boutons « Voir »/« Copier ») ne sont rendus que pour le créateur (§7.12) ; l'entrée « Participants » de la navigation n'est affichée qu'au créateur jusqu'à la refonte de la page en B020.
- F33 (partiel) : B017 fournit à B022 les fondations utilisables par la grille des repas — feuille `<dialog>` accessible (pour « Déplacer vers… »), toasts, dialogue de confirmation, anti double envoi.
- Corrections minimales de débordement horizontal dans le CSS historique (N2, §2.6).
- Chaînes i18n nouvelles du shell (FR + EN), correction de l'entrée « Créer » (fuzzy, traduction fausse).

### 1.4 Hors périmètre (lot responsable)

| Sujet | Lot |
|---|---|
| Réécriture visuelle des pages (accueil événement, planning, repas, listes, frais…) | B019–B026 |
| Résolution des cibles < 44 px **dans le contenu des pages historiques** (I3 page par page) — B017 garantit ≥ 44 px pour le shell et les composants et fournit la garde | lot de chaque page |
| Menu « Événement » complet (partager, mon code, export, gestion) — B017 ne fournit que le groupe « Événement » de la feuille « Plus » | B020 |
| Refonte de la page Participants et son ouverture aux invités (sans aucun code d'autrui) | B020 |
| F33 : glisser-déposer par pointer events, navigation clavier de la grille, rôles ARIA des cellules | B022 |
| Pastille créateur éditable, nom d'affichage (F22) — B017 affiche la pastille en lecture seule | B020 |
| Traduction des `flash()` et du reste du catalogue | B018 |
| Modale d'upgrade (3 copies), génération de code `Math.random` (F30), JS repas/listes/chat | B028/F19, B029, B022, B023, B025 |
| Gestionnaires `push`/`notificationclick` du SW | B027 |
| Icônes PWA maskable dédiées, page 500 | B028 |
| Suppression du CSS historique, activation du Preflight Tailwind, durcissement CSP | B028 |

---

## 2. Arborescence, build et CI

### 2.1 Fichiers

**Créés**

```
package.json
package-lock.json
app/static/src/app.css            # entrée Tailwind (couches, imports, sources)
app/static/src/theme.css          # tokens (@theme) + surcharges sombres + variables :root
app/static/src/base.css           # @layer base (html/body/focus/hidden/reduced-motion)
app/static/src/components.css     # @layer components (classes ui-*)
app/static/css/app.css            # CSS compilé et minifié (commité)
app/static/js/ui/main.js          # entrée unique (module ES)
app/static/js/ui/strings.js
app/static/js/ui/theme.js
app/static/js/ui/dialog.js
app/static/js/ui/toast.js
app/static/js/ui/clipboard.js
app/static/js/ui/reveal.js
app/static/js/ui/confirm.js
app/static/js/ui/forms.js
app/static/js/ui/pwa.js
app/ui.py                         # helpers Jinja + navigation + empreintes d'assets
app/icons.py                      # données SVG (Lucide)
app/templates/_components/ui.html          # macros field, sheet, empty_state
app/templates/_components/theme_script.html # script anti-flash (inclus par base et offline)
app/templates/main/offline.html
app/templates/main/ui_catalog.html
app/templates/sw.js               # service worker (gabarit Jinja)
scripts/ui/seed_demo.py
scripts/ui/serve_demo.py
scripts/ui/lib.mjs
scripts/ui/check.mjs
scripts/ui/shoot.mjs
scripts/ui/scenes.json
scripts/ui/exceptions.json        # contenu initial : []
scripts/ui/selftest-scenes.json   # scènes volontairement fausses (auto-contrôle de la garde, §9.10)
tests/ui_helpers.py               # fonctions d'extraction HTML pour les tests (pas de test dedans)
tests/test_ui_shell.py
tests/test_ui_assets.py
tests/test_ui_catalog.py
tests/test_ui_tooling.py
tests/test_pwa.py
```

**Déplacé** : `git mv app/static/css/main.css app/static/src/legacy.css` (contenu identique, sauf corrections N2 du §2.6).

**Modifiés** : `app/__init__.py`, `app/main/__init__.py`, `app/templates/base.html` (réécrit), `app/static/manifest.json`, `app/templates/events/dashboard.html`, `app/templates/events/members.html`, `app/templates/events/invite.html`, `app/templates/costs/index.html`, `translations/messages.pot`, `translations/fr/LC_MESSAGES/messages.po|.mo`, `translations/en/LC_MESSAGES/messages.po|.mo`, `scripts/translate_en.py` (dictionnaire `T`), `tests/conftest.py` (fixtures ajoutées), `tests/test_module_gating.py` (table §11.3), `.github/workflows/ci.yml`, `.dockerignore`, `.env.example`, `CHANGELOG.md`, `TASKS.md`, `DEV_LOG.md`.

**Supprimés** : `app/static/js/service-worker.js`, `app/static/js/alpine.min.js` (jamais chargé).

**Inchangés (justification)** : `Dockerfile` (l'image copie `app/`, qui contient le CSS compilé : aucun Node en production) ; `nginx/saas.conf` (les URL d'assets portent une empreinte `?v=`, donc le cache 30 jours de `/static/` est sûr ; `/sw.js` passe par `location /` et reçoit `Cache-Control: no-cache` de Flask) ; `pyproject.toml` (aucune dépendance Python ajoutée) ; `.gitignore` (`node_modules/` y figure déjà ; les artefacts vont hors dépôt).

### 2.2 `package.json` (contenu exact)

```json
{
  "name": "holishared-ui",
  "private": true,
  "type": "module",
  "engines": { "node": ">=22 <23" },
  "scripts": {
    "build:css": "tailwindcss -i app/static/src/app.css -o app/static/css/app.css --minify",
    "watch:css": "tailwindcss -i app/static/src/app.css -o app/static/css/app.css --watch",
    "ui:seed": "node scripts/ui/lib.mjs seed",
    "ui:serve": "node scripts/ui/lib.mjs serve",
    "ui:shoot": "node scripts/ui/shoot.mjs",
    "ui:check": "node scripts/ui/check.mjs",
    "ui:selftest": "node scripts/ui/check.mjs --self-test"
  },
  "devDependencies": {
    "@tailwindcss/cli": "4.3.3",
    "tailwindcss": "4.3.3"
  }
}
```

Versions figées sans `^` (vérifiées : `npm view tailwindcss version` = `npm view @tailwindcss/cli version` = 4.3.3). `package-lock.json` généré par `npm install` sous Node 22 et commité. Aucune autre dépendance npm (les scripts `scripts/ui/*.mjs` n'utilisent que Node 22 : `fetch`, `WebSocket` global, `child_process`, `fs`).

### 2.3 Entrée Tailwind `app/static/src/app.css` (contenu exact)

```css
@layer legacy, theme, base, components, utilities;

@import "./legacy.css" layer(legacy);
@import "tailwindcss/theme.css" layer(theme);
@import "tailwindcss/utilities.css" layer(utilities) source(none);

@source "../../templates";
@source "../js/ui";

@custom-variant dark (&:where([data-theme="dark"], [data-theme="dark"] *));

@import "./theme.css";
@import "./base.css";
@import "./components.css";
```

Décisions :

- **Le Preflight Tailwind n'est pas importé** jusqu'à B028 : placé en couche `base` (au-dessus de `legacy`), il écraserait les styles d'éléments du CSS historique (`h1`, `ul`, `button`…) et casserait les pages non migrées. Le CSS historique contient déjà un reset (`* { margin:0; padding:0; box-sizing:border-box }`) qui s'applique aussi au shell.
- `source(none)` + `@source` explicites : Tailwind ne scanne que les gabarits et les modules JS (jamais `legacy.css`, `node_modules` ni les scripts). Vérifié avec 4.3.3.
- Les noms de classes Tailwind générés par les gabarits existants qui recoupent le CSS historique se limitent à `container` (uniquement dans l'ancien `base.html`, supprimé) et `sr-only` (même sémantique) : aucun risque pour les pages historiques.
- **Collisions de variables, voulues** : `legacy.css` déclare aussi sur `:root` `--radius-sm/md/lg/full`, `--shadow-card` et `--font-mono`. Les déclarations de B017 (couches `theme` et `base`, plus fortes) les remplacent pour les pages historiques : rayons identiques (6/12/18/9999 px), ombre de carte et police monospace très légèrement modifiées. Aucune variable `--color-*` n'existe dans `legacy.css` : pas de collision de palette.
- Le build minifié émet aussi un bloc `@layer properties` (replis `@property` des variables `--tw-*`) avant `legacy` : sans effet sur la cascade des styles.
- **Ordre des couches** : `legacy` (la plus faible) < `theme` < `base` < `components` < `utilities`. Tout style nouveau l'emporte sur l'historique à spécificité quelconque ; les utilitaires l'emportent sur les composants.
- Le CSS compilé minifié ne conserve pas la déclaration d'ordre `@layer a, b…;` mais l'ordre de première apparition des blocs `@layer` est identique (vérifié) ; le test T47 vérifie cet ordre.
- **Règle d'écriture** : aucune classe construite par concaténation (dans Jinja, Python ou JS) ; chaque classe utilitaire apparaît en entier dans un gabarit ou un fichier de `app/static/js/ui/`. Le JS ne bascule jamais de classes : il bascule des attributs (`data-state`, `data-masked`, `aria-expanded`, `aria-pressed`, `data-loading`…), que le CSS cible.

### 2.4 Pipeline de build

- `npm ci && npm run build:css` produit `app/static/css/app.css` (minifié, bannière `/*! tailwindcss v4.3.3 … */`).
- Développement : `npm run watch:css` en parallèle du serveur Flask. Le helper `asset_url` recalcule l'empreinte quand le fichier change (clé = chemin + `mtime_ns`).
- Le CSS compilé est commité à chaque commit qui modifie `app/static/src/**`, un gabarit ou un fichier `app/static/js/ui/*.js` (les classes scannées changent).

### 2.5 CI (`.github/workflows/ci.yml`)

**Dépôt sans remote** : le dépôt local n'a aucun remote git (`git remote -v` vide) ; le workflow ci-dessous est donc **inopérant localement** et ne servira qu'après publication sur GitHub. **La porte réelle de chaque commit et de la clôture est la définition de terminé locale (§12.2)**, exécutée par l'agent avant tout commit.

**Variables du job `test`** : `create_app()` refuse de démarrer sans `SECRET_KEY` (≥ 32 caractères, ≠ `dev`) ni `SUPERADMIN_PASSWORD` (≠ `change`) ; en CI aucun `.env` n'existe, donc le job `test` actuel échouerait. On ajoute au job `test` (et au job `frontend`, qui lance la graine et le serveur de démo) un bloc `env:` avec des valeurs factices de test, jamais réutilisées ailleurs :

```yaml
    env:
      SECRET_KEY: ci-test-secret-key-not-for-production-0123456789
      SUPERADMIN_PASSWORD: ci-test-superadmin-password
```

**Déclencheurs** : aujourd'hui le workflow ne tourne que sur `main`, alors que tout le programme B017 → B028 vit sur `ui/tailwind-refonte` jusqu'au merge final : aucun contrôle ne s'exécuterait. Le bloc `on:` devient exactement :

```yaml
on:
  push:
    branches: [main, "ui/**"]
  pull_request:
    branches: [main, "ui/**"]
```

Les jobs `lint` et `test` sont inchangés (ils tournent donc aussi sur `ui/**`). Ajout d'un job :

```yaml
  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
      - run: npm ci
      - name: CSS compilé à jour
        run: npm run build:css && git diff --exit-code -- app/static/css/app.css
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - name: Auto-contrôle de la garde
        run: npm run ui:selftest
        env:
          PYTHON: python
      - name: Garde UI
        run: npm run ui:check
        env:
          PYTHON: python
```

(`google-chrome` est préinstallé sur `ubuntu-latest`.)

### 2.6 Isolation et corrections du CSS historique

- `app/static/src/legacy.css` = ancien `main.css`, chargé uniquement via `app.css` (couche `legacy`). `base.html` ne référence plus aucun `main.css`.
- Corrections N2 autorisées (et seules modifications permises dans `legacy.css` en B017) :
  1. `.mgmt-export` et `.mgmt-danger-btn` : `white-space: nowrap` → `white-space: normal;` + `text-align: center;`.
  2. Bande de pastilles repas des listes : ajouter `min-width: 0;` à `.meal-chips` et à l'ancêtre flex/grid de la colonne principale des listes (`.list-main`), et `max-width: 100%;` à `.meal-chips-row`, de sorte que le défilement horizontal reste interne à `.meal-chips-row`.
  3. Toute autre cause de défilement horizontal **de page** révélée par la garde (§9.7, contrôle `hscroll`) sur une scène B017 est corrigée de la même façon : modification minimale (`min-width: 0`, `max-width: 100%`, `overflow-wrap: anywhere`, `white-space: normal`) sur le sélecteur fautif, regroupée dans le commit `fix(css)` (§10). Interdits : `overflow-x: hidden|clip` sur `html`, `body`, `main` ou le conteneur du shell (masquerait les défauts et casse `position: sticky`).

### 2.7 `.dockerignore`

Ajouter les lignes : `node_modules/`, `package.json`, `package-lock.json`, `app/static/src/`.

---

## 3. Design tokens et thèmes

### 3.1 `app/static/src/theme.css`

```css
@theme static {
  --color-*: initial;
  --text-*: initial;
  --radius-*: initial;
  --shadow-*: initial;
  --font-sans: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-mono: ui-monospace, "SFMono-Regular", Menlo, Consolas, "Liberation Mono", monospace;
  /* couleurs : tableau 3.2 (valeurs claires) */
  /* typographie : tableau 3.4 ; rayons 3.5 (les ombres 3.6 ne sont PAS dans @theme) */
}
```

- **Ombres hors `@theme`** : Tailwind 4.3.3 recopie la valeur d'une ombre de thème dans l'utilitaire `shadow-*`, qui ne suivrait donc pas le thème sombre. Les ombres sont des variables simples déclarées sur `:root` dans `@layer base` (§3.6) ; `--shadow-*: initial` supprime les utilitaires `shadow-*` par défaut. Règle : **aucun utilitaire `shadow-*`** ; les ombres s'utilisent par `var(--shadow-…)` dans `components.css`.

- `--color-*: initial` retire la palette Tailwind par défaut : seules les couleurs du tableau 3.2 existent (`bg-red-500` n'est pas généré ; vérifié).
- Les breakpoints Tailwind par défaut sont conservés : `sm` 40rem (640 px), `md` 48rem (768 px), `lg` 64rem (1024 px), `xl` 80rem. **Bascule shell mobile → bureau à `lg` (1024 px)** : à 820 px (tablette portrait, tactile) la barre du bas reste affichée (N9).
- `--spacing` par défaut (0.25rem) conservé : `p-4` = 1rem.
- Surcharges sombres dans `@layer base` sous `:root[data-theme="dark"] { … }` (une seule source : le script de `<head>` pose toujours `data-theme`, §3.8). `color-scheme: light` sur `:root`, `color-scheme: dark` sur `:root[data-theme="dark"]`.

### 3.2 Couleurs (valeurs exactes)

| Token (`--color-…`) | Utilitaire | Rôle | Clair | Sombre |
|---|---|---|---|---|
| `canvas` | `bg-canvas` | fond de page | `#faf8f5` | `#171512` |
| `surface` | `bg-surface` | cartes, en-tête, barres, feuilles | `#ffffff` | `#211e1a` |
| `surface-2` | `bg-surface-2` | fonds atténués, squelettes, segments | `#f4f0ea` | `#2b2722` |
| `line` | `border-line` | séparateurs décoratifs | `#e6dfd5` | `#3a352d` |
| `line-strong` | `border-line-strong` | bordures de champs/contrôles (≥ 3:1) | `#8c8278` | `#80776b` |
| `ink` | `text-ink` | texte principal | `#23201d` | `#f0ede8` |
| `ink-2` | `text-ink-2` | texte secondaire | `#57514a` | `#c9c3b8` |
| `ink-muted` | `text-ink-muted` | texte tertiaire, onglets inactifs | `#6f675e` | `#a39b91` |
| `primary` | `bg-primary` | aplats, icônes, anneau (non-texte) | `#c25e38` | `#e27a50` |
| `primary-strong` | `text-primary-strong` | texte d'accent, liens, bouton plein | `#a24a2a` | `#f0906b` |
| `primary-stronger` | — | survol du bouton plein | `#8a3e22` | `#f5a583` |
| `primary-soft` | `bg-primary-soft` | pastille active, fonds d'accent | `#fbeee7` | `#3a271e` |
| `on-primary` | `text-on-primary` | texte sur `primary-strong` | `#ffffff` | `#1d120c` |
| `success` / `success-soft` | | statut positif | `#2e5c4e` / `#e8f1ed` | `#7fb5a4` / `#1f2d28` |
| `warning` / `warning-soft` | | avertissement | `#9a4a07` / `#fdf3e1` | `#f5b94a` / `#33281a` |
| `danger` / `danger-soft` | | destructif, erreur | `#b42318` / `#fdeceb` | `#f4877c` / `#3a201d` |
| `danger-strong` | — | survol du bouton danger | `#912018` | `#f7a097` |
| `on-danger` | | texte sur `danger` | `#ffffff` | `#1d0d0b` |
| `info` / `info-soft` | | information | `#0b5f8a` / `#e8f3fa` | `#6cc4ef` / `#16293a` |
| `inverse` / `on-inverse` | | toasts | `#23201d` / `#faf8f5` | `#f0ede8` / `#171512` |
| `overlay` | | fond des feuilles (`::backdrop`) | `rgb(23 21 18 / 0.5)` | `rgb(0 0 0 / 0.6)` |

V10 : le terracotta (`primary`) ne sert plus aux actions destructives (`danger` rouge distinct) ; badges et statuts ont chacun leur couleur, toujours accompagnée d'un texte ou d'une icône.

### 3.3 Contrastes calculés (WCAG 2.1, luminance relative)

Seuils : texte 4,5:1 ; composants/non-texte 3:1. Toutes les paires utilisées par le shell et les composants :

| Paire (texte / fond) | Clair | Sombre | Seuil |
|---|---|---|---|
| `ink` / `canvas` | 15,29 | 15,61 | 4,5 |
| `ink` / `surface` | 16,21 | 14,21 | 4,5 |
| `ink` / `surface-2` | 14,28 | 12,70 | 4,5 |
| `ink-2` / `canvas` | 7,39 | 10,40 | 4,5 |
| `ink-2` / `surface` | 7,83 | 9,47 | 4,5 |
| `ink-2` / `surface-2` | 6,90 | 8,46 | 4,5 |
| `ink-muted` / `canvas` | 5,24 | 6,64 | 4,5 |
| `ink-muted` / `surface` | 5,56 | 6,05 | 4,5 |
| `ink-muted` / `surface-2` | 4,90 | 5,41 | 4,5 |
| `primary-strong` / `canvas` | 5,58 | 7,73 | 4,5 |
| `primary-strong` / `surface` | 5,92 | 7,04 | 4,5 |
| `primary-strong` / `surface-2` | 5,21 | 6,29 | 4,5 |
| `primary-strong` / `primary-soft` | 5,21 | 5,98 | 4,5 |
| `on-primary` / `primary-strong` | 5,92 | 7,79 | 4,5 |
| `on-primary` / `primary-stronger` (survol) | 7,52 | 9,26 | 4,5 |
| `success` / `success-soft` | 6,61 | 6,18 | 4,5 |
| `success` / `surface` | 7,62 | 7,15 | 4,5 |
| `warning` / `warning-soft` | 5,69 | 8,17 | 4,5 |
| `warning` / `surface` | 6,26 | 9,42 | 4,5 |
| `danger` / `danger-soft` | 5,75 | 6,13 | 4,5 |
| `danger` / `surface` | 6,57 | 6,80 | 4,5 |
| `on-danger` / `danger` | 6,57 | 7,72 | 4,5 |
| `on-danger` / `danger-strong` (survol) | 8,66 | 9,36 | 4,5 |
| `info` / `info-soft` | 6,17 | 7,63 | 4,5 |
| `info` / `surface` | 6,96 | 8,52 | 4,5 |
| `on-inverse` / `inverse` (toast) | 15,29 | 15,61 | 4,5 |
| `on-inverse` / survol d'un bouton ghost dans un toast | 10,5 | 13,1 | 4,5 |
| icônes de ton sur `inverse` (`--ui-toast-*`, §5.11) | ≥ 5,36 | ≥ 5,36 | 3 |
| filet actif `primary` / `surface` (onglet actif, §4.5.1) | 4,24 | 5,64 | 3 |
| `primary` / `surface` (icône, anneau) | 4,24 | 5,64 | 3 |
| `primary` / `canvas` | 4,00 | 6,19 | 3 |
| `primary` / `surface-2` | 3,74 | 5,04 | 3 |
| `line-strong` / `surface` (bordure de champ) | 3,76 | 3,77 | 3 |
| `line-strong` / `canvas` | 3,55 | 4,14 | 3 |

Règles d'usage : aucun texte en `primary` (seulement `primary-strong`) ; aucun texte en `line`/`line-strong` ; les états désactivés (opacité 0,5) sont exemptés (WCAG 1.4.3) et la garde les ignore.

### 3.4 Typographie (V10)

| Token | Taille | Interligne (`--text-…--line-height`) | Graisse d'usage | Usage |
|---|---|---|---|---|
| `--text-title` | 1.75rem (28 px) | 1.2 | 700 | titre de page (h1) |
| `--text-heading` | 1.25rem (20 px) | 1.3 | 650 | titre de section (h2) |
| `--text-subheading` | 1.0625rem (17 px) | 1.35 | 600 | sous-titre (h3), titre de carte |
| `--text-body` | 1rem (16 px) | 1.5 | 400 | texte courant, champs (16 px évite le zoom iOS) |
| `--text-small` | 0.875rem (14 px) | 1.45 | 400/500 | aides, méta |
| `--text-caption` | 0.75rem (12 px) | 1.3 | 500/600 | libellés d'onglets, badges |

Ratio 1,4 entre titre de page et section ; graisses distinctes. `letter-spacing: -0.01em` sur `title` et `heading` (dans les composants qui les utilisent).

### 3.5 Rayons

`--radius-sm: 0.375rem` (6 px, badges, champs) · `--radius-md: 0.75rem` (12 px, boutons, cartes) · `--radius-lg: 1.125rem` (18 px, feuilles) · `--radius-full: 9999px` (avatars, pastilles).

### 3.6 Ombres

| Token | Clair | Sombre |
|---|---|---|
| `--shadow-card` | `0 1px 2px rgb(35 32 29 / 0.05), 0 2px 8px rgb(35 32 29 / 0.04)` | `0 1px 3px rgb(0 0 0 / 0.5)` |
| `--shadow-raised` | `0 8px 24px rgb(35 32 29 / 0.12)` | `0 8px 24px rgb(0 0 0 / 0.6)` |
| `--shadow-bar` | `0 -1px 0 rgb(35 32 29 / 0.06), 0 -4px 16px rgb(35 32 29 / 0.06)` | `0 -1px 0 rgb(0 0 0 / 0.4), 0 -4px 16px rgb(0 0 0 / 0.4)` |

(Variables simples sur `:root` dans `@layer base`, hors `@theme` ; les valeurs sombres redéfinissent les mêmes variables sous `:root[data-theme="dark"]`.)

### 3.7 Variables de mise en page (hors `@theme`, déclarées sur `:root` dans `@layer base`)

| Variable | Valeur | Usage |
|---|---|---|
| `--ui-header-h` | `3.5rem` (56 px) | hauteur de l'en-tête (hors safe area) |
| `--ui-bar-h` | `4rem` (64 px) | hauteur de la barre du bas (hors safe area) |
| `--ui-sidebar-w` | `15rem` | barre latérale bureau |
| `--ui-content-max` | `60rem` (960 px, identique à l'ancien `--container` pour ne pas changer les pages historiques) | largeur max du contenu |
| `--ui-gutter` | `1rem` ; `1.5rem` à partir de `md` | marges latérales |
| `--ui-safe-top/-bottom/-left/-right` | `env(safe-area-inset-*, 0px)` | iOS |
| `--z-header` | `30` | en-tête collant |
| `--z-nav` | `40` | barre du bas, barre latérale |
| `--z-toast` | `60` | zone de toasts |
| `--ui-duration` | `150ms` | transitions |

Les feuilles et dialogues utilisent la *top layer* de `<dialog>` (pas de z-index).

### 3.8 Thème : `data-theme` + préférence système, sans flash (F31)

`app/templates/_components/theme_script.html` (inclus dans `<head>` de `base.html` **avant** la feuille de style, et dans `main/offline.html`) contient exactement :

```html
<script>(function(){var t=null;try{t=localStorage.getItem('theme');}catch(e){}if(t!=='light'&&t!=='dark'){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}document.documentElement.setAttribute('data-theme',t);})();</script>
```

- Clé `localStorage` `theme` conservée (continuité avec l'existant). Valeurs : `light` | `dark` ; absente = suivre le système.
- Le CSS historique (couche `legacy`) réagit déjà à `data-theme`, donc les pages non migrées suivent le même thème.
- `theme.js` (§7.4) synchronise ensuite `aria-pressed` et la balise `<meta name="theme-color">`.

---

## 4. Contrat HTML du shell (`base.html`)

### 4.1 Contextes de navigation

Le shell a deux contextes, calculés par `build_nav` (§4.6) :

- **`event`** : l'URL est celle d'un événement actif (`current_event` non nul) **et** le visiteur y participe (`event_role` ∈ {`creator`, `guest`}).
- **`global`** : tous les autres cas (accueil, `/e/`, `/e/new`, `/admin/login`, `/e/<code>/join` et `/e/<code>/mycode` pour un visiteur non participant, pages d'erreur, `/_ui`).

`event_role` est ajouté par `inject_globals` (`app/__init__.py`) : `"creator"` si `current_user.is_authenticated and current_user.id == current_event.creator_id`, sinon `"guest"` si `current_guest` est non nul, sinon `None` (toujours `None` hors événement). Le rôle créateur l'emporte si les deux sont vrais.

### 4.2 `<head>` (ordre exact)

```html
<!DOCTYPE html>
<html lang="{{ current_lang or 'fr' }}" data-sw="{{ 'on' if config.SW_ENABLED else 'off' }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#faf8f5">
  <meta name="color-scheme" content="light dark">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="default">
  <title>{% block title %}holishared{% endblock %}</title>
  {% include "_components/theme_script.html" %}
  <link rel="stylesheet" href="{{ asset_url('css/app.css') }}">
  <link rel="manifest" href="{{ asset_url('manifest.json') }}">
  <link rel="icon" type="image/png" href="{{ asset_url('icons/icon-192.png') }}">
  <link rel="apple-touch-icon" href="{{ asset_url('icons/icon-192.png') }}">
  <script type="importmap">{{ ui_importmap()|tojson }}</script>
  <script type="module" src="{{ asset_url('js/ui/main.js') }}"></script>
  <script src="{{ asset_url('js/htmx.min.js') }}" defer></script>
  {% block head %}{% endblock %}
</head>
```

- `apple-mobile-web-app-capable` est retiré (Chrome émet un avertissement console de dépréciation, interdit par la garde) ; le mode autonome iOS ≥ 16.4 vient du manifest.
- Le lien `rel="icon"` évite la requête `/favicon.ico` (404 = erreur console).
- htmx passe en `defer` (le seul usage, `hx-trigger="load"` / polling du chat, est traité à `DOMContentLoaded`).

### 4.3 `<body>` (structure et ordre)

```
body [data-has-bottom-nav]
├─ a.ui-skip-link            [data-testid=skip-link][data-ui-shell] href="#main"  « Aller au contenu »
├─ header.ui-header          [data-testid=app-header][data-ui-shell]
├─ div.ui-layout             [data-context=event|global]
│   ├─ nav (barre latérale)  [data-testid=nav-desktop][data-context=event][data-ui-shell]   ← contexte event seulement
│   └─ main#main             [data-testid=main-content] tabindex="-1"
│        └─ {% block content %}
├─ footer                    [data-testid=site-footer][data-ui-shell]   ← contexte global seulement
├─ nav (barre du bas)        [data-testid=nav-bottom][data-context=…][data-ui-shell]
├─ dialog#more-sheet         [data-testid=more-sheet][data-ui-shell]     ← contexte event seulement
├─ dialog#privacy-sheet      [data-testid=privacy-sheet][data-ui-shell]
├─ div.ui-toast-region       [data-testid=toast-region][data-ui-shell] role="region" aria-label="Notifications"
├─ template#ui-confirm-template
├─ template#ui-toast-template
├─ script#ui-strings type="application/json"
└─ {% block scripts %}
```

Blocs Jinja exposés : `title`, `head`, `content`, `scripts` (noms existants conservés : aucun gabarit à modifier). **Pas de bloc `page_actions`** : l'action primaire unique d'un écran fait partie du contenu de la page (principe §10.1 de l'audit) ; un lot ultérieur qui aurait besoin d'une action flottante l'ajoutera.

L'attribut `data-ui-shell` délimite les régions du shell pour la garde (portée `shell`, §9.5).

### 4.4 En-tête `[data-testid=app-header]`

Collant en haut (`position: sticky; top: 0; z-index: var(--z-header)`), fond `surface`, bordure basse `line`, hauteur `--ui-header-h` + `padding-top: var(--ui-safe-top)`, marges latérales `max(var(--ui-gutter), var(--ui-safe-left|right))`. Contenu de gauche à droite :

1. **Marque** `<a data-testid="brand-link" href="/" aria-label="{{ _('Accueil holishared') }}">` : logo SVG existant (soleil, `aria-hidden="true"`) + mot-symbole « holishared ». Le mot-symbole est masqué sous `sm` (640 px) ; en contexte `event` il est masqué sous `lg`. Cible ≥ 44 × 44.
2. **Titre d'événement** (contexte `event`) : `<a data-testid="header-event-title" href="{{ url_for('events.dashboard', code=…) }}" title="{{ current_event.title }}" translate="no">{{ current_event.title }}</a>` — **titre complet côté serveur** (plus de `[:20]`), tronqué par CSS seulement (`min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap`), `text-subheading`, graisse 600, hauteur 44 px (N6).
3. **Navigation bureau globale** (contexte `global`, ≥ `lg` uniquement) : `<nav data-testid="nav-desktop" data-context="global" aria-label="{{ _('Navigation principale') }}">` contenant les liens `navlink-landing`, `navlink-create`, `navlink-events` (ce dernier si `current_user.is_authenticated`), mêmes libellés que §4.5.2.
4. **Pastille identité** `<span data-testid="identity-chip" data-role="creator|guest">` affichée si `event_role` est non nul, ou hors événement si `current_user.is_authenticated` (`data-role="creator"`). Contenu : `<span class="ui-avatar" aria-hidden="true">` (initiale en majuscule) + `<span class="ui-identity__name" translate="no">nom</span>` + pour le créateur `<span class="ui-badge ui-badge--primary">{{ _("Créateur") }}</span>`. Nom : invité → `current_guest.display_name` ; créateur → `current_user.display_name` ou, s'il est vide, `_("Créateur")`. Sous `sm`, nom et badge sont en `sr-only` (seul l'avatar est visible). Élément **non interactif**.
5. **Langue** `<a data-testid="lang-switch">` : sur page FR, `href="?lang=en" hreflang="en" lang="en" aria-label="English"`, texte visible `EN` ; sur page EN, `href="?lang=fr" hreflang="fr" lang="fr" aria-label="Français"`, texte `FR`. Même comportement à toutes les tailles (N7). Classe `ui-btn ui-btn--ghost ui-btn--icon`. En contexte `event`, masqué sous `lg` (il est dans la feuille « Plus »).
6. **Thème** `<button type="button" data-testid="theme-toggle" data-theme-toggle aria-pressed="false" aria-label="{{ _('Thème sombre') }}">` avec `icon('moon', class_='ui-theme-icon-moon')` et `icon('sun', class_='ui-theme-icon-sun')` ; CSS : en thème clair la lune est visible, en sombre le soleil. En contexte `event`, masqué sous `lg`.
7. **Déconnexion** (contexte `global` et `current_user.is_authenticated`) : `<a data-testid="logout-link" href="{{ url_for('auth.logout') }}" class="ui-btn ui-btn--ghost ui-btn--icon" aria-label="{{ _('Déconnexion') }}">{{ icon('log-out') }}</a>`.

L'en-tête ne contient jamais de `h1`.

### 4.5 Navigation

#### 4.5.1 Contexte `event`

**Ordre des modules** : `PRIMARY_ORDER = ("planning", "meals", "lists", "costs", "voting", "logistics", "chat", "media")`.

**Destinations de la barre du bas** : `Accueil` puis les 4 premiers modules **activés** de `PRIMARY_ORDER` (au plus 5 destinations). Si un module principal est désactivé, le suivant activé dans l'ordre prend sa place (ex. `ENABLED_MODULES=planning,voting,chat` → Accueil, Planning, Sondages, Chat). Les modules activés restants vont dans « Plus ». Le bouton **« Plus » est toujours présent** (le groupe « Événement » de la feuille n'est jamais vide). La barre compte donc de 2 à 6 éléments, en colonnes égales (`grid-auto-flow: column; grid-auto-columns: 1fr`) : à 360 px, 6 éléments font 60 px de large chacun (≥ 44).

Tableau des entrées (clé → endpoint, icône, libellé msgid, `data-testid` barre / feuille / bureau) :

| Clé | Endpoint | Icône | Libellé | Barre | Feuille | Bureau |
|---|---|---|---|---|---|---|
| `home` | `events.dashboard` | `house` | « Accueil » | `tab-home` | — | `navlink-home` |
| `planning` | `planning.index` | `calendar-days` | « Planning » | `tab-planning` | `more-item-planning` | `navlink-planning` |
| `meals` | `meals.index` | `utensils` | « Repas » | `tab-meals` | `more-item-meals` | `navlink-meals` |
| `lists` | `lists.index` | `list-checks` | « Listes » | `tab-lists` | `more-item-lists` | `navlink-lists` |
| `costs` | `costs.index` | `wallet` | « Frais » | `tab-costs` | `more-item-costs` | `navlink-costs` |
| `voting` | `voting.index` | `vote` | « Sondages » | `tab-voting` | `more-item-voting` | `navlink-voting` |
| `logistics` | `logistics.index` | `info` | « Infos » | `tab-logistics` | `more-item-logistics` | `navlink-logistics` |
| `chat` | `chat.index` | `message-circle` | « Chat » | `tab-chat` | `more-item-chat` | `navlink-chat` |
| `media` | `media.gallery` | `image` | « Media » | `tab-media` | `more-item-media` | `navlink-media` |
| `participants` (créateur seul en B017) | `events.members` | `users` | « Participants » | — | `more-item-participants` | `navlink-participants` |
| `invite` (créateur seul) | `events.invite` | `user-plus` | « Inviter » | — | `more-item-invite` | `navlink-invite` |
| `log` | `events.log` | `scroll-text` | « Journal » | — | `more-item-log` | `navlink-log` |
| `privacy` (bouton) | ouvre `privacy-sheet` | `shield-check` | « Confidentialité » | — | `more-item-privacy` | `navlink-privacy` |
| `events` (créateur seul) | `events.index` | `calendar-range` | « Mes événements » | — | `more-item-events` | `navlink-events` |
| `logout` (créateur seul) | `auth.logout` | `log-out` | « Déconnexion » | — | `more-item-logout` | `navlink-logout` |
| bouton « Plus » | ouvre `more-sheet` | `ellipsis` | « Plus » | `tab-more` | — | — |

Une seule entrée par module existe à la fois : dans la barre **ou** dans la feuille (selon la promotion), jamais les deux. Aucun `url_for` n'est appelé pour un module désactivé (évite les `BuildError`, F32).

**Participants réservé au créateur (sécurité)** : la page `events.members` affiche aujourd'hui le code personnel (seul secret d'accès) de chaque participant. B017 publie cette page orpheline (F04) uniquement pour le créateur ; pour un invité, le groupe « Événement » ne contient que `log`. En complément, `members.html` ne rend plus aucun code aux invités qui y accèdent par l'URL (§7.12). B020 refondra la page et pourra l'ouvrir aux invités sans code d'autrui.

**Barre du bas** `<nav class="ui-bottom-nav" data-testid="nav-bottom" data-context="event" aria-label="{{ _('Navigation principale') }}"><ul>…</ul></nav>` :

```html
<li><a class="ui-tab" href="…" data-testid="tab-planning" aria-current="page">
  {{ icon('calendar-days', size=24) }}<span class="ui-tab__label">{{ label }}</span></a></li>
…
<li><button type="button" class="ui-tab" data-testid="tab-more" data-sheet-open="more-sheet"
    aria-haspopup="dialog" aria-controls="more-sheet" aria-expanded="false" data-active="true">
  {{ icon('ellipsis', size=24) }}<span class="ui-tab__label">{{ _("Plus") }}</span></button></li>
```

- Affichée sous `lg` uniquement (`lg:hidden`) ; `position: fixed; inset-inline: 0; bottom: 0; z-index: var(--z-nav)` ; hauteur `calc(var(--ui-bar-h) + var(--ui-safe-bottom))`, `padding-bottom: var(--ui-safe-bottom)`, `padding-inline: var(--ui-safe-left) var(--ui-safe-right)` (iPhone en paysage) ; fond `surface`, ombre `--shadow-bar`.
- Élément : colonne icône 24 px + libellé `text-caption` (graisse 500), hauteur 64 px, libellé sur une ligne (`white-space: nowrap; overflow: hidden; text-overflow: ellipsis`), `position: relative`.
- **Actif** : `aria-current="page"` sur le lien ; style : icône et libellé `primary-strong`, graisse 600, pastille `primary-soft` de 4 rem × 2 rem derrière l'icône, **et filet supérieur** `::before` de 3 px × 2rem centré en haut de l'onglet, couleur `primary` (4,24:1 en clair, 5,64:1 en sombre sur `surface` : indicateur non coloré ≥ 3:1, la pastille seule étant à 1,14:1). Inactif : `ink-muted`, sans filet ni pastille.
- **« Plus » actif** : `data-active="true"` quand la page courante correspond à une entrée de la feuille (même style que l'actif, filet compris ; un `<button>` ne prend pas `aria-current`). Absent sinon.
- **Réserve de place** (les deux contextes, sous `lg`) : `body[data-has-bottom-nav] { padding-bottom: calc(var(--ui-bar-h) + var(--ui-safe-bottom)); }`, l'attribut `data-has-bottom-nav` étant posé sur `<body>` par `base.html` uniquement (toujours présent avec le shell) ; `/offline`, document autonome sans barre, ne le porte pas et n'a donc aucune réserve — la réserve est sur `body`, donc sous le dernier élément du flux (pied de page compris en contexte `global`), et rien n'est recouvert par la barre fixe. `<main>` garde un `padding-bottom: 1.5rem`. À partir de `lg` : `body[data-has-bottom-nav] { padding-bottom: 0 }`. Contrôlé par la garde (`nav`, §9.7).

**Feuille « Plus »** `{% call sheet('more-sheet', _('Plus')) %}` (macro §5.10), contenu :

```
nav[aria-label="Plus"] > ul.ui-menu     ← modules restants (more-item-<module>), si au moins un
h3.ui-menu__heading « Événement »
ul.ui-menu                               ← participants (créateur), invite (créateur), log
h3.ui-menu__heading « Préférences »
ul.ui-menu                               ← [data-testid=sheet-theme-toggle] bouton « Thème sombre » (aria-pressed),
                                           [data-testid=sheet-lang-switch] lien « English »/« Français » (lang, hreflang),
                                           more-item-privacy (bouton data-sheet-open="privacy-sheet")
h3.ui-menu__heading « Compte »           ← créateur seulement
ul.ui-menu                               ← more-item-events, more-item-logout
```

Chaque entrée : `<a class="ui-menu__item">` (ou `<button>`) icône 20 px + libellé, hauteur ≥ 48 px ; l'entrée de la page courante porte `aria-current="page"`. B020 ajoutera ses entrées au groupe « Événement ».

**Barre latérale bureau** (≥ `lg`) `<nav class="ui-sidebar" data-testid="nav-desktop" data-context="event" aria-label="{{ _('Navigation principale') }}">` : liste verticale, dans cet ordre : destinations de la barre du bas (`navlink-home`, modules principaux), modules de la feuille, puis groupe « Événement » (`navlink-participants` et `navlink-invite` pour le créateur, `navlink-log`), puis en pied de barre `navlink-privacy` (bouton), `navlink-events`, `navlink-logout` (créateur). Collante sous l'en-tête (`top: calc(var(--ui-header-h) + var(--ui-safe-top))`, hauteur `calc(100vh - var(--ui-header-h) - var(--ui-safe-top))` puis la même expression en `100dvh`, `overflow-y: auto`). Entrées de 44 px ; actif : `aria-current="page"`, fond `primary-soft`, texte `primary-strong`, graisse 600, filet gauche 3 px `primary`. **Le titre de l'événement n'y figure pas** (il est dans l'en-tête : fin du doublon N8). Thème et langue restent dans l'en-tête sur bureau.

Mise en page ≥ `lg` en contexte `event` : `.ui-layout { display: grid; grid-template-columns: var(--ui-sidebar-w) minmax(0, 1fr); }` ; `<main>` : `max-width: var(--ui-content-max)`, padding `2rem`.

#### 4.5.2 Contexte `global`

| Clé | Endpoint | Icône | Libellé | Barre (< lg) | Bureau (≥ lg, dans l'en-tête) | Condition |
|---|---|---|---|---|---|---|
| `landing` | `main.index` | `house` | « Accueil » | `tab-landing` | `navlink-landing` | toujours |
| `create` | `events.create` | `calendar-plus` | « Créer » (barre) / « Créer un événement » (bureau) | `tab-create` | `navlink-create` | toujours |
| `events` | `events.index` | `calendar-range` | « Mes événements » | `tab-events` | `navlink-events` | `current_user.is_authenticated` |

- Barre du bas `data-context="global"`, même composant, sans bouton « Plus ». Elle existe donc hors événement (N1).
- Pied de page `[data-testid=site-footer]` (contexte `global` seulement, N5) : une ligne « holishared » + bouton `[data-testid=footer-privacy]` `ui-btn ui-btn--ghost` « Confidentialité » (`data-sheet-open="privacy-sheet"`). En contexte `event` il n'y a **pas** de pied de page : la confidentialité est accessible par `more-item-privacy` et `navlink-privacy`.

### 4.6 Calcul de la navigation et de l'état actif (`app/ui.py`)

```python
@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    icon: str
    href: str | None  # None pour les boutons (privacy)
    active: bool


@dataclass(frozen=True)
class Nav:
    context: str  # "event" | "global"
    primary: list[NavItem]  # destinations de la barre du bas (sans « Plus »)
    more_modules: list[NavItem]  # modules relégués dans « Plus »
    event_items: list[NavItem]  # créateur : participants, invite, log ; invité : log
    account_items: list[NavItem]  # events, logout (créateur, contexte event) ; [] sinon
    more_active: bool  # une entrée de more_modules/event_items/account_items/privacy est active


def nav_section(endpoint: str | None) -> str | None: ...
def build_nav(
    endpoint: str | None,
    enabled_modules: Sequence[str],
    event_code: str | None,
    role: str | None,
    authenticated: bool,
) -> Nav: ...
```

`nav_section` (fonction pure) :

| Endpoint | Retour |
|---|---|
| `None` | `None` |
| `main.index` | `"landing"` |
| `events.create`, `events.verify_sent` | `"create"` |
| `events.index` | `"events"` |
| `events.dashboard` | `"home"` |
| `events.members` | `"participants"` |
| `events.invite`, `events.invite_qr`, `events.invite_email`, `events.invite_resend` | `"invite"` |
| `events.log` | `"log"` |
| `<bp>.<vue>` avec `<bp>` ∈ {planning, meals, lists, costs, voting, logistics, chat, media} | `"<bp>"` |
| tout autre endpoint | `None` |

`PRIMARY_ORDER: Final[tuple[str, ...]]` est une constante de module (§4.5.1). `build_nav` : contexte `event` si `event_code` et `role` ∈ {`creator`, `guest`}, sinon `global`. `active = (item.key == nav_section(endpoint))`. Les libellés sont produits par des appels littéraux `gettext("…")` (importé comme `_`) dans une fonction interne évaluée à chaque appel, pour rester extractibles par `pybabel` et traduits à la requête. Appel dans `base.html` :

```jinja
{% set nav = build_nav(request.endpoint, enabled_modules, current_event.code if current_event else None, event_role, current_user.is_authenticated) %}
```

**Contrat à conserver par B029** (refonte du contexte d'événement) : les variables de gabarit `current_event`, `current_guest`, `event_role` (valeurs `"creator"`, `"guest"`, `None`, règle du §4.1) et `enabled_modules`, ainsi que la signature et le comportement de `build_nav(...)` et `nav_section(...)`, sont un contrat du shell. B029 peut changer leur calcul (contexte unique mis en cache sur `g`) mais pas leurs noms, valeurs ni sémantique ; les tests T09–T33 et T44d en sont la garantie.

### 4.7 Zone de contenu, toasts, safe area, hauteurs dynamiques

- `<main id="main" class="ui-main" tabindex="-1" data-testid="main-content">` : `min-width: 0`, padding-block `1.25rem 1.5rem`, padding-inline `max(var(--ui-gutter), var(--ui-safe-left))` / `max(var(--ui-gutter), var(--ui-safe-right))` (< `lg`), `margin-inline: auto`, `max-width: var(--ui-content-max)`.
- `body { min-height: 100vh; min-height: 100dvh; }` (+ réserve de la barre du bas, §4.5.1) ; feuilles `max-height: 85vh` puis `85dvh` ; barre latérale §4.5.1.
- **Zone de toasts** (structure exacte, persistante dès le chargement pour que les régions vivantes soient annoncées de façon fiable) :

```html
<div class="ui-toast-region" id="toast-region" data-testid="toast-region" data-ui-shell
     role="region" aria-label="{{ _('Notifications') }}">
  <div class="ui-toast-stack" data-toast-live="polite" aria-live="polite" aria-relevant="additions text"></div>
  <div class="ui-toast-stack" data-toast-live="assertive" aria-live="assertive" aria-relevant="additions text"></div>
</div>
```

- **Messages flash → toasts** : rendus côté serveur, un `<div class="ui-toast" data-testid="toast" data-tone="…">` par message, dans la pile `polite` (success/info) ou `assertive` (warning/danger). Correspondance de catégorie : `success`→`success`, `danger`/`error`→`danger`, `warning`→`warning`, autre→`info`. Les toasts n'ont **pas** d'attribut `role` (l'annonce vient de la pile vivante, évitant une double lecture). Markup d'un toast :

```html
<div class="ui-toast" data-testid="toast" data-tone="success">
  {{ icon('circle-check') }}<p class="ui-toast__message">…</p>
  <button type="button" class="ui-btn ui-btn--ghost ui-btn--icon" data-toast-close aria-label="{{ _('Fermer') }}">{{ icon('x') }}</button>
</div>
```

- **Toasts et feuilles ouvertes** : un `<dialog>` ouvert par `showModal()` est dans la *top layer* et rend le reste du document inerte ; un toast de `#toast-region` serait alors masqué par le fond et non cliquable. Règle : `toast()` insère le toast dans la zone de toasts **du dernier `dialog[open]`** s'il y en a un (zone créée à la demande dans ce dialogue en clonant la structure ci-dessus sans `id` ni `data-testid`, mêmes classes, positionnée en `fixed` comme la zone principale), sinon dans `#toast-region`. Choisi plutôt que `popover="manual"` : comportement déterministe, sans dépendre des règles d'inertie entre top layer et dialogues modaux. Les toasts insérés dans une feuille disparaissent avec elle. Vérifié par la scène `sheet-toast` (§9.6).

Icônes par ton : success `circle-check`, info `info`, warning `triangle-alert`, danger `circle-alert` ; un toast serveur ne contient que l'icône de son ton. `<template id="ui-toast-template">` contient le même markup avec les **quatre** icônes, chacune enveloppée dans `<span data-tone-icon="success|info|warning|danger">` (message vide) ; `toast()` supprime les trois qui ne correspondent pas au ton. Position : `position: fixed`, centrée, `bottom: calc(var(--ui-bar-h) + var(--ui-safe-bottom) + 0.75rem)` sous `lg` (au-dessus de la barre), `bottom: 1.5rem` à partir de `lg` ; largeur `min(28rem, 100vw - 2 × gutter)` ; fond `inverse`, texte `on-inverse`, ombre `raised`. Maximum 3 toasts visibles (le plus ancien est retiré).

### 4.8 Liste exhaustive des `data-testid` du shell

| `data-testid` | Élément | Présence |
|---|---|---|
| `skip-link` | lien d'évitement | toujours |
| `app-header` | `<header>` | toujours |
| `brand-link` | lien marque | toujours |
| `header-event-title` | titre d'événement | contexte event |
| `identity-chip` (+ `data-role`) | pastille identité | §4.4 point 4 |
| `lang-switch` | lien de langue (en-tête) | toujours |
| `theme-toggle` | bouton thème (en-tête) | toujours |
| `logout-link` | déconnexion (en-tête) | contexte global + authentifié |
| `nav-desktop` (+ `data-context`) | barre latérale (event) / nav d'en-tête (global) | toujours (une seule par page) |
| `navlink-<clé>` | entrées de `nav-desktop` | selon §4.5 |
| `nav-bottom` (+ `data-context`) | barre du bas | toujours |
| `tab-<clé>` | entrées de la barre du bas (dont `tab-more`) | selon §4.5 |
| `more-sheet` | feuille « Plus » (`<dialog>`) | contexte event |
| `more-sheet-close` | bouton fermer de la feuille | contexte event |
| `more-item-<clé>` | entrées de la feuille | selon §4.5.1 |
| `sheet-theme-toggle`, `sheet-lang-switch` | préférences dans la feuille | contexte event |
| `main-content` | `<main>` | toujours |
| `site-footer`, `footer-privacy` | pied de page | contexte global |
| `privacy-sheet`, `privacy-sheet-close` | feuille confidentialité | toujours |
| `toast-region` | zone de toasts | toujours |
| `toast` | chaque toast | par message |
| `confirm-dialog`, `confirm-accept`, `confirm-cancel` | dialogue de confirmation (cloné du template) | à la demande |
| `offline-page` | `<main>` de `/offline` | page hors ligne |
| `ui-catalog` | `<main>` interne du catalogue | `/_ui` |

### 4.9 Feuille confidentialité

`{% call sheet('privacy-sheet', _('Confidentialité garantie')) %}` : paragraphe d'introduction (msgid existant « Holishared respecte ta vie privée : 0 cookie tiers, 0 pistage, 0 revente de données. ») puis `ul.ui-list` de 3 points (msgids existants, inchangés) avec icônes `user` (« Aucun compte forcé »), `eye-off` (« Aucun cookie tiers, aucun pistage »), `shield-check` (« Vos données restent vos données ») ; titre de point en `<strong>`, texte en `<p>`. **Aucun emoji.** Aucun JS dédié : `dialog.js` suffit.

### 4.10 Règle d'étanchéité vis-à-vis du CSS historique

Le CSS historique stylise des éléments nus. Liste exhaustive (extraction automatique de `main.css`, confirmée par l'audit) : `html` (`font-size`, `-webkit-text-size-adjust`, `scroll-behavior: smooth`), `body` (`font-family`, `background`, `color`, `line-height`, `min-height`, lissage), `h1`–`h4`, `p`, `a`, `a:hover`, `code`, `label`, `input` (+ `:hover`, `:focus`, `::placeholder`, `[type=checkbox]`, `[type=radio]` — `width/height: 20px`, `min-height: 0`, `accent-color` —, `[type=file]`, `[type=submit]`), `select` (+ `:hover`, `:focus`, `[aria-invalid]`), `textarea` (`resize: vertical`, `line-height: 1.5`), **`form`** (`display: flex; flex-direction: column; gap: var(--sp-4); max-width: var(--container-narrow)`), `button[type="submit"]`, `table`, `th`, `td`, `thead`, `tbody`, `tfoot`, `details.form-options`. Chaque composant `ui-*` et chaque élément du shell **déclare explicitement** les propriétés que ces règles touchent : boutons et onglets (`display`, `align-items`, `justify-content`, `gap`, `min-height`, `min-width`, `padding`, `border`, `border-radius`, `background`, `color`, `font`, `line-height`, `text-decoration` y compris au survol, `width`, `box-shadow`, `cursor`) ; champs (`width`, `min-height`, `padding`, `border`, `border-radius`, `background-color`, `background-image`, `color`, `font`, `box-shadow`, `outline`) ; libellés (`display`, `font-weight`, `font-size`, `color`, `margin`) ; titres et paragraphes du shell (`font-size`, `font-weight`, `line-height`, `margin`, `letter-spacing`, `color`) ; cases et radios du kit (`width`, `height`, `min-height`, `padding`, `margin`, `accent-color: auto`, `appearance`) ; `ui-textarea` (`resize: vertical`, `line-height: 1.5`).

**Formulaires** : tout `<form>` écrit avec le kit porte la classe **`ui-form`** : `display: flex; flex-direction: column; gap: 1rem; max-width: none;` (neutralise la règle historique `form`). `.ui-sheet__panel`, qui est un `<form method="dialog">` dans le dialogue de confirmation, déclare `display: block; max-width: none; gap: 0;`. Le formulaire de démonstration du catalogue porte `ui-form`. Un formulaire d'une seule action en ligne (bouton seul) porte `ui-form ui-form--inline` : `display: inline-flex; flex-direction: row; gap: 0.5rem; max-width: none;`.

**Non neutralisés volontairement** : `html { scroll-behavior: smooth }` (comportement conservé ; `prefers-reduced-motion` le ramène à `auto`, §4.11) ; `table/th/td` (le kit B017 n'a pas de composant tableau ; un lot qui en crée un redéclare `border-collapse`, `width`, `padding`, `text-align`, `border` et `font-size` des cellules) ; `body` (toutes ses propriétés sont redéclarées par `@layer base`, §4.11).

### 4.11 `@layer base` (`app/static/src/base.css`, liste exhaustive)

- `:root` : variables §3.7, `color-scheme: light` ; `:root[data-theme="dark"]` : surcharges des couleurs §3.2 et ombres §3.6, `color-scheme: dark`.
- `html` : `-webkit-text-size-adjust: 100%; text-size-adjust: 100%; -webkit-tap-highlight-color: transparent;`.
- `body` : `margin: 0; background: var(--color-canvas); color: var(--color-ink); font-family: var(--font-sans); font-size: var(--text-body); line-height: 1.5; min-height: 100vh; min-height: 100dvh;` + `padding-bottom` réservé à la barre du bas sous `lg`, seulement sur `body[data-has-bottom-nav]` (§4.5.1).
- `:root` : variables d'ombres §3.6 et variables `--ui-toast-*` §5.11 (clair et sombre).
- `:focus-visible` : `outline: 2px solid var(--color-primary-strong); outline-offset: 2px;`.
- `html:has(dialog[open])` : `overflow: hidden;` (pas de défilement de fond sous une feuille).
- `@media (prefers-reduced-motion: reduce)` : `*, *::before, *::after { animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; transition-duration: 0.01ms !important; scroll-behavior: auto !important; }`.

Aucune autre règle sur des éléments nus pendant la transition (pas de typographie de base : elle viendrait écraser les pages historiques).

---

## 5. Catalogue de composants

### 5.1 Décision : classes sémantiques + macros ciblées

- Tous les composants sont des **classes CSS préfixées `ui-`** dans `@layer components` (`components.css`, CSS simple utilisant `var(--color-…)`, sans `@apply`). Le préfixe est obligatoire : le CSS historique définit déjà `.btn`, `.card`, `.badge`, `.field`, `.tab`, `.avatar`, `.empty-state`, `.progress`… qui fuiraient dans les nouveaux composants.
- **Macros Jinja** (`app/templates/_components/ui.html`) uniquement là où le câblage d'accessibilité est non trivial et répété : `field`, `sheet`, `empty_state`. L'icône est un global Python (`icon()`, §6). Boutons, cartes, badges, listes… restent du HTML + classes : markup court, lisible, compatible avec les utilitaires Tailwind.
- Import dans un gabarit : `{% from "_components/ui.html" import field, sheet, empty_state %}`.
- Variantes par modificateurs `--x` ; états par pseudo-classes ou attributs (`[aria-disabled="true"]`, `[data-loading="true"]`, `[aria-invalid="true"]`, `[aria-current="page"]`, `[data-active="true"]`, `[data-state="copied"]`).
- Toutes les cibles interactives ≥ 44 × 44 px (y compris `--sm`).

### 5.2 Bouton `ui-btn`

```html
<button type="button" class="ui-btn ui-btn--primary">{{ icon('plus') }}<span>{{ _("Ajouter") }}</span></button>
<a class="ui-btn ui-btn--secondary" href="…">…</a>
<button type="button" class="ui-btn ui-btn--ghost ui-btn--icon" aria-label="{{ _('Fermer') }}">{{ icon('x') }}</button>
```

| Variante | Fond / texte / bordure (repos) | Survol | Actif (`:active`) |
|---|---|---|---|
| `--primary` | `primary-strong` / `on-primary` / transparente | `primary-stronger` | `primary-stronger` + `transform: translateY(1px)` |
| `--secondary` | `surface` / `ink` / `line-strong` | `surface-2` | `surface-2` |
| `--ghost` | transparent / `primary-strong` / transparente | `primary-soft` | `primary-soft` |
| `--danger` | `danger` / `on-danger` / transparente | `danger-strong` | `danger-strong` |

- Base : `display: inline-flex; align-items: center; justify-content: center; gap: 0.5rem; min-height: 44px; min-width: 44px; padding: 0.625rem 1.125rem; border: 1px solid; border-radius: var(--radius-md); font: 600 var(--text-small)/1.2 var(--font-sans); text-decoration: none; cursor: pointer; width: auto;` transitions `background-color, border-color, color` en `--ui-duration`.
- Tailles : `--sm` (padding `0.5rem 0.75rem`, police `text-caption`, hauteur toujours ≥ 44 px), défaut, `--lg` (`min-height: 52px`, police `text-body`). `--block` : `width: 100%`. `--icon` : carré 44 × 44, padding 0, **`aria-label` obligatoire**.
- Focus visible : anneau global (§4.11). Désactivé : `:disabled, [aria-disabled="true"]` → `opacity: 0.5; cursor: not-allowed;` (et `pointer-events: none` pour `[aria-disabled="true"]`). Chargement : `[data-loading="true"]` → contenu conservé (largeur stable), `::after` rotatif 1 em (bordure 2 px `currentColor`, coin transparent, animation `spin 0.8s linear infinite`), `cursor: progress` ; l'élément porte aussi `aria-busy="true"`.
- **Règle « une seule action primaire par écran »** : au plus un `ui-btn--primary` visible dans `<main>` ; les autres actions sont `--secondary` ou `--ghost` ; destructif = `--danger` (dans une feuille de confirmation ou une zone dépriorisée), jamais en `--primary`. La garde contrôle sur les scènes de portée `page` : nombre de `.ui-btn--primary` visibles dans `main` ≤ 1 (contrôle `primary`, §9.5).

### 5.3 Carte `ui-card` (et carte cliquable en entier, I1)

```html
<article class="ui-card ui-card--link">
  <h3 class="ui-card__title"><a class="ui-card__link" href="…">Titre</a></h3>
  <p>Méta…</p>
  <button type="button" class="ui-btn ui-btn--ghost ui-btn--icon ui-card__action" aria-label="…">…</button>
</article>
```

- `ui-card` : fond `surface`, bordure 1 px `line`, `border-radius: var(--radius-md)`, padding `1rem`, ombre `card`.
- `ui-card--link` : `position: relative` ; `.ui-card__link::after { content: ""; position: absolute; inset: 0; border-radius: inherit; }` (lien étiré : toute la carte est cliquable, une seule tabulation, nom accessible = texte du lien) ; `.ui-card__link` : couleur `ink`, `text-decoration: none` à tous les états ; survol de la carte : bordure `line-strong` + ombre `raised` ; focus : `.ui-card__link:focus-visible { outline: none } .ui-card__link:focus-visible::after { outline: 2px solid var(--color-primary-strong); outline-offset: 2px; }`.
- `ui-card__action` : `position: relative; z-index: 1;` (reste cliquable au-dessus du lien étiré).
- `ui-card__title` : `text-subheading`, graisse 600, `margin: 0 0 0.25rem`.

### 5.4 Champ de formulaire — macro `field`

Signature exacte :

```jinja
{% macro field(name, label, type="text", value="", id=None, help=None, error=None, required=False,
               options=None, placeholder=None, autocomplete=None, attrs=None) %}
```

Rendu (cas `type="text"` avec aide et erreur, `id` par défaut `"f-" ~ name`) :

```html
<div class="ui-field" data-invalid="true">
  <label class="ui-label" for="f-title">Titre</label>
  <input class="ui-input" type="text" id="f-title" name="title" value="…" required
         aria-describedby="f-title-help f-title-error" aria-invalid="true">
  <p class="ui-help" id="f-title-help">…</p>
  <p class="ui-error" id="f-title-error">{{ icon('circle-alert', size=16) }}<span>…</span></p>
</div>
```

- `type` ∈ {`text`, `email`, `number`, `date`, `time`, `password`, `search`, `tel`, `url`, `textarea`, `select`}. `textarea` → `<textarea class="ui-input ui-textarea" rows="3">` ; `select` → `<select class="ui-input ui-select">` avec `options` = liste de paires `(valeur, libellé)`, `selected` si `valeur|string == value|string`.
- `aria-describedby` ne liste que les identifiants existants (`-help` si `help`, `-error` si `error`) et est omis si aucun. `aria-invalid="true"` et `data-invalid="true"` seulement si `error`.
- `required=True` → attribut `required` ; `required=False` → suffixe dans le libellé `<span class="ui-label__optional">({{ _("facultatif") }})</span>`.
- `placeholder`, `autocomplete` rendus s'ils sont fournis ; `attrs` (dict) rendu via le filtre `xmlattr`.
- Styles : `ui-label` (bloc, `text-small`, graisse 600, `ink`, marge basse 0.375rem) ; `ui-input` (largeur 100 %, `min-height: 44px`, padding `0.625rem 0.75rem`, bordure 1 px `line-strong`, `radius-sm`, fond `surface`, texte `ink`, `text-body`, focus : bordure `primary-strong` + anneau global) ; `[aria-invalid="true"]` → bordure `danger` ; `ui-select` → `appearance: none` + chevron SVG en `background-image` (data URI, autorisé par la CSP) ; `ui-help` (`text-small`, `ink-2`) ; `ui-error` (`text-small`, `danger`, flex avec icône). Les erreurs ne sont jamais portées par la seule couleur (icône + texte).

### 5.5 Sélecteur de segments `ui-segmented`

```html
<fieldset class="ui-segmented">
  <legend class="sr-only">…</legend>
  <label class="ui-segmented__option"><input type="radio" name="rsvp" value="yes" checked><span>Oui</span></label>
  …
</fieldset>
```

Radios natives (flèches clavier natives) visuellement masquées (`position: absolute; opacity: 0; width: 1px; height: 1px`) ; `span` = cible ≥ 44 px ; conteneur fond `surface-2`, `radius-md`, padding 4 px ; `input:checked + span` → fond `surface`, ombre `card`, graisse 600, texte `ink` ; `input:focus-visible + span` → anneau `primary-strong`.

### 5.6 Case, radio, interrupteur

```html
<label class="ui-check"><input type="checkbox" name="…"><span>Libellé</span></label>
<label class="ui-radio"><input type="radio" name="…" value="…"><span>Libellé</span></label>
<label class="ui-switch"><input type="checkbox" role="switch" name="…"><span>Libellé</span></label>
```

- Le `<label>` est la cible (`display: flex; align-items: center; gap: 0.75rem; min-height: 44px; font-weight: 400; margin: 0;`).
- `ui-check input` / `ui-radio input` : `appearance: none; width: 22px; height: 22px; min-height: 0; padding: 0; margin: 0; border: 2px solid var(--color-line-strong); background: var(--color-surface);` rayon 6 px (case) ou 50 % (radio) ; coché : fond et bordure `primary-strong` + coche (case : SVG data URI blanc/`on-primary`) ou point central (radio : `box-shadow: inset 0 0 0 4px var(--color-surface)`).
- `ui-switch input` : `appearance: none; width: 44px; height: 26px; border-radius: 9999px;` piste `line-strong`, pouce `surface` 20 px (`::before`) ; coché : piste `primary-strong`, pouce translaté de 18 px.
- Désactivé : opacité 0,5.

### 5.7 Badge `ui-badge`

`<span class="ui-badge ui-badge--success">Confirmé</span>` : `inline-flex`, `text-caption`, graisse 600, padding `0.125rem 0.5rem`, `radius-sm`. Tons : `--neutral` (`surface-2`/`ink-2`), `--primary` (`primary-soft`/`primary-strong`), `--success`, `--warning`, `--danger`, `--info` (`*-soft`/`*`). Non interactif, toujours avec texte.

### 5.8 État vide — macro `empty_state`

```jinja
{% macro empty_state(icon_name, title, text=None) %}
<div class="ui-empty">
  {{ icon(icon_name, size=40) }}
  <p class="ui-empty__title">{{ title }}</p>
  {% if text %}<p class="ui-empty__text">{{ text }}</p>{% endif %}
  {% if caller is defined %}<div class="ui-empty__action">{{ caller() }}</div>{% endif %}
</div>
{% endmacro %}
```

Centré, padding `2rem 1rem`, icône `ink-muted`, titre `text-subheading` 600 `ink`, texte `text-small` `ink-2`.

### 5.9 Squelette de chargement `ui-skeleton`

`<div aria-busy="true"><span class="sr-only">{{ _("Chargement…") }}</span><div class="ui-skeleton h-4 w-2/3"></div>…</div>` : fond `surface-2`, `radius-sm`, animation d'opacité 1 → 0,55 → 1 en 1,2 s (neutralisée par `prefers-reduced-motion`). Dimensions par utilitaires.

### 5.10 Feuille / dialogue — macro `sheet`

```jinja
{% macro sheet(id, title, variant="sheet") %}
<dialog id="{{ id }}" class="ui-sheet{% if variant == 'dialog' %} ui-sheet--dialog{% endif %}"
        aria-labelledby="{{ id }}-title" data-testid="{{ id }}" data-ui-shell>
  <div class="ui-sheet__panel">
    <div class="ui-sheet__header">
      <h2 class="ui-sheet__title" id="{{ id }}-title">{{ title }}</h2>
      <button type="button" class="ui-btn ui-btn--ghost ui-btn--icon" data-sheet-close
              data-testid="{{ id }}-close" aria-label="{{ _('Fermer') }}">{{ icon('x') }}</button>
    </div>
    <div class="ui-sheet__body">{{ caller() }}</div>
  </div>
</dialog>
{% endmacro %}
```

- `<dialog>` natif ouvert par `showModal()` : **focus piégé** (le reste de la page est inerte), **Échap** ferme (évènement `cancel`), focus initial sur le premier élément focusable ou l'élément `autofocus`.
- Ancrage bas sous `lg` : `.ui-sheet { margin: auto 0 0 0; width: 100%; max-width: 100%; padding: 0; border: 0; background: transparent; color: var(--color-ink); }` ; `.ui-sheet__panel { background: var(--color-surface); border-radius: var(--radius-lg) var(--radius-lg) 0 0; max-height: 85dvh; overflow-y: auto; padding: 0.5rem 1rem calc(1rem + var(--ui-safe-bottom)); box-shadow: var(--shadow-raised); }`. Le panneau occupe toute la boîte du `<dialog>` (un clic hors du panneau atteint le `::backdrop`, dont la cible est le `<dialog>` lui-même).
- ≥ `lg`, et toujours pour `ui-sheet--dialog` : centré (`margin: auto; width: min(32rem, calc(100vw - 2rem))`, dialogue : `28rem`), panneau aux 4 coins arrondis.
- `::backdrop` : `var(--color-overlay)`. Animation d'entrée **sur `.ui-sheet__panel`** (jamais sur le `<dialog>`, pour ne pas créer de bloc conteneur qui piégerait la zone de toasts `fixed` insérée dans le dialogue, §4.7) : translation 16 px → 0 et opacité 0 → 1 en 200 ms (supprimée en mouvement réduit).
- `ui-sheet__title` : `text-heading`, 650, `margin: 0`. `ui-sheet__header` : flex, `justify-content: space-between`, `align-items: center`, `min-height: 52px`.
- Comportements JS (§7.5) : fermeture au clic sur le fond, retour du focus à l'élément déclencheur, `aria-expanded` synchronisé.
- La macro pose `data-ui-shell` sur toute feuille : les feuilles sont contrôlées par la garde quelle que soit la portée de la scène.

### 5.11 Toast

Voir §4.7 (markup, tons, position) et §7.6 (comportement). Classes : `ui-toast-region` (flex colonne, `gap: 0.5rem`, `z-index: var(--z-toast)`, `pointer-events: none` ; enfants `pointer-events: auto`), `ui-toast` (flex, `align-items: center`, `gap: 0.75rem`, padding `0.5rem 0.5rem 0.5rem 1rem`, `radius-md`), `ui-toast__message` (`margin: 0`, `text-small`, `flex: 1`). Icône teintée par ton via des variables déclarées dans `@layer base` : `--ui-toast-success|info|warning|danger` valent en thème clair (fond `inverse` sombre) les couleurs **sombres** du tableau 3.2 (`#7fb5a4`, `#6cc4ef`, `#f5b94a`, `#f4877c`) et en thème sombre (fond `inverse` clair) les couleurs **claires** (`#2e5c4e`, `#0b5f8a`, `#9a4a07`, `#b42318`). Boutons dans un toast : `.ui-toast .ui-btn--ghost { color: var(--color-on-inverse); }`, fond au survol `rgb(255 255 255 / 0.12)` en thème clair et `rgb(0 0 0 / 0.08)` en thème sombre (le `primary-strong` du ghost standard n'atteint pas 4,5:1 sur `inverse`).

### 5.12 Barre de progression

`<progress class="ui-progress" value="3" max="10" aria-label="…">3/10</progress>` (élément natif, accessible) : `appearance: none; width: 100%; height: 8px; border: 0; border-radius: 9999px; background: var(--color-surface-2);` ; valeur via `::-webkit-progress-bar` (fond `surface-2`), `::-webkit-progress-value` et `::-moz-progress-bar` (`primary`). Le texte de la valeur est toujours affiché à côté (non porté par la seule barre).

### 5.13 Avatar

`<span class="ui-avatar" aria-hidden="true">A</span>` : cercle 32 px (`--lg` : 40 px), fond `primary-soft`, texte `primary-strong`, `text-caption`, graisse 700, `flex-shrink: 0`. Toujours accompagné du nom en texte (visible ou `sr-only`).

### 5.14 Liste d'éléments

```html
<ul class="ui-list">
  <li class="ui-list__item">…</li>
  <li class="ui-list__item ui-list__item--link"><a class="ui-list__link" href="…">…</a>…</li>
</ul>
```

`ui-list` : `list-style: none; margin: 0; padding: 0;` fond `surface`, bordure `line`, `radius-md` ; `ui-list__item` : flex, `gap: 0.75rem`, `min-height: 56px`, padding `0.5rem 1rem`, séparateur `line` entre éléments ; `--link` : même principe de lien étiré que la carte (`.ui-list__link::after`).

### 5.15 Autres classes du kit (utilisées par le shell)

`ui-skip-link` (hors écran via `transform: translateY(-200%)`, visible au focus en haut à gauche, fond `surface`, ≥ 44 px), `ui-header`, `ui-layout`, `ui-main`, `ui-sidebar`, `ui-bottom-nav`, `ui-tab`, `ui-tab__label`, `ui-menu`, `ui-menu__item`, `ui-menu__heading` (`text-caption`, graisse 600, `ink-muted`, majuscules, `margin: 1rem 0 0.25rem`), `ui-identity`, `ui-identity__name`, `ui-label__optional`, `ui-page-header` (bloc titre de page : `h1` `text-title` 700 `margin: 0`, sous-titre `p` `text-small` `ink-2`, zone d'actions alignée à droite à partir de `sm`), `ui-link` (lien dans un texte : `primary-strong`, souligné, `text-underline-offset: 2px`), `ui-icon` (`flex-shrink: 0; vertical-align: middle;`), `ui-form`, `ui-form--inline` (§4.10), `ui-toast-stack` (piles vivantes, flex colonne, `gap: 0.5rem`), `ui-dialog-actions` (`display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 0.5rem; margin-top: 1.25rem;`), `ui-icon--spin`, `ui-offline`, `ui-theme-icon-sun`, `ui-theme-icon-moon`, et l'attribut `[data-secret][data-masked="true"]` (`filter: blur(0.35em); user-select: none;`).

### 5.16 Page catalogue `/_ui`

- Route `main.ui_catalog` (`GET /_ui`), gabarit `main/ui_catalog.html` (étend `base.html`, contexte `global`).
- **Désactivée en production** : la vue renvoie `abort(404)` sauf si `current_app.config["UI_CATALOG_ENABLED"]` est vrai. `create_app` : `app.config["UI_CATALOG_ENABLED"] = os.environ.get("UI_CATALOG_ENABLED", "false") == "true"`. Valeur absente (production Docker) = désactivée. Seul `serve_demo.py` la met à `true`. Documenter la variable dans `.env.example` (commentée, valeur `false`).
- Contenu : un `h1` « Catalogue de composants » puis une `section` par composant, chacune avec `data-testid="catalog-<clé>"` et un `h2` : `page-header`, `button` (4 variantes × états défaut, désactivé, chargement ; tailles sm/défaut/lg/icône/block ; le catalogue montre donc plusieurs `--primary`, et ses scènes désactivent le contrôle `primary`, §9.6), `card` (une carte simple, une carte cliquable avec action), `field` (texte avec aide, texte en erreur, select, textarea, champ facultatif), `segmented`, `check` (case, radio, interrupteur, chacun coché/non coché/désactivé), `badge` (6 tons), `empty` (avec action), `skeleton`, `sheet` (bouton `data-testid="catalog-sheet-trigger"` ouvrant `catalog-demo-sheet`, qui contient un bouton `ui-btn ui-btn--secondary` `data-copy="holishared"` avec `data-testid="catalog-sheet-copy"` : toast émis depuis une feuille ouverte), `confirm` (formulaire `class="ui-form"`, `method="get"` vers `/_ui` avec `data-confirm`, bouton `data-testid="catalog-confirm-trigger"`), `toast` (un bouton `data-copy` qui produit un toast « Copié » ; et un exemple statique de chaque ton), `progress`, `avatar`, `list`, `secret` (code masqué + bouton `data-reveal`), `icons` (grille des 71 icônes : chaque icône dans un élément `data-icon="<nom>"` avec son nom en texte).
- Tous les textes passent par `_()` et ont une traduction EN (contrôlée par la scène EN de la garde). Clés `catalog-*` exactes : `page-header`, `button`, `card`, `field`, `segmented`, `check`, `badge`, `empty`, `skeleton`, `sheet`, `confirm`, `toast`, `progress`, `avatar`, `list`, `secret`, `icons`.

---

## 6. Icônes

- **Un seul jeu** : Lucide (`lucide-static@1.52.0`, licence ISC). Données copiées une fois dans `app/icons.py` (aucune dépendance runtime ; pour récupérer les fichiers : `npm pack lucide-static@1.52.0` dans un répertoire temporaire hors dépôt, puis lire `package/icons/<nom>.svg`). En-tête du module : `"""Icônes Lucide v1.52.0 — ISC License, Copyright (c) Lucide Contributors."""`.
- Noms **canoniques** Lucide : `funnel` (et non l'alias `filter`), `circle-question-mark` (et non l'alias `circle-help`).
- `ICON_NAMES: Final[tuple[str, ...]]` (ordre ci-dessous) et `ICONS: Final[dict[str, str]]` (nom → éléments enfants du `<svg>` Lucide, sans la balise `<svg>` ni le commentaire de licence).
- Global Jinja `icon(name: str, label: str | None = None, size: int = 20, class_: str = "") -> Markup` (dans `app/ui.py`). Rendu exact (décoratif) :

```html
<svg class="ui-icon{{ ' ' ~ class_ if class_ }}" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">…</svg>
```

  Avec `label` : `aria-hidden="true"` est remplacé par `role="img" aria-label="<label échappé>"`. Nom inconnu → `KeyError` (la page échoue en test plutôt que d'afficher un vide).
- **Liste exacte (71)** — navigation : `house`, `calendar-days`, `utensils`, `list-checks`, `wallet`, `ellipsis`, `vote`, `info`, `message-circle`, `image`, `users`, `scroll-text`, `user-plus`, `shield-check`, `calendar-plus`, `calendar-range` ; en-tête : `sun`, `moon`, `globe`, `log-out`, `log-in`, `user`, `arrow-left` ; actions : `plus`, `x`, `check`, `pencil`, `trash-2`, `copy`, `share-2`, `link`, `eye`, `eye-off`, `download`, `upload`, `camera`, `qr-code`, `mail`, `send`, `search`, `funnel`, `ellipsis-vertical`, `chevron-down`, `chevron-up`, `chevron-left`, `chevron-right`, `grip-vertical`, `move`, `arrow-left-right`, `refresh-cw`, `external-link`, `map-pin`, `clock`, `shopping-cart`, `bell`, `bell-off`, `settings`, `lock`, `key-round`, `sunset`, `euro`, `undo-2`, `archive` ; états : `circle-check`, `circle-alert`, `triangle-alert`, `loader-circle`, `wifi-off`, `circle-question-mark`, `inbox`, `sparkles`.
- **Fin des emojis comme icônes** : le shell, les feuilles et les composants n'en contiennent aucun. Les emojis restants dans le contenu des pages historiques disparaissent avec la réécriture de chaque page (lots B019–B026) ; règle pour ces lots : `icon()` uniquement.

---

## 7. JavaScript partagé

### 7.1 Principes

- Modules ES dans `app/static/js/ui/`, chargés par **un seul** `<script type="module" src="{{ asset_url('js/ui/main.js') }}">`. Les imports entre modules utilisent des spécificateurs nus `"ui/<nom>"` résolus par l'import map (`ui_importmap()`), dont chaque URL porte l'empreinte du fichier : aucun module n'est jamais servi périmé (le cache nginx de 30 jours et le cache du SW s'appliquent à des URL versionnées).
- `ui_importmap()` (Python) → `{"imports": {"ui/<stem>": asset_url("js/ui/<stem>.js") for chaque fichier de app/static/js/ui/*.js, trié}}`.
- **Délégation d'évènements** sur `document` : aucun écouteur par élément, aucune réinitialisation nécessaire après un échange HTMX.
- **Aucune chaîne en dur** : toute chaîne visible vient du DOM rendu par Jinja (libellés existants) ou du bloc JSON `#ui-strings` (§7.2). Gabarits HTML clonés depuis `<template>`.
- Le JS bascule des attributs, jamais des classes (§2.3).
- **HTMX : pas de `hx-boost`.** Raisons : les pages historiques ont des scripts inline exécutés au chargement et des formulaires `onchange="this.form.submit()"` ; le boost casserait aussi la gestion du focus, le script de thème et les mises à jour du SW. htmx reste chargé (`defer`) pour les usages partiels ciblés (chat ; lots B023/B025).
- Ordre d'initialisation dans `main.js` (exact) : `initTheme()`, `initSheets()`, `initToasts()`, `initClipboard()`, `initReveal()`, `initConfirm()`, `initForms()`, `initPwa()`. Chaque `init*` est idempotent (garde `if (initialized) return`).
- Aucune erreur ni avertissement console en fonctionnement normal (contrôle de la garde).

### 7.2 Chaînes JS : registre unique `JS_STRINGS`, bloc `#ui-strings`, `t(key)`

**Un seul mécanisme pour tout le programme.** Aucun autre bloc JSON de chaînes, aucun autre global Jinja, aucun attribut `data-*` porteur de libellés JS génériques n'est créé par B017 ni par les lots suivants (B018 compris, qui doit s'y conformer : il ajoute ses clés à ce registre et n'introduit ni `#i18n-js` ni `js_strings()`).

1. **Registre (Python, `app/ui.py`)** — source unique, clé → msgid FR :

```python
def N_(s: str) -> str:  # marqueur d'extraction (mot-clé pybabel par défaut), sans traduction
    return s


JS_STRINGS: Final[dict[str, str]] = {
    "copied": N_("Copié"),
    # … une entrée par ligne du tableau ci-dessous
}


def ui_strings() -> dict[str, str]:  # global Jinja ; traduit à la requête
    return {key: gettext(msgid) for key, msgid in JS_STRINGS.items()}
```

2. **Rendu** (dans `base.html`, une seule fois) : `<script type="application/json" id="ui-strings">{{ ui_strings()|tojson }}</script>` (bloc de données non exécuté).
3. **API JS** (`strings.js`) :

```js
export function t(key) // chaîne traduite ; clé absente → console.error("ui-strings: clé manquante " + key) et retourne key
```

   Lit une fois `JSON.parse(document.getElementById('ui-strings').textContent)`. Une clé manquante produit une erreur console, donc un échec de la garde.
4. **Ajouter des clés (lots suivants)** : ajouter une ligne `"<clé>": N_("<msgid FR>")` au registre, la traduction EN au catalogue (procédure §11.4), et utiliser `t('<clé>')` dans le module JS. Rien d'autre à modifier : le test T43 compare les clés rendues au registre, T43a vérifie la convention, T39 la traduction EN de tous les msgids du registre.
5. **Convention de nommage** : `snake_case` ASCII (regex `^[a-z][a-z0-9_]*$`). Les clés génériques du kit (tableau ci-dessous) n'ont pas de préfixe ; une clé propre à un domaine est préfixée par le scope du lot (`lists_noted`, `meals_moved`, `costs_…`). Une clé n'est jamais renommée ni réutilisée pour un autre sens ; pour changer un texte, on change le msgid de la clé.

Clés livrées par B017 (11) :

| Clé | msgid FR | EN |
|---|---|---|
| `copied` | Copié | Copied |
| `copy_failed` | Copie impossible | Copy failed |
| `close` | Fermer | Close |
| `cancel` | Annuler | Cancel |
| `confirm` | Confirmer | Confirm |
| `confirm_title` | Confirmer l'action | Confirm action |
| `new_version` | Nouvelle version disponible | New version available |
| `reload` | Recharger | Reload |
| `show` | Voir | Show |
| `hide` | Masquer | Hide |
| `loading` | Chargement… | Loading… |

Choix d'un bloc JSON plutôt que des attributs `data-*` : point unique, extractible (`N_`), testable.

### 7.3 `main.js`

Importe les modules par `"ui/<nom>"` et appelle les `init*` dans l'ordre §7.1. Rien d'autre.

### 7.4 `theme.js`

```js
export function getTheme()                           // 'light' | 'dark' (lit data-theme)
export function setTheme(theme, { persist = true } = {}) // pose data-theme ; met à jour <meta name="theme-color"> avec
                                                     // getComputedStyle(documentElement).getPropertyValue('--color-canvas').trim() ;
                                                     // aria-pressed="true|false" (sombre = true) sur tous les [data-theme-toggle] ;
                                                     // si persist : localStorage.setItem('theme', theme) dans un try/catch
export function initTheme()                          // synchronise aria-pressed et meta ; clic délégué sur [data-theme-toggle] → bascule ;
                                                     // si aucune préférence stockée : suit les changements de prefers-color-scheme
                                                     // (setTheme(…, { persist: false }))
```

### 7.5 `dialog.js` (feuilles et dialogues)

```js
export function openSheet(target, opener = document.activeElement) // target : id ou HTMLDialogElement ; retourne le dialog
export function closeSheet(dialog, returnValue = '')
export function initSheets()
```

- Clic délégué sur `[data-sheet-open]` → `openSheet(el.dataset.sheetOpen, el)` ; sur `[data-sheet-close]` → ferme le `<dialog>` ancêtre.
- `openSheet` : si une autre feuille est ouverte, elle est fermée d'abord et **son** déclencheur devient le déclencheur à restaurer (ex. confidentialité ouverte depuis « Plus » → au retour, focus sur `tab-more`) ; `dialog.showModal()` ; `opener.setAttribute('aria-expanded', 'true')` si l'attribut existe.
- Clic sur un `dialog.ui-sheet` lui-même (`event.target === dialog`, c.-à-d. le fond) → fermeture. Limité aux feuilles du kit (`.ui-sheet`) : les dialogues historiques (ex. `#meal-modal` de `meals/index.html`, qui a un padding) ne sont pas concernés.
- Évènement `close` : `aria-expanded="false"` sur le déclencheur, puis `opener.focus()` s'il est encore dans le document.
- Échap : comportement natif (`cancel` → `close`).
- La modale de confidentialité n'a pas de module propre : elle utilise `data-sheet-open="privacy-sheet"`.

### 7.6 `toast.js`

```js
export function toast(message, { tone = 'info', action = null, timeout } = {}) // action : { label, onClick } ; retourne l'élément
export function initToasts()
```

- `toast()` clone `#ui-toast-template`, pose `data-tone`, supprime les `[data-tone-icon]` dont la valeur diffère du ton, ajoute, si `action`, un `<button type="button" class="ui-btn ui-btn--ghost ui-btn--sm" data-toast-action>` (libellé `textContent`) avant le bouton fermer, puis insère le toast **avec un message vide** dans la pile `[data-toast-live="polite"]` (success/info) ou `[data-toast-live="assertive"]` (warning/danger) de la zone cible (§4.7 : zone du dernier `dialog[open]`, sinon `#toast-region`) ; le texte est écrit via `textContent` au `requestAnimationFrame` suivant (un contenu ajouté à une région vivante déjà présente est annoncé de façon fiable). Au-delà de 3 toasts dans la zone, retire le plus ancien.
- `timeout` par défaut : 6000 ms pour success/info, `null` (persistant) pour warning/danger (WCAG 2.2.1). Le minuteur est suspendu au survol (`pointerenter`) et au focus (`focusin`) du toast, et relancé (6000 ms) à `pointerleave`/`focusout`.
- Fermeture : `[data-toast-close]` ou fin du minuteur → `data-state="leaving"` puis suppression après 200 ms (immédiate si `prefers-reduced-motion: reduce`).
- `initToasts()` applique minuteur et fermeture aux toasts rendus par le serveur, et, pour qu'ils soient annoncés, vide puis réécrit leur message au `requestAnimationFrame` suivant le chargement.

### 7.7 `clipboard.js`

```js
export async function copyText(text) // Promise<boolean> ; navigator.clipboard.writeText si disponible,
                                     // sinon repli <textarea> hors écran + document.execCommand('copy') dans un try/catch
export function initClipboard()
```

- Clic délégué sur `[data-copy]` (texte = valeur de l'attribut) ou `[data-copy-target]` (sélecteur CSS : `value` d'un `input`/`textarea`, sinon `textContent.trim()`).
- Succès : `toast(t('copied'), { tone: 'success' })` + `data-state="copied"` sur le déclencheur pendant 2000 ms.
- Échec : `toast(t('copy_failed'), { tone: 'danger' })` ; si la cible est un champ, `focus()` + `select()` (copie manuelle possible).

### 7.8 `reveal.js`

```js
export function initReveal()
```

Clic délégué sur `[data-reveal]` : bouton avec `aria-controls="<id>"` et `aria-pressed`. Bascule `data-masked="true|false"` sur l'élément cible (`[data-secret]`), `aria-pressed` sur le bouton, et le texte de son enfant `[data-reveal-label]` entre `t('show')` (masqué) et `t('hide')` (visible). Le code lui-même n'est plus cliquable (fin de l'affordance cachée I8).

### 7.9 `confirm.js` (remplace `confirm()`, I7)

```js
export function confirmAction({ message, confirmLabel, tone = 'danger' }) // Promise<boolean>
export function initConfirm()
```

- `<template id="ui-confirm-template">` (rendu par `base.html`) :

```html
<dialog class="ui-sheet ui-sheet--dialog" data-testid="confirm-dialog" aria-labelledby="ui-confirm-title" aria-describedby="ui-confirm-message">
  <form method="dialog" class="ui-sheet__panel">
    <div class="ui-sheet__header"><h2 class="ui-sheet__title" id="ui-confirm-title">{{ _("Confirmer l'action") }}</h2></div>
    <p id="ui-confirm-message" data-confirm-message></p>
    <div class="ui-dialog-actions">
      <button value="cancel" class="ui-btn ui-btn--secondary" data-testid="confirm-cancel" autofocus>{{ _("Annuler") }}</button>
      <button value="accept" class="ui-btn ui-btn--danger" data-testid="confirm-accept" data-confirm-accept>{{ _("Confirmer") }}</button>
    </div>
  </form>
</dialog>
```

- `confirmAction` : clone, écrit `message` par `textContent`, remplace le libellé d'acceptation par `confirmLabel` s'il est fourni, passe le bouton en `ui-btn--primary` si `tone === 'primary'`, ajoute au `body`, `showModal()` ; résout `dialog.returnValue === 'accept'` à l'évènement `close` puis retire le dialogue. Échap → `false`. Focus initial sur « Annuler » (sûr pour une action destructive) ; retour du focus au déclencheur.
- Délégation `submit` sur `document` : source = `event.submitter?.closest('[data-confirm]')` sinon le formulaire s'il porte `data-confirm`. Sans source → rien. Si `form.dataset.confirmed === '1'` → supprimer le drapeau et laisser passer. Sinon `preventDefault()`, `confirmAction({ message: source.dataset.confirm, confirmLabel: source.dataset.confirmLabel, tone: source.dataset.confirmTone })` ; si vrai : `form.dataset.confirmed = '1'` puis `form.requestSubmit(event.submitter ?? undefined)` (fonctionne avec les boutons associés par l'attribut `form=`).
- Sans JS, le formulaire est envoyé sans confirmation (amélioration progressive assumée).

### 7.10 `forms.js` (anti double envoi, I9)

```js
export function initForms()
```

- Écouteur `submit` sur `document`, enregistré **après** celui de `confirm.js` ; ignore l'évènement si `event.defaultPrevented`.
- Ignore les formulaires `[data-no-lock]`, `method="dialog"`, et ceux portant un attribut `hx-get|hx-post|hx-put|hx-patch|hx-delete` (htmx gère lui-même).
- Si `form.dataset.submitting === '1'` → `preventDefault()` (deuxième envoi bloqué). Sinon `form.dataset.submitting = '1'` et, sur `event.submitter` s'il existe : `aria-disabled="true"`, `aria-busy="true"`, `data-loading="true"`. Le bouton n'est **pas** passé en `disabled` (sa valeur `name=value` doit rester dans l'envoi).
- `pageshow` avec `event.persisted` (retour arrière, bfcache) → retire `data-submitting` de tous les formulaires et les trois attributs des boutons.

### 7.11 `pwa.js`

```js
export function initPwa()
```

1. Sortir si `!('serviceWorker' in navigator)` ou `document.documentElement.dataset.sw !== 'on'`.
2. Nettoyage de l'ancien SW : `navigator.serviceWorker.getRegistrations()` → `unregister()` de toute inscription dont `scope` se termine par `/static/js/`.
3. `const hadController = !!navigator.serviceWorker.controller` ; `register('/sw.js', { scope: '/' })`.
4. Mise à jour : si `registration.waiting` et `hadController` → `promptUpdate(registration.waiting)` ; sur `updatefound`, quand le nouveau worker atteint `installed` et que `navigator.serviceWorker.controller` existe → `promptUpdate(worker)`. `promptUpdate(w)` = `toast(t('new_version'), { tone: 'info', timeout: null, action: { label: t('reload'), onClick: () => w.postMessage({ type: 'SKIP_WAITING' }) } })`.
5. `controllerchange` → `location.reload()` une seule fois, **seulement si `hadController`** (la première installation, qui appelle `clients.claim()`, ne recharge pas la page).
6. Localhost : enregistrement aussi en local (contexte sécurisé ; les empreintes rendent le cache sûr en développement). Pour désactiver : `SW_ENABLED=false` (`create_app` : `app.config["SW_ENABLED"] = os.environ.get("SW_ENABLED", "true") == "true"`, documenté dans `.env.example`).

### 7.12 Migration des gabarits existants (fin de la duplication inline)

| Gabarit | Avant | Après |
|---|---|---|
| `events/dashboard.html` (bloc code) | `<code class="guest-code" data-code=…>`, boutons `.reveal-code` / `.copy-code` | `<code class="guest-code" id="guest-code-{{ guest.id }}" data-secret data-masked="true">` ; bouton `type="button" class="btn btn-small" data-reveal aria-controls="guest-code-{{ guest.id }}" aria-pressed="false"` contenant `<span data-reveal-label>{{ _("Voir") }}</span>` ; bouton `type="button" class="btn btn-small" data-copy="{{ guest.code }}"` « Copier » |
| `events/dashboard.html` (partage) | `#share-btn` + script inline `{% block scripts %}` | `data-copy="{{ request.host_url.rstrip('/') }}{{ url_for('events.dashboard', code=event.code) }}"` sur le bouton (même URL qu'aujourd'hui : la correction F03 relève de B020) ; attributs `id`, `data-url`, `data-copied` et le bloc `scripts` supprimés |
| `events/dashboard.html` (suppression) | `onsubmit="return confirm('…')"` | `data-confirm="{{ _('Supprimer définitivement cet événement et toutes ses données ?') }}"` sur le `<form>` |
| `events/members.html` (**sécurité**) | `<code class="guest-code" data-code="{{ g.code }}">`, bouton « Voir » et bouton « Copier » rendus pour **tout** visiteur, y compris un invité : n'importe quel invité peut lire et copier le code personnel (seul secret d'accès) des autres participants | le `<code>` et les deux boutons sont enveloppés dans `{% if is_creator %}…{% endif %}` (variable déjà passée par la vue) ; pour le créateur, même transformation que le tableau de bord (id `guest-code-{{ g.id }}`, `data-secret data-masked="true"`, `data-reveal`, `data-copy="{{ g.code }}"`). Un invité ne reçoit **aucun** code dans le HTML (T44e) |
| `events/members.html` (retrait) | `onclick="return confirm('{{ _("Retirer") }} {{ g.display_name }} ?')"` | `data-confirm="{{ _('Retirer %(name)s ?', name=g.display_name) }}"` sur le bouton (msgid traduisible avec paramètre ; l'échappement d'attribut Jinja supprime l'injection possible du nom dans une chaîne JS) |
| `events/invite.html` | `onclick="this.select()"` sur l'input ; `onclick="navigator.clipboard.writeText(…)"` | input sans `onclick` ; bouton `type="button" class="btn btn-secondary" data-copy-target="#invite-url"` |
| `costs/index.html` (4 boutons) | `onclick="return confirm('…')"` | `data-confirm="{{ _('…même msgid…') }}"` sur chaque bouton (les boutons conservent `form=…`, `formmethod`, `type="submit"`) |

Après migration : aucun `confirm(` ni `navigator.clipboard` dans `app/templates/` (tests T40, T41).

**Scripts inline qui restent (hors B017, lot responsable)** : `events/dashboard.html` aucun ; `freemium/paywall.html`, `events/invite.html` (bloc `scripts` de la modale d'upgrade), `media/gallery.html` → B028 (F19) ; `events/join.html`, `events/verify.html` (génération de code) → B029 ; `meals/index.html` → B022 ; `lists/detail.html` → B023 ; `chat/index.html` → B025 ; `costs/index.html` (pastilles de catégorie) → B024.

---

## 8. Service worker et PWA

### 8.1 Route `/sw.js` (`main.service_worker`)

- `GET /sw.js` → `render_template("sw.js", cache_name=…, precache=…, offline_url=url_for("main.offline"))` ; réponse `mimetype="application/javascript"` ; en-têtes `Cache-Control: no-cache` et `Service-Worker-Allowed: /`.
- Servi depuis la racine : portée `/` (F20 suite). Le fichier `app/static/js/service-worker.js` est supprimé.

### 8.2 Empreintes et version de cache (`app/ui.py`)

```python
def asset_hash(filename: str) -> str     # sha256 du contenu de Path(current_app.static_folder, filename), 10 premiers caractères hex ;
                                         # cache functools.lru_cache(maxsize=256) sur (chemin absolu, st_mtime_ns) ;
                                         # fichier absent → FileNotFoundError
def asset_url(filename: str) -> str      # url_for("static", filename=filename, v=asset_hash(filename))
                                         # → "/static/css/app.css?v=0123456789"
def precache_static() -> list[str]       # ["css/app.css", "js/htmx.min.js", "icons/icon-192.png"]
                                         # + ["js/ui/<f>.js" pour chaque module, trié]
def precache_urls() -> list[str]         # [asset_url(f) for f in precache_static()] + [url_for("main.offline")]
def asset_version() -> str               # sha256 de la concaténation de f"{f}:{asset_hash(f)}\n" pour f in precache_static(),
                                         # + octets de app/templates/sw.js + octets de app/templates/main/offline.html
                                         # + octets de translations/*/LC_MESSAGES/messages.mo (triés) : une traduction
                                         #   corrigée de la page hors ligne renouvelle le cache ;
                                         # 12 premiers caractères hex
```

`cache_name = "holishared-" + asset_version()`. `asset_url` est le seul moyen de référencer un asset statique dans `base.html`, `offline.html` et le catalogue (cache busting). Les helpers sont enregistrés comme globaux Jinja par `init_ui(app)` (appelé dans `create_app`) : `asset_url`, `icon`, `ui_importmap`, `ui_strings`, `build_nav`.

### 8.3 Contenu de `app/templates/sw.js` (comportement exact)

```js
const CACHE = {{ cache_name|tojson }};
const PRECACHE = {{ precache|tojson }};
const OFFLINE_URL = {{ offline_url|tojson }};

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('holishared-') && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }
  if (url.pathname.startsWith('/static/') && url.searchParams.has('v')) {
    event.respondWith(caches.match(request).then((cached) => cached || fetch(request)));
  }
});

// Point d'extension B027 : les gestionnaires push, notificationclick et notificationclose s'ajoutent après ce commentaire.
```

Stratégie : pages **réseau d'abord** avec repli `/offline`, **jamais mises en cache** (aucun contenu authentifié ni PII dans le cache ; aucun `cache.put`) ; assets versionnés **cache d'abord** ; tout le reste (HTMX, médias, POST) passe au réseau sans interception. Pas de `skipWaiting()` à l'installation : la mise à jour attend le clic « Recharger » (§7.11). Alpine n'est plus précaché (fichier supprimé). L'ancien cache `holishared-v3` est supprimé à l'activation (préfixe commun).

### 8.4 Page hors ligne `/offline` (`main.offline`)

- `GET /offline` → `main/offline.html`, **document autonome** (n'étend pas `base.html` : aucune identité, aucun jeton CSRF, aucune donnée de session ; il est précaché avec les cookies de l'utilisateur et ne doit rien en contenir).
- Contenu : doctype, `<html lang="{{ current_lang or 'fr' }}">`, mêmes métas que §4.2 (charset, viewport, theme-color, color-scheme), titre `{{ _("Hors ligne") }} — holishared`, `{% include "_components/theme_script.html" %}`, `<link rel="stylesheet" href="{{ asset_url('css/app.css') }}">`, `<link rel="icon" type="image/png" href="{{ asset_url('icons/icon-192.png') }}">` (précaché : pas de requête `/favicon.ico` hors ligne, donc pas d'erreur console), puis `<main class="ui-offline" data-testid="offline-page">` avec `icon('wifi-off', size=48)`, `<h1>{{ _("Vous êtes hors ligne") }}</h1>`, `<p>{{ _("Vérifiez votre connexion puis réessayez.") }}</p>`, `<a class="ui-btn ui-btn--primary" href="">{{ _("Réessayer") }}</a>` (`href=""` recharge l'URL demandée, puisque le SW sert cette page à la place de la navigation échouée). Aucun script autre que le script de thème.
- Limite connue et acceptée : la page est précachée dans la langue active lors de l'installation du SW ; un changement de langue ultérieur ne la re-précache qu'à la prochaine nouvelle version (toute modification d'asset, de gabarit ou de catalogue `.mo` en crée une, §8.2).
- `ui-offline` : centré verticalement (`min-height: 100dvh`, flex colonne, `gap: 1rem`, padding gutter).

### 8.5 Manifest (`app/static/manifest.json`, contenu exact)

```json
{
  "id": "/",
  "name": "holishared",
  "short_name": "holishared",
  "description": "Planification de vacances et événements en groupe",
  "lang": "fr",
  "dir": "ltr",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "background_color": "#faf8f5",
  "theme_color": "#faf8f5",
  "icons": [
    { "src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable" },
    { "src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable" }
  ],
  "shortcuts": [
    { "name": "Mes événements", "short_name": "Événements", "url": "/e/" },
    { "name": "Créer un événement", "short_name": "Créer", "url": "/e/new" }
  ]
}
```

`orientation` est retiré (verrouillage d'orientation contraire à WCAG 1.3.4). Icônes inchangées (refonte maskable en B028).

### 8.6 Cas particuliers

- **Pages HTML** : `security_headers` continue de poser `Cache-Control: no-cache, must-revalidate` ; la route `/sw.js` pose son propre `Cache-Control: no-cache` (non HTML, donc non écrasé).
- **CSP inchangée** : `script-src 'self' 'unsafe-inline'` reste nécessaire (script de thème, import map inline, scripts et gestionnaires inline des pages non migrées). Seul le commentaire `# Alpine.js inline` devient `# scripts inline : thème, import map, pages historiques (durcissement en B028)`. Le test `test_csp_header` reste valide sans modification.
- **iOS** : la mise à jour du SW n'a lieu qu'au retour au premier plan ; le toast « Nouvelle version disponible » apparaît alors.

---

## 9. Outillage UI (`scripts/ui/`)

### 9.1 Vue d'ensemble

| Fichier | Rôle |
|---|---|
| `seed_demo.py` | crée une base SQLite et un `instance_path` jetables **hors dépôt**, des données de démo, et `fixtures.json` (cookies signés par rôle, identifiants) |
| `serve_demo.py` | sert l'application sur la base de démo (Waitress, `127.0.0.1`), limiteur désactivé, SMTP vide, catalogue activé |
| `lib.mjs` | fonctions communes Node (Python, démo, Chrome/CDP, scènes) + CLI `seed` / `serve` |
| `scenes.json` | scènes déclaratives |
| `check.mjs` | garde : exécute les scènes et les contrôles, code de sortie |
| `shoot.mjs` | captures PNG des scènes |
| `exceptions.json` | exceptions justifiées (initialement `[]`) |
| `selftest-scenes.json` | scènes volontairement fausses de l'auto-contrôle (§9.10) |

Répertoires : `UI_DEMO_DIR` (défaut `<tmp>/holishared-ui/demo`) pour la démo ; `--out` (défaut `<tmp>/holishared-ui/check` pour la garde, `<tmp>/holishared-ui/shots` pour les captures), où `<tmp>` = `tempfile.gettempdir()` (Python) / `os.tmpdir()` (Node). Port `UI_PORT` (défaut `8499`). Aucun artefact dans le dépôt. Les scripts Python respectent ruff (pas de chaîne littérale `/tmp`, règle S108 : utiliser `tempfile.gettempdir()`).

### 9.2 `seed_demo.py`

Fonctions (importables par les tests) :

```python
REPO_ROOT: Path  # = Path(__file__).resolve().parents[2]

def demo_env(out_dir: Path, secret_key: str, superadmin_password: str, port: int) -> dict[str, str]
def seed(out_dir: Path, port: int = 8499) -> dict[str, Any]
def main() -> int   # CLI : python scripts/ui/seed_demo.py [--out DIR] [--port N] ; défauts : UI_DEMO_DIR / UI_PORT
```

`demo_env` retourne exactement : `SECRET_KEY`, `SUPERADMIN_EMAIL=admin@demo.invalid`, `SUPERADMIN_PASSWORD`, `DATABASE_URL=sqlite:///<out_dir>/demo.db` (chemin absolu, donc quatre `/`), `ENABLED_MODULES=planning,meals,lists,logistics,voting,media,chat,costs`, `MAX_GUESTS_PER_EVENT=10`, `MAX_DURATION_DAYS=30`, `MAX_EVENTS_PER_CREATOR=10`, `SESSION_COOKIE_SECURE=false`, `REDIS_URL=` (vide → stockage mémoire du limiteur), `SMTP_HOST=`, `SMTP_USER=`, `SMTP_PASSWORD=`, `DEFAULT_LANGUAGE=fr`, `SUPPORTED_LANGUAGES=fr,en`, `APP_URL=http://127.0.0.1:<port>`, `UI_CATALOG_ENABLED=true`, `SW_ENABLED=true`. (Ces variables explicites l'emportent sur le `.env` du développeur, chargé avec `override=False` : la démo est hermétique.)

`seed(out_dir, port)` :

1. Si `out_dir.resolve()` est dans `REPO_ROOT` → `ValueError` (rien n'est créé).
2. Crée `out_dir` ; supprime s'ils existent `demo.db`, `demo.db-wal`, `demo.db-shm`, `fixtures.json` et le dossier `instance/`.
3. `secret_key = secrets.token_hex(32)`, `superadmin_password = secrets.token_urlsafe(16)` ; `os.environ.update(demo_env(...))` **avant** `from app import create_app` (import dans la fonction).
4. `app = create_app()` ; `app.instance_path = str(out_dir / "instance")` (créé) ; dans `app.app_context()` :
   - Créateur : `email="camille@demo.invalid"`, `email_verified=True`, `display_name="Camille"`, `personal_code="camille1"`.
   - Événements (`today = date.today()`, `verified_at = datetime.utcnow()` sauf mention) :

| Clé | Titre | Début → fin | Lieu | Particularité |
|---|---|---|---|---|
| `rich` | Vacances au Vercors | J-1 → J+5 | Villard-de-Lans | description « Une semaine entre amis dans le Vercors. », contenu complet |
| `empty` | Week-end en Bretagne | J+40 → J+42 | Quiberon | aucun contenu |
| `full` | Anniversaire de Léa | J+20 → J+22 | Lyon | invités `Invité 01`, `Invité 02`… (codes `full0001`…) ajoutés tant que `can_add_guest(event)` est vrai |
| `unverified` | Séjour à confirmer | J+60 → J+63 | Annecy | **seul événement non vérifié**, réservé aux pages `verify` / `verify_sent` : `verified_at=None`, `verification_token=secrets.token_hex(32)` (exposé en placeholder `token.unverified`) ; tous les autres événements ont `verified_at` renseigné |
| `past` | Ski à Chamrousse | J-20 → J-14 | Chamrousse | terminé (non purgé : < 30 jours) |
| `long` | Réveillon de la Saint-Sylvestre chez Jean-Baptiste, Marie-Charlotte et toute la famille Delacroix-Montgomery à Saint-Rémy-de-Provence | J+80 → J+83 | Saint-Rémy-de-Provence | titre > 80 caractères |

   - Pour chaque événement : `ensure_creator_guest(event, creator)`.
   - Contenu de `rich` : invités `Antoine` (code `antoine1`) avec foyer `Household(name="Antoine & Béa", num_adults=2, guest_id=antoine.id)` ; `Chloé` (code `chloe001`) **sans foyer** ; `Dimitri` (`dimitri1`), `Béatrice` (`beatrice`). 4 activités (« Randonnée Grande Moucherolle » J 09:00 avec description et lieu ; « Piscine » J+1 14:30 ; « Visite des grottes de Choranche » J+2 sans heure ; « Soirée jeux de société » J+2 21:00), `created_by=antoine.id`. Repas : pour d de -1 à 4, un `dinner` chaque jour et un `lunch` les jours pairs, titres alternés « Raclette », « Pique-nique », « Pâtes au pesto ». Liste « Courses » (`list_type="shopping"`) : « Pâtes » (×2), « Fromage à raclette », « Pain », « Vin rouge » (`assigned_to="Antoine"`, `assigned_to_id=antoine.id`), « Sel » (`is_done=True`). Sondage « Quel jour pour la grande randonnée ? » options Mardi/Mercredi/Jeudi, un vote d'Antoine sur Mercredi. Infos : « Adresse du gîte » (`category="address"`), « Code d'accès » (`category="access"`). Chat : 3 messages (Antoine, Chloé — invités avec `guest_id` —, Camille `author_type="creator"`). Dépenses (date J) : « Courses supermarché » `amount_cents=14250` (`food`) payée par le foyer du créateur, « Location gîte » `amount_cents=84000` (`lodging`) payée par le foyer d'Antoine.
5. Cookies (`ser = app.session_interface.get_signing_serializer(app)`) :
   - `creator` : `ser.dumps({"_user_id": creator.id, "_fresh": True})` — **seulement** ces deux clés ;
   - `guest_household` : `ser.dumps({f"guest_{rich.code}": antoine.id})` — **seulement** cette clé ;
   - `guest_solo` : `ser.dumps({f"guest_{rich.code}": chloe.id})`.
6. Écrit `out_dir/fixtures.json` (permissions `0o600`) et le retourne :

```json
{
  "version": 1,
  "port": 8499,
  "secret_key": "…",
  "superadmin_password": "…",
  "database_path": "<out_dir>/demo.db",
  "instance_path": "<out_dir>/instance",
  "roles": ["anonymous", "creator", "guest_household", "guest_solo"],
  "cookies": { "creator": "…", "guest_household": "…", "guest_solo": "…" },
  "placeholders": {
    "event.rich": "…", "event.empty": "…", "event.full": "…", "event.unverified": "…",
    "event.past": "…", "event.long": "…", "list.rich": "<id de la liste Courses>", "poll.rich": "<id du sondage>",
    "token.unverified": "<verification_token de l'événement unverified>"
  }
}
```

`main()` affiche le chemin de `fixtures.json` et renvoie 0 ; `ValueError` → message sur stderr, code 2.

### 9.3 `serve_demo.py`

```python
def build_app(fixtures: dict[str, Any]) -> Flask
def main() -> int   # CLI : python scripts/ui/serve_demo.py [--demo-dir DIR] ; défaut UI_DEMO_DIR
```

`build_app` : `os.environ.update(demo_env(out_dir, fixtures["secret_key"], fixtures["superadmin_password"], fixtures["port"]))` (avec `from seed_demo import demo_env`, `out_dir` = parent de `database_path`) puis `create_app()`, `app.instance_path = fixtures["instance_path"]`, `limiter.enabled = False` (`from app.extensions import limiter`). `main` : lit `fixtures.json` (absent → message « lancer npm run ui:seed », code 2), `waitress.serve(app, host="127.0.0.1", port=fixtures["port"], threads=4)`.

### 9.4 `lib.mjs`

Exports (contrat utilisé par `check.mjs` et `shoot.mjs`) :

- `pythonBin()` : `process.env.PYTHON`, sinon `<repo>/.venv/bin/python` s'il existe, sinon `python3`.
- `DEMO_DIR`, `PORT`, `BASE_URL` (`http://127.0.0.1:<PORT>`).
- `runSeed()` : `spawnSync(pythonBin(), ['scripts/ui/seed_demo.py', '--out', DEMO_DIR, '--port', String(PORT)], { cwd: REPO_ROOT, stdio: 'inherit' })` ; code ≠ 0 → `ToolError`. (`REPO_ROOT` = deux niveaux au-dessus de `scripts/ui/lib.mjs` ; tous les processus Python sont lancés avec `cwd: REPO_ROOT`.)
- `startServer()` : si `GET BASE_URL/health` répond déjà → `ToolError("port <PORT> occupé")` (jamais de test contre un serveur inconnu) ; lance `serve_demo.py`, attend `/health` = 200 (sondage toutes les 200 ms, délai 20 s) ; retourne `{ stop() }` (SIGTERM puis attente de la fin du processus).
- `loadFixtures()`, `loadScenes()`, `expandRuns(scenes, filters)` → liste de runs `{ scene, viewport, theme, lang }`.
- `resolvePath(path, placeholders)` : remplace `{clé}` ; clé inconnue → `ToolError`.
- `launchChrome()` : `CHROME_BIN` (défaut `google-chrome`) avec `--headless=new --no-sandbox --disable-gpu --hide-scrollbars --mute-audio --no-first-run --no-default-browser-check --remote-debugging-port=<UI_CDP_PORT, défaut 9333> --user-data-dir=<dossier temporaire neuf>` ; attend `/json/version`, se connecte au WebSocket navigateur (WebSocket natif de Node 22). `close()` : tue Chrome, **attend l'évènement `exit`**, puis supprime le dossier de profil avec `fs.rmSync(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 })` (des sous-processus de Chrome écrivent encore après `exit` : `ENOTEMPTY` sans relance).
- Client CDP minimal : `send(method, params, sessionId)`, abonnement aux évènements par `sessionId`.
- `openRun(cdp, run, fixtures)` : **contexte de navigation isolé par run** (`Target.createBrowserContext` → `Target.createTarget('about:blank')` → `Target.attachToTarget({ flatten: true })`) : cookies, stockage, cache et SW ne fuient jamais d'un run à l'autre. Puis, dans l'ordre : `Emulation.setDeviceMetricsOverride` (table viewports), `Emulation.setTouchEmulationEnabled({ enabled: width < 1024 })`, `Emulation.setEmulatedMedia({ features: [{ name: 'prefers-color-scheme', value: theme }, { name: 'prefers-reduced-motion', value: run.scene.reducedMotion === false ? 'no-preference' : 'reduce' }] })`, `Network.enable`, `Network.setUserAgentOverride({ userAgent, acceptLanguage: lang })` (la langue passe par `Accept-Language`, jamais par `?lang=` qui écrirait en session), `Network.setCookie({ name: 'session', value, url: BASE_URL })` si le rôle n'est pas `anonymous`, `Runtime.enable`, `Log.enable`, `Page.enable`, collecte console, `Page.navigate`, attente de `Page.loadEventFired` puis `document.fonts.ready` et deux `requestAnimationFrame`, puis exécution des actions. `close()` : `Target.disposeBrowserContext`.
- CLI : `node scripts/ui/lib.mjs seed` → `runSeed()` ; `node scripts/ui/lib.mjs serve` → `runSeed()` **systématiquement** (une graine ancienne serait en partie purgée par `create_app` : événement non vérifié de plus de 3 jours), puis serveur au premier plan jusqu'à Ctrl-C.

Viewports :

| Largeur | Hauteur | `deviceScaleFactor` | `mobile` |
|---|---|---|---|
| 360 | 800 | 2 | true |
| 390 | 844 | 2 | true |
| 820 | 1180 | 2 | true |
| 1280 | 800 | 1 | false |

**Évaluations CDP (règle unique)** : toute évaluation de code dans la page (actions `waitFor`, `assert`, mesures, fonction d'audit) passe par un seul helper `evaluate(session, expression, timeoutMs)` qui appelle `Runtime.evaluate({ expression: "Promise.race([Promise.resolve().then(() => (" + expression + ")), new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), " + timeoutMs + "))])", awaitPromise: true, returnByValue: true })`. Une promesse est donc toujours attendue, avec un délai explicite (défaut 5000 ms pour `assert`, durée de l'action pour `waitFor`, 10 000 ms pour la fonction d'audit). Résultat : la présence de `exceptionDetails` (exception ou délai dépassé) est un échec ; pour `assert` et `waitFor`, **seule la valeur booléenne `true` stricte** (`result.type === "boolean" && result.value === true`) compte comme succès — un objet (y compris `{}`, ce que renvoie une promesse non attendue), `undefined` ou une valeur « truthy » non booléenne est un échec avec le message « valeur non booléenne : <type> ». Les expressions des scènes doivent donc renvoyer un booléen.

Console collectée (= échec du contrôle `console`) : `Runtime.consoleAPICalled` de type `error`, `warning`, `assert` ; `Runtime.exceptionThrown` ; `Log.entryAdded` de niveau `error` ou `warning` (ressources en échec, violations CSP, dépréciations).

### 9.5 `scenes.json` — format

```json
{
  "defaults": { "viewports": [360, 390, 820, 1280], "themes": ["light", "dark"], "langs": ["fr"], "scope": "shell" },
  "scenes": [
    {
      "id": "planning",
      "lot": "B017",
      "role": "guest_household",
      "path": "/e/{event.rich}/planning",
      "scope": "shell",
      "expect": { "nav": "event" },
      "langs": ["fr", "en"],
      "actions": [],
      "skip": []
    }
  ]
}
```

Champs : `id` (kebab-case, unique, stable), `lot` (dernier lot ayant créé/modifié la scène), `role` ∈ `fixtures.roles`, `path` (avec `{placeholders}`), `scope` ∈ {`shell`, `page`}, `expect.nav` ∈ {`event`, `global`, `none`}, `viewports`/`themes`/`langs` (surchargent `defaults`), `actions` (liste ordonnée), `skip` (liste d'identifiants de contrôles désactivés pour cette scène, **chacun justifié** par un champ `note` obligatoire quand `skip` n'est pas vide), `reducedMotion` (booléen, défaut `true` : `prefers-reduced-motion: reduce` émulé pour des mesures stables ; `false` pour exercer les animations), `expectFail` et `forceLang` (réservés aux scènes d'auto-contrôle, §9.10).

Actions :

| `type` | Paramètres | Effet |
|---|---|---|
| `click` | `target` (sélecteur `[data-testid=…]` ou rôle ARIA) | `scrollIntoView`, clic souris réel (`Input.dispatchMouseEvent` pressed/released au centre), puis 2 rAF + 250 ms |
| `press` | `key` ∈ {`Escape`, `Tab`, `Enter`} | `Input.dispatchKeyEvent` keyDown/keyUp |
| `scroll` | `to` ∈ {`top`, `bottom`} | `window.scrollTo` + 2 rAF |
| `wait` | `ms` (≤ 2000) | pause |
| `waitFor` | `expr`, `timeout` (défaut 5000) | évalue `expr` (helper `evaluate`, promesse attendue) toutes les 100 ms jusqu'à obtenir `true` strict ; délai total dépassé → échec `assert` « waitFor : délai dépassé » |
| `reload` | — | `Page.reload` + attente du chargement |
| `navigate` | `path` | navigation (placeholders résolus) + attente |
| `offline` | — | `Network.emulateNetworkConditions({ offline: true, latency: 0, downloadThroughput: -1, uploadThroughput: -1 })` sur la session de page **et** sur chaque cible `service_worker` du contexte (`Target.getTargets`, filtre `browserContextId`, `attachToTarget({ flatten: true })`, `Network.enable`). Vérifié : l'émulation sur la seule page ne coupe pas les requêtes du SW |
| `assert` | `expr`, `message`, `timeout` (défaut 5000) | évalue `expr` (helper `evaluate`) ; tout résultat autre que `true` strict, une exception ou un délai dépassé → échec du contrôle `assert` avec `message` |

**Portée** : `shell` = les contrôles d'éléments ne portent que sur les descendants de `[data-ui-shell]` (pages historiques pas encore migrées) ; `page` = tout le document. Les contrôles `hscroll`, `console`, `nav` et `assert` portent toujours sur toute la page.

**Ajout de scènes par les lots suivants** : chaque lot qui réécrit une page passe sa scène en `"scope": "page"`, met à jour `lot`, et ajoute les scènes d'interaction nécessaires (feuilles, formulaires en erreur, états vides) ; aucun lot ne supprime une scène ; une exception (§9.8) n'est permise qu'avec le lot qui la résoudra ; B028 exige que toutes les scènes soient en portée `page` et que `exceptions.json` soit `[]`.

### 9.6 Scènes initiales (B017)

Toutes avec `lot: "B017"` et les `defaults` sauf mention. Total : **32 scènes, 280 runs** (scènes × largeurs × thèmes × langues : 275 pour les 30 premières, + 4 pour `sheet-toast`, + 1 pour `more-sheet-motion`). Les 7 scènes d'auto-contrôle (§9.10) sont à part.

| id | rôle | chemin | portée | langs | nav | actions / particularités |
|---|---|---|---|---|---|---|
| `catalog` | anonymous | `/_ui` | page | fr, en | global | `skip: ["primary"]`, `note`: « le catalogue montre volontairement chaque variante » |
| `landing` | anonymous | `/` | shell | fr, en | global | |
| `admin-login` | anonymous | `/admin/login` | shell | fr | global | |
| `events-index` | creator | `/e/` | shell | fr, en | global | |
| `join` | anonymous | `/e/{event.rich}/join` | shell | fr, en | global | |
| `event-home-creator` | creator | `/e/{event.rich}` | shell | fr, en | event | |
| `event-home-guest` | guest_household | `/e/{event.rich}` | shell | fr | event | |
| `event-home-solo` | guest_solo | `/e/{event.rich}` | shell | fr | event | |
| `planning` | guest_household | `/e/{event.rich}/planning` | shell | fr, en | event | |
| `meals` | guest_household | `/e/{event.rich}/meals` | shell | fr | event | |
| `lists` | guest_household | `/e/{event.rich}/lists` | shell | fr | event | |
| `list-detail` | guest_household | `/e/{event.rich}/lists/{list.rich}` | shell | fr | event | |
| `costs` | guest_household | `/e/{event.rich}/costs` | shell | fr | event | |
| `voting` | guest_household | `/e/{event.rich}/voting` | shell | fr | event | |
| `logistics` | guest_household | `/e/{event.rich}/logistics` | shell | fr | event | |
| `chat` | guest_household | `/e/{event.rich}/chat` | shell | fr | event | |
| `media` | guest_household | `/e/{event.rich}/media` | shell | fr | event | |
| `members` | creator | `/e/{event.rich}/members` | shell | fr | event | |
| `invite` | creator | `/e/{event.rich}/invite` | shell | fr | event | |
| `log` | guest_household | `/e/{event.rich}/log` | shell | fr | event | |
| `event-empty` | creator | `/e/{event.empty}` | shell | fr | event | |
| `event-full` | creator | `/e/{event.full}` | shell | fr | event | |
| `event-unverified` | anonymous | `/e/verify/{token.unverified}` | shell | fr | global | page de vérification (`events.verify`) — jamais une page `/e/<code>/…` d'un événement non vérifié (404 après B029) |
| `verify-sent` | anonymous | `/e/new/sent/{event.unverified}` | shell | fr | global | page « e-mail envoyé » (`events.verify_sent`), valide avant et après B029 |
| `event-past` | creator | `/e/{event.past}` | shell | fr | event | |
| `event-long-title` | creator | `/e/{event.long}` | shell | fr | event | `assert` : `(e => e.scrollWidth > e.clientWidth && e.getBoundingClientRect().right <= innerWidth)(document.querySelector('[data-testid=header-event-title]'))`, message « titre long tronqué par CSS dans la largeur » |
| `more-sheet` | guest_household | `/e/{event.rich}/chat` | shell | fr | event | viewports [360, 390, 820] ; `click [data-testid=tab-more]` ; `assert document.querySelector('[data-testid=more-sheet]').open` ; `assert document.querySelector('[data-testid=more-sheet]').contains(document.activeElement)` (focus dans la feuille) ; `assert document.querySelector('[data-testid=more-item-chat]').getAttribute('aria-current') === 'page'` ; `press Escape` ; `assert !document.querySelector('[data-testid=more-sheet]').open` ; `assert document.activeElement === document.querySelector('[data-testid=tab-more]')` (retour du focus) |
| `privacy-sheet` | anonymous | `/` | shell | fr, en | global | viewports [390, 1280] ; `click [data-testid=footer-privacy]` ; `assert document.querySelector('[data-testid=privacy-sheet]').open` (les contrôles s'exécutent feuille ouverte) |
| `confirm-dialog` | anonymous | `/_ui` | page | fr | global | viewports [390, 1280] ; `skip: ["primary"]` (même note que `catalog`) ; `click [data-testid=catalog-confirm-trigger]` ; `assert document.querySelector('[data-testid=confirm-dialog]')?.open` ; `assert document.activeElement === document.querySelector('[data-testid=confirm-cancel]')` |
| `sheet-toast` | anonymous | `/_ui` | page | fr | global | viewports [390, 1280] ; `skip: ["primary"]` (même note que `catalog`) ; `click [data-testid=catalog-sheet-trigger]` ; `click [data-testid=catalog-sheet-copy]` ; `waitFor` (2000 ms) `(() => { const t = [...document.querySelectorAll('.ui-toast')].pop(); if (!t) return false; const r = t.getBoundingClientRect(); const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return t.contains(el); })()` (« toast visible et au-dessus de la feuille ouverte ») |
| `more-sheet-motion` | guest_household | `/e/{event.rich}/chat` | shell | fr | event | viewports [390], themes [light], `reducedMotion: false` ; mêmes actions que `more-sheet` (animations réelles exercées), puis `click [data-testid=tab-more]`, `click [data-testid=more-item-privacy]`, `assert document.querySelector('[data-testid=privacy-sheet]').open && !document.querySelector('[data-testid=more-sheet]').open` |
| `pwa-offline` | guest_household | `/e/{event.rich}` | page | fr | none | viewports [390], themes [light] ; `waitFor navigator.serviceWorker.ready.then(() => true)` (promesse attendue, §9.4) ; `reload` ; `assert navigator.serviceWorker.controller !== null` (« le SW contrôle la page ») ; `offline` ; `navigate /e/{event.rich}/planning` ; `assert document.querySelector('[data-testid=offline-page]') !== null` (« page hors ligne servie ») |

### 9.7 Contrôles de la garde (`check.mjs`)

Fonction d'audit exécutée dans la page (sérialisée par `Function.prototype.toString`). « Visible » = `display ≠ none`, `visibility ≠ hidden`, opacité calculée cumulée > 0, aire > 0, pas dans un `<dialog>` fermé ni sous `[hidden]`/`[inert]`, et rectangle intersectant le viewport (le lien d'évitement hors écran est ainsi ignoré). « Dans la portée » = §9.5.

| Id | Règle | Seuil / détail |
|---|---|---|
| `hscroll` | `document.documentElement.scrollWidth <= innerWidth` | tolérance 0 ; message : 5 premiers éléments dont `getBoundingClientRect().right > innerWidth + 1` (hors `position: fixed`), sélecteur court |
| `console` | aucune entrée console collectée (§9.4) | liste des messages |
| `nav` | `expect.nav` = `event`/`global` et largeur < 1024 : `[data-testid=nav-bottom]` visible, `position: fixed`, `data-context` = attendu, `|rect.bottom − innerHeight| ≤ 1` mesuré en haut de page **et** après défilement en bas ; **et, après défilement en bas, aucun recouvrement** : `main-content.getBoundingClientRect().bottom ≤ nav-bottom.top + 1` et, si `[data-testid=site-footer]` existe, `site-footer.bottom ≤ nav-bottom.top + 1` (le pied de page et `footer-privacy` restent visibles et cliquables au-dessus de la barre) ; largeur ≥ 1024 : `nav-bottom` non affiché et `[data-testid=nav-desktop]` visible avec `data-context` = attendu ; `none` : ni l'un ni l'autre visible **et** `getComputedStyle(document.body).paddingBottom === '0px'` (aucune réserve de barre sur une page sans barre, ex. `/offline`) | |
| `targets` | éléments `a[href]`, `button`, `input:not([type=hidden])`, `select`, `textarea`, `summary`, `[role=button]`, `[role=tab]`, `[role=switch]`, `[tabindex]:not([tabindex="-1"])` visibles : largeur ≥ 44 et hauteur ≥ 44 (tolérance 0,5 px) | exemptions : lien en ligne (`display: inline` dont le parent bloc contient d'autres nœuds texte non vides) ; `input` case/radio dont le `<label>` associé mesure ≥ 44 × 44 ; éléments `:disabled`/`[aria-disabled=true]` |
| `contrast-text` | pour chaque élément visible ayant un nœud texte direct non vide : ratio(couleur, fond effectif) ≥ 4,5 ; ≥ 3 si texte grand (`font-size ≥ 24px`, ou `≥ 18.66px` et graisse ≥ 700) | fond effectif = composition alpha des `background-color` des ancêtres jusqu'au fond de `html`/`body` (blanc si transparent partout) ; ignorés : éléments désactivés, `aria-hidden`, ancêtre avec `background-image` (signalés en `skipped` dans le rapport, pas en échec) |
| `contrast-ui` | `input` (hors hidden/submit/button), `select`, `textarea`, `[role=switch]`, `.ui-check input`, `.ui-radio input` visibles : bordure ≥ 1 px → ratio(couleur de bordure, fond du parent) ≥ 3 ; sinon ratio(fond de l'élément, fond du parent) ≥ 3 | |
| `labels` | chaque `input` (hors `hidden`, `submit`, `button`, `reset`, `image`), `select`, `textarea` visible a un nom accessible : `<label for>`, `<label>` englobant, `aria-label` ou `aria-labelledby` non vides (placeholder exclu) | |
| `names` | chaque `a[href]`, `button`, `[role=button]` visible a un nom accessible non vide (texte, `aria-label`, `aria-labelledby`, `title` d'image enfant ou `alt`) | |
| `img-alt` | chaque `img` a un attribut `alt` (vide autorisé) ; chaque `svg` visible a `aria-hidden="true"` ou `role="img"` + nom | |
| `h1` | portée `page` : exactement un `h1` visible dans le document ; portée `shell` : aucun `h1` dans `[data-ui-shell]` | |
| `primary` | portée `page` : au plus un `.ui-btn--primary` visible dans `main` | |
| `lang-fr` | langue `en` seulement : aucun texte français dans la portée. Texte examiné : `innerText` des éléments de la portée + attributs `aria-label`, `title`, `placeholder`, `alt` ; exclus : éléments sous `[translate="no"]` ou sous un `[lang]` dont la langue n'est pas `en`. Détection : (a) présence d'un msgid de `translations/en/LC_MESSAGES/messages.po` dont `msgstr` est non vide et différent du msgid, sans `%` ni `{`, de longueur ≥ 4, recherché en mot entier sensible à la casse ; (b) tout mot contenant une lettre de `àâçéèêëîïôûùüÿœæ` (majuscules incluses) | message : extraits fautifs |
| `assert` | actions `assert`/`waitFor` de la scène | message de l'action |

**Contenu utilisateur** : tout élément affichant une donnée saisie par un utilisateur (titre d'événement, nom de participant…) porte `translate="no"` (attribut HTML standard). Règle obligatoire pour tous les lots.

**Sortie** (stdout), une ligne par run en échec, puis un résumé :

```
FAIL planning 360x800 dark en [lang-fr] « Planning » … extrait : "Rejoindre"
FAIL lists 360x800 light fr [hscroll] scrollWidth 512 > 360 : section.meal-chips, …
EXCEPTED lists 390x844 light fr [hscroll] (B023 : …)
ui:check — 272 runs, 2 échecs, 1 exception, 0 erreur d'outil — rapport : /tmp/holishared-ui/check/report.json
```

`report.json` : `{ runs: [{ id, scene, viewport, theme, lang, url, results: { <check>: { ok, details[] } } }], summary }`. Codes de sortie : `0` tout vert ; `1` au moins un échec non excepté ou une exception inutilisée ; `2` erreur d'outil (seed, serveur, Chrome, placeholder inconnu, JSON invalide).

Options CLI : `--scenes a,b` `--viewports 360,1280` `--themes dark` `--langs en` (filtres), `--out DIR`, `--shots` (enregistre aussi la capture de chaque run en échec dans `--out`), `--no-server` (utilise un serveur déjà lancé par `npm run ui:serve` et le `fixtures.json` existant ; sans cette option, `check.mjs` exécute `runSeed()` + `startServer()` et arrête le serveur à la fin, y compris en cas d'erreur).

**Pas de mode `--update`** : la garde ne compare pas à des captures de référence (pas de baseline à régénérer) ; le seul mécanisme d'acceptation est `exceptions.json`.

### 9.8 `exceptions.json`

Tableau d'objets `{ "scene": "lists", "check": "hscroll", "viewport": 360 | "*", "theme": "light" | "*", "lang": "fr" | "*", "match": "<sous-chaîne du détail>", "reason": "<justification>", "lot": "B023" }`, tous champs obligatoires. Un échec qui correspond à une entrée est affiché `EXCEPTED` et ne fait pas échouer ; une entrée qui ne correspond à aucun échec fait échouer (code 1 : « exception inutilisée »). Valeur livrée par B017 : `[]` (toute entrée ajoutée pendant B017 doit être validée par l'audit du code).

### 9.9 `shoot.mjs`

Mêmes runs et filtres que la garde (`--scenes`, `--viewports`, `--themes`, `--langs`, `--no-server`), sortie `--out` (défaut `<tmp>/holishared-ui/shots`). Fichiers `<scene>__<largeur>__<theme>__<lang>.png` (capture du viewport après les actions, ce qui montre la barre fixe à sa vraie place) ; `--full` : page entière (`captureBeyondViewport`, hauteur plafonnée à 6000 px). Écrit `index.json` (liste des fichiers et URL). Code 0, ou 2 en erreur d'outil.


### 9.10 Auto-contrôle de la garde (`npm run ui:selftest`)

But : prouver que la garde sait échouer (une garde qui passe toujours est sans valeur). `check.mjs --self-test` exécute **uniquement** `scripts/ui/selftest-scenes.json` (même format que §9.5, champ `expectFail` obligatoire, exceptions ignorées) contre le serveur de démo, et réussit (code 0) si et seulement si, pour chaque run, l'ensemble des contrôles en échec est **exactement** `expectFail` ; sinon code 1 avec la ligne `SELFTEST <scene> attendu [<ids>] obtenu [<ids>]`. Scènes livrées (toutes : viewport [390], thème [light], langue [fr], `lot: "B017"`) :

| id | rôle | chemin | portée | nav | actions | `expectFail` |
|---|---|---|---|---|---|---|
| `selftest-pass` | anonymous | `/_ui` | page | global | `skip: ["primary"]` (note : catalogue) | `[]` (témoin positif) |
| `selftest-assert-false` | anonymous | `/` | shell | global | `assert document.title === '__jamais__'` | `["assert"]` |
| `selftest-unresolved-promise` | anonymous | `/` | shell | global | `assert new Promise(() => {})` avec `timeout: 500` (promesse jamais résolue : délai dépassé, et non objet vide vu comme vrai) | `["assert"]` |
| `selftest-promise-false` | anonymous | `/` | shell | global | `waitFor Promise.resolve(false)` avec `timeout: 500` | `["assert"]` |
| `selftest-non-boolean` | anonymous | `/` | shell | global | `assert document.body` (objet « truthy » non booléen) | `["assert"]` |
| `selftest-wrong-nav` | anonymous | `/` | shell | **event** (volontairement faux) | — | `["nav"]` |
| `selftest-lang-fr` | anonymous | `/` | shell | global | `"forceLang": "fr-content"` : page servie en français, contrôles exécutés comme pour une page EN | `["lang-fr"]` |

Pour `selftest-lang-fr`, le champ `forceLang` (réservé à l'auto-contrôle) vaut `"fr-content"` : `openRun` envoie `Accept-Language: fr` et la fonction d'audit reçoit `lang = "en"`. Le shell FR (« Accueil », « Créer ») doit alors être détecté comme texte français.

L'étape CI « Auto-contrôle de la garde » (§2.5) précède « Garde UI ».

---

## 10. Commits atomiques (ordre de réalisation)

Chaque commit passe `ruff check . && ruff format --check . && mypy app/ && pytest` (les tests B017 sont commités avec le commit qui les fait passer : jamais de commit rouge). Le CSS compilé est régénéré et commité dans chaque commit qui le concerne. Messages terminés par la ligne d'attribution en vigueur.

1. `chore(infra): build Tailwind v4 et isolation du CSS historique` — `package.json` (scripts `build:css`, `watch:css` seulement), `package-lock.json`, `app/static/src/app.css` (+ `theme.css`, `base.css`, `components.css` sans règles), `git mv` de `main.css` → `src/legacy.css`, `app/static/css/app.css`, lien de `base.html` vers `css/app.css` (par `url_for`), job CI `frontend` (étape CSS seulement), `.dockerignore`. Tests : T45, T46, T56.
2. `feat(css): design tokens, couche base et composants ui-*` — `theme.css`, `base.css`, `components.css` (toutes les classes du §5, y compris celles du shell §5.15), `app/icons.py`, `app/ui.py` (`asset_hash`, `asset_url`, `icon`, `init_ui`), `_components/ui.html`, `_components/theme_script.html`, CSS recompilé. Tests : T47–T55, T57–T66.
3. `chore(i18n): chaînes du shell, du catalogue et de la page hors ligne` — `.pot`, `.po` FR/EN, `.mo`, dictionnaire `T` de `scripts/translate_en.py` (procédure §11.4), correction de « Créer ». Aucun test propre (T39 importe `JS_STRINGS`, créé au commit 4 : il est rattaché au commit 4).
4. `feat(css): shell responsive, navigation, modules JS partagés et migration des hooks` — `base.html` réécrit (sans l'attribut `data-sw`, ajouté au commit 6 `feat(pwa)`), `app/ui.py` (`PRIMARY_ORDER`, `nav_section`, `build_nav`, `JS_STRINGS`, `ui_strings`, `ui_importmap`), `event_role` dans `inject_globals`, `app/static/js/ui/*.js` sauf `pwa.js` (`main.js` n'importe pas encore `ui/pwa`), suppression d'`alpine.min.js`, **dans le même commit** la migration de `dashboard.html`, `members.html` (y compris le correctif de sécurité) et `invite.html` (§7.12) — sinon, entre la suppression du JS inline de `base.html` et la migration, les codes s'afficheraient en clair et « Copier » serait inopérant —, `tests/conftest.py` (fixtures), `tests/ui_helpers.py`, adaptation de `tests/test_module_gating.py`. Tests : T01–T39, T42, T43, T43a, T44a–T44e, et T84f (fichier `tests/test_pwa.py`, créé à ce commit avec ce seul test).
5. `refactor(costs): confirmations via data-confirm` — `costs/index.html`. Tests : T40, T41.
6. `feat(pwa): service worker racine, page hors ligne et manifest` — routes `/sw.js` et `/offline`, `templates/sw.js`, `main/offline.html`, `pwa.js` (+ import et `initPwa()` dans `main.js`), `SW_ENABLED` et attribut `data-sw` de `base.html`, `manifest.json`, suppression de `service-worker.js`, `.env.example`. Tests : T67–T84e.
7. `feat(css): catalogue de composants /_ui` — route, gabarit, `UI_CATALOG_ENABLED`, `.env.example`. Tests : T85–T90.
8. `feat(infra): outillage UI (graine, serveur de démo, captures, garde, auto-contrôle)` — `scripts/ui/*` (dont `selftest-scenes.json`), scripts npm `ui:*`, étapes CI « Auto-contrôle de la garde » et « Garde UI », déclencheurs `ui/**` du workflow. Tests : T91–T101b ; `npm run ui:selftest` à 0.
9. `fix(css): débordements horizontaux des pages historiques (N2)` — corrections §2.6 révélées par `npm run ui:check`, CSS recompilé.
10. `chore: close lot B017` — `CHANGELOG.md`, `TASKS.md` (B017 ✅), `DEV_LOG.md`.

---

## 11. Plan de tests

### 11.1 Fixtures et helpers ajoutés

`tests/conftest.py` (ajouts, rien de modifié dans l'existant) :

- `creator_client(client, creator)` : pose `_user_id` = `creator.id` et `_fresh` = `True` en session ; renvoie `client`.
- `guest_client(client, event, guest)` : pose `guest_<event.code>` = `guest.id` ; renvoie `client`.
- `app_factory(monkeypatch)` : renvoie `build(env: dict[str, str]) -> Flask` qui pose les variables (`DATABASE_URL=sqlite:///:memory:` par défaut + `env`), appelle `create_app()`, met `TESTING=True`, `WTF_CSRF_ENABLED=False`, pousse un `app_context`, exécute `db.create_all()` ; au démontage : `db.drop_all()` et retrait des contextes poussés.

`tests/ui_helpers.py` (fonctions pures, importées par `from ui_helpers import …` ; pytest ajoute `tests/` au `sys.path`) :

- `tag(html, testid) -> str` : balise ouvrante du premier élément `data-testid="<testid>"` (regex `<[^>]*\bdata-testid="<testid>"[^>]*>`) ; `AssertionError` si absent.
- `block(html, testid, element) -> str` : de la balise ouvrante `<element … data-testid="<testid>"` jusqu'au premier `</element>` suivant.
- `testids(fragment, prefix) -> list[str]` : `data-testid` commençant par `prefix`, dans l'ordre du document.
- `text_of(html, testid, element) -> str` : contenu texte (balises retirées, espaces normalisés) de `block(html, testid, element)`.

Convention de nommage : `test_<comportement>_<condition>_<résultat>`, un assert par test.

**Compatibilité B029** (exécuté après B017, rend 404 tout événement non vérifié hors `verify`/`verify_sent`) : tout événement créé par un test ou une fixture de B017 renseigne `verified_at` ; aucun test ni scène de B017 n'ouvre une page `/e/<code>/…` d'un événement non vérifié. La fixture partagée `event` (existante, hors B017) relève de B029.

### 11.2 Liste des tests

**`tests/test_ui_shell.py`**

| # | Nom | Préparation | Assertion |
|---|---|---|---|
| T01 | `test_base_stylesheet_uses_fingerprinted_app_css` | `client.get("/")` | regex `href="/static/css/app\.css\?v=[0-9a-f]{10}"` trouvée |
| T02 | `test_base_does_not_reference_legacy_main_css` | `/` | `"main.css"` absent du HTML |
| T03 | `test_base_viewport_meta_has_viewport_fit_cover` | `/` | `"viewport-fit=cover"` présent |
| T04 | `test_theme_script_precedes_stylesheet_in_head` | `/` | index de `setAttribute('data-theme'` < index de `css/app.css` |
| T05 | `test_base_has_single_module_script` | `/` | `html.count('type="module"') == 1` |
| T06 | `test_importmap_lists_every_ui_module` | `/` ; JSON du `<script type="importmap">` | `set(imports) == {"ui/" + p.stem for p in Path("app/static/js/ui").glob("*.js")}` |
| T07 | `test_base_has_importmap_and_no_inline_event_handlers` | `/` | `'type="importmap"' in html and not re.search(r'\son[a-z]+="', html)` |
| T08 | `test_htmx_script_is_deferred_and_fingerprinted` | `/` | regex `<script src="/static/js/htmx\.min\.js\?v=[0-9a-f]{10}" defer>` trouvée |
| T09 | `test_landing_bottom_nav_has_global_context` | `/` anonyme | `'data-context="global"'` dans `tag(html, "nav-bottom")` |
| T10 | `test_landing_bottom_nav_has_no_event_tabs` | `/` anonyme | `testids(block(html,"nav-bottom","nav"), "tab-") == ["tab-landing", "tab-create"]` |
| T11 | `test_global_nav_shows_events_tab_for_authenticated_creator` | `creator_client.get("/")` | `testids(block(...), "tab-") == ["tab-landing", "tab-create", "tab-events"]` |
| T12 | `test_event_page_bottom_nav_has_event_context_for_creator` | `creator_client.get(f"/e/{code}")` | `'data-context="event"'` dans `tag(html, "nav-bottom")` |
| T13 | `test_event_page_bottom_nav_has_event_context_for_guest` | `guest_client.get(f"/e/{code}")` | idem |
| T14 | `test_join_page_uses_global_nav_for_anonymous` | anonyme `/e/{code}/join` | `'data-context="global"'` dans `tag(html, "nav-bottom")` |
| T15 | `test_bottom_nav_order_with_all_modules_enabled` | `guest_client` `/e/{code}` | `testids(block(...,"nav-bottom","nav"), "tab-") == ["tab-home","tab-planning","tab-meals","tab-lists","tab-costs","tab-more"]` |
| T16 | `test_bottom_nav_promotes_secondary_modules_when_primary_disabled` | `app_factory({"ENABLED_MODULES": "planning,voting,chat"})`, créateur + événement créés dans le test (avec `verified_at=datetime.utcnow()`), client créateur, `GET /e/{code}/planning` | tabs `== ["tab-home","tab-planning","tab-voting","tab-chat","tab-more"]` |
| T17 | `test_bottom_nav_keeps_more_tab_when_no_module_enabled` | `app_factory({"ENABLED_MODULES": ""})`, créateur + événement créés dans le test (avec `verified_at=datetime.utcnow()`), client créateur, `GET /e/{code}/members` | tabs `== ["tab-home","tab-more"]` |
| T18 | `test_more_sheet_lists_remaining_modules_in_order` | `guest_client` `/e/{code}` ; `sheet = block(html,"more-sheet","dialog")` ; `PRIMARY_ORDER` importé de `app.ui` | `[t for t in testids(sheet,"more-item-") if t.removeprefix("more-item-") in PRIMARY_ORDER] == ["more-item-voting","more-item-logistics","more-item-chat","more-item-media"]` |
| T19 | `test_more_sheet_event_group_is_log_only_for_guest` | `guest_client` `/e/{code}` | `[t for t in testids(sheet,"more-item-") if t in ("more-item-participants","more-item-invite","more-item-log")] == ["more-item-log"]` |
| T20 | `test_more_sheet_hides_invite_for_guest` | idem | `"more-item-invite" not in testids(sheet,"more-item-")` |
| T21 | `test_more_sheet_shows_participants_and_invite_for_creator` | `creator_client` `/e/{code}` | `{"more-item-participants","more-item-invite"} <= set(testids(sheet,"more-item-"))` |
| T22 | `test_more_sheet_hides_account_items_for_guest` | `guest_client` | `"more-item-logout" not in testids(sheet,"more-item-")` |
| T23 | `test_active_tab_has_aria_current_on_planning_page` | `guest_client` `/e/{code}/planning` | `'aria-current="page"'` dans `tag(html,"tab-planning")` |
| T24 | `test_more_tab_marked_active_on_chat_page` | `guest_client` `/e/{code}/chat` | `'data-active="true"'` dans `tag(html,"tab-more")` |
| T25 | `test_more_item_has_aria_current_on_chat_page` | idem | `'aria-current="page"'` dans `tag(html,"more-item-chat")` |
| T26 | `test_more_tab_not_active_on_planning_page` | `/e/{code}/planning` | `'data-active="true"'` absent de `tag(html,"tab-more")` |
| T27 | `test_desktop_nav_lists_all_destinations_for_creator` | `creator_client` `/e/{code}` ; `block(html,"nav-desktop","nav")` | `testids(nav,"navlink-") == ["navlink-home","navlink-planning","navlink-meals","navlink-lists","navlink-costs","navlink-voting","navlink-logistics","navlink-chat","navlink-media","navlink-participants","navlink-invite","navlink-log","navlink-privacy","navlink-events","navlink-logout"]` |
| T28 | `test_desktop_nav_does_not_repeat_event_title` | `creator_client` `/e/{code}` | `event.title not in block(html,"nav-desktop","nav")` |
| T29 | `test_header_renders_full_long_event_title` | titre de l'événement remplacé par `"Réveillon " + "x" * 110` puis commit ; `creator_client` `/e/{code}` | `text_of(html,"header-event-title","a") == event.title` |
| T30 | `test_header_event_title_is_marked_translate_no` | `creator_client` `/e/{code}` | `'translate="no"'` dans `tag(html,"header-event-title")` |
| T31 | `test_identity_chip_has_guest_role_for_guest` | `guest_client` `/e/{code}` | `'data-role="guest"'` dans `tag(html,"identity-chip")` |
| T32 | `test_identity_chip_has_creator_role_for_creator` | `creator_client` `/e/{code}` | `'data-role="creator"'` dans `tag(html,"identity-chip")` |
| T33 | `test_identity_chip_absent_for_anonymous_visitor` | anonyme `/` | `'data-testid="app-header"' in html and 'data-testid="identity-chip"' not in html` |
| T34 | `test_flash_message_rendered_as_danger_toast` | anonyme `client.post("/e/access", data={"code": "x"}, follow_redirects=True)` | `'data-tone="danger"'` dans `tag(html,"toast")` |
| T35 | `test_footer_rendered_outside_event` | anonyme `/` | `'data-testid="site-footer"'` présent |
| T36 | `test_footer_absent_inside_event` | `creator_client` `/e/{code}` | `'data-testid="nav-bottom"' in html and 'data-testid="site-footer"' not in html` |
| T37 | `test_privacy_sheet_is_dialog_without_emoji` | anonyme `/` ; `sheet = block(html,"privacy-sheet","dialog")` | `not any(e in sheet for e in ("🛡", "🚫", "🍪", "🔐"))` |
| T38 | `test_landing_has_exactly_one_h1_with_new_shell` | anonyme `/` | `'data-testid="main-content"' in html and html.count("<h1") == 1` |
| T39 | `test_shell_msgids_have_english_translation` | `babel.messages.pofile.read_po` sur `translations/en/LC_MESSAGES/messages.po` ; liste `SHELL_MSGIDS` = tous les msgids des tableaux §11.4 (nouveaux et réutilisés) **+ `list(JS_STRINGS.values())`** (registre §7.2, importé de `app.ui`) | `[m for m in SHELL_MSGIDS if not translated(m)] == []` (traduit = présent, `string` non vide, pas `fuzzy`) |
| T40 | `test_templates_contain_no_native_confirm_call` | lecture de tous les `app/templates/**/*.html` | aucun fichier ne contient `confirm(` |
| T41 | `test_templates_contain_no_direct_clipboard_api` | idem | aucun fichier ne contient `navigator.clipboard` |
| T42 | `test_ui_strings_json_is_translated_in_english` | `client.get("/?lang=en")` ; JSON de `#ui-strings` | `data["copied"] == "Copied"` |
| T43 | `test_ui_strings_json_matches_registry` | `/` ; `JS_STRINGS` importé de `app.ui` | `set(data) == set(JS_STRINGS)` |
| T43a | `test_js_strings_registry_keys_follow_convention` | `JS_STRINGS` | `[k for k in JS_STRINGS if not re.fullmatch(r"[a-z][a-z0-9_]*", k)] == [] and {"copied","copy_failed","close","cancel","confirm","confirm_title","new_version","reload","show","hide","loading"} <= set(JS_STRINGS)` |
| T44a | `test_guest_dashboard_has_copy_hook_for_code` | `guest_client` `/e/{code}` | `f'data-copy="{guest.code}"'` présent |
| T44b | `test_guest_dashboard_code_is_masked_by_default` | `guest_client` `/e/{code}` | `'data-masked="true"'` présent |
| T44c | `test_members_remove_button_uses_data_confirm` | `creator_client` `/e/{code}/members` (fixture `guest` présente) | `"data-confirm="` présent |
| T44e | `test_members_page_hides_other_participant_codes_for_guest` | un second invité `Guest(code="autre123", display_name="Autre", event_id=event.id)` créé dans le test ; `guest_client.get(f"/e/{code}/members")` | `resp.status_code == 200 and "autre123" not in html` (échoue aujourd'hui : le gabarit rend le code de chaque participant) |

Paramétré (une assertion par cas) : T44d `test_nav_section_maps_endpoint_to_key[endpoint-attendu]` sur les paires du tableau §4.6 : (`None`, `None`), (`main.index`, `landing`), (`events.create`, `create`), (`events.verify_sent`, `create`), (`events.index`, `events`), (`events.dashboard`, `home`), (`events.members`, `participants`), (`events.invite`, `invite`), (`events.invite_qr`, `invite`), (`events.log`, `log`), (`planning.index`, `planning`), (`meals.index`, `meals`), (`media.gallery`, `media`), (`costs.index`, `costs`), (`events.guest_access`, `None`), (`auth.login`, `None`) → `nav_section(endpoint) == attendu`.

**`tests/test_ui_assets.py`**

| # | Nom | Assertion |
|---|---|---|
| T45 | `test_package_json_pins_tailwind_versions` | `json.load(package.json)["devDependencies"] == {"@tailwindcss/cli": "4.3.3", "tailwindcss": "4.3.3"}` |
| T46 | `test_source_css_imports_legacy_into_legacy_layer` | `'@import "./legacy.css" layer(legacy);'` dans `app/static/src/app.css` |
| T47 | `test_compiled_css_layers_appear_in_order` | dans `app/static/css/app.css`, indices de la première occurrence de `@layer legacy`, `@layer theme`, `@layer base`, `@layer components`, `@layer utilities` strictement croissants |
| T48 | `test_compiled_css_defines_dark_theme_tokens` | regex `\[data-theme=("?)dark\1\]\{[^}]*--color-canvas:#171512` trouvée |
| T49 | `test_compiled_css_contains_all_component_classes` | `[c for c in COMPONENT_CLASSES if f".{c}" not in css] == []`, avec `COMPONENT_CLASSES` = `ui-btn`, `ui-btn--primary`, `ui-btn--secondary`, `ui-btn--ghost`, `ui-btn--danger`, `ui-btn--sm`, `ui-btn--lg`, `ui-btn--icon`, `ui-btn--block`, `ui-card`, `ui-card--link`, `ui-card__link`, `ui-card__action`, `ui-card__title`, `ui-field`, `ui-label`, `ui-label__optional`, `ui-input`, `ui-select`, `ui-textarea`, `ui-help`, `ui-error`, `ui-segmented`, `ui-segmented__option`, `ui-check`, `ui-radio`, `ui-switch`, `ui-badge`, `ui-badge--neutral`, `ui-badge--primary`, `ui-badge--success`, `ui-badge--warning`, `ui-badge--danger`, `ui-badge--info`, `ui-empty`, `ui-skeleton`, `ui-sheet`, `ui-sheet--dialog`, `ui-sheet__panel`, `ui-sheet__header`, `ui-sheet__title`, `ui-sheet__body`, `ui-toast-region`, `ui-toast`, `ui-progress`, `ui-avatar`, `ui-list`, `ui-list__item`, `ui-list__link`, `ui-icon`, `ui-page-header`, `ui-link`, `ui-skip-link`, `ui-tab`, `ui-bottom-nav`, `ui-sidebar`, `ui-menu`, `ui-menu__item`, `ui-menu__heading`, `ui-identity`, `ui-offline`, `ui-form`, `ui-form--inline`, `ui-toast-stack`, `ui-dialog-actions` |
| T50 | `test_compiled_css_has_no_default_tailwind_palette` | `"--color-red-500" not in css` |
| T51 | `test_asset_url_appends_content_hash` | dans `app.test_request_context()` : `asset_url("css/app.css") == "/static/css/app.css?v=" + sha256(bytes).hexdigest()[:10]` |
| T52 | `test_asset_url_changes_when_file_content_changes` | `monkeypatch.setattr(app, "static_folder", str(tmp_path))`, fichier `a.css` écrit, URL 1 ; contenu changé + `os.utime` (mtime + 1 s) ; URL 2 → `url1 != url2` |
| T53 | `test_asset_url_raises_for_missing_file` | `pytest.raises(FileNotFoundError)` sur `asset_url("css/absent.css")` |
| T54 | `test_icon_renders_decorative_svg_by_default` | `'aria-hidden="true"' in str(icon("house"))` |
| T55 | `test_icon_with_label_renders_img_role` | `'role="img" aria-label="Fermer"' in str(icon("x", label="Fermer"))` |
| T56 | `test_static_css_dir_no_longer_contains_main_css` | `not Path("app/static/css/main.css").exists()` |
| T57 | `test_icon_unknown_name_raises_key_error` | `pytest.raises(KeyError)` sur `icon("inconnue")` |
| T58 | `test_icon_set_matches_specified_names` | `list(ICON_NAMES) == SPEC_ICON_NAMES` (liste §6, 71 noms canoniques dont `funnel` et `circle-question-mark`, même ordre) |
| T59 | `test_icon_label_is_html_escaped` | `'aria-label="&lt;b&gt;"' in str(icon("x", label="<b>"))` |
| T60 | `test_field_macro_links_help_and_error_with_describedby` | macro `field("title", "Titre", help="Aide", error="Erreur")` rendue via `app.jinja_env.get_template("_components/ui.html").module` dans un `test_request_context` | `'aria-describedby="f-title-help f-title-error"'` présent |
| T61 | `test_field_macro_sets_aria_invalid_when_error` | idem | `'aria-invalid="true"'` présent |
| T62 | `test_field_macro_omits_describedby_without_help_or_error` | `field("title","Titre")` | `"aria-describedby"` absent |
| T63 | `test_field_macro_label_targets_input_id` | `field("title","Titre")` | `'<label class="ui-label" for="f-title">' in out and 'id="f-title"' in out` |
| T64 | `test_field_macro_marks_optional_field` | `field("title","Titre")` (non requis) | `"(facultatif)"` présent |
| T65 | `test_sheet_macro_renders_labelled_dialog` | `{% call sheet("demo","Titre") %}x{% endcall %}` rendu par `app.jinja_env.from_string` (avec import de la macro) | `'aria-labelledby="demo-title"'` présent |
| T66 | `test_empty_state_macro_renders_title` | `empty_state("inbox","Rien ici")` | `'<p class="ui-empty__title">Rien ici</p>'` présent |

**`tests/test_pwa.py`**

| # | Nom | Assertion |
|---|---|---|
| T67 | `test_sw_route_returns_200` | `client.get("/sw.js").status_code == 200` |
| T68 | `test_sw_route_has_javascript_mimetype` | `resp.mimetype == "application/javascript"` |
| T69 | `test_sw_route_has_no_cache_header` | `resp.headers["Cache-Control"] == "no-cache"` |
| T70 | `test_sw_route_allows_root_scope` | `resp.headers["Service-Worker-Allowed"] == "/"` |
| T71 | `test_sw_cache_name_derived_from_asset_version` | dans un `test_request_context` : `f'"holishared-{asset_version()}"' in body` |
| T72 | `test_asset_version_changes_when_an_asset_hash_changes` | `monkeypatch` de `app.ui.asset_hash` renvoyant `"a"*10` puis `"b"*10` → versions différentes |
| T73 | `test_sw_precaches_fingerprinted_app_css` | `asset_url("css/app.css") in body` |
| T74 | `test_sw_precaches_offline_page` | `'"/offline"' in body` |
| T75 | `test_sw_does_not_precache_alpine` | `resp.status_code == 200 and "alpine" not in body` |
| T76 | `test_sw_handles_skip_waiting_message` | `"SKIP_WAITING" in body` |
| T77 | `test_sw_never_writes_runtime_cache` | `resp.status_code == 200 and "cache.put(" not in body` |
| T78 | `test_offline_page_returns_200` | `client.get("/offline").status_code == 200` |
| T79 | `test_offline_page_has_offline_testid` | `'data-testid="offline-page"' in html` |
| T80 | `test_offline_page_omits_creator_identity` | `creator_client.get("/offline")` : `resp.status_code == 200 and "Test Creator" not in html` |
| T81 | `test_offline_page_contains_no_csrf_token` | `creator_client.get("/offline")` : `resp.status_code == 200 and "csrf" not in html` |
| T82 | `test_offline_page_is_translated_in_english` | `client.get("/offline", headers={"Accept-Language": "en"})` : `"You are offline" in html` |
| T83 | `test_manifest_scope_id_and_start_url_are_root` | `(m["id"], m["scope"], m["start_url"]) == ("/", "/", "/")` |
| T84 | `test_manifest_has_no_orientation_lock` | `"orientation" not in m` |
| T84a | `test_manifest_declares_shortcuts` | `[s["url"] for s in m["shortcuts"]] == ["/e/", "/e/new"]` |
| T84b | `test_base_links_fingerprinted_manifest` | regex `rel="manifest" href="/static/manifest\.json\?v=[0-9a-f]{10}"` dans `/` |
| T84c | `test_base_marks_service_worker_enabled_by_default` | `'data-sw="on"' in html` |
| T84d | `test_base_marks_service_worker_disabled_by_config` | `app.config["SW_ENABLED"] = False` : `'data-sw="off"' in html` |
| T84e | `test_legacy_service_worker_file_removed` | `not Path("app/static/js/service-worker.js").exists()` |
| T84f | `test_alpine_asset_removed` | `not Path("app/static/js/alpine.min.js").exists()` |

**`tests/test_ui_catalog.py`**

| # | Nom | Assertion |
|---|---|---|
| T85 | `test_ui_catalog_returns_404_by_default` | `client.get("/_ui").status_code == 404` — **garde de non-régression** (voir §11.2 bis) |
| T86 | `test_ui_catalog_flag_defaults_to_false` | `app_factory({})` (sans `UI_CATALOG_ENABLED`, variable retirée par `monkeypatch.delenv(..., raising=False)`) : `app.config["UI_CATALOG_ENABLED"] is False` |
| T87 | `test_ui_catalog_flag_enabled_from_env` | `app_factory({"UI_CATALOG_ENABLED": "true"})` : `app.config["UI_CATALOG_ENABLED"] is True` |
| T88 | `test_ui_catalog_returns_200_when_enabled` | `app.config["UI_CATALOG_ENABLED"] = True` : statut 200 |
| T89 | `test_ui_catalog_renders_every_component_section` | `[k for k in CATALOG_KEYS if f'data-testid="catalog-{k}"' not in html] == []` (clés §5.16) |
| T90 | `test_ui_catalog_renders_every_icon` | `[n for n in ICON_NAMES if f'data-icon="{n}"' not in html] == []` |

**`tests/test_ui_tooling.py`** (chaque test isole l'environnement : `monkeypatch.setattr(os, "environ", os.environ.copy())` ; modules chargés depuis `scripts/ui/` par `importlib.util.spec_from_file_location`, `sys.path` complété par `monkeypatch.syspath_prepend("scripts/ui")` ; `seed(tmp_path)` appelé dans le test ; décodage des cookies par `URLSafeTimedSerializer` de l'application construite par `serve_demo.build_app(fixtures)` → `app.session_interface.get_signing_serializer(app).loads(cookie)`)

| # | Nom | Assertion |
|---|---|---|
| T91 | `test_seed_demo_writes_cookies_for_every_authenticated_role` | `set(fixtures["cookies"]) == {"creator","guest_household","guest_solo"}` |
| T92 | `test_seed_demo_creator_cookie_contains_only_login_keys` | `set(loads(cookies["creator"])) == {"_user_id","_fresh"}` |
| T93 | `test_seed_demo_guest_cookie_contains_only_guest_key` | `set(loads(cookies["guest_household"])) == {f"guest_{placeholders['event.rich']}"}` |
| T94 | `test_seed_demo_creates_every_event_kind` | `{k for k in placeholders if k.startswith("event.")} == {"event.rich","event.empty","event.full","event.unverified","event.past","event.long"}` |
| T95 | `test_seed_demo_full_event_reaches_guest_limit` | dans le contexte de l'app de démo : `can_add_guest(Event.query.filter_by(code=placeholders["event.full"]).one()) is False` |
| T96 | `test_seed_demo_unverified_event_has_no_verified_at` | `verified_at is None` |
| T97 | `test_seed_demo_long_event_title_exceeds_80_chars` | `len(title) > 80` |
| T98 | `test_seed_demo_writes_database_under_output_dir` | `Path(fixtures["database_path"]).is_relative_to(tmp_path)` |
| T99 | `test_seed_demo_refuses_output_inside_repository` | `pytest.raises(ValueError)` sur `seed(REPO_ROOT / "ui-demo")` |
| T100 | `test_serve_demo_disables_rate_limiter` | `monkeypatch.setattr(limiter, "enabled", True)` (restauré au démontage) puis `build_app(fixtures)` : `limiter.enabled is False` |
| T101 | `test_serve_demo_redirects_instance_path` | `build_app(fixtures).instance_path == fixtures["instance_path"]` |
| T101a | `test_serve_demo_enables_ui_catalog` | `build_app(fixtures).config["UI_CATALOG_ENABLED"] is True` |
| T101b | `test_serve_demo_disables_smtp` | `build_app(fixtures).config["SMTP_HOST"] == ""` |

Total : **114 fonctions de test** (shell 49 dont T44d paramétré, assets 22, PWA 24, catalogue 6, outillage 13), soit **129 éléments collectés** (T44d = 16 cas). Contrôle à l'étape 5 : `pytest tests/test_ui_shell.py tests/test_ui_assets.py tests/test_pwa.py tests/test_ui_catalog.py tests/test_ui_tooling.py --collect-only -q` liste 129 éléments.

### 11.2 bis TDD : tests qui doivent échouer avant le code

Règle (AGENTS.md, étape 3) : chaque test ci-dessus échoue avant l'implémentation. Les assertions négatives portent donc toujours sur une réponse valide du nouveau contrat (statut 200 ou présence d'un `data-testid` du nouveau shell) : T07, T33, T36, T38, T75, T77, T80, T81 ont été formulés ainsi pour ne pas passer sur l'ancien gabarit ou sur une page 404.

**Exception unique, reclassée en garde de non-régression : T85** (`/_ui` renvoie 404 par défaut). Justification : un drapeau désactivé par défaut est vert par nature (la route n'existe pas encore) ; ce test protège contre une activation accidentelle du catalogue en production une fois la route créée. **L'exigence « les tests doivent échouer » de l'étape 3 ne s'applique pas à T85** ; T88 (200 quand le drapeau est actif) porte la partie TDD.

**Non-régression** : toute la suite existante reste verte. En particulier, les tests i18n existants (`test_en_locale_translates`, `test_lang_persists_in_session`, `test_en_nav_translated`) imposent que le shell n'introduise aucune chaîne non traduite en EN (d'où T39) ; aucune chaîne du shell ne contient « Rejoindre » ni « Votre code ».

### 11.3 Tests existants modifiés

| Fichier / test | Assertion actuelle | Nouvelle assertion | Justification |
|---|---|---|---|
| `tests/test_module_gating.py::test_nav_hides_disabled_modules` | `nav = re.search(r'<ul class="nav-links">.*?</ul>', html, re.S).group(0)` puis `"Media" not in nav`, `"Frais" not in nav`, `"Planning" in nav`, `"Listes" in nav` | `nav = re.search(r'<nav[^>]*data-testid="nav-desktop".*?</nav>', html, re.S).group(0)` puis les **quatre mêmes** assertions sur `nav` ; le commentaire « Event nav is now in the main header (.nav-links) » devient « Navigation bureau : data-testid="nav-desktop" » | La classe `nav-links` disparaît avec l'ancien `base.html` ; les hooks de test doivent être des `data-testid`, jamais des classes (règle du programme). Le comportement vérifié (liens des modules désactivés absents, actifs présents) est inchangé. |

Aucun autre test existant n'est modifié ni supprimé.

### 11.4 Chaînes i18n

**Procédure** (ne pas lancer `scripts/extract_i18n.py`, qui réécrit le `.pot` en perdant les chaînes Python — corrigé en B018) : ajouter chaque nouveau msgid au `.pot`, au `.po` FR (`msgstr ""`) et au `.po` EN (traduction ci-dessous, sans drapeau `fuzzy`) ; ajouter les paires au dictionnaire `T` de `scripts/translate_en.py` ; corriger l'entrée existante « Créer » (actuellement `#, fuzzy` / `msgstr "Access"`) en `msgstr "Create"` sans `fuzzy` ; renseigner l'entrée existante « Créateur » (actuellement `msgstr ""`) en `msgstr "Creator"` — terme unique du rôle dans tout le programme (pastille d'identité B017, badge de `members.html`, libellés d'acteur de B018), au lieu d'introduire « Organisateur » ; le msgid `Retirer %(name)s ?` porte le drapeau `python-format` ; puis `pybabel compile -d translations` et commiter les `.mo`.

Nouveaux msgids :

| FR | EN |
|---|---|
| Événement | Event |
| Participants | Participants |
| Préférences | Preferences |
| Compte | Account |
| Aller au contenu | Skip to content |
| Thème sombre | Dark theme |
| Retirer %(name)s ? | Remove %(name)s? |
| Accueil holishared | holishared home |
| Notifications | Notifications |
| Annuler | Cancel |
| Confirmer | Confirm |
| Confirmer l'action | Confirm action |
| Copié | Copied |
| Copie impossible | Copy failed |
| Nouvelle version disponible | New version available |
| Recharger | Reload |
| Hors ligne | Offline |
| Vous êtes hors ligne | You are offline |
| Vérifiez votre connexion puis réessayez. | Check your connection and try again. |
| Réessayer | Try again |
| facultatif | optional |
| Catalogue de composants | Component catalog |
| (textes de démonstration du catalogue, choisis par le codeur) | (traduction obligatoire) |

Msgids réutilisés (doivent être traduits et non `fuzzy` ; inclus dans `SHELL_MSGIDS` de T39) : Créateur, Accueil, Planning, Repas, Listes, Frais, Plus, Sondages, Infos, Chat, Media, Inviter, Journal, Mes événements, Créer, Créer un événement, Déconnexion, Fermer, Navigation principale, Confidentialité, Confidentialité garantie, Voir, Masquer, Copier, Chargement…, et les 7 msgids de la feuille confidentialité (introduction + 3 titres + 3 textes, §4.9).

---

## 12. Critères d'acceptation et définition de terminé

### 12.1 Critères d'acceptation

1. **CA01** — `npm ci && npm run build:css` réussit sous Node 22 et `git diff --exit-code -- app/static/css/app.css` ne montre aucune différence.
2. **CA02** — `package.json` est exactement celui du §2.2 ; `package-lock.json` est commité ; aucune autre dépendance npm.
3. **CA03** — `app.css` compilé contient le CSS historique en couche `legacy`, avant `theme`, `base`, `components`, `utilities` (T46, T47) ; `app/static/css/main.css` n'existe plus et n'est référencé nulle part.
4. **CA04** — Les valeurs de tokens du §3 sont celles du CSS compilé ; la palette Tailwind par défaut est absente (T48, T50).
5. **CA05** — Le script de thème précède la feuille de style ; `data-theme` est posé avant le premier rendu ; le thème choisi persiste (clé `theme`) et suit le système sans choix explicite (F31).
6. **CA06** — `base.html` respecte §4.2–§4.3 : un seul `<script type="module">`, import map complète, aucun attribut `on*=`, aucun script inline hormis le script de thème, l'import map et le bloc JSON `#ui-strings` (T03–T08).
7. **CA07** — Contexte `event` : barre du bas = Accueil + 4 premiers modules activés de `PRIMARY_ORDER` + « Plus » toujours présent ; promotion des modules secondaires ; aucune entrée en double ; « Participants » et « Inviter » réservés au créateur (T15–T22).
8. **CA08** — État actif : `aria-current="page"` sur l'onglet, l'entrée de feuille et le lien bureau de la page courante ; `data-active="true"` sur « Plus » pour les pages de la feuille (T23–T26, T44d).
9. **CA09** — Contexte `global` : barre du bas (Accueil, Créer, Mes événements si authentifié) sous 1024 px, navigation d'en-tête au-dessus ; pied de page minimal (T09–T11, T14, T35) ; la barre fixe ne recouvre jamais le contenu ni le pied de page (réserve sur `body`, contrôle `nav`).
10. **CA10** — Bureau ≥ 1024 px en contexte `event` : barre latérale avec toutes les destinations dans l'ordre de T27, sans le titre de l'événement (N8) ; aucune barre du bas affichée (contrôle `nav`).
11. **CA11** — En-tête : titre d'événement complet tronqué par CSS seulement (N6, T29, scène `event-long-title`) ; bascule de langue identique à toutes les tailles (N7) ; pastille identité invité/créateur (T31–T33).
12. **CA12** — Pas de pied de page en contexte `event` (N5, T36) ; confidentialité accessible depuis la feuille « Plus », la barre latérale et le pied de page global, dans un `<dialog>` sans emoji (T37).
13. **CA13** — Feuilles et dialogues : focus piégé, Échap, retour du focus au déclencheur, fermeture au clic sur le fond, `aria-expanded` synchronisé (scènes `more-sheet`, `more-sheet-motion`, `privacy-sheet`, `confirm-dialog`) ; fermeture au fond limitée aux `dialog.ui-sheet`.
14. **CA14** — Toutes les classes du §5 existent dans le CSS compilé (T49) ; règle d'étanchéité §4.10 appliquée (dont `ui-form` neutralisant la règle historique `form`) ; macros `field`, `sheet`, `empty_state` conformes (T60–T66) ; toutes les cibles du shell et des composants ≥ 44 × 44 px (contrôle `targets`).
15. **CA15** — `/_ui` renvoie 404 sauf `UI_CATALOG_ENABLED=true` ; rend toutes les sections et icônes (T85–T90) ; la scène `catalog` passe tous les contrôles en clair et sombre, FR et EN, aux 4 largeurs.
16. **CA16** — Jeu d'icônes = 71 noms du §6 exactement, via `icon()` (T54–T59) ; aucun emoji dans le shell.
17. **CA17** — Modules JS du §7 présents avec l'API décrite ; plus aucun `confirm(` ni `navigator.clipboard` dans les gabarits ; gabarits du §7.12 migrés (T40–T44c) ; chaînes JS servies par le seul registre `JS_STRINGS` / `#ui-strings` / `t(key)`, avec le point d'extension du §7.2 (T43, T43a).
18. **CA18** — Messages flash rendus en toasts accessibles (piles vivantes `polite`/`assertive` persistantes, fermeture, auto-masquage 6 s suspendu au survol/focus pour success/info, persistants pour warning/danger) (T34) ; un toast émis pendant qu'une feuille est ouverte est visible et au-dessus d'elle (scène `sheet-toast`).
19. **CA19** — Formulaires : un second envoi est bloqué, le bouton d'envoi passe en état chargement, l'état est réinitialisé au retour arrière.
20. **CA20** — `/sw.js` servi à la racine avec `application/javascript`, `Cache-Control: no-cache`, `Service-Worker-Allowed: /`, nom de cache `holishared-<asset_version>`, précache des assets versionnés et de `/offline`, sans Alpine ni écriture de cache à l'exécution (T67–T77) ; scène `pwa-offline` verte (le SW contrôle la page et sert la page hors ligne).
21. **CA21** — `/offline` autonome, traduit, sans donnée de session (T78–T82) ; manifest conforme au §8.5 (T83–T84b) ; ancien SW et Alpine supprimés, ancienne inscription désinscrite par `pwa.js` (T84e, T84f).
22. **CA22** — Toute référence d'asset dans `base.html`, `offline.html` et le catalogue passe par `asset_url` (empreinte `?v=` de 10 hex) (T01, T08, T51–T53, T84b).
23. **CA23** — Nouvelles chaînes présentes en FR et EN, « Créer » corrigée, `.mo` recompilés (T39, T42) ; les scènes EN ne signalent aucun texte français dans leur portée (`lang-fr`).
24. **CA24** — Aucun défilement horizontal de page sur toutes les scènes B017 aux 4 largeurs, en clair et sombre (N2, N9 ; contrôle `hscroll`).
25. **CA25** — `scripts/ui/` conforme au §9 : graine (6 événements, 4 rôles, cookies minimaux), serveur de démo (limiteur désactivé, `instance_path` redirigé, SMTP vide, catalogue actif), runner de captures, garde avec codes 0/1/2 ; artefacts hors dépôt (T91–T101b).
26. **CA26** — `exceptions.json` livré vide (ou chaque entrée validée par l'audit du code avec son lot de résolution).
27. **CA27** — CI (inopérante tant que le dépôt n'a pas de remote ; la porte réelle est le §12.2) : jobs `test` et `frontend` dotés de `SECRET_KEY` et `SUPERADMIN_PASSWORD` factices ; workflow déclenché sur `main` **et `ui/**`** (push et pull_request), job `frontend` (CSS à jour, auto-contrôle de la garde, garde UI) ajouté, jobs `lint`/`test` inchangés hormis leurs déclencheurs.
28. **CA28** — `Dockerfile` et `nginx/saas.conf` inchangés ; `.dockerignore` complété (§2.7) ; CSP inchangée (seul le commentaire change) ; `.env.example` documente `UI_CATALOG_ENABLED` et `SW_ENABLED`.
29. **CA29** — Seul `test_module_gating.py::test_nav_hides_disabled_modules` est modifié, conformément au §11.3 ; aucun test supprimé.
30. **CA30** — `CHANGELOG.md`, `TASKS.md` (B017 ✅ avec date) et `DEV_LOG.md` mis à jour.
31. **CA31** — **Sécurité** : aucun invité ne reçoit dans le HTML le code personnel d'un autre participant (`members.html`, T44e) ; l'entrée « Participants » n'est proposée qu'au créateur (T19, T21, T27).
32. **CA32** — Garde : toute évaluation CDP attend les promesses avec délai explicite et n'accepte que `true` strict (§9.4) ; `npm run ui:selftest` renvoie 0, chaque scène d'auto-contrôle échouant exactement sur ses contrôles `expectFail` (§9.10).

### 12.2 Définition de terminé

```bash
ruff check . && ruff format --check .
mypy app/
pytest
npm ci && npm run build:css && git diff --exit-code -- app/static/css/app.css
npm run ui:selftest       # code de sortie 0
npm run ui:check          # code de sortie 0
```

Cette liste est **la porte réelle** du lot : le dépôt n'ayant pas de remote, la CI GitHub ne s'exécute pas ; chaque commande est lancée localement avant chaque commit et avant la clôture.

Plus : audit du code (étape 6) approuvé ; commit final `chore: close lot B017`.

---

## 13. Risques et points de vigilance

| Risque | Impact | Mesure |
|---|---|---|
| **Pages historiques sous le nouveau shell** : règles d'éléments nus du CSS historique qui fuient dans le shell, ou mise en page qui dépendait de `main.container` | Shell mal stylé, pages décalées | Règle d'étanchéité §4.10 ; contenu limité à 960 px comme avant ; garde sur toutes les pages (portée `shell` + `hscroll` + `console`) ; captures `npm run ui:shoot` avant/après pour revue visuelle |
| **Preflight absent** jusqu'à B028 | Les nouveaux composants ne peuvent pas compter sur un reset Tailwind | Reset historique (`* { margin:0; padding:0; box-sizing:border-box }`) toujours actif ; composants auto-suffisants (§4.10) ; B028 active le Preflight en supprimant `legacy` |
| **Débordements inconnus à 360 px** sur des pages historiques | Garde rouge, barre du bas mal placée | Corrections minimales autorisées (§2.6.3) ; `exceptions.json` réservé aux cas justifiés avec lot de résolution |
| **`dvh`** (Safari ≥ 15.4, Chrome ≥ 108, Firefox ≥ 101) | Hauteurs fausses sur navigateurs anciens | Déclaration `vh` placée avant chaque `dvh` (repli) |
| **`:has()`** (Firefox ≥ 121) | Défilement de fond non bloqué sous une feuille | Utilisé uniquement pour ce verrou de défilement (dégradation sans gravité) ; le lien étiré n'en dépend pas |
| **`color-mix()`** | — | Non utilisé (couleurs explicites) |
| **`<dialog>` / `showModal()`** (Safari ≥ 15.4) ; retour du focus natif variable | Focus perdu à la fermeture | Retour du focus fait explicitement par `dialog.js` ; contrôlé par la scène `more-sheet` |
| **Import maps** (Safari ≥ 16.4, Firefox ≥ 108) | Modules non chargés sur iOS < 16.4 | Navigation et formulaires restent fonctionnels sans JS (liens, envois natifs) ; seules les feuilles, copies et confirmations sont indisponibles |
| **iOS PWA** : mise à jour du SW au retour au premier plan, safe areas | Ancienne version affichée, barre sous l'indicateur d'accueil | Toast « Nouvelle version disponible » ; `viewport-fit=cover` + `env(safe-area-inset-*)` sur en-tête, barre, feuilles, toasts |
| **Cache SW périmé** (incident 7b05bb0) | CSS obsolète servi | Assets uniquement en URL versionnée (cache d'abord sûr), nom de cache dérivé du contenu, `/sw.js` en `no-cache`, suppression des caches `holishared-*` obsolètes, désinscription de l'ancien SW `/static/js/` |
| **Contenu authentifié en cache** | Fuite de données entre utilisateurs d'un même appareil | Navigations jamais mises en cache ; page hors ligne autonome sans session (T80, T81) ; aucun `cache.put` (T77) |
| **Flash de thème** (F31) | Éclair clair en mode sombre | Script synchrone avant la feuille de style (T04) ; `color-scheme` déclaré |
| **Émulation hors ligne du SW dans la garde** | Faux négatif de la scène `pwa-offline` | Émulation appliquée aussi aux cibles `service_worker` (vérifié expérimentalement : la page seule ne suffit pas) |
| **Garde lente ou instable** | Itérations pénibles, CI fragile | Contexte isolé par run, mouvement réduit émulé, attentes déterministes (`load`, `fonts.ready`, rAF) au lieu de délais fixes ; filtres `--scenes`/`--viewports` ; 272 runs (scènes × largeurs × thèmes × langues, §9.6) |
| **Divergence du CSS compilé entre machines** | Échec CI « CSS à jour » | Versions figées + lockfile + Node 22 en CI et en local ; le build est déterministe pour une même version |
| **`.env` du développeur** chargé à l'import de `app` | Démo non hermétique | `demo_env` pose explicitement toutes les variables utiles avant l'import (`override=False` les respecte) |
| **CSP `'unsafe-inline'`** maintenue | Surface XSS inchangée | Suppression de deux injections potentielles (noms dans `onclick`) ; durcissement planifié en B028 quand les scripts inline des pages auront disparu |
| **Barre latérale bureau : décision non validée par l'utilisateur** (TASKS dit « navigation bureau » sans en fixer la forme) | Colonne des pages historiques réduite à environ 720 px utiles à 1 024 px (contre environ 912 px aujourd'hui) | Décision maintenue (cohérente avec la barre du bas mobile, évite le débordement de 9 pilules, N9) et **signalée pour confirmation** à l'utilisateur ; si elle est refusée, seul le gabarit de `nav-desktop` (contexte `event`) change : contrat `data-testid`, ordre T27 et tests inchangés |
| **Mouvement réduit émulé par défaut dans la garde** | Animations des feuilles et des toasts peu exercées | Scène `more-sheet-motion` (`reducedMotion: false`) ; les autres scènes restent en mouvement réduit pour des mesures stables |
| **Garde qui passerait toujours** (promesses non attendues, valeurs « truthy ») | Faux sentiment de sécurité | Helper `evaluate` unique (promesse attendue, délai, `true` strict, §9.4) et auto-contrôle `npm run ui:selftest` en CI (§9.10) |
| **Toast sous une feuille modale** | Retour de copie invisible dans une feuille | Toast inséré dans le dernier `dialog[open]` (§4.7) ; scène `sheet-toast` |

---

## 14. Suivi de l'audit de spec (`specs/audits/B017-spec.md`)

| # | Sévérité | Traitement (section) |
|---|---|---|
| 1 | bloquant | Participants réservé au créateur (§4.5.1, §4.6) ; `members.html` ne rend plus les codes aux invités (§1.3, §7.12) ; T19, T21 reformulés, T44e ajouté ; CA31 |
| 2 | majeur | Helper `evaluate` : `awaitPromise`, délai, `true` strict (§9.4, §9.5) ; auto-contrôle (§9.10) ; CA32 |
| 3 | majeur | Registre unique `JS_STRINGS` + `#ui-strings` + `t(key)`, point d'extension, convention, conformité imposée à B018 (§7.2) ; T43, T43a, T39 |
| 4 | majeur | Déclencheurs `main` + `ui/**` (§2.5) ; CA27 |
| 5 | majeur | Réserve de place sur `body` dans les deux contextes (§4.5.1, §4.11) ; contrôle `nav` sans recouvrement (§9.7) ; CA09 |
| 6 | majeur | Toast inséré dans le dernier `dialog[open]`, animation sur le panneau (§4.7, §5.10, §7.6) ; scène `sheet-toast` ; CA18 |
| 7 | majeur | Liste exhaustive des éléments nus, classe `ui-form`, `.ui-sheet__panel` neutralisé (§4.10) ; T49 complété |
| 8 | majeur | T07, T33, T36, T38, T75, T77, T80, T81 reformulés ; T85 reclassé en garde de non-régression (§11.2 bis) |
| 9 | mineur | 15,29 (§3.3) |
| 10 | mineur | Ombres hors `@theme`, aucun utilitaire `shadow-*` (§3.1, §3.6) |
| 11 | mineur | Collisions de variables documentées et voulues (§2.3) |
| 12 | mineur | Filet actif `primary` 3 px (§4.5.1, §3.3) |
| 13 | mineur | Fermeture au fond limitée à `dialog.ui-sheet` (§7.5) |
| 14 | mineur | `Path(current_app.static_folder, filename)` (§8.2) |
| 15 | mineur | `text_of(html, testid, element)` (§11.1, T29) |
| 16 | mineur | Noms canoniques `funnel`, `circle-question-mark` (§6, T58) |
| 17 | mineur | `rmSync` avec `maxRetries: 10, retryDelay: 200` (§9.4) |
| 18 | mineur | Commits 4 et 5 fusionnés ; T84f au commit 4 (§10) |
| 19 | mineur | `amount_cents=14250` / `84000` ; `ui:serve` relance toujours la graine (§9.2, §9.4) |
| 20 | mineur | F33 cité au périmètre et hors périmètre (§1) |
| 21 | mineur | Décision conservée et signalée pour confirmation utilisateur (§13) |
| 22 | mineur | 272 runs, décompte détaillé (§9.6, §13) |
| 23 | mineur | `rel="icon"` dans `offline.html` ; `.mo` inclus dans `asset_version` ; limite de langue documentée (§8.2, §8.4) |
| 24 | mineur | `_('Retirer %(name)s ?', name=…)` ; terme unique « Créateur » (§4.4, §7.12, §11.4) |
| 25 | mineur | Piles `aria-live` persistantes, texte inséré après l'élément, pas de `role` par toast (§4.7, §7.6) |
| 26 | mineur | Safe areas latérales sur la barre et `main` (§4.5.1, §4.7) |
| 27 | mineur | Contrat `current_event`/`current_guest`/`event_role`/`build_nav` à conserver par B029 (§4.6) |
| 28 | mineur | Scène `more-sheet-motion` sans mouvement réduit ; limite notée (§9.6, §13) |
| 29 | mineur (re-audit) | T39 rattaché au commit 4 (il importe `JS_STRINGS`) ; commit 3 sans test propre (§10) |
| 30 | mineur (re-audit) | Réserve conditionnée à `body[data-has-bottom-nav]`, absente de `/offline` ; contrôle `nav` : `padding-bottom` de `body` nul quand `expect.nav = none` (§4.5.1, §4.11, §9.7) |
| 31 | mineur (re-audit) | Dépôt sans remote : CI inopérante localement, porte réelle = §12.2 ; `SECRET_KEY`/`SUPERADMIN_PASSWORD` factices ajoutés aux jobs `test` et `frontend` (§2.5, §12.2, CA27) |
| 32 | adaptation B029 | Événements des tests T16/T17 vérifiés (§11.1) ; scènes `event-unverified` (`/e/verify/…`) et `verify-sent` (`/e/new/sent/…`) seulement ; graine : seul `unverified` non vérifié, placeholder `token.unverified` (§9.2, §9.6) ; 32 scènes, 280 runs |

### Constats écartés

Aucun. (Le n° 21 n'est pas écarté : la décision est maintenue en attendant la confirmation de l'utilisateur, comme le rapport le prévoit.)
