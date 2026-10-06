# TASKS.md — Décomposition en lots

Chaque lot est une unité de travail autonome, testable, et committable.
Un lot est terminé quand tous ses critères d'acceptation sont vérifiés.

**Légende** : ⬜ à faire | 🔄 en cours | ✅ terminé | ⛔ bloqué

---

## B001 — Fondations & infra

**Statut** : ✅ (2026-10-04)

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 1.1 | App factory + config | `create_app()` retourne une app Flask fonctionnelle |
| 1.2 | Extensions (db, login, babel) | `db.init_app`, `login_manager.init_app`, `babel.init_app` |
| 1.3 | Modèles SQLAlchemy (12 modèles) | `db.create_all()` sans erreur |
| 1.4 | Blueprint auth (login superadmin) | POST /admin/login → redirect |
| 1.5 | Blueprint events (CRUD + guest) | Création, dashboard, join, verify |
| 1.6 | Module freemium | 5 fonctions de contrôle |
| 1.7 | Nginx + systemd + manage.py | Service démarre, port 8400 |
| 1.8 | .env + .env.example | Toutes les variables documentées |

**Commits** :
- `feat: app factory, extensions, models`
- `feat(auth): superadmin login + disposable email block`
- `feat(events): CRUD, guest access, email verification`
- `feat: freemium limits module`
- `chore(infra): nginx, systemd, manage.py, requirements`

---

## B002 — Tracabilité (ActivityLog)

**Statut** : 🔄

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 2.1 | Modèle ActivityLog | Champ actor, action, target, details, timestamp |
| 2.2 | Helper `log_action()` | Fonction utilitaire dans `app/utils.py` |
| 2.3 | Intégration dans events | Chaque création/join/verify loggée |
| 2.4 | Intégration dans planning | Chaque activité/RSVP loggée |
| 2.5 | Intégration dans lists | Chaque item créé/modifié loggée |
| 2.6 | Intégration dans voting | Chaque vote/fermeture loggée |
| 2.7 | Intégration dans chat | Chaque message loggée |
| 2.8 | Route `/e/<code>/log` | Page listant tous les logs (paginé) |
| 2.9 | Template log | Tableau accessible, filtres par type |
| 2.10 | Tests | Couverture > 80% sur le log |

**Commits prévus** :
- `feat(models): ActivityLog model for traceability`
- `feat: log_action helper in utils`
- `feat(events): integrate activity logging`
- `feat(planning): integrate activity logging`
- `feat(lists): integrate activity logging`
- `feat(voting): integrate activity logging`
- `feat(chat): integrate activity logging`
- `feat(events): /e/<code>/log route + template`
- `test: activity log coverage`

---

## B003 — Blueprint Planning (activités + RSVP)

**Statut** : ✅

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 3.1 | Route création activité | POST avec titre, date, heure, lieu, min_headcount |
| 3.2 | Route liste activités | GET par date, tri chronologique |
| 3.3 | Route RSVP | POST yes/no/maybe, 1 par invité |
| 3.4 | Route modification activité | POST (créateur ou créateur de l'activité) |
| 3.5 | Route suppression activité | POST (créateur) |
| 3.6 | Template planning | Liste + formulaire + RSVP buttons |
| 3.7 | Tests | CRUD + RSVP + permissions (45 tests) |

---

## B004 — Blueprint Lists (listes partagées)

**Statut** : ⬜

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 4.1 | Route création liste | POST avec titre, type |
| 4.2 | Route ajout item | POST avec name, qty, section, assigned_to |
| 4.3 | Route toggle done | PATCH is_done |
| 4.4 | Route suppression item | DELETE |
| 4.5 | Route suppression liste | DELETE (créateur) |
| 4.6 | Template lists | Liste + items + checkboxes |
| 4.7 | Tests | CRUD + permissions |

---

## B005 — Blueprint Logistics (infos pratiques)

**Statut** : ⬜

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 5.1 | Route ajout info | POST avec titre, contenu, catégorie |
| 5.2 | Route liste infos | GET triées par catégorie + ordre |
| 5.3 | Route modification | PUT |
| 5.4 | Route suppression | DELETE (créateur) |
| 5.5 | Template logistics | Sections par catégorie |
| 5.6 | Tests | CRUD + permissions |

---

## B006 — Blueprint Voting (sondages)

**Statut** : ⬜

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 6.1 | Route création sondage | POST avec question + options |
| 6.2 | Route vote | POST 1 vote par invité par option |
| 6.3 | Route résultats | GET avec barres de progression |
| 6.4 | Route fermeture | PATCH is_closed (créateur) |
| 6.5 | Template voting | Sondages ouverts + résultats |
| 6.6 | Tests | Vote + résultats + fermeture |

---

## B007 — Blueprint Media (partage photos/vidéos + geo + datation)

**Statut** : ⬜

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 7.1 | Route upload media | POST multipart (photo/video), extraction EXIF GPS + date |
| 7.2 | Stockage disque | `instance/media/<event_code>/<id>_<filename>` |
| 7.3 | Extraction EXIF | GPS (lat/lng) + date prise (piexif/exifread) |
| 7.4 | Quota check | Refus si `can_upload_media()` = False |
| 7.5 | Consume/release quota | `consume_media_quota()` / `release_media_quota()` |
| 7.6 | Route galerie | GET `/e/<code>/media` — grille photos + map |
| 7.7 | Route détail | GET `/e/<code>/media/<id>` — full + caption + geo |
| 7.8 | Route suppression | DELETE (uploader ou créateur) → release quota |
| 7.9 | Map intégrée | Leaflet.js (pas de clé API) pour afficher les points |
| 7.10 | Template media | Grille responsive, lightbox, map, filtres par date |
| 7.11 | Tests | Upload, quota, EXIF, suppression, permissions |

**Quota par tier** :
| Tier | Quota | Prix (futur) |
|------|-------|-------------|
| free | 500 MB | 0 € |
| basic | 5 GB | 2 €/mois |
| premium | 50 GB | 5 €/mois |

---

## B008 — Blueprint Chat

**Statut** : ⬜

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 7.1 | Route envoi message | POST avec content (HTMX partial) |
| 7.2 | Route historique | GET paginé (50 messages) |
| 7.3 | Polling / WebSocket | HTMX polling 5s (pas de WS pour v1) |
| 7.4 | Template chat | Bulles, timestamps, auto-scroll |
| 7.5 | Tests | Envoi + historique + permissions |

---

## B009 — Templates & UI

**Statut** : ⬜

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 8.1 | base.html | Layout responsive, nav, lang switcher |
| 8.2 | events/create.html | Formulaire création |
| 8.3 | events/dashboard.html | Vue d'ensemble (activités, listes, votes) |
| 8.4 | events/join.html | Formulaire guest join |
| 8.5 | events/invite.html | Lien d'invitation + QR code |
| 8.6 | events/mycode.html | Saisie code perso |
| 8.7 | events/log.html | Log de tracabilité |
| 8.8 | errors/404.html, 403.html | Pages d'erreur |
| 8.9 | WCAG 2.1 AA | Lighthouse ≥ 95 accessibilité |

---

## B010 — PWA

**Statut** : ⬜

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 9.1 | manifest.json | Nom, icônes, theme-color, display |
| 9.2 | Service worker | Cache offline (app shell) |
| 9.3 | Icônes | 192px, 512px, maskable |
| 9.4 | Meta tags | viewport, theme-color, apple-touch |
| 9.5 | Test install | PWA installable sur mobile |

---

## B011 — i18n

**Statut** : ⬜

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 10.1 | Extraction gettext | `pybabel extract` sur templates + code |
| 10.2 | Fichiers .po fr/en | Tous les strings traduits |
| 10.3 | Compilation .mo | `pybabel compile` |
| 10.4 | Lang switcher | Lien ?lang=fr / ?lang=en |
| 10.5 | Tests | Pas de string en dur dans les templates |

---

## B012 — CSS & Responsive

**Statut** : ⬜

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 11.1 | CSS base | Variables, reset, typography |
| 11.2 | Layout responsive | Mobile-first, breakpoints 480/768/1024 |
| 11.3 | Composants | Cards, buttons, forms, tables |
| 11.4 | Accessibilité CSS | Focus visible, contrast, touch targets ≥ 44px |
| 11.5 | Dark mode | Media query prefers-color-scheme |

---

## B013 — Tests & CI

**Statut** : ⬜

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 12.1 | conftest.py | Fixtures app, db, client, users |
| 12.2 | Tests modèles | Unit tests generate codes, relationships |
| 12.3 | Tests auth | Login, logout, permissions |
| 12.4 | Tests events | CRUD, guest flow, freemium limits |
| 12.5 | Tests planning | CRUD + RSVP |
| 12.6 | Tests lists | CRUD |
| 12.7 | Tests voting | Vote + results |
| 12.8 | Tests chat | Send + history |
| 12.9 | GitHub Actions | CI : ruff + mypy + pytest sur push/PR |
| 12.10 | Couverture | ≥ 80% sur app/ |

---

## B014 — Web Push (hooks) — remplacé par B027

**Statut** : ⬜

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 13.1 | Service worker push | Handler push event |
| 13.2 | Endpoint subscribe | POST /push/subscribe |
| 13.3 | Endpoint notify | Fonction send_notification() |
| 13.4 | Intégration | Notification sur nouvelle activité |
| 13.5 | Tests | Subscribe + notify (mock) |

---

## B015 — Hardening & Production

**Statut** : ⬜

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 14.1 | Security headers | HSTS, CSP, X-Frame-Options, X-Content-Type |
| 14.2 | CSRF tokens | Sur tous les formulaires POST |
| 14.3 | Rate limiting | Flask-Limiter sur create/join |
| 14.4 | Logging structuré | JSON logs en production |
| 14.5 | Health check | GET /health → 200 + db check |
| 14.6 | Backup DB | Script cron SQLite backup |
| 14.7 | Monitoring | Uptime check + alert |

---

## B016 — Refonte UI/UX

**Statut** : ✅ (Lot 1 ✅, Lot 2 ✅, Lot 3 ✅, Lot 4 ✅, Lot 5 ✅)

### Lot 1 — Design System, palette chaleureuse & shell mobile ✅
| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 16.1 | Tokens palette + rayons + ombres | Variables --bg/--surface/--primary/--accent-sage, radius 6/12/18/9999 |
| 16.2 | Dark mode réchauffé | data-theme=dark + prefers-color-scheme alignés |
| 16.3 | Contraste AA | ≥4.5:1 texte, ≥3:1 UI sur --primary |
| 16.4 | Shell mobile tabbar | Barre fixe bas, blur, 4-5 actions, menu Plus |
| 16.5 | Header discret | Logo + titre événement + avatar/code, main padding 5rem |
| 16.6 | i18n + manifest | Chaînes en, .mo recompilés, theme_color aligné |

**Commits** :
- `style(css): design system chaleureux terracotta + palette AA`
- `feat(ui): shell mobile tabbar + header événement + chip invité`
- `chore(i18n): chaînes nav mobile + recompile .mo`

### Lot 2 — Timeline du jour & ergonomie Repas ↔ Courses ✅
| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 17.1 | Dashboard : repas du jour | today_meals (Midi/Soir) + activités ordonnés chronologiquement |
| 17.2 | Statut courses par repas | covered_meal_ids alimente un badge "Listed / À lister" |
| 17.3 | Chips repas en liste de courses | Rangée horizontale défilable, ≥44px, coche en 1 tap |
| 17.4 | i18n + recompile .mo | Chaînes en traduites, .mo recompilés |

**Commits** :
- `feat(events): timeline du jour unissant repas et activités`
- `feat(lists): panneau repas → pastilles horizontales (mobile)`
- `chore(i18n): chaînes timeline + pastilles`

### Lot 3 — Frais "Splitwise-like" & Listes Fluides ✅
| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 18.1 | Carte "Ton solde" héro | my_household + i_owe/owed_to_me → bandeau sauge/ocre/neutre |
| 18.2 | "Qui doit à qui" en cartes | .settlement/who-owes-card (avatars, flèche, montant net, "Rembourser") |
| 18.3 | Foyers en cartes compactes | .group-card avec statut visuel (reçoit/doit/réglé) |
| 18.4 | Dépenses relevé + quick-add | .expense-row + pastilles catégorie ; formulaire compact icônes |
| 18.5 | Listes fluides | article coché → barre + opacité 0.5 ; "Je m'occupe" = pastille immédiate |
| 18.6 | i18n + recompile .mo | Chaînes en traduites, .mo recompilés |
| 18.7 | Zéro régression algo | _settlement/_per_expense_shares intacts ; tests verts |

**Commits** :
- `feat(costs): carte solde + cartes de transfert + dépenses relevé`
- `feat(lists): fade items cochés + confirmation "je m'occupe"`
- `chore(i18n): chaînes frais/listes`

### Lot 4 — Confidentialité "Privacy by Design" & RGPD ✅
| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 19.1 | Badge + modale footer | 🛡️ cliquable sur toutes pages, 3 points RGPD |
| 19.2 | Export ZIP (créateur) | GET /e/<code>/export → zip (evenement.json + medias/), 403 guest |
| 19.3 | Suppression définitive (créateur) | POST /e/<code>/delete → cascade DB + purge disque, 403 guest |
| 19.4 | Zone de gestion dashboard | Bouton export + bouton suppression + mention purge 30j |
| 19.5 | Masquage codes invités | Texte masqué par défaut, toggle "Voir", "Copier" séparé |
| 19.6 | Cascade delete-orphan guests+logs | Aucun orphelin à la suppression d'un événement |
| 19.7 | i18n + tests | Chaînes en, .mo recompilés, 8 nouveaux tests privacy verts |

**Commits** :
- `feat(events): export ZIP + suppression définitive (privacy)`
- `feat(ui): badge confidentialité + modale + codes masqués`
- `chore(models): cascade guests + activity_logs`
- `test(privacy): export/suppression + contrôle d'accès`

### Lot 5 — Architecture Freemium propre & Paywall élégant ✅
| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 20.1 | API déclarative freemium.py | get_tier/has_feature/require_tier, tiers free/pro/unlimited |
| 20.2 | Creator.tier colonne | Défaut "free", distinct de MediaQuota.tier |
| 20.3 | require_tier soft paywall | free → teaser (pas 400/403 brut), guest non redirigé |
| 20.4 | Route export_pdf gated | GET /e/<code>/export/pdf : free→paywall, pro+→vue PDF |
| 20.5 | Modale "Vacances+" (partial) | 50Go / Export PDF certifié / Participants illimités, CTA hook |
| 20.6 | Jauge stockage (média) | usage/quotas + incitation douce (75 % + quota atteint) |
| 20.7 | Jauge invités (invite) | count/max + état premium (illimité ✓ / carte upgrade) |
| 20.8 | i18n + tests | Chaînes en, .mo, 10 nouveaux tests freemium verts |
| 20.9 | Zéro régression | ENABLED_MODULES + tests freemium/module-gating intacts |

**Commits** :
- `feat(freemium): API déclarative tiers + require_tier soft paywall`
- `feat(ui): modale Vacances+ + jauges stockage/invités`
- `test(freemium): tiers, has_feature, require_tier (export_pdf)`

---

# Programme « Refonte pro » (B017 → B028)

**Objectif** : une application en production, parfaitement utilisable, de niveau professionnel en ergonomie, usage et efficacité. Source : `AUDIT_UI.md` (constats `N`, `I`, `V` et registre `F01`–`F25`).

**Décisions** (validées par l'utilisateur) :
- Tailwind CSS v4 (CLI via npm, Node 22), CSS compilé commité dans `app/static/css/` : la prod (Docker) n'a pas besoin de Node, aucun CDN.
- Navigation mobile : barre du bas à 5 onglets (Accueil, Planning, Repas, Listes, Frais) + feuille « Plus » ancrée en bas.
- Repas : glisser-déposer tactile (pointer events, sans bibliothèque) **et** action « Déplacer vers… » accessible.
- Migration « big-bang » sur la branche `ui/tailwind-refonte` : `main.css` historique reste isolé en couche basse jusqu'à B028, qui le supprime. Merge en `main` à la clôture de B028 (un seul merge pour le programme).

**Ordre d'exécution** : B017 → **B029** → **B030** → B018 → B019 → B020 → B021 → B022 → B023 → B024 → B025 → B026 → B027 → B028 (B029 est numéroté après coup mais s'exécute juste après le socle : toutes les vues qui suivent en dépendent).

**Chaîne de production par lot** (voir `AGENTS.md`, adaptée aux modèles) :
1. Spec `specs/B0XX-slug.md` — Opus.
2. Audit de la spec — Opus (contexte vierge), corrections jusqu'à approbation.
3. Tests écrits d'abord (pytest + garde UI) — Opus ; ils doivent échouer.
4. Codage — Sonnet (contexte vierge : spec + tests + `AGENTS.md`).
5. Exécution : `ruff check . && ruff format --check . && mypy app/ && pytest` + `npm run ui:check`.
6. Audit du code livré — Opus (contexte vierge : spec + code).
7. Gate + `CHANGELOG.md` + `TASKS.md` + `DEV_LOG.md` + commit `chore: close lot B0XX`.

**Règles transverses** : jamais supprimer un test existant (adapter uniquement selon la table « Tests existants modifiés » de la spec) ; hooks de test = `data-testid` ou rôles ARIA, jamais des classes CSS ; garde UI = aucun défilement horizontal, cibles ≥ 44 px, barre du bas visible, aucun texte français en EN, aucune erreur console, contraste AA, clair et sombre, à 360/390/820/1280 px.

## B017 — Socle Tailwind, shell mobile & outillage UI

**Statut** : ⬜ · **Réf.** N1–N9, I3, V10, F20

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 17.1 | Build Tailwind v4 | `npm run build:css` produit `app/static/css/app.css` ; `package.json` + lockfile ; CI vérifie que le CSS commité est à jour |
| 17.2 | Design tokens & thèmes | Palette terracotta/lin, clair + sombre (`data-theme`), échelle d'espacement/typo/rayons ; contraste AA mesuré |
| 17.3 | Shell responsive | En-tête sobre ; navigation bureau ; **barre du bas 5 onglets + feuille « Plus »** ancrée en bas, état actif y compris pour les pages de « Plus », visible hors événement (accueil/événements) |
| 17.4 | Kit de composants | Boutons (1 primaire/écran), cartes cliquables en entier, formulaires, feuille/dialogue, toast, état vide, squelette de chargement, icônes SVG uniques (fin des emojis comme icônes) |
| 17.5 | JS partagé | Modules uniques : copie dans le presse-papiers avec retour, thème, feuille, modale confidentialité, confirmation ; fin de la duplication inline |
| 17.6 | Service worker | Nom de cache dérivé du hash des assets ; page hors ligne ; Alpine retiré du précache |
| 17.7 | Outillage UI | `scripts/ui/` : graine de démo, serveur de démo (base et `instance_path` jetables), garde `npm run ui:check` (CDP, sans dépendance) ; `main.css` isolé en couche basse |

## B029 — Contexte d'événement & identité participant unique

**Statut** : ⬜ · **Réf.** F29, F30 (serveur), F32 ; §11.2 et §11.5 de l'audit · **S'exécute après B017**

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 29.1 | Contexte unique | Un seul module résout événement + participant + rôle (une requête, mise en cache sur `g`) ; les 8 copies de `_get_event_or_404`/`_resolve_actor`/`_actor_name` sont supprimées ; `inject_globals` réutilise ce contexte |
| 29.2 | Identité unique | Le créateur est toujours un participant `Guest` (créé à la vérification, idempotent, rétro-rempli par migration) ; `assigned_to_id`, `created_by`, auteurs de chat et RSVP utilisent `Guest.id` ; migration des anciennes valeurs (`Creator.id`, `None`, noms) idempotente |
| 29.3 | Droits | Fonctions uniques `can_edit(objet)`, `can_delete(objet)`, `is_creator` ; tests d'autorisation par module |
| 29.4 | Réponses homogènes | Non connecté → `/mycode` partout ; 403/404 rendus par les gabarits d'erreur (plus de chaînes brutes) ; aucun `BuildError` quand un module est désactivé (F32) |
| 29.5 | Codes d'accès | Génération côté serveur (`secrets`), longueur minimale 8 pour les nouveaux codes créateur, limitation des essais par compte/événement ; l'ancien code reste valable |
| 29.6 | Non-régression | Comportement externe inchangé ; tous les tests existants verts (adaptation traçable uniquement) |

## B030 — Modèle freemium relationnel (Plan / Abonnement)

**Statut** : ⬜ · **Réf.** §11.6 de l'audit, F19 · **S'exécute après B029**

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 30.1 | Schéma | Tables `plans`, `plan_features`, `subscriptions` avec clés étrangères ; plan « free » créé par défaut ; `Creator.tier` et `MediaQuota.tier` remplacés par la relation (migration idempotente, données préservées) |
| 30.2 | Limites en données | Invités/événement, événements actifs, durée max, stockage : lus depuis le plan ; les variables d'environnement alimentent le plan gratuit |
| 30.3 | API inchangée | `get_tier`, `has_feature`, `require_tier`, `can_add_guest`, `can_create_event`, `can_upload_media` gardent leurs signatures ; tests freemium existants verts |
| 30.4 | Extensibilité | Une fonctionnalité payante se déclare par une ligne `plan_features` ; documentation dans un ADR ; aucun paiement branché |
| 30.5 | Honnêteté | Aucun abonnement fictif : changement de plan réservé à l'administration (commande `manage.py`) tant qu'aucun paiement n'existe (F19) |

## B018 — Internationalisation complète

**Statut** : ⬜ · **Réf.** §5 de l'audit, F17, F18 (libellés)

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 18.1 | Catégories traduites | Frais (général, courses…), infos, types de liste : libellés via un dictionnaire central, plus aucune clé brute affichée |
| 18.2 | Messages serveur | 100 % des `flash()`, erreurs de validation, `abort`/réponses texte passent par `_()` |
| 18.3 | JS et attributs | Chaînes JS via `data-*`/gabarits traduits ; `aria-label`, `title`, `placeholder` traduits |
| 18.4 | Catalogue | 0 entrée vide, 0 « fuzzy » en EN ; `.pot/.po/.mo` régénérés et vérifiés |
| 18.5 | Erreurs par champ | Les formulaires reçoivent des erreurs `{champ: message}` (plus de recherche de sous-chaînes) |
| 18.6 | Formats | Dates, heures, nombres et devises via Babel selon la langue |
| 18.7 | Garde i18n | Test : chaque page rendue en EN ne contient aucun msgid français ni mot-clé français |

## B019 — Accès, comptes & parcours d'entrée

**Statut** : ⬜ · **Réf.** F01, F09, F15, F16, F17, F22, V9

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 19.1 | Accueil | Un seul champ « code » : reconnaît code créateur (4–8) et code événement ; chemin clair « Créer » / « J'ai un code » |
| 19.2 | Mes événements | Cartes entièrement cliquables avec statut (à venir / en cours / terminé), dates, nombre de participants ; accessible aussi aux invités (liste des événements de l'appareil) |
| 19.3 | Création d'événement | Parcours court, erreurs par champ ; explication de la vérification e-mail avant l'envoi |
| 19.4 | Vérification & code | Pages `verify`, `verify_sent`, `recover` revues ; aucune fuite du code sans e-mail (F16) ; vouvoiement homogène |
| 19.5 | Rejoindre | Un seul écran lisible (pseudo, code, foyer optionnel) ; pas de saisie inutile |
| 19.6 | Session | Sessions invité et créateur durables et maîtrisées (F15) ; redirections cohérentes `/mycode` (F09) |
| 19.7 | Connexion admin, 403/404/500 | Pages d'erreur utiles avec chemin de retour |

## B020 — Accueil de l'événement, Participants & Journal

**Statut** : ⬜ · **Réf.** F02, F03, F04, F18, F21, V3, V8

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 20.1 | Accueil événement | Héros (titre, dates, lieu, compte à rebours) + « Aujourd'hui » + « Pour moi » + derniers messages ; une action primaire ; plus de bloc code personnel en tête |
| 20.2 | Menu « Événement » | Partager (lien `/join` correct, F03), mon code, participants, journal, export, gestion/suppression (confirmation forte) |
| 20.3 | Participants | Fusion Membres + Invitations ; liste, ajout, retrait, renvoi, QR, jauge ; accessible depuis l'interface ; foyer créé à l'ajout (F21) |
| 20.4 | Limite d'invités | La page reste accessible à la limite avec la carte d'upgrade honnête (F02) |
| 20.5 | Journal | Phrases lisibles et traduites, filtres, pagination (F18) ; accessible depuis le menu |
| 20.6 | Identité créateur | Pastille créateur dans l'en-tête ; nom d'affichage éditable (F22) |

## B021 — Planning

**Statut** : ⬜ · **Réf.** F10, V1, V2

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 21.1 | Vue par jour | Chronologie par jour avec jours vides visibles, repas du jour, saut au jour courant |
| 21.2 | Carte d'activité | RSVP intégré (Oui / Peut-être / Non), décompte, seuil `min_headcount` atteint ou non, `bring_items` affiché |
| 21.3 | Ajout/édition | Feuille d'ajout rapide + formulaire avancé en sections ; pas de doublon liste/RSVP |
| 21.4 | Créateur participant | Le créateur peut répondre (F10) |
| 21.5 | Statut de couverture & programme unifié | Chaque activité affiche « pas encore dans une liste » ou « pris en compte dans : <listes> » (liens), `bring_items` affiché sur la carte (F10), programme du jour/semaine avec les repas en lecture seule (contrat §11.5) |

## B022 — Repas

**Statut** : ⬜ · **Réf.** I2, V5, F25

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 22.1 | Vue mobile | Un jour à la fois (balayage ou sélecteur de jour) ; vue calendrier sur grand écran |
| 22.2 | Déplacer | Action « Déplacer vers… » (jour + créneau) + glisser-déposer tactile et souris + clavier ; déposer sur une case occupée **ajoute** le repas à la case (plusieurs repas par créneau) ; réordonnancement dans la case ; l'ancien échange (swap) reste disponible comme action explicite « Échanger avec… » |
| 22.3 | Cellules | « + » visible sur les cases vides, statut « courses » par repas, lien vers la liste de courses |
| 22.4 | Backend | Échange sans créneau temporaire `tmp` ; réponses JSON/HTMX sans rechargement complet |
| 22.6 | Statut de couverture | Chaque repas affiche « pas encore dans une liste » ou « pris en compte dans : <listes> » (liens vers les listes), sur la grille, le tableau de bord et la feuille du repas ; identifiants de repas stables lors des déplacements (contrat §11.5) |
| 22.5 | Plusieurs repas par créneau | Suppression de la contrainte d'unicité `(event, date, slot)` avec migration SQLite (reconstruction de table, données préservées, idempotente) ; colonne d'ordre dans la case ; cellule = pile de cartes + « Ajouter un repas » ; tableau de bord, chips de courses, journal, export ZIP et `covered_meals` gèrent n repas par créneau ; limite raisonnable (6 par créneau) |

## B023 — Listes

**Statut** : ⬜ · **Réf.** F11, I5, V6

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 23.1 | Saisie complète | Ajout rapide avec quantité et section ; types de liste utilisés |
| 23.2 | Cocher en un geste | Un article se coche sans « Je m'occupe » préalable ; l'attribution est facultative |
| 23.3 | Mises à jour sans rechargement | HTMX sur cocher, attribuer, ajouter, supprimer ; position de défilement conservée ; pas de clavier automatique au chargement |
| 23.4 | Identité d'attribution | Basée sur l'identifiant (plus le nom d'affichage) |
| 23.6 | Panneau « Repas & activités » | Dans chaque liste, bouton avec compteur ouvrant un panneau à côté de la liste (colonne repliable sur bureau, feuille en bas sur mobile) : repas et activités par jour, libellés complets, case « pris en compte » en HTMX sans rechargement, filtre « masquer les pris en compte », bascule Repas/Activités/Tout ; jamais imposé aux listes libres ; couverture stockée en clés étrangères (`ListMealCoverage`, `ListActivityCoverage`, cascade) en remplacement des tableaux JSON `covered_meals`/`covered_activities`, avec migration idempotente (contrat §11.5) |
| 23.5 | Suppression | Chacun supprime ses propres articles (avec annulation) ; suppression de liste dépriorisée |

## B024 — Frais

**Statut** : ⬜ · **Réf.** F06, F07, F08, V4

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 24.1 | Correctifs de données | Note de demande de paiement enregistrée et affichée ; devise avec taux ; date de dépense saisie (défaut : aujourd'hui) |
| 24.2 | Structure | En-tête « Mon solde » ; « Qui doit à qui » avec noms complets ; ajout via feuille ; détails dépliables ; formats localisés |
| 24.3 | Droits | Chacun modifie/supprime ses propres dépenses ; droits UI = droits serveur ; confidentialité des dépenses personnelles |
| 24.4 | Transferts | Formulaire de transfert toujours accessible |
| 24.5 | Non-régression | `_settlement` et `_per_expense_shares` inchangés ; tests d'algorithme verts |

## B025 — Sondages, Infos pratiques & Chat

**Statut** : ⬜ · **Réf.** F05, F12, F14

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 25.1 | Sondages | Création rapide ; clore et supprimer (créateur) ; résultats après le vote ; vote en un geste |
| 25.2 | Infos pratiques | Cartes avec copie en un geste ; édition sur place ; plus de champ « Ordre » exposé ; ordre logique des catégories |
| 25.4 | Sondage d'activités | À la création, choix du type « Question libre » ou « Départager des activités » : sélection d'une ou plusieurs activités existantes comme options (au moins 2), possibilité d'ajouter des options libres ; les activités en vote portent un badge « En vote » dans le Planning avec lien vers le sondage |
| 25.5 | Issue du vote | À la clôture d'un sondage d'activités : activité(s) gagnante(s) (égalité gérée) ; le créateur peut « Retenir » le gagnant : l'activité passe « Retenue », les autres « Non retenues » (grisées, restaurables ou supprimables) ; journal et notification associés |
| 25.3 | Chat | Saisie ancrée en bas ; envoi sans rechargement ; polling sans forcer le défilement ; actions de message discrètes ; aperçu accueil limité à 3 messages côté serveur |

## B026 — Média

**Statut** : ⬜ · **Réf.** F13

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 26.1 | Miniatures | Génération côté serveur (Pillow), grille légère, originaux à la demande |
| 26.2 | Formats | HEIC converti ou refusé avec message clair ; vidéo avec affiche |
| 26.3 | Envoi | Multi-sélection, progression, limite de débit adaptée |
| 26.4 | Visionneuse | Précédent/suivant, balayage, téléchargement, légende, date et lieu lisibles |

## B027 — Notifications Web Push (PWA)

**Statut** : ⬜ · **Remplace** B014 (jamais implémenté : seules les clés VAPID existent dans `manage.py`/`.env.example`)

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 27.1 | Modèle et API d'abonnement | Table `PushSubscription` (participant, événement, endpoint, clés, agent, dates) ; `POST /push/subscribe` et `/push/unsubscribe` (CSRF, authentifiés par la session créateur/invité) ; clé publique VAPID exposée ; abonnements purgés avec l'événement et au retrait du participant ; endpoints expirés (404/410) supprimés |
| 27.2 | Envoi asynchrone | Dépendance `pywebpush` (pyproject + requirements) ; tâche RQ `send_push` sans contexte Flask ; clés VAPID lues de l'environnement ; sans clés ou sans Redis : dégradation silencieuse et journalisée, jamais d'erreur utilisateur |
| 27.3 | Déclencheurs | Nouveau message de chat (aux autres participants), nouveau sondage (à tous), nouvelle demande de remboursement (au participant du foyer destinataire) ; jamais à l'auteur ; regroupement des messages de chat rapprochés (même `tag`) ; contenu tronqué ; lien profond vers la bonne page |
| 27.4 | Service worker | Gestionnaires `push` et `notificationclick` (focalise un onglet ouvert ou ouvre la page), `notificationclose` ; icône/badge ; i18n FR/EN du texte |
| 27.5 | Préférences | Par participant et par événement : chat / sondages / remboursements activables séparément ; option « aperçu du message » ; coupure totale en un geste |
| 27.6 | Parcours d'activation | Invite contextuelle (jamais au chargement) dans le menu « Événement » et après un premier geste utile ; états : non supporté, refusé, accordé, installé/non installé ; sur iOS, consigne « Ajouter à l'écran d'accueil » (permission possible seulement en PWA installée) |
| 27.7 | Vie privée | Mise à jour de la modale de confidentialité (les push transitent par le service du navigateur) ; ADR ; abonnement révocable ; aucune donnée personnelle dans le payload au-delà du texte affiché |
| 27.8 | Tests | Abonnement/désabonnement, droits, déclencheurs, exclusion de l'auteur, purge des endpoints expirés (envoi simulé) ; garde UI de l'invite |

## B028 — Clôture : qualité, accessibilité, PWA & mise en production

**Statut** : ⬜ · **Réf.** F19, F20, F24, §6 de l'audit

| # | Tâche | Critère d'acceptation |
|---|-------|----------------------|
| 28.1 | Suppression du CSS historique | `main.css` supprimé ; aucune règle orpheline |
| 28.2 | Accessibilité | Contraste, étiquettes, focus, navigation clavier, pièges de focus des feuilles ; vérifiés clair et sombre |
| 28.3 | Honnêteté freemium | Plus d'appel à l'action factice ; état « bientôt » explicite ou masqué (F19) |
| 28.4 | PWA | Manifest, icônes, page hors ligne, 500 |
| 28.5 | Performance | Poids de page, images, pas de requêtes inutiles (chat) |
| 28.6 | Recette | Parcours complets créateur/invité en FR et EN à 360/390/820/1280 px ; documentation (README, CHANGELOG, DEV_LOG) ; merge en `main` |
