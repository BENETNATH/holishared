# AGENTS.md — Instructions pour agents de codage

Ce fichier est le contrat entre l'agent et le projet. Tout agent (IA ou humain)
qui code sur ce repo DOIT respecter ces règles.

---

## Règles fondamentales

### 1. Un commit = une unité logique atomique

- Un commit fait **une seule chose** (une feature, un fix, un refactor).
- Message au format **Conventional Commits** :
  ```
  <type>(<scope>): <description courte>

  [corps optionnel — le POURQUOI, pas le quoi]

  [footer optionnel — BREAKING CHANGE, refs]
  ```
- Types : `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `style`, `ci`
- Scopes : `auth`, `events`, `planning`, `lists`, `logistics`, `voting`, `chat`, `models`, `infra`, `i18n`, `pwa`, `css`, `meals`, `costs`, `media`, `context`, `ui`
- Exemples :
  ```
  feat(planning): ajouter création d'activité avec RSVP
  fix(events): corriger le guest_count après désactivation
  test(models): couvrir generate_event_code
  ```

### 2. Travailler par lots (batches)

- Un **lot** = un ensemble de commits qui forment une fonctionnalité complète testable.
- Chaque lot a un **numéro** (B001, B002, …) et un **nom**.
- Le lot est défini dans `TASKS.md` avant de commencer.
- Un lot est **terminé** quand :
  - Tous les commits sont faits
  - Les tests passent (`pytest`)
  - Le lint passe (`ruff check . && ruff format --check .`)
  - Le type-check passe (`mypy app/`)
  - Le `CHANGELOG.md` est mis à jour
  - Le `TASKS.md` est mis à jour (statut → ✅)

### 3. Vérification avant commit

Avant chaque commit, l'agent DOIT :
```bash
ruff check .
ruff format --check .
mypy app/
pytest
```
Si un check échoue → corriger avant de committer. Jamais de commit rouge.

### 4. Pas de code mort, pas de TODO sans issue

- Pas de `# TODO` sans référence à un lot dans `TASKS.md`.
- Pas de code commenté (git a l'historique).
- Pas de `print()` de debug (utiliser `logging`).

### 5. Sécurité

- Jamais de secret dans le code (env vars uniquement).
- Validation de toutes les entrées utilisateur.
- SQL : uniquement via SQLAlchemy ORM (pas de raw SQL sauf agrégats).
- CSRF : tokens sur tous les formulaires POST.
- Rate limiting sur les endpoints de création.

### 6. Accessibilité (WCAG 2.1 AA)

- Tous les inputs ont un `<label>`.
- Contraste minimum 4.5:1.
- Navigation clavier complète.
- `aria-*` sur les composants interactifs.
- Pas d'info transmise uniquement par la couleur.

### 7. i18n

- Tout texte utilisateur passe par `gettext()` / `_()`.
- Pas de texte en dur dans les templates.
- Fichiers : `app/translations/fr/LC_MESSAGES/messages.po` + `.en`.

---

## Pipeline de codage (7 étapes, non négociable)

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. PLAN + SPECS                                                    │
│     - Analyse complète du lot (modèles, routes, templates, tests)   │
│     - Spec écrite dans specs/B00X-slug.md                          │
│     - Chaque route, champ, comportement est spécifié                │
│     - Pas d'ambiguïté : si un dev ne peut pas coder sans poser     │
│       de question, la spec est incomplète                          │
├─────────────────────────────────────────────────────────────────────┤
│  2. AUDIT DES SPECS                                                 │
│     - Agent d'audit relit la spec                                   │
│     - Vérifie : complétude, cohérence, cas limites, sécurité        │
│     - Si problème → corriger la spec → re-audit                    │
│     - Gate : spec approuvée                                        │
├─────────────────────────────────────────────────────────────────────┤
│  3. TESTS (avant le code)                                           │
│     - Écrire les tests D'ABORD (TDD)                               │
│     - Tests déterministes, pas de "vibe testing"                   │
│     - Chaque test = un comportement précis, un assert précis        │
│     - Pas de test qui passe "parce que c'est flou"                 │
│     - Les tests DOIVENT échouer (code pas encore écrit)            │
├─────────────────────────────────────────────────────────────────────┤
│  4. CODAGE (agent au contexte propre)                               │
│     - Agent reçoit : spec + tests + AGENTS.md                      │
│     - Agent lit la spec, lit les tests, code                       │
│     - Agent ne devine rien : tout est dans la spec                 │
│     - Commits atomiques pendant le codage                          │
├─────────────────────────────────────────────────────────────────────┤
│  5. EXÉCUTION DES TESTS                                             │
│     - pytest (tous les tests du lot + régression)                  │
│     - Si échec → retour étape 4 (fix)                              │
│     - Gate : tous les tests verts                                 │
├─────────────────────────────────────────────────────────────────────┤
│  6. AUDIT DU CODE                                                   │
│     - Agent d'audit relit le code livré                            │
│     - Vérifie : conformité spec, sécurité, accessibilité,          │
│       i18n, pas de code mort, pas de TODO                          │
│     - Si problème → retour étape 4 (fix)                           │
│     - Gate : code approuvé                                         │
├─────────────────────────────────────────────────────────────────────┤
│  7. GATE + COMMIT                                                   │
│     - ruff check . && ruff format --check .                        │
│     - mypy app/                                                    │
│     - pytest (full suite)                                          │
│     - Si tout vert :                                               │
│       a. Mettre à jour CHANGELOG.md                                │
│       b. Mettre à jour TASKS.md (statut ✅)                        │
│       c. Mettre à jour DEV_LOG.md (journal)                        │
│       d. Commit final : chore: close lot B00X                      │
│       e. Merge en main                                             │
└─────────────────────────────────────────────────────────────────────┘
```

### Règles du pipeline

- **Jamais de codage sans spec approuvée** (étape 2 gate).
- **Jamais de commit sans tests verts** (étape 5 gate).
- **Jamais de merge sans audit code** (étape 6 gate).
- **L'agent de codage ne voit que** : spec + tests + AGENTS.md. Pas de contexte
  conversationnel, pas de "rappelle-toi qu'on a dit…".
- **L'agent d'audit ne voit que** : spec + code livré. Il compare.
- **Si un gate échoue 2 fois** → escalade à l'utilisateur, pas de retry infini.

---

## Workflow d'un lot (résumé)

```
1. specs/B00X-slug.md écrit
2. Audit spec → approuvé
3. tests/test_B00X.py écrits (doivent échouer)
4. Agent code (contexte propre : spec + tests + AGENTS.md)
5. pytest → verts
6. Agent audit code → approuvé
7. ruff + mypy + pytest → verts → commit + merge
```

---

## Structure des tests

```
tests/
├── conftest.py          # Fixtures (app, db, client, creator, event, guest)
├── test_models.py       # Unit tests des modèles
├── test_auth.py         # Tests blueprint auth
├── test_events.py       # Tests blueprint events
├── test_planning.py     # Tests blueprint planning
├── test_lists.py        # Tests blueprint lists
├── test_logistics.py    # Tests blueprint logistics
├── test_voting.py       # Tests blueprint voting
├── test_chat.py         # Tests blueprint chat
└── test_freemium.py     # Tests limites freemium
```

Règles :
- Un test = un comportement.
- Nom : `test_<comportement>_<condition>_<résultat>`
- Pas de test qui dépend de l'ordre.
- Fixtures dans `conftest.py`, pas dans les fichiers de test.

---

## Ce que l'agent NE DOIT PAS faire

- Modifier `pyproject.toml` sans raison (dépendances, config lint).
- Supprimer des tests qui passent.
- Commiter un état non fonctionnel.
- Créer de fichiers hors de la structure définie.
- Utiliser `datetime.now()` sans timezone (utiliser `datetime.utcnow()` ou `zoneinfo`).
- Ajouter une dépendance sans l'ajouter à `pyproject.toml`.
- Ignorer les erreurs de mypy/ruff.

---

## Contexte rapide pour l'agent

- **Stack** : Flask 3, SQLAlchemy, Flask-Login, Flask-Babel, Waitress, SQLite
- **Pattern** : Blueprints par domaine, app factory
- **Auth** : Créateur (email) + Invités (code 8 chars, zéro PII)
- **Freemium** : limites via env vars, pas de paiement
- **i18n** : FR/EN via Flask-Babel
- **PWA** : manifest + service worker (à implémenter)
- **Tracabilité** : `ActivityLog` — chaque action est loggée et visible par tous
