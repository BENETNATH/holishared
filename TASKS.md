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

## B014 — Web Push (hooks)

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

**Statut** : ✅ (Lot 1 ✅, Lot 2 ✅)

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
