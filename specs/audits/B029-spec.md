# Audit de spec — B029 Contexte d'événement & identité participant unique

- **Date** : 2026-10-06
- **Spec auditée** : `specs/B029-contexte-identite.md` (branche `ui/tailwind-refonte`, base `06278ee`)
- **Auditeur** : agent indépendant, contexte vierge (étape 2 du pipeline `AGENTS.md`)
- **Verdict global (vérification finale du 2026-10-06)** : **APPROUVÉ**. Aucun bloquant ni majeur ne reste ; 1 mineur non bloquant (V1). Historique : audit initial 3 bloquants, 6 majeurs, 12 mineurs ; re-audit 1 majeur (N1) et 6 mineurs ; tous corrigés (voir « Re-audit » et « Vérification finale »).

---

## Constats

| # | Sévérité | Section | Constat (vérifié dans le code) | Correction attendue |
|---|---|---|---|---|
| 1 | **bloquant** | §3.3 étape 1, §8 (tous les tests HTTP) | Le cache « `g.event_ctx` existe et `event.code == code` → réutiliser » **fuit d'une requête à l'autre dans les tests**. La fixture `app` de `tests/conftest.py` garde `with app.app_context(): yield app` ouvert. Avec Flask 3.1.3, `RequestContext.push()` réutilise le contexte d'application déjà poussé s'il s'agit de la même app (`flask/ctx.py`, `if app_ctx is None or app_ctx.app is not self.app`). `g` est donc partagé par toutes les requêtes d'un même test (vérifié : `/set` puis `/get` renvoie `leaked`). Conséquences : `test_events::test_join_success_with_own_code` et `test_my_code_access` (POST, puis redirection suivie vers le tableau de bord) réutiliseraient le contexte visiteur posé par le POST (l'étape 5 pose `g` **avant** les refus), d'où une redirection vers `/mycode` et des tests rouges. Pire, un test qui enchaîne deux identités dans le même test (C3 « après deux requêtes », C20, R7/R9) obtiendrait le rôle de la requête précédente, ce qui peut donner des faux verts sur des tests de droits. En prod (Waitress, un contexte d'app par requête), pas de fuite ; elle existe aussi dans `app.test_request_context()` imbriqué. | Lier le cache à la requête : soit `@app.before_request` qui fait `g.pop("event_ctx", None)` (et le préciser pour les tests unitaires C*, qui doivent ouvrir un `test_request_context()` distinct par « requête »), soit une clé de cache incluant l'identité de la requête (`id(request._get_current_object())`). Ajouter un test : deux requêtes successives, la première en visiteur puis la seconde en invité, dans le même test → la seconde a le rôle `guest`. |
| 2 | **bloquant** | §2.3, §3.5, H2, H3 | La spec est rédigée sur le `base.html` de `06278ee`, alors que **B017 s'exécute avant B029 et réécrit ce fichier** (`specs/B017-socle-tailwind.md` §4.1 et §4.4). (a) B017 ajoute `event_role` à `inject_globals` et `build_nav(…, event_role, …)` l'utilise. Or le `inject_globals` « réécrit » du §3.5 ne fournit pas `event_role` : le shell B017 casse, ou l'agent doit deviner. (b) B017 remplace la pastille par `<span data-testid="identity-chip" data-role="creator\|guest">`, sans attribut `title`, avec le nom du créateur tiré de `current_user.display_name` (ou `_("Organisateur")`), et l'affiche aussi **hors événement** pour un créateur connecté. B029 cite un bloc `title="{{ current_guest.code }}"` qui n'existera plus et ajoute un second `data-testid="participant-chip"`, attendu par H2. Les deux contrats se contredisent : source du nom du créateur, testid, affichage hors événement. | Réécrire §2.3/§3.5 contre le contrat B017 : `inject_globals` conserve `event_role` (= `ctx.role` si `ctx`, `None` pour « visitor » ; hors événement : règle B017 inchangée) ; la pastille garde `data-testid="identity-chip"` et le nom du créateur vient de `current_guest.display_name` (participant) en contexte événement ; supprimer `participant-chip`, ou dire explicitement qu'il remplace `identity-chip` et l'aligner dans B017. Adapter H2/H3. |
| 3 | **bloquant** | §4.2 `run_identity_migration`, §4.5, §4.1 | La sauvegarde est déclenchée par « `check_identity` non vide », pas par « `migrate_identity` changerait quelque chose ». Or `check_identity` signale des anomalies que la migration **ne corrige jamais** : `duplicate_creator_guest` (doublons produits par la course décrite au #10), `list_item_creator_id` d'un autre créateur, `list_item_foreign_guest`, et les auteurs `NULL` d'événements non vérifiés (`media_null_uploader` et `chat_creator_null_guest` n'ont aucun filtre d'événement). Dès qu'une seule de ces lignes existe, **chaque démarrage** (et chaque `manage.py` qui appelle `create_app`) écrit une copie complète de la base dans `instance/backups/`, sans rotation. Ce volume Docker (`holishared_data`) contient aussi les médias, et `/health` passe en 503 à 90 % de disque. De plus, ces copies conservent indéfiniment les événements purgés à J+30 et les e-mails, ce qui contredit la purge « droit à l'oubli » (`Event.activity_logs` cascade, purge automatique). | (1) Déclencher la sauvegarde sur un calcul à blanc des 8 compteurs de `migrate_identity` (somme > 0), pas sur `check_identity`. (2) Écrire une seule sauvegarde par migration effective et fixer une rétention (par exemple, suppression par `_purge_expired_events` des `pre-identity-*.db` de plus de 30 jours) ; documenter que la sauvegarde contient des données personnelles. (3) Aligner les conditions de `check_identity` sur le périmètre de la migration (événements actifs et vérifiés) ou séparer les avertissements (non corrigeables) des corrections. Ajouter les tests : « anomalie non corrigeable → aucune sauvegarde au 2e démarrage » et « rétention ». |
| 4 | **majeur** | §7.6 (limite globale) | `CREATOR_CODE_GLOBAL_LIMIT = "100 per hour"` avec `key_func=lambda: "creator-code"` = **un compteur unique pour tout le site**. Vérifié avec Flask-Limiter 4.1.1 : une fois le quota atteint, **toute** requête est refusée en 429, y compris un code correct (`deduct_when` ne règle que le décompte, pas le contrôle) : la séquence 3 succès, 3 échecs, 1 succès donne `[200,200,200,200,200,429,200]`. Avec la limite existante de 10/h par IP, 10 IP suffisent pour empêcher **tous les créateurs** de se connecter depuis l'accueil, en continu. La spec n'accepte ce plafond que pour le quota par événement, pas pour celui-ci. | Ne pas bloquer globalement. Remplacer par une limite par IP ou préfixe /24 plus stricte sur les échecs (par exemple 5 échecs/h), un seuil global **d'alerte** (journal `app.security` en WARNING au-delà de N échecs/h) sans 429, ou un plafond global beaucoup plus élevé (≥ 1000/h) à documenter comme plafond assumé. Adapter A25. |
| 5 | **majeur** | §7.6 (quota par événement), §9.3 | Le DoS par épuisement du quota d'un événement est confirmé par le test ci-dessus : 30 échecs/h, soit 3 IP à 10 requêtes, bloquent `mycode` **et** `join` pour tous les participants, et ce **indéfiniment** si l'attaquant renouvelle ses requêtes chaque heure. La spec dit « au plus une heure », c'est faux pour une attaque soutenue. La tâche 29.5 demande une limitation « par compte/événement », pas un verrou d'événement entier. | Clé `event:<code>:<ip>` (par exemple 10 échecs/h), plus un plafond par événement nettement plus haut (par exemple 300/h) qui ne bloque qu'au-delà, plus une alerte. Ou, en option, un délai progressif. Corriger le texte « au plus une heure ». Adapter A22–A24. |
| 6 | **majeur** | §7.2, §7.5 (`verify`) | « `form_data["personal_code"]` vaut la saisie s'il y en a une, sinon `suggest_creator_code()` ». Pour un **créateur existant** (même e-mail, nouvel événement : `create()` réutilise le `Creator`), le formulaire est prérempli avec un **nouveau** code aléatoire. S'il valide sans y prêter attention, son `personal_code` est remplacé, et son ancien code ne fonctionne plus pour **tous** ses événements. La règle (a) « l'ancien code reste valable » ne protège que s'il le ressaisit lui-même. | Si `creator.personal_code` existe : ne pas suggérer ; laisser le champ vide, où « vide » veut dire « conserver le code actuel », avec un libellé dédié (nouveau msgid `_()`), et ne jamais afficher l'ancien code dans la page. Ajouter un test : créateur avec code existant, POST sans code → code inchangé. |
| 7 | **majeur** | §10, §1.2-6 (compatibilité B018) | L'inventaire des éléments B018 rendus caducs est **incomplet** : B018 E21 « Événement introuvable. » (6 occurrences : `dashboard`, `members`, `export`, `delete`, `join`, `mycode`) disparaît entièrement avec D12, mais n'est pas listé. E36 « Code invalide. » (`mycode`) dépend d'un comportement que B029 ne spécifie pas (#8). L'ordre du programme cité (« B017 → B029 → B018 ») omet **B030**, qui s'exécute entre les deux selon `TASKS.md` §371. | Ajouter E21 (retiré de B018) et le statut de E36 au §10.7 ; corriger l'ordre (B017 → B029 → B030 → B018) en tête de spec. |
| 8 | **majeur** | §5.1 `my_code`, §7.3, A23 | La réponse d'un échec de `/mycode` n'est pas spécifiée (flash, texte, statut, rendu). `test_events::test_my_code_invalid` exige `b"Code invalide"`, et A23 attend 200. Le POST `/mycode` avec un participant déjà résolu n'est pas spécifié non plus (D15 ne couvre que le GET). Le POST `join` qui atteint le plafond de `can_add_guest` est-il compté comme échec par `mark_attempt_failed` ? « tout POST join refusé par la validation » inclut « Événement complet. », ce qui fait consommer le quota de sécurité par des utilisateurs légitimes. | Fixer : échec `mycode` → `flash("Code invalide.", "danger")` (message existant) puis rendu 200 de `mycode.html` ; POST avec participant → redirection vers le tableau de bord sans résolution ; `mark_attempt_failed` pour `join` **uniquement** sur un code refusé (doublon ou égal au code créateur), pas sur les erreurs de pseudo, d'e-mail ou d'événement complet. |
| 9 | **majeur** | §3.6/§3.7 (exhaustivité de « aucun autre droit ne change ») | Changements de réponse non listés : (a) `export_pdf` par le créateur d'**un autre** événement : 404 aujourd'hui (`filter_by(code, creator_id=_cu.id).first_or_404()`), `/mycode` après B029 ; (b) `export_pdf`, `invite*` et `my_code` sur un événement non vérifié, et `invite`/`invite_email`/`invite_resend` sur un événement **inactif** (aujourd'hui sans filtre `is_active`) → 404, ce qui n'est couvert qu'en partie par D11/D13 ; (c) ordre « objet avant droit » inversé dans `lists.claim_item`/`unclaim_item`/`delete_list`/`toggle_*` et `chat.delete` (aujourd'hui l'objet est chargé avant l'acteur : un visiteur sur un objet inexistant reçoit 404, il recevra `/mycode`) ; seul costs est mentionné (§5.8). (d) `media.gallery` appelle `get_media_quota`, qui écrit (commit) pendant un GET : écriture GET non traitée alors que l'objectif 4 du §1.1 les vise. | Ajouter ces lignes à la table D (ou un D17 « ordre de chargement unifié : contexte → objet → droit, partout ») et préciser le sort de l'écriture de `get_media_quota` (hors périmètre explicite). |
| 10 | mineur | §2.1 I2, §3.3 I3c | « Unicité garantie par l'application » n'est pas vrai sous concurrence : pysqlite n'ouvre la transaction qu'au premier `INSERT`, donc deux requêtes créateur simultanées (deux onglets) passent toutes les deux le `SELECT`, puis insèrent chacune un participant. La seconde requête travaille alors avec un participant non canonique (votes et RSVP rattachés au doublon). | Dans `get_or_create_creator_participant` : après le commit, relire le canonique (le plus ancien) et le renvoyer ; documenter le plafond. `check-identity` signale déjà les doublons. |
| 11 | mineur | §4.1, `manage.py migrate` | `cmd_migrate` appelle `create_app()` **avant** ses `add_col` : la migration d'identité de démarrage s'exécute donc sur un schéma ancien. Si une colonne manque, elle lève une erreur, qui est journalisée puis ignorée. C'est sans gravité, mais la spec doit dire que l'appel explicite se place **après** les `add_col`. `manage.py migrate` utilise `.venv/bin/python`, inexistant en Docker : la doc de retour arrière (§4.6) doit donner la commande Docker (`docker compose exec app python -c …` ou équivalent). | Préciser la position de l'appel et la commande Docker de `check-identity`. |
| 12 | mineur | §4.3 | La création de `Guest` aux étapes 1–2 exige un `session.flush()` avant les étapes 3–8 (l'`id` est une valeur par défaut Python appliquée au flush). Ce n'est pas écrit. Le comportement face à `Creator.display_name` (100 caractères) et `Guest.display_name` (50) n'est pas fixé (troncature ?). | Ajouter « `flush()` après les étapes 1–2 » et « `display_name[:50]` ». |
| 13 | mineur | H1 | Le test « un seul `SELECT … FROM events` » n'est déterministe que si le participant créateur existe déjà. Sinon, le secours I3c fait un commit, `expire_on_commit` recharge `event`, et on obtient 2 `SELECT`. | Préciser : H1 utilise la fixture `creator_guest`. |
| 14 | mineur | §8.9 (tests existants) | Après correction du #1, l'inventaire est juste pour les fichiers relus (`test_module_gating._seed`, `test_logistics` `other`, `test_events` codes 7→8, `test_planning`, `test_chat`, `test_costs`, `test_media`). La phrase « Total prévu : 13 adaptations » doit intégrer celles qu'impliquent #6 et #8. Pour mémoire, `test_freemium::test_cannot_create_event_at_limit` crée un `Event` sans `verified_at`, mais ne fait aucune requête HTTP : c'est sans effet, et à signaler comme « vérifié ». | Mettre à jour la table et les totaux. |
| 15 | mineur | §6.1 HTMX | Une redirection 302 vers `/mycode` dans une requête HTMX (polling du chat sur le tableau de bord) injecte la page `mycode` complète dans le fragment. C'est le comportement actuel, mais la spec dit « (aussi en HTMX) » sans le justifier. | Soit `HX-Redirect` si `HX-Request: true` (réponse 204), soit acter explicitement le comportement actuel comme plafond (B019). |
| 16 | mineur | §7.5 | « Plus d'`IntegrityError` possible » est faux en cas de course entre deux `verify` avec le même code (contrainte `UNIQUE` sur `personal_code`). | Attraper l'`IntegrityError` au commit, faire un `rollback`, puis rendre la même erreur « déjà utilisé ». |
| 17 | mineur | §8.8 T-S2 | La regex `(?<!["'.])\bguest\b(?!["'])` donne des faux positifs sur un msgid contenant « guest » au milieu d'une chaîne, par exemple `{{ _("Add a guest here") }}`, qui seront nombreux après B018. | Retirer d'abord les littéraux de chaîne du bloc Jinja avant d'appliquer la regex. |
| 18 | mineur | §9.2 scopes | Les scopes `meals`, `costs`, `media` et `access` ne figurent pas dans la liste de `AGENTS.md` (auth, events, planning, lists, logistics, voting, chat, models, infra, i18n, pwa, css). Le commit 5 classe `app/access.py` dans `auth`. Le commit 4 (migration) est en `models`, ce qui est acceptable. | Recommandé : ajouter `meals`, `costs`, `media` à la liste des scopes de `AGENTS.md` (déjà utilisés dans l'historique, `5af3d33`) dans un commit `docs` distinct, avant B029. |
| 19 | mineur | §1.3 / B030 | `can_add_guest` compte `event.guests.count()`, ce qui inclut le participant créateur **et les invités inactifs**. La migration et le secours I3c ajoutent un `Guest` aux événements anciens, ce qui décale silencieusement la limite d'invités d'une unité. | Mentionner l'effet dans les risques et le transmettre explicitement à B030 (ou B020) : compter seulement les actifs avec `creator_id IS NULL`. |
| 20 | mineur | §8.1 | La fixture `make_app` pousse un second contexte d'application pendant que celui de la fixture `app` est actif (si les deux sont demandées). Ce n'est pas spécifié : utiliser `make_app` seule. | Préciser que `make_app` ne dépend pas de `app`/`client` et fournit son propre client. |
| 21 | mineur | §7.6 stockage | Le Redis de prod tourne en `maxmemory-policy allkeys-lru` (`docker-compose.yml`) : les compteurs de limitation peuvent être évincés. Si Redis est indisponible, Flask-Limiter lève une erreur, ce qui produit des 500 sur `access`, `mycode` et `join` (pas de `RATELIMIT_IN_MEMORY_FALLBACK_ENABLED`). | Documenter le plafond, ou activer `in_memory_fallback_enabled=True` dans `_create_limiter`, avec un test. |

---

## Vérifications effectuées

| Commande / action | Résultat |
|---|---|
| `grep -rn "def _get_event_or_404\|def _resolve_actor\|def _actor_name\|def _actor\b\|_can_modify\|_can_delete\|_is_event_creator\|_get_current_guest\|ensure_creator_guest\|first_or_404\|Not found\|Pas autorisé" app` | Inventaire du §1.1 confirmé : 6 `_get_event_or_404` + celui de costs (qui renvoie `None`), 8 `_resolve_actor`, 6 `_actor_name` + `_actor` (costs), `_can_modify` (planning, meals), `_can_delete` (chat), `_is_event_creator` (events, freemium), `_get_current_guest` (events) ; 16 « Not found » et 4 « Pas autorisé. » dans costs ; `media.delete` journalise `item.uploaded_by_name`. |
| Lecture de `app/events/__init__.py` | Confirmés : `access_by_code` exige `len == 8` ; `invite*` sans filtre `is_active` ; `invite_qr` sans filtre `is_active` ; `export_pdf` filtré par `creator_id` (404 pour un autre créateur) ; `log` → `/join` et « Not found » ; `dashboard` appelle `ensure_creator_guest` (avec foyer) pendant un GET ; `members remove` peut désactiver le participant créateur. |
| Lecture de `app/utils.py` | `ensure_creator_guest` fait un commit, crée un foyer et filtre `is_active=True` (un participant créateur retiré est **recréé**, pas réactivé). Confirmé. |
| Lecture des gabarits (`grep guest\|is_creator\|current_user\|can_modify\|url_for('module.`) | Confirmés : `dashboard.html` `my_name` avec `.first`, lien « Planifier les repas » → `planning.index`, titre de repas sous la condition `planning`, `lists.toggle_item` sans condition ; `lists/detail.html` compare par nom. `is_creator_guest` n'est pas attrapé par T-S2 (`\b` après `_`). |
| Script `/tmp/…/scratchpad/gtest.py` (Flask 3.1.3) | Contexte d'application externe ouvert + 2 requêtes du client de test → `g.x` défini par la 1re requête est visible dans la 2e (`b'leaked'`). Sans contexte externe : `b'none'`. → constat #1. |
| `inspect.signature(Limiter.limit / shared_limit / reset)` (Flask-Limiter 4.1.1, limits 5.8.0) | `methods`, `deduct_when`, `scope` et `key_func` existent sur les deux décorateurs ; `reset()` sans argument. L'API citée est valide. |
| Script `/tmp/…/scratchpad/lim.py` : `shared_limit("3 per hour", deduct_when=failed)` + `limit("100 per hour")` | Les succès ne décomptent pas ; après 3 échecs, un code **correct** reçoit 429 ; un autre événement reste à 200 ; `reset()` remet à zéro. → constats #4 et #5 ; A22–A24 sont réalisables tels qu'écrits. |
| Lecture de `tests/conftest.py` et de chaque fichier de test (grep ciblé + lecture de `test_events`, `test_freemium`, `test_privacy`, `test_meals`, `test_hardening`) | Seuls `conftest.event`, `test_module_gating._seed` et `test_logistics` `other` construisent un `Event` utilisé en HTTP ; `test_freemium` en construit un sans requête. `test_my_code_invalid` dépend de « Code invalide » (#8). |
| Lecture de `Dockerfile`, `docker-compose.yml`, `manage.py` | Un seul processus Waitress (`--threads 4 --call app:create_app`), donc une migration par démarrage, sans course entre workers ; utilisateur `appuser` propriétaire de `/app/instance` (volume) : la sauvegarde y est inscriptible. `cmd_migrate` appelle `create_app()` avant les `add_col` (#11). Redis en `allkeys-lru` (#21). |
| Lecture de `specs/B017-socle-tailwind.md` §4.1, §4.4, §7.11 | `event_role` dans `inject_globals`, pastille `identity-chip` sans `title`, `Math.random` laissé à B029, `dashboard.html` utilise `guest.id` pour l'id du code. → constat #2. |
| `grep` dans `specs/B018-i18n.md` (E1, E17, E21, E33, E36, E37, C2–C4, P2, P5, L4, L5, G5, V3, V4, H2, D10, U1, §2.9, ligne 1488) | Les références citées au §10 existent et sont correctes ; E21 et E36 manquent (#7). Le SQL de §2.9 (lignes 334–335) correspond bien aux deux conditions à réécrire. |
| Exécution mentale de `migrate_identity` sur 3 états | **Base vide** : 0 partout, et `check_identity` vide, donc pas de sauvegarde. **Base héritée** (événement vérifié sans participant, `created_by NULL`, `assigned_to_id = Creator.id`) : étapes 1/2, puis 3–8 ; un seul commit ; le 2e passage donne des zéros (M14). **Base déjà migrée avec doublon de participant ou article étranger** : `migrate_identity` donne 0, mais `check_identity` n'est pas vide, d'où une sauvegarde à **chaque** démarrage (#3). |

## Points confirmés

- Le diagnostic du §1.1 est exact sur tous les points vérifiés (8 copies, variantes costs/media, écritures pendant un GET, F32, `access_by_code` à 8 caractères, `invite_qr` sans `is_active`, codes réservés `access`/`verify`).
- Le choix d'une fonction plutôt qu'un décorateur, et l'absence de paramètre `module=` (blueprint non enregistré → 404 par le routage), sont justes et cohérents avec `test_module_gating`.
- La priorité créateur > invité et le refus d'une session invité qui pointe vers un participant créateur ferment l'élévation actuelle : aujourd'hui, `/mycode` accepte le jeton du `Guest` créateur. L'exclusion `creator_id IS NULL` dans `resolve_event_code` est correcte.
- Aucun IDOR entre événements : tout objet est rechargé avec `event_id=ctx.event.id` ; `members remove` filtre déjà par événement.
- D2 (créateur non retirable), D6 et D7 (403/404 rendus par gabarit) et D10 (journal de l'acteur qui supprime) corrigent de vrais défauts.
- La migration en ORM uniquement, avec un seul commit, un `rollback` et des étapes conditionnées par la valeur héritée, est idempotente pour tout ce qu'elle corrige. Le retour arrière « code seul » est valable (les anciens contrôles acceptent un `Guest.id`).
- La sauvegarde par `sqlite3.backup` est compatible WAL ; l'exécution au démarrage dans un seul processus Waitress est acceptable (temps négligeable, erreurs absorbées par le `try/except` comme la purge), sous réserve du #3.
- La priorité « code d'événement avant code créateur » sur l'accueil est correcte : les codes d'événement font 6 caractères, une collision avec un ancien code créateur de 6 caractères est possible et l'événement doit gagner ; D16 offre la reconnexion.
- L'API Flask-Limiter citée existe ; « seuls les échecs comptent » fonctionne comme décrit (vérifié).
- Les tests nommés suivent `test_<comportement>_<condition>_<résultat>`, avec un assert principal ; aucune suppression de test n'est prévue.
- Les commits sont atomiques et ordonnés, chacun avec ses tests ; le commit de clôture est conforme.

---

## Résumé

- **Verdict : À CORRIGER**. 21 constats : 3 bloquants, 6 majeurs, 12 mineurs.
- **#1 (bloquant)** : le cache `g.event_ctx` fuit entre les requêtes d'un même test (Flask 3.1 réutilise le contexte d'app de la fixture). Des tests existants deviennent rouges (`join`/`mycode` puis tableau de bord) et les tests de droits peuvent passer à tort. Il faut purger le cache à chaque requête.
- **#2 (bloquant)** : la spec ignore le `base.html` et le `inject_globals` de B017 (`event_role`, pastille `identity-chip` sans `title`), alors que B017 passe avant. L'interface est à réaligner.
- **#3 (bloquant)** : la sauvegarde est déclenchée par `check_identity`, qui signale aussi des anomalies que la migration ne corrige jamais. Résultat : une copie complète de la base à chaque démarrage, sans rotation, avec des données personnelles conservées au-delà de la purge.
- **Majeurs** : limite globale de 100/h qui bloque tous les créateurs (DoS trivial, vérifié) ; quota par événement épuisable en continu ; code d'un créateur existant écrasé par la suggestion ; inventaire B018 incomplet (E21) et ordre sans B030 ; réponse d'échec de `mycode` non spécifiée ; changements de réponse non listés (`export_pdf`, ordre objet/droit).


---

## Re-audit (2026-10-06)

Version relue : `specs/B029-contexte-identite.md` corrigée (1184 lignes, traçabilité au §11.1), comparée à la version **actuelle** de `specs/B017-socle-tailwind.md`.

### Statut des 21 constats initiaux

| # | Sév. initiale | Statut | Vérification |
|---|---|---|---|
| 1 | bloquant | **corrigé** | `reset_event_context` est enregistré par `app.before_request` (§3.3). Les tests unitaires ouvrent un `test_request_context` par requête simulée. C27 et H26 sont testables. Vérifié à blanc : avec un contexte d'application externe ouvert et le hook, la 2e requête voit `None`. |
| 2 | bloquant | **corrigé** | §3.5 et §3.8 sont conformes au B017 actuel : `event_role` (règle §4.1 de B017), `current_guest` = invité seul, une seule pastille `identity-chip`, badge et nom de repli `_("Créateur")` identiques à B017 §4.4, appel `build_nav(...)` inchangé, respect du « Contrat à conserver par B029 » (B017 §4.6). Ajouts sans collision (`ctx`, `current_participant`). H2 et H3 sont cohérents avec le helper `text_of` de B017. |
| 3 | bloquant | **corrigé** | La sauvegarde dépend de `plan_identity_migration` (somme > 0). `check_identity` est en lecture seule et son périmètre est aligné. Rotation à 3, purge à 30 jours, `0o600`, emplacement hors médias et hors export. Tests M23–M28. Réserve mineure N5. |
| 4 | majeur | **corrigé** | Plus de compteur global bloquant. Quotas d'échecs par IP et par (IP, événement), alerte sans 429. Vérifié : les échecs d'une IP ne bloquent pas une autre IP. Réserves mineures N2 et N3. |
| 5 | majeur | **corrigé** | Plus de verrou d'événement : `ip_event_key` + `shared_limit`, paliers progressifs. Le texte « au plus une heure » est supprimé. A22–A25 sont réalisables. |
| 6 | majeur | **corrigé** | `has_existing_code` : pas de suggestion, champ non requis, champ vide = code conservé, code jamais affiché (§7.2, §7.5 a–d). Tests A43, A44. |
| 7 | majeur | **corrigé** | Ordre avec B030 en tête et au §10. E21, E1 et E36, ainsi que les 3 flashes de meals, sont ajoutés (§10.2-7/8). |
| 8 | majeur | **corrigé** | `mycode` : flash existant « Code invalide. », rendu 200, décompte ; POST avec participant → redirection sans décompte (D15) ; `join` ne compte que les refus de code. Tests A38, A41, A42. |
| 9 | majeur | **corrigé** | D17–D20 sont présents et testés (H27, H29–H31). D20 (« inchangé, B030 ») est une décision ferme et cohérente avec TASKS B030. |
| 10 | mineur | corrigé | Relecture du participant canonique (I2) ; C28. |
| 11 | mineur | corrigé | Appel placé après les `add_col` ; `python -m app.migrations check` ; commandes de restauration Docker. |
| 12 | mineur | corrigé | `flush()` après les étapes 1–2 et troncature `[:50]` (migration et `ensure_creator_guest`) ; M29. |
| 13 | mineur | corrigé | H1 utilise `creator_guest`. |
| 14 | mineur | **partiel** | Totaux recomptés et exacts. En revanche, la liste des adaptations omet des tests **B017** qui seront rouges après D11 (voir N1). |
| 15 | mineur | corrigé | Réponse 204 + `HX-Redirect` en HTMX (§3.3, §6.1) ; C29, H28. `abort(Response(...))` est valide. |
| 16 | mineur | corrigé | `IntegrityError` attrapée au commit de `verify`, `rollback`, erreur « déjà pris » ; A45. |
| 17 | mineur | corrigé | Les littéraux de chaîne sont retirés avant la regex de T-S2. |
| 18 | mineur | corrigé | Commit 0 `docs` qui ajoute les scopes. Réserve mineure N7 (phrase contradictoire). |
| 19 | mineur | corrigé | Effet sur la limite d'invités documenté et transmis à B030. |
| 20 | mineur | corrigé | `make_app` supprimée ; `app_factory` (B017) utilisée seule, sans `app`/`client`. |
| 21 | mineur | corrigé | `in_memory_fallback_enabled=True` + `swallow_errors=True`. Vérifié avec Flask-Limiter 4.1.1 et un Redis injoignable (`redis://127.0.0.1:6399`) : pas de 500, limites appliquées en mémoire (`[200, 200, 429, 429]` pour `2 per minute`). Éviction LRU documentée. |

### Recomptes

- Tests : C1–C29 (29), H1–H31 (31), R1–R22 (22), M1–M29 (29), A1–A45 (45), L1–L6 (6), T-S1–T-S4 (4), soit **166**. C'est conforme au total annoncé. La numérotation est continue et sans doublon.
- 36 critères d'acceptation, chacun relié à des tests. La table D1–D20 est cohérente avec §5 et §9.1-13.
- Les 13 lignes du §8.9 sont exactes pour les tests actuels du dépôt, mais incomplètes vis-à-vis des tests B017 (N1).

### Nouveaux constats

| # | Sévérité | Section | Constat | Correction attendue |
|---|---|---|---|---|
| N1 | **majeur** | §3.8 (données de démo), §8.9, CA 34/35 | **Adaptations B017 manquantes ou inapplicables après D11.** (a) Les tests B017 **T16** et **T17** (`app_factory(...)`, « créateur + événement créés dans le test », `GET /e/{code}/planning` et `/members`) créent un `Event` sans `verified_at` : après D11, réponse 404, donc tests rouges. Ils ne figurent pas dans les 13 adaptations, et CA 34 dit « les 13 adaptations ». (b) La scène `ui:check` `event-unverified` (B017 §8, `expect.nav: event`, rôle `creator`) recevra une page 404 en contexte `global`, et une requête 404 est comptée comme erreur console par la garde (B017 §4.2). La consigne « son scénario est adapté pour attendre 404 », de plus au conditionnel « si », est **inapplicable** : le format des scènes n'a aucun champ de statut HTTP (champs `id, lot, role, path, scope, expect.nav, …, skip`). | Ajouter à §8.9 : T16 et T17 (B017) reçoivent `verified_at=datetime(2026, 1, 1)` sur l'événement créé, et porter le total à 15 adaptations. Pour la scène : décision ferme, par exemple remplacer `path` par `/e/new/sent/{event.unverified}` (`verify_sent`, qui reste à 200) avec `expect.nav: global`, `lot: B029`, ou supprimer la scène ; la graine (T94, T96) reste inchangée. Rendre CA 35 inconditionnel. |
| N2 | mineur | §7.6 | `limiter.limit(IP_FAILURE_LIMIT, …)` posé sur trois routes crée **trois compteurs distincts** : un `limit()` non partagé est indexé par endpoint (vérifié : 3 échecs sur `/a` → 429 ; `/b` reste à 200). La phrase « par IP, toutes cibles » et le plafond « 30 échecs par jour en tout » sont donc faux : c'est 30 par jour **et par route**, soit 90. | Utiliser `limiter.shared_limit(IP_FAILURE_LIMIT, scope="ip-failures", …)` sur les trois routes, ou corriger le texte du plafond. |
| N3 | mineur | §7.6 « Ce qui reste possible » | « Aucune attaque ne peut empêcher un participant légitime, depuis sa propre IP… » est vrai par IP, mais les participants d'un même séjour partagent souvent **la même IP publique** (box du lieu, CGNAT mobile). 3 fautes de frappe bloquent toute la maison 1 minute, 10 la bloquent 15 minutes. | Documenter ce plafond explicitement (usage réel, non malveillant), et éventuellement relever le premier palier (par exemple 5 par minute). |
| N4 | mineur | §7.6 alerte | `mark_attempt_failed` appelle `limiter.limiter.hit(limits.parse(...))` : l'API existe (vérifié : `FixedWindowRateLimiter.hit` renvoie `True`). Deux réserves : (1) `limits` est importé directement alors que ce n'est qu'une dépendance transitive (règle AGENTS : toute dépendance utilisée figure dans `pyproject.toml`) ; (2) cet appel direct n'est pas couvert par `swallow_errors`, donc une erreur de stockage pourrait remonter jusqu'à la vue. | Déclarer `limits` dans `pyproject.toml` (ou passer par l'API Flask-Limiter) et entourer l'appel d'alerte d'un `try/except` journalisé. |
| N5 | mineur | §4.2 Rétention | « Aucune [sauvegarde] de plus de 30 jours » n'est garanti qu'au **démarrage** (`_purge_expired_events` et `run_identity_migration`). Un processus Waitress qui tourne plus de 30 jours conserve la sauvegarde au-delà. | Reformuler (« supprimée au premier démarrage après 30 jours ») ou ajouter une purge périodique. |
| N6 | mineur | §4.2 `plan_identity_migration` | La règle « un événement qui recevrait un participant créateur aux étapes 1–2 est compté comme s'il l'avait déjà » ne précise pas l'étape `list_items_from_name` : un article dont la **seule** correspondance de nom est ce futur participant créateur n'est pas compté à blanc, alors que `migrate_identity` l'attribue. Les compteurs diffèrent, sans effet sur la décision de sauvegarde (l'étape 2 est déjà > 0). | Préciser que le futur participant (nom = `creator.display_name or CREATOR_FALLBACK_NAME`) entre dans la comparaison de nom du calcul à blanc, ou dire que seules la somme nulle ou non nulle fait foi. Option : un test `plan == migrate` sur la base héritée de M27. |
| N7 | mineur | §9.2 | La phrase « B029 ne modifie pas `AGENTS.md` dans cette spec » contredit le commit 0, qui modifie `AGENTS.md`. | Reformuler : « le commit 0, préalable et isolé, modifie seulement la liste des scopes de `AGENTS.md` ». |

### Vérifications du re-audit

| Action | Résultat |
|---|---|
| `scratchpad/re1.py` : hook `before_request` qui vide `g.event_ctx`, client de test dans un `app_context` ouvert | 2e requête : `b'None'`. Le correctif du #1 est efficace. |
| `Limiter(storage_uri="redis://127.0.0.1:6399/0", in_memory_fallback_enabled=True, swallow_errors=True)`, `2 per minute`, `deduct_when` | `[200, 200, 429, 429]` : aucune erreur 500, limites appliquées en mémoire (#21). |
| `lim.limiter.hit(limits.parse("2 per hour"), "target-alert", "abc")` | `FixedWindowRateLimiter`, `True` : API valide (N4). |
| Deux routes avec le même `limit()` non partagé | `/a` → `[200, 200, 429]`, `/b` → 200 : compteurs par route (N2). |
| `grep` B017 : `event_role`, `identity-chip`, `current_guest`, `app_factory`, `creator_client`, `guest_client`, `_("Créateur")`, contrat §4.6, scènes, T16/T17 | Contrat §3.8 conforme. Écarts : T16/T17 et scène `event-unverified` (N1). |
| Exécution à blanc de `plan_identity_migration` / `migrate_identity` sur 3 états | Base vide : 0, pas de sauvegarde. Base héritée : somme > 0, d'où sauvegarde, rotation, puis migration. Base migrée avec doublon : 0, pas de sauvegarde (M24). Seul écart : N6. |
| Recompte des tests et des critères | 166 tests, 36 critères ; numérotation continue. |

### Verdict du re-audit

**À CORRIGER** : les 3 bloquants et les 6 majeurs initiaux sont corrigés, mais il reste un majeur nouveau, **N1** (tests B017 T16/T17 et scène `ui:check` rouges après D11, avec une consigne inapplicable). La spec sera approuvable dès que N1 sera corrigé : les mineurs N2–N7 et le #14 (partiel) peuvent être traités dans la même passe sans nouvel audit complet.


---

## Vérification finale (2026-10-06)

Vérification ciblée des constats N1–N7 (traçabilité au §11.3 de la spec), contre la version actuelle de `specs/B017-socle-tailwind.md`.

### Constats N1–N7

| # | Statut | Vérification dans le corps de la spec |
|---|---|---|
| N1 | **corrigé** | Côté B017 (version actuelle) : T16 et T17 créent l'événement avec `verified_at=datetime.utcnow()` (lignes 1501–1502) ; la graine ne garde que `unverified` comme événement non vérifié, avec le placeholder `token.unverified` ; la scène `event-unverified` vise `/e/verify/{token.unverified}` (`expect.nav: global`, anonyme) et la scène `verify-sent` vise `/e/new/sent/…`. Aucune page `/e/<code>/…` d'un événement non vérifié n'est visitée. Côté B029 : les critères 34 et 35 sont inconditionnels, et H32/H33 reproduisent les scénarios T16/T17. |
| N2 | **corrigé** | `IP_FAILURES = limiter.shared_limit(..., scope="ip-failures")` est appliqué aux trois routes (§7.6), et la raison est écrite (un `limit()` simple serait indexé par route). Test A47. Vérifié à blanc : 3 échecs sur `/access` → 429 sur `/e/<code>/mycode` avec le même objet `shared_limit`. |
| N3 | **corrigé** | Paliers par (IP, événement) `5 per minute;10 per 15 minutes;15 per hour;30 per day`. Le compromis de l'IP partagée est documenté. |
| N4 | **corrigé** | `limits>=5.0` est déclaré dans `pyproject.toml` et `requirements.txt` ; l'alerte est sous `try/except`, journalisée en `code_target_alert_failed` ; test A46. |
| N5 | **corrigé** | La purge a lieu à chaque sauvegarde, à chaque démarrage et à chaque `manage.py migrate`. La garantie est reformulée exactement et le plafond est assumé ; test M30. |
| N6 | **corrigé** | Une seule implémentation `_run_identity_steps(apply=…)`, avec le participant prévu en sentinelle utilisé aussi dans la comparaison de nom : les compteurs à blanc sont identiques à ceux de la migration ; test M31. |
| N7 | **corrigé** | §9.2 : le commit 0, isolé, modifie seulement la liste des scopes de `AGENTS.md`. |
| #14 | **corrigé** | Les tests B017 sont traités par N1 (vérifiés, non modifiés par B029). |

### Cohérence des paliers

- §7.6 définit `IP_FAILURE_LIMIT = "20 per 15 minutes;50 per day"` (en tout) et `TARGET_FAILURE_LIMIT = "5/min;10/15 min;15/h;30/jour"`.
- **A22** (6e échec, même IP et même événement, dans la minute → 429), **A24** (5 échecs `mycode` puis `join` refusé → 429), **A36** (21e échec sur `/e/access` → 429) et **A47** (20 échecs sur `access` puis 1 sur `mycode` → 429) sont cohérents avec ces valeurs. **A46** est cohérent avec la protection de l'alerte.
- Critères **21** (calcul à blanc identique), **22** (purge), **27** (5/minute, `shared_limit`), **34** et **35** (B017 vert sans condition) : cohérents avec le corps de la spec.
- Le texte « 30 échecs par jour et par événement, 50 par jour en tout » est cohérent avec les constantes.

### Décomptes

- Tests : C 29 + H 33 + R 22 + M 31 + A 47 + L 6 + T-S 4 = **172**. Conforme au total annoncé ; numérotation continue.
- **36** critères d'acceptation : conforme.

### Constat résiduel (non bloquant)

| # | Sévérité | Constat | Correction suggérée |
|---|---|---|---|
| V1 | mineur | Le drapeau `g.code_attempt_failed`, lu par `attempt_failed`, n'est pas remis à zéro par `reset_event_context`. Il fuit donc entre les requêtes d'un même test, à cause du contexte d'application ouvert par la fixture (même mécanisme que le constat #1). Vérifié à blanc : après 1 échec, des succès depuis la même IP sont décomptés et finissent en 429 (`[200, 200, 429, 429]` pour 3 par 15 minutes). Aucun test prévu ne devient rouge, car les séquences A22–A47 placent les succès avant les échecs ou sur une autre IP. En production, il n'y a pas de fuite (un contexte d'application par requête). | Dans le hook `before_request`, faire aussi `g.pop("code_attempt_failed", None)` (ou un hook dédié dans `app/access.py`). L'agent de codage peut l'appliquer sans nouvel audit. |

### Nouveaux bloquants ou majeurs

Aucun.

### Verdict final

**APPROUVÉ**. Aucun constat bloquant ni majeur ne reste ouvert. V1 est un mineur à intégrer pendant le codage.
