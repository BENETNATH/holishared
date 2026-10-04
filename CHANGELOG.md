# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/)
Versioning : [SemVer](https://semver.org/lang/fr/)

Chaque lot (B00X) correspond à une section. Les commits atomiques sont listés
sous chaque lot.

---

## [Unreleased]

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
