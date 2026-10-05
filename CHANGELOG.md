# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/)
Versioning : [SemVer](https://semver.org/lang/fr/)

Chaque lot (B00X) correspond à une section. Les commits atomiques sont listés
sous chaque lot.

---

## [Unreleased]

### B016 — Refonte UI/UX (Design System, shell mobile, timeline, frais, confidentialité, freemium)

#### Lot 1 — Design System, palette chaleureuse & shell mobile
- [x] Design tokens : palette chaude terracotta/lin (#FAF8F5, #C25E38), rayons
      6/12/18/9999px, ombres card/hover, `--accent-sage` pour les statuts positifs
- [x] Typographie : stack system + Inter, titres h1–h3 en 650 / -0.02em
- [x] Dark mode réchauffé (charbon + terracotta doux)
- [x] Contraste WCAG 2.1 AA : textes/boutons solides sur `--primary-hover`
      (≥4.5:1), `--primary` réservé aux surfaces/contours/icônes (≥3:1)
- [x] Shell mobile : header discret (logo + titre événement + avatar/code)
      + barre tactile fixe en bas (Hub, Planning, Listes, Frais, Plus) avec
      `backdrop-filter: blur(12px)` et menu "Plus" (Media, Chat, Sondages, Infos, Repas)
- [x] `padding-bottom: 5rem` sur `<main>` mobile ; icônes SVG inline ;
      conteneur centré 960px ; nav desktop en pilules
- [x] Chip identité invité dans le header (initiale sage + nom/code)
- [x] i18n : chaînes "Accueil/Plus/Navigation/Fermer" (en) + recompile .mo
- [x] manifest.json + theme-color alignés sur la palette
- [x] 238 tests passent (0 régression)

#### Lot 2 — Timeline du jour & ergonomie Repas ↔ Courses
- [x] Dashboard "Aujourd'hui" : timeline chronologique unifiée (repas Midi/Soir
      + activités), chaque entrée horodatée
- [x] Passerelle Repas → Courses : badge de statut sur chaque repas du dashboard
      ("Listed" si les ingrédients sont cochés dans une liste, "À lister" sinon)
- [x] Liste de courses : le panneau latéral de repas devient une rangée de
      pastilles horizontales (chips) défilables, ≥44px, coche en un tap sans
      masquer les articles
- [x] i18n : chaînes timeline + pastilles (en) + recompile .mo
- [x] 238 tests passent (0 régression ; un test obsolète sur l'ancien toggle
      repas remplacé par une assertion sur les pastilles)

#### Lot 3 — Frais "Splitwise-like" & Listes Fluides
- [x] Carte "Ton solde" héro en haut : fond sauge (on te doit X€) / ocre
      (tu dois X€) / neutre ("Tu es quitte ! 👌"), grand chiffre tabular-nums,
      détail de qui doit à qui pour l'acteur courant
- [x] "Qui doit à qui" : liste textuelle remplacée par des cartes de transfert
      (avatars initiales, flèche, montant net en grand) + bouton "Rembourser"
      pré-remplissant un transfert
- [x] Foyers : tableau lourd remplacé par des cartes compactes avec statut
      visuel (reçoit / doit / réglé)
- [x] Dépenses du séjour : relevé typé (pastille catégorie 🍔🚗🏡🎟️, payeur +
      date en sous-titre gris, montant à droite), suppression discrète
- [x] Quick-Add : formulaire compact, sélecteurs + chips de catégories à icônes
- [x] Listes de courses : article coché se barre en douceur (opacité 0.5 +
      transition), bouton "Je m'occupe" avec pastille de confirmation immédiate
- [x] i18n : chaînes frais/listes (en) + recompile .mo
- [x] Algorithme de calcul (`_settlement` / `_per_expense_shares`) intact
- [x] 238 tests passent (0 régression)

#### Lot 4 — Confidentialité "Privacy by Design" & RGPD
- [x] Badge "🛡️ Confidentialité garantie" dans le footer (toutes pages),
      cliquable → modale 3 points (zéro compte forcé, zéro cookie/pistage,
      export + effacement)
- [x] Export ZIP (GET /e/<code>/export, créateur uniquement) :
      `evenement.json` (titre, dates, invités, activités, dépenses, soldes,
      listes, sondages) + dossier `medias/` (photos avec nom d'origine)
- [x] Suppression définitive (POST /e/<code>/delete, créateur uniquement +
      CSRF) : cascade SQL (invités, activités, repas, listes, frais, médias,
      logs) + purge disque `instance/media/<code>/` + déconnexion
- [x] Zone de gestion sur le dashboard (créateur) : bouton export ZIP +
      bouton suppression (confirm()) + mention "purge 30 jours après fin"
- [x] Masquage des codes invités (dashboard + membres) : texte masqué
      par défaut (shoulder-surfing), bouton "Voir" pour révéler, "Copier"
      reste séparé
- [x] `Event.guests` et `Event.activity_logs` en cascade delete-orphan
      (suppression complète sans orphelins)
- [x] i18n : chaînes confidentialité/export/suppression (en) + recompile .mo
- [x] 246 tests passent (0 régression, 8 nouveaux tests privacy)

#### Lot 5 — Architecture Freemium propre & Paywall élégant
- [x] API déclarative dans `app/freemium.py` : `get_tier`, `has_feature`,
      `require_tier("pro")` (soft paywall → teaser, pas de 400/403 brut),
      tiers `free`/`pro`/`unlimited`, features `pdf_export`/`unlimited_guests`/
      `hd_video`. Fonctions existantes (can_add_guest, quotas média) intactes.
- [x] `Creator.tier` (colonne, défaut "free") — distinct de `MediaQuota.tier`
- [x] Route `GET /e/<code>/export/pdf` : free → paywall ; pro+ → vue PDF
      (hook Stripe/LemonSqueezy prêt)
- [x] Modale "Holishared Vacances+" (partial `_upgrade_modal.html`) : 50 Go,
      Export PDF certifié, Participants illimités, CTA factice
- [x] Paywall page `freemium/paywall.html` (aperçu d'upgrade soigné)
- [x] Galerie média : jauge de stockage (usage/quotas) + incitation douce
      (carte upgrade au quota atteint, hint à 75 %)
- [x] Page invitation : jauge d'invités (count/max) + état premium
      ("illimité ✓" / carte upgrade au plafond)
- [x] Zéro régression : `ENABLED_MODULES`, tests freemium & module-gating intacts
- [x] 256 tests passent (0 régression, 10 nouveaux tests freemium)

### B008 — Frictions UX (code invité, auth, i18n, CSS, formulaires)
- [x] Code invité : l'invité saisit son propre code (4-8 car.), toujours visible
      sur le dashboard (plus de flash) ; reconnexion via /mycode
- [x] Invitation par email du créateur + renvoi à un membre existant (Guest.email)
- [x] QR code d'invitation (génération serveur, CSP intacte)
- [x] Auth créateur : l'événement appartient au créateur connecté ; l'email est
      l'identifiant (Event.creator_email), pas un compte séparé
- [x] i18n réel : .po/.mo fr+en (160 chaînes traduites), Babel configuré,
      switcher persistant en session
- [x] CSS : classes manquantes stylées (btn-primary, poll-*, day-header,
      form-group, invite-box, event-list, hint, badge-*, guest-list, …)
- [x] Formulaires : erreurs par champ + valeurs préservées (events/create)
- [x] Dates localisées (format_date) partout ; auto-scroll chat après swap HTMX
- [x] Migration légère (manage.py migrate) pour les nouvelles colonnes
- [x] 215 tests passent

### B003 — Blueprint Planning (activités + RSVP)
- [x] Helper log_action() (app/utils.py)
- [x] Modèle ActivityLog (app/models.py)
- [x] Blueprint planning : 5 routes (index, create, edit, delete, rsvp)
- [x] Templates planning (index + form) + erreurs 403/404
- [x] CSRFProtect + flask-wtf
- [x] 45 tests passent (tests/test_planning.py)

### B002 — Tracabilité (ActivityLog)
- [ ] Modèle ActivityLog
- [ ] Helper log_action()
- [ ] Intégration dans tous les blueprints
- [ ] Route /e/<code>/log
- [ ] Tests

### B007 — Media (partage photos/vidéos + geo + datation)
- [ ] Modèle MediaItem (GPS WGS84, taken_at, uploaded_at)
- [ ] Modèle MediaQuota (tier: free/basic/premium)
- [ ] Freemium : can_upload_media, consume/release quota, set_tier
- [ ] Blueprint media (upload, galerie, détail, suppression)
- [ ] Extraction EXIF (GPS + date)
- [ ] Map Leaflet.js
- [ ] Tests

---

## [0.1.0] — 2026-10-04

### B001 — Fondations & infra
- feat: app factory, extensions, 12 modèles SQLAlchemy
- feat(auth): superadmin login + bloc domaines jetables
- feat(events): CRUD, guest access (code 8 chars), email verification
- feat: module freemium (5 fonctions de contrôle)
- chore(infra): nginx, systemd, manage.py, requirements.txt
- docs: DEV_LOG.md, AGENTS.md, TASKS.md
