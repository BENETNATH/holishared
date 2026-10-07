# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/)
Versioning : [SemVer](https://semver.org/lang/fr/)

Chaque lot (B00X) correspond à une section. Les commits atomiques sont listés
sous chaque lot.

---

## [Unreleased]

### B031 — Finitions (retours du test utilisateur)

- `feat(events)` : section « Mon foyer » sur `/e/<code>/me` (nom, adultes ≥ 1, enfants ≥ 0, erreurs par champ, toast ; création si le participant n'a pas de foyer) ; liens « Modifier mon foyer » depuis la carte « Mon solde » (Frais) et la ligne « Vous » de Participants. Logique partagée avec `costs` (`parse_household`, `save_my_household`) ; journal `household.created` / `household.updated`.
- `fix(css)` : `/lists` : le formulaire de création rapide héritait de la règle legacy `form { flex-direction: column }` (le `flex-basis` du champ devenait une hauteur) ; `flex-row max-w-none`.
- `fix(chat)` : `test_history_shows_50_max` (et un test voisin) cherchaient « msg-09 » dans le HTML brut alors que chaque `<li id="msg-<hex>">` peut le contenir ; ils lisent désormais le texte des messages. Le code (ordre `(created_at, id)`) était déjà déterministe.
- `test(ui)` : scènes `my-household`, `my-household-error` ; assertion d'espacement sur `lists`.

### B022c — Repas : zones de dépôt et vue d'ensemble mobile

- `feat(meals)` : pendant le glisser, chaque carte (autre que celle saisie) est une zone « Échanger » (libellé, icône, titre), l'espace libre de la case une zone « Ajouter ici » (« Déposer ici » si vide) ; l'insertion entre deux cartes reste possible ; `swap` renumérote les deux cases sans trous (identifiants inchangés) ; un déplacement vers une autre case annonce « Repas ajouté à : … ».
- `feat(meals)` : vue mobile d'ensemble (tous les jours, colonnes Midi / Soir compactes) à la place du sélecteur de jours et du balayage ; même glisser que sur desktop.
- `fix(ui)` : `forms.js` écoute `submit` sur `window` (après les modules à envoi fetch) : le bouton de la feuille d'ajout ne reste plus en chargement et un second ajout est possible.
- `feat(css)` / `fix(css)` : zones de dépôt (teintes info / succès, zone active nette, clair/sombre) ; cartes de l'accueil en colonnes maçonnerie.
- `test(ui)` : scènes `meals-drag-add-zone`, `meals-drag-swap-zone`, `meals-drop-zones`, `meals-add-twice`, `meals-overview` (remplace `meals-day-tabs`) ; l'action `drag` résout sa cible après le début du glisser et accepte `expr:`.
- Tests existants adaptés : `TestGridDays` (sélecteur de jours supprimé).

### B026 — Média

- `feat(media)` : miniatures WebP (320 et 960 px) générées à la demande par Pillow et mises en cache sur disque (`<instance>/media/<code>/thumbs/<id>-<taille>.webp`), orientation EXIF appliquée, EXIF/GPS absents des dérivés, bornes anti-bombe de décompression (50 Mpx) et échecs de décodage sans 500 ; route `media.thumb` (mêmes droits que `media.file`, `Cache-Control: private, max-age=86400`, ETag/304) ; dérivés supprimés avec le média, purgés avec l'événement, absents de l'export ZIP et du quota ; les médias existants sont servis sans migration (génération au premier accès).
- `feat(media)` : HEIC/HEIF refusé avec un message clair (réglage iPhone « Le plus compatible ») et plus annoncé dans `accept` ; vidéos en tuile à icône de lecture (sans chargement du fichier) ; extraction EXIF corrigée (secondes et décimales des coordonnées, `DateTimeOriginal`).
- `feat(media)` : envoi multiple fichier par fichier (`ui/media.js` : XHR, barre de progression, concurrence 2, annulation, réessai, glisser-déposer, légende commune), erreurs traduites par fichier (format, taille, stockage plein, trop d'envois), grille rafraîchie sans rechargement ; limite de débit portée de 10 à 200 envois/heure/IP ; `MAX_CONTENT_LENGTH` par requête ; noms d'origine assainis.
- `feat(media)` : galerie en grille de miniatures carrées groupées par jour de prise de vue (EXIF, sinon envoi), compteur, pagination de 60 par « Afficher plus » (HTMX), état vide ; la jauge de stockage n'affiche plus de faux bouton de paiement (texte honnête : supprimer des médias).
- `feat(media)` : visionneuse (mêmes URLs) : miniature 960 puis original à la demande, précédent/suivant (`rel=prev/next`, préchargement), flèches clavier, balayage tactile, Échap vers la galerie à la bonne position, téléchargement (`attachment`, nom assaini), légende modifiable par l'auteur ou le créateur (`MediaItem` : édition `author` dans `app/context.py`), date et lieu lisibles, lien « Voir sur la carte » OpenStreetMap en nouvel onglet (aucune requête tierce avant le clic), suppression avec confirmation.
- `feat(ui)` : icônes `play` et `rotate-cw` ; chaînes JS `media_*`.
- `test(ui)` : `tests/test_media_b026.py` (86 tests) ; graine de démo avec de vraies images (paysage, portrait, carré, EXIF GPS/date) et une vidéo ; scènes `media`, `media-creator`, `media-empty`, `media-upload-sheet`, `media-upload-queue`, `media-viewer`, `media-viewer-located`, `media-caption-sheet` ; touches fléchées dans l'outil de garde.
- `test(infra)` : le fixture `app` isole `instance_path` dans un dossier temporaire (les tests n'écrivent plus dans le vrai `instance/media`).
- Tests existants adaptés : `test_rights.py` (la légende d'un média est modifiable par l'auteur et le créateur), `test_ui_assets.py` (deux icônes ajoutées au jeu d'icônes).

### B019 — Accès, comptes & parcours d'entrée

- `feat(auth)` : sessions durables (F15) : `session.permanent` + cookie « se souvenir » du créateur, 30 jours glissants (`PERMANENT_SESSION_LIFETIME`, `REMEMBER_COOKIE_DURATION` équivalent), cookies `HttpOnly`/`SameSite=Lax`/`Secure` selon l'environnement ; déconnexion en POST (CSRF) qui efface aussi les accès invité de l'appareil (« Se déconnecter » / « Oublier cet appareil », menu, en-tête et `/e/`).
- `fix(auth)` : plus aucune fuite de secret sans SMTP (F16) : l'indicateur `DEV_SHOW_SECRETS` (défaut désactivé, documenté dans `.env.example`) est seul à autoriser l'affichage du lien de vérification et du code ; `recover` répond de la même façon que l'adresse existe ou non ; page refaite et vouvoyée.
- `feat(events)` : « Mes événements » accessible aux invités (F01) : liste dérivée des sessions `guest_<code>` valides de l'appareil, isolation entre sessions, redirection explicative vers l'accueil sans accès connu ; macro de carte partagée.
- `feat(auth)` : accueil à deux chemins (Créer en primaire, « J'ai un code » : un champ, 4 à 8 caractères, événement ou créateur) avec « Vos événements » ; échec neutre et identique pour tous les cas, saisie conservée.
- `feat(events)` : création en parcours court (F17 : erreurs par champ, description repliée, durée max, explication de la vérification avant l'envoi, cohérence des dates) ; `verify_sent` (e-mail masqué, délai de 3 jours, que faire si rien n'arrive, renvoi limité au navigateur créateur et à 3 par heure) ; `verify` refaite (code suggéré, foyer et invitations repliés, case « conserver mon e-mail » expliquée honnêtement).
- `feat(events)` : `/join` et `/mycode` lisibles (erreurs par champ, foyer et e-mail repliés, aide « Vous n'avez pas encore de code ? Rejoindre ») ; aucun JS de génération de secret.
- `feat(ui)` : pages 403/404/500 du kit avec chemin de retour (accueil, « Vos événements », retour à l'événement), gestionnaire 500 sans trace, connexion admin restylée.
- `test` : `test_sessions_b019.py`, `test_recover_b019.py`, `test_device_events_b019.py`, `test_home_access_b019.py`, `test_creation_b019.py`, `test_join_b019.py`, `test_errors_b019.py`, `test_ui_scenes_b019.py` ; 17 scènes de garde (page entière, FR/EN, clair/sombre).
- Tests existants adaptés : message d'échec du code (flash -> erreur inline), titre « Confirmez votre événement », « Se déconnecter » dans la liste des msgids du shell, connexion admin en POST.

### B025b — Infos pratiques & Chat (clôture de B025)

- `feat(logistics)` : infos en cartes groupées par catégorie dans l'ordre du registre (adresse, accès, horaires, documents, notes, divers ; clés inconnues à la fin) puis `order`, puis ancienneté ; bouton « Copier » ; liens http(s) cliquables et échappés (`app/infos.py`, filtre `linkify`, aucun HTML brut) ; menu Modifier/Supprimer ; ajout et modification dans une feuille ancrée en bas (HTMX, fragment de liste, erreurs par champ). Le champ « Ordre d'affichage » disparaît de l'interface : la colonne reste en base, la valeur postée est ignorée (les anciennes valeurs continuent de trier dans leur catégorie). Droits inchangés (modifier : tout participant ; supprimer : créateur). L'accueil affiche les 3 premières infos dans le même ordre. `confirm.js` gère `data-confirm` sur les formulaires HTMX (`htmx:confirm`).
- `feat(chat)` : composeur collant au-dessus de la barre du bas (Entrée envoie sur bureau, Maj+Entrée = saut de ligne, champ extensible), envoi sans rechargement (la réponse contient tout ce qui est arrivé depuis le curseur du client : aucun trou), polling incrémental `GET /chat?after=<id>&ts=<iso>` (ordre `(created_at, id)`, repli sur l'horodatage si le curseur a été supprimé) ralenti quand l'onglet est masqué, défilement automatique seulement si la personne est déjà en bas sinon bouton « Nouveaux messages », historique « Messages précédents » (`?before=<id>`, par 50), messages groupés par auteur (5 min) avec séparateurs de date, libellé « Vous », menu par message (`data-confirm`, suppression sans rechargement). Plus de gros bouton « Supprimer ». Gestionnaire global 429 : toast lisible pour les requêtes HTMX.
- `test(ui)` : scènes Infos (cartes, copie, feuille d'ajout/édition/erreur, suppression) et Chat (page, envoi, historique, nouveaux messages, suppression).

### B025a — Sondages (partie de B025 ; 25.2 Infos pratiques et 25.3 Chat à faire)

- `feat(models)` : `Poll.kind` (`free` / `activities`), `Poll.created_by`, `PollOption.activity_id` (FK `ON DELETE SET NULL` : l'option garde son libellé), `Activity.status` (`planned` / `retained` / `dropped`) ; migration idempotente `migrate_polls` (calcul à blanc, sauvegarde `pre-polls-*` seulement si des lignes existent, exécutée au démarrage avant la purge). Droits : un sondage est géré par le créateur ou son auteur (`test_rights` adapté).
- `feat(voting)` : page Sondages refaite (cartes cliquables, ouverts puis clos, état vide, bouton « Nouveau sondage » ouvrant une feuille de création rapide, formulaire page entière en sections avec erreurs par champ) ; types « Question libre » (2 à 10 options) et « Départager des activités » (cases à cocher des activités non écartées, filtre par jour, options libres en plus, question préremplie ; type désactivé avec explication sans Planning ou avec moins de 2 activités). Vote en un geste (HTMX : fragment de carte ; redirection sinon), modifiable tant que le sondage est ouvert ; les résultats ne s'affichent qu'après le vote (ou à tous une fois clos), pourcentages localisés, gagnants et égalités à la clôture. « Clore » (créateur ou auteur, avec confirmation), « Rouvrir » (créateur), « Supprimer » ; journal `poll.created/voted/closed/reopened/deleted`. Test existant `test_index_shows_results` devenu `test_index_hides_results_before_vote` (l'ancien comportement exposait les scores avant le vote). Le pourcentage utilisait un total partiel (erreur corrigée).
- `feat(planning)` : badge « En vote » (lien vers le sondage) sur les activités d'un sondage ouvert ; après clôture d'un sondage d'activités le créateur « Retient » la ou les gagnantes (égalité : les autres gagnantes restent planifiées), les autres options liées passent « Non retenues » (carte grisée dans une section repliée du jour, restaurable par le créateur ou l'auteur, supprimable), exclues de l'accueil « Aujourd'hui », du panneau Listes et des seuils ; journal `activity.retained/dropped/restored`.
- `feat(events)` : accueil — sondages ouverts, « À voter » en premier avec la mention.
- `test` : `test_voting_b025.py` (68), `test_polls_planning.py` (41), `test_polls_migration.py` (9), scènes `voting-*` et `planning-poll-badge` (graine de démo enrichie).

### Corrections de l'audit B018–B024 (`specs/audits/B018-B024-code.md`)

- `fix(infra)` (bloquant) : un événement avec au moins un vote est supprimable (cascade `delete-orphan` sur `PollOption.votes`, `Guest.poll_votes`, `Guest.activity_rsvps`) ; `app/startup.py` : un `try/except` + `rollback` par étape de démarrage (migrations, purge un commit par événement, identité), `SKIP_STARTUP_MIGRATION=1` neutralise aussi la purge (`python -m app.migrations check` n'écrit plus).
- `fix(infra)` (majeur) : rotation des sauvegardes par préfixe (3 par étape) et jamais de suppression d'une copie de moins de 30 jours ni de la dernière d'une étape ; restauration documentée dans le README.
- `fix(media)` : supprimer un média référencé par un justificatif ne produit plus de 500 (référence mise à NULL ; fichier et quota seulement après le commit).
- `fix(costs)` : montant ≥ 0,01 après arrondi et conversion, taux entre 1e-4 et 1e4 ; `min_headcount` / `exchange_rate` NULL tolérés.
- `fix(i18n)` : `extract` et `check` échouent sur une erreur de syntaxe Jinja.
- `fix(lists)` : couverture idempotente sur double clic ; limite de 6 repas revérifiée sous `BEGIN IMMEDIATE`.
- `fix(infra)` : `PRAGMA foreign_key_check` journalisé au démarrage, `python manage.py fk-check` (rapport sans réparation) ; `/me` et `/manage` en `Cache-Control: no-store`.

### B021 — Planning

- `feat(planning)` : programme par jour — tous les jours de l'événement (jours vides inclus), sélecteur horizontal sur mobile (`aria-pressed`, jour courant `aria-current`, `?day=`), bouton « Aujourd'hui », chronologie multi-jours à en-têtes collants dès 1024 px ; repas du jour en lecture seule (Midi/Soir, plusieurs possibles, lien vers Repas seulement si le module est actif) ; la section RSVP séparée disparaît.
- `feat(planning)` : carte d'activité — heure ou « Journée », lieu, description repliable (« Voir plus »), « À apporter » (`bring_items`), RSVP Oui / Peut-être / Non intégré (appui sur la réponse active = retrait, `status=none`), décompte « N oui · M peut-être », badge de seuil `min_headcount` (si > 1), liste des participants par réponse (prénoms d'affichage, jamais d'e-mail), auteur, menu Modifier/Supprimer (`can_edit`/`can_delete`, suppression confirmée). Le créateur répond comme tout participant.
- `feat(planning)` : la route `rsvp` renvoie le fragment de carte en HTMX (422 si statut inconnu), redirection sinon ; les réponses de tout l'événement sont lues par une seule requête jointe (nombre de requêtes de la page indépendant du nombre d'activités).
- `feat(ui)` : feuille d'ajout rapide (titre, date du jour sélectionné, heure + « Plus d'options ») également utilisée en édition (`ui/planning`, textes en `data-*`) ; formulaire page entière `/planning/new` et `/planning/<id>/edit` refondu en sections « L'essentiel » / « Détails » (kit `field`, erreurs par champ, dates bornées, `?date=`).
- `test` : `test_planning_b021.py` (77 tests) ; aucun test existant modifié ; scènes de garde UI `planning-*` ; graine de démo enrichie.

### B024 — Frais

- `feat(models)` : `created_by` sur `expenses`, `transfers`, `payment_requests` ; migration idempotente `migrate_costs` (calcul à blanc, sauvegarde `pre-costs-` seulement si des dates sont réécrites) : les `Expense.date` / `Transfer.date` NULL prennent la date de `created_at` (fin de « aujourd'hui » à chaque lecture).
- `feat(costs)` : droits UI = serveur par `can_edit` / `can_delete` — dépense : auteur, propriétaire du foyer payeur ou créateur ; foyer : composition par son propriétaire (ajout/suppression : créateur) ; ratio : créateur seul (serveur aussi) ; transfert : tout participant pour son foyer, créateur partout, suppression par l'auteur ou le créateur ; demande : créée depuis son foyer, réglée par le destinataire ou le créateur, supprimée par l'auteur ou le créateur.
- `fix(costs)` : la note d'une demande de paiement est enregistrée (`message`) et affichée ; taux de change saisi et validé (0 < taux <= 10000, obligatoire hors EUR, montant d'origine + équivalent affichés, totaux et soldes en EUR) ; date de dépense (défaut aujourd'hui, bornée 5 ans avant / 1 an après) ; montants acceptant la virgule, valeurs non finies refusées ; un foyer référencé n'est plus supprimable (message au lieu d'une erreur 500).
- `feat(costs)` : confidentialité — une dépense personnelle n'est visible (liste, totaux, détail du foyer, export) que des membres du foyer payeur, 404 pour les autres (créateur compris) ; son journal n'expose ni description ni montant.
- `feat(ui)` : page Frais en segments Dépenses · Équilibre · Demandes (`?tab=`, conservé après chaque action), en-tête « Mon solde », ajout/modification de dépense dans une feuille ancrée en bas (rouverte avec les erreurs par champ), détail dépliable, « Qui doit à qui » avec noms complets, formulaire de remboursement toujours accessible, foyers et ratio en feuilles ; `_settlement` / `_per_expense_shares` inchangés.
- `test` : `test_costs_b024.py`, `test_costs_migration.py` ; adaptés (jamais supprimés) — `test_costs` (structure en segments, dépenses partagées explicitement, dépenses personnelles dans un foyer du participant), `test_rights` (table des droits) ; scènes `costs*`.

### B023 — Listes

- `feat(models)` : tables d'association `ListMealCoverage` / `ListActivityCoverage` (clé primaire composite, `ON DELETE CASCADE` des deux côtés, `covered_by` -> `guests` `SET NULL`) en remplacement des tableaux JSON `SharedList.covered_meals` / `covered_activities` (colonnes conservées, ni lues ni écrites, suppression en B028) ; `ListItem.created_by` (nullable) ; `PRAGMA foreign_keys=ON` sur chaque connexion SQLite (les cascades jouent vraiment) ; migration idempotente `app/migrations.py` (`plan_lists_migration` / `migrate_lists` / `run_lists_migration` : ajout de colonne, transfert des tableaux JSON, identifiants orphelins ignorés, tableaux vidés après transfert, sauvegarde `pre-lists-*` seulement si des écritures sont prévues, au démarrage avant la purge et par `manage.py migrate`) ; la reconstruction de `meals` (B022) suspend les clés étrangères comme le prescrit SQLite.
- `feat(lists)` : ajout rapide avec quantité et section facultatives (sans `autofocus`), articles groupés par section puis cochés repliables ; cocher en un geste sans « Je m'occupe » ; attribution facultative (« Je m'occupe » / « Libérer » discrets, avatar et nom) ; chacun supprime ses propres articles (`ListItem.created_by`, le créateur supprime tout) avec annulation (toast ~ 8 s, route `items/restore`) ; toutes les actions en HTMX (fragment `lists/_items.html`, erreurs en toast via `HX-Trigger` `ui:toast`) ; suppression de la liste dans un menu discret avec confirmation ; page d'index en cartes cliquables avec progression n/m, création rapide avec type (registre `list_type` : général, courses, matériel, valise, à faire, buffet) ; journal `list_item.restored`, `list.meal_covered/uncovered`, `list.activity_covered/uncovered`.
- `feat(lists)` : panneau « Repas & activités » à la demande (bouton + compteur « n/m pris en compte », colonne repliable mémorisée sur bureau, tiroir non modal sur mobile, par jour, filtre « masquer », bascule Repas/Activités/Tout, cases en HTMX sans recharger) ; `toggle_meal` / `toggle_activity` réécrites sur les nouvelles tables (idempotentes, `covered=0|1`) ; tableau de bord (union des couvertures) et export ZIP lisent les nouvelles tables ; module `ui/lists.js`.
- `fix(context)` : `ListItem` — suppression réservée à l'auteur (`created_by`) ou au créateur (avant : tout participant), édition inchangée (`assigned_to_id`).
- `test` : `test_lists_migration.py`, `test_lists_items.py`, `test_lists_panel.py`, `test_lists_index.py` ; adaptés (jamais supprimés) — `test_lists` (pastilles de repas -> panneau, `quick-add` -> `data-testid`), `test_rights` (suppression d'article = auteur), `test_i18n_messages` (plus de script « C'est noté » en ligne), `test_ui_assets` (icône `user-minus`) ; scènes `lists`, `list-detail`, `list-panel-mobile`, `list-panel-desktop`, `list-panel-check`, `list-item-actions`.

### B022 — Repas

- `feat(models)` : `Meal.position` ; suppression de l'unicité `uq_meal_event_slot` (plusieurs repas par case, 6 maximum) ; migration SQLite idempotente par reconstruction de table (`app/migrations.py` : `plan_meals_migration` / `migrate_meals_schema` / `run_meals_migration`, ids préservés, positions 0..n par `created_at`, sauvegarde `pre-meals-*.db` seulement s'il y a des lignes), exécutée au démarrage avant la purge et par `manage.py migrate`.
- `feat(meals)` : `create` ajoute en fin de case ; `move` ajoute dans la case cible (ou insère avant `before_id`) et renumérote ; nouvelle route `swap` (échange explicite, droits sur les deux repas, plus de créneau `tmp`) ; identifiants stables ; journal `meal.swapped` ; réponses HTMX = fragment `meals/_grid.html` + `HX-Trigger` (toast), redirection sinon.
- `feat(ui)` : un jour à la fois < 1024 px (sélecteur de jours, balayage), calendrier jours × (Midi, Soir) au-delà, « Ajouter un repas » toujours visible, feuille accessible (modifier, déplacer vers…, échanger avec…, monter/descendre, supprimer avec confirmation), glisser aux pointer events (`ui/meals.js` : fantôme, case surlignée, indicateur d'insertion, défilement automatique, Échap, repli en toast) ; CSS legacy de la grille retiré.
- `fix(lists,events)` : tableau de bord, chips des listes et grille triés jour > midi/soir > position (l'ancien tri alphabétique plaçait « soir » avant « midi »).
- `test` : adaptés (jamais supprimés) — hooks `data-testid`/`aria-current`, case occupée = ajout, `test_module_links` cible l'URL de la page (l'import map liste `ui/meals`) ; scènes `meals-sheet`, `meals-add-sheet`, `meals-day-tabs`, `meals-drag` (glisser réel CDP, ordre conservé après rechargement) et action `drag` dans `scripts/ui/lib.mjs`.

### B020 (partie B) — Participants, limite d'invités, Journal et identité

- `feat(events)` : **Journal lisible** (20.5, F18) : phrases complètes et traduites par code d'action (`ACTION_SENTENCES`, « Antoine a ajouté une activité : Randonnée »), jamais de code technique ; regroupement par jour, icône par module, filtres `?type=` (module) et `?who=` (personne), pagination de 50 (« Plus ancien » / « Plus récent »), état vide ; cible/détails échappés ; dépenses personnelles toujours sans description ni montant. Registre enrichi (`participant.added/removed/renamed`) et garde statique AST : tout code passé à `log_event`/`_log_expense`/`log_action` a un libellé court et une phrase.
- `feat(events)` : **identité** (20.6, F22) : le nom d'affichage se modifie dans « Mon profil » (`/e/<code>/me`, 2 à 50 caractères, erreur par champ) ; journal `participant.renamed` ; le nom du compte créateur suit ; les messages de chat et entrées de journal existants gardent le nom stocké (précisé dans l'aide). L'entrée de menu « Mon code » devient « Mon profil ».
- `feat(events)` : **page Participants** (20.3/20.4, F02/F21) fusionnant Membres et Invitations (`/e/<code>/members` canonique ; `/invite` redirige vers `#invite`) : liste (créateur, foyer et composition), lien de rejoindre à copier, QR, invitation par e-mail (formulaire seulement si SMTP configuré, sinon note honnête), ajout par le créateur **avec son foyer** « Foyer <nom> » (visible dans les Frais), retrait (désactivation ; foyer supprimé seulement si l'événement n'a aucune dépense et que le foyer n'a ni transfert ni demande, sinon conservé et signalé), renvoi d'invitation. Un invité ne voit que les noms (jamais code ni e-mail d'autrui) et un bouton « Partager le lien ». Entrée de menu « Participants » pour tous, « Inviter » fusionnée.
- `fix(freemium)` : `Event.guest_count` compte les participants **actifs** (créateur compris) ; `can_add_guest` respecte l'offre (`unlimited_guests`) ; `guest_gauge()` partage la même base. À la limite, la page Participants reste accessible avec une carte « Limite du plan gratuit atteinte… Les plans payants arrivent bientôt » et aucun faux bouton « Passer à Vacances+ ».
- `test(ui)` : scènes `members`, `participants-guest`, `participants-full`, `log`, `log-filtered`, `log-empty`, `rename-error` ; la démo de la garde sème des entrées de journal.
- Tests adaptés : `test_ui_shell` (menu invité, section de navigation de `/invite`, msgid de confirmation), `test_events` (redirection de `/invite`, formulaire/renvoi avec SMTP), `test_i18n_guard` (phrase du journal).

### B020 (partie A) — Accueil, « Mes événements » et menu « Événement »

- `feat(lists)` : « Pour moi » / « À répartir » cochables en place — `toggle_item` et `claim_item` renvoient le fragment `events/_my_items.html` quand `HX-Request` (sinon redirection inchangée) ; `toggle_item` honore `is_done` (idempotent) et refuse (403) un article attribué à un autre sans droit d'édition (B029) ; module JS `ui/htmx` (toast sur erreur HTMX).
- `feat(events)` : accueil mobile d'abord — héros (titre, dates, lieu, « Dans N jours » / « Jour X sur N » / « Terminé », progression, description repliée), une seule action primaire, **Partager copie le lien `/join`** (`APP_URL`), « Aujourd'hui » (liens conditionnés aux modules), sondages, 3 derniers messages limités côté serveur, infos avec « Copier » ; le bloc code personnel et la « Zone de gestion » quittent l'accueil.
- `feat(events)` : menu « Événement » (Partager le lien, Journal, Mon code, Gérer l'événement pour le créateur) ; pages `/e/<code>/me` (code masqué par défaut, copie) et `/e/<code>/manage` (export ZIP, export PDF au statut honnête sans CTA, suppression avec confirmation renforcée, purge à 30 jours).
- `feat(events)` : « Mes événements » en cartes entièrement cliquables (lien étiré), statut texte + couleur, dates localisées, lieu, participants ; tri en cours / à venir / terminés.
- `test` : adaptés (jamais supprimés) — le code personnel d'un invité se lit désormais sur `/me` (`test_events`, `test_ui_shell`), nouveaux liens du menu bureau (`test_ui_shell`).

### B018 — Internationalisation complète (FR/EN)

- `feat(i18n)` : `app/i18n.py` (registre unique des catégories de frais/infos, types de liste, statuts RSVP, créneaux de repas ; filtres `label`, `money`, `number`, `time`, `date_short`, `datetime_short`, `filesize`, `action_label` ; devises traduites) ; plus de clé brute ni de `|capitalize` ; catégorie de frais validée côté serveur ; `format_date(None)` renvoie `""`.
- `feat(i18n)` : `scripts/i18n.py` (`extract`, `compile`, `check`) remplace `extract_i18n.py` et `translate_en.py` ; `babel.cfg` extrait aussi `app/meals` et `_components/` ; catalogue EN complet (0 vide, 0 fuzzy, 0 obsolète), `.mo` commités, vérifié par un test.
- `feat(i18n)` : `app/forms.py` (`FormErrors` `{champ: [messages]}`, itérable comme une liste) et macros `aria_invalid`/`field_errors`/`form_errors` ; création d'événement, validation, rejoindre, planning, infos pratiques, sondage, liste : erreurs par champ avec `aria-invalid`/`aria-describedby`, plus de détection par sous-chaînes françaises.
- `feat(i18n)` : 100 % des `flash()` et erreurs via `_()` (placeholders, `ngettext`), vouvoiement du français, chaînes JS (`lists_noted`), `FEATURE_LABELS` en lazy, `{{ event.title }}` hors de `_()` dans `pdf_export.html`.
- `feat(i18n)` : e-mails (`app/tasks.py`) traduits et vouvoyés, paramètre `lang="fr"`, catalogue chargé via `babel.support.Translations`, invitation envoyée dans la langue de l'invitant.
- `test(i18n)` : garde i18n (toutes les pages GET en EN puis FR, créateur et invité), journal d'actions traduit (registre des codes).
- `fix(models)` : `PaymentRequest.amount` manquant (la page des frais renvoyait 500 dès qu'une demande de paiement existait).
- Audit B017/B029 : `fix(events)` oracle de codes sur `/join` supprimé et créations d'invités limitées à 20/heure/IP ; `fix(lists)` `claim_item` respecte `can_edit` ; `fix(events)` e-mails des invités visibles du seul créateur ; `fix(infra)` sauvegarde privée dès la création, `SKIP_STARTUP_MIGRATION` strict (`1`), repli de `get_or_create_creator_participant` commité.

### B029 — Contexte d'événement & identité participant unique

- `feat(context)` : `app/context.py` (`load_event_context`, `EventContext`, `can_edit`/`can_delete`, `log_event`), cache vidé à chaque requête ; les 8 copies de `_get_event_or_404`/`_resolve_actor`/`_actor_name` sont supprimées.
- `feat(models)` : le créateur est toujours un participant `Guest` ; migration d'identité idempotente au démarrage et par `manage.py migrate` (sauvegarde conditionnelle dans `instance/backups/`, rotation à 3 fichiers et 30 jours), `python -m app.migrations check` / `manage.py check-identity` en lecture seule.
- `feat(auth)` : `app/access.py` (résolution des codes, suggestion serveur via `secrets`, limiteur d'échecs par IP et par (IP, événement) avec repli mémoire), nouveaux codes créateur de 8 caractères, codes courts existants toujours valables ; `limits>=5.0` déclaré.
- `fix(events)` : événement non vérifié ou inactif = 404 (sauf `verify`/`verify_sent`) ; visiteur renvoyé vers `/mycode` partout (HTMX : 204 + `HX-Redirect`) ; 403/404 rendus par gabarits ; plus de `BuildError` quand un module est désactivé (F32).
- `refactor(planning|meals|lists|logistics|voting|chat|costs|media)` : contexte unique, ordre contexte -> objet -> droit ; le créateur répond aux RSVP (D1), refus en 403 (D6), journal de l'acteur réel (D10), plus d'écriture pendant un GET.
- `refactor(ui)` : `inject_globals` sans requête (ajoute `ctx` et `current_participant`), nom du participant créateur dans la pastille, `inject_event_days` supprimé.

### B017 — Socle Tailwind, shell mobile & outillage UI

- `chore(infra)` : build Tailwind CSS v4.3.3 (`npm run build:css`, CSS compilé commité), ancien `main.css` isolé en couche `legacy` (`app/static/src/legacy.css`), job CI `frontend`.
- `feat(css)` : design tokens clair/sombre (contrastes AA mesurés), couche `base`, kit de composants `ui-*`, jeu d'icônes Lucide unique (71), helpers `asset_url`/`icon`, macros `field`/`sheet`/`empty_state`, thème sans flash (F31).
- `chore(i18n)` : chaînes du shell, des dialogues et de la page hors ligne (FR/EN) ; « Créer » corrigé, « Créateur » traduit.
- `feat(css)` : shell responsive (en-tête sobre, barre du bas à 5 destinations + feuille « Plus », navigation hors événement, barre latérale ≥ 1024 px, pastille d'identité), modules JS partagés (thème, feuilles, toasts, copie, révélation, confirmation, anti double envoi), registre `JS_STRINGS`/`#ui-strings`, fin du JS inline de `base.html`.
- `fix(sécurité)` : `events/members.html` ne rend plus les codes personnels qu'au créateur ; l'entrée « Participants » n'est proposée qu'au créateur.
- `refactor(costs)` : confirmations via `data-confirm` (plus de `confirm()` natif).
- `feat(pwa)` : service worker servi à la racine (`/sw.js`, cache versionné par empreinte), page `/offline` autonome, manifest corrigé, mise à jour annoncée par toast ; Alpine (jamais chargé) supprimé.
- `feat(css)` : catalogue de composants `/_ui` (dev uniquement, `UI_CATALOG_ENABLED`).
- `feat(infra)` : outillage `scripts/ui/` (graine de démo jetable, serveur de démo, captures, garde CDP `npm run ui:check`, auto-contrôle `npm run ui:selftest`).
- `fix(css)` : débordements horizontaux de page des pages historiques (N2).

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
