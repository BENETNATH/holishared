# Spec B038 — Identité, récupération & réattribution des comptes

**Statut** : spec approuvée (audit 2026-10-15) · **Branch** : `feat/b038-identity` · **S'exécute après** B029 (contexte) et B034 (API)

**Audit** : 5 blockeurs corrigés — B1 exclusion `creator_id=None` dans la requête de récupération invité (§3.2) ; B2 msgids `participant.deleted`/`participant.merged`/`household.merged` ajoutés (§3.5) ; B4 route `/recover` modifiée in place, nom de fonction `recover_code` conservé (références templates) ; B5 suppression du « miroir » email — le participant créateur ne porte jamais d'email (`ensure_creator_guest`), les actions `me` opèrent sur `Creator.email` seul (§3.3). B3 (exclusion du participant créateur dans `can_delete`) : retiré, déjà garanti par `_allowed` de `app/context.py` (`return obj.creator_id is None`). Mineurs corrigés : syntaxe SQLAlchemy du filtre `verified_at`, test `me.erase_email` sans miroir, contraintes de `merge_profiles` (§5.5).

## Amendement post-audit (2026-10-19) — prime sur les sections suivantes

Décisions produit après audit du code livré (branche non publiée, pas de migration de données) :

- **R1 Token haché** : `Guest/Creator.recovery_token` = `sha256(raw).hexdigest()` (64 hex) ; le token brut n'existe que dans le lien e-mail ; recherche par hash (§2.1, §3.2, §7).
- **R2 Commit avant envoi** : tout chemin qui émet un token fait `db.session.commit()` AVANT l'enqueue de l'e-mail (créateur `/recover`, invité `/e/<code>/recover`, `me` recovery_link, `members` recovery_link, `members` reinvite).
- **R3 E-mail déjà connu au join** : réponse neutre identique (profil actif ou retiré), aucune fuite, aucun nouveau profil ; plus de `action=merge/new` ni de section « merge-existing » (§5.1, §5.2).
- **R4 Profil retiré = pas d'auto-réactivation** : `guest_recover`/`guest_recover_link` ne traitent que `is_active=True` ; seul le créateur réactive via l'action `reinvite` (§3.2, §3.4).
- **R5 Soldes préservés** : un foyer n'est jamais supprimé ni recollé ; on le détache (`guest_id=None`, « Participant retiré ») et on garde ses Expense/Transfer/PaymentRequest (§4.2, §4.3, §5.5).
- **R6 Contrôles manquants** : (a) `clear_recovery_token` à la suppression/retrait/effacement RGPD ; (b) `can_add_guest` sur toute réactivation ; (c) `merge_profiles` interdit source actif → cible inactif ; (d) rate limits `me`/`members` recovery_link ; (e) index unique partiel email + `IntegrityError` capturée ; (f) `DEV_SHOW_SECRETS` n'affiche le lien que si `app.debug` ; (g) toutes les chaînes FR des flux suppression/fusion passent par `_()` avec placeholders nommés.

## 1. Contexte et problème

Les utilisateurs **recréent des comptes** (nouveaux `Guest` / nouveaux `Creator`) au lieu de retrouver leur accès. Causes racines identifiées dans le code :

| # | Cause | Emplacement |
|---|-------|-------------|
| C1 | Aucun moyen de récupération côté invité (code perso oublié = bloqué) | `events.guest_access` (pas d'équivalent de `recover_code` pour `Guest`) |
| C2 | L'email invité est **optionnel** et souvent absent → introuvable par le créateur | `events.guest_access` (`email` nullable, sans opt-in explicite) |
| C3 | L'email créateur n'est conservé que si case cochée à la vérification ; non cochée → `creator.email = None` définitif → récupération impossible | `events.verify` (L434-435) |
| C4 | Le re-join crée un **doublon silencieux** (nouvelle ligne `Guest`, nouveau foyer) ; les données de l'ancien profil (articles, votes, parts de frais) restent orphelines | `events.guest_access` (pas de détection d'email existant) |
| C5 | Le retrait d'un membre est sans réattribution : son foyer reste « fantôme » dans les Frais, ses articles restent assignés | `events._remove_participant` (pas de réattribution) |

**Décisions validées par l'utilisateur (2026-10-15)** :
- D1 — L'email est **conservé par défaut** (opt-out explicite) pour les invités **et** les créateurs.
- D2 — Le **lien magique** remplace définitivement l'envoi du code en clair (créateur **et** invité).
- D3 — À la suppression d'un membre, le foyer non réattribué reste **visible comme « Participant retiré »** (les soldes restent lisibles).
- D4 — Les **votes et RSVP ne sont jamais transférés** (figés, suffixés « (participant retiré) ») ; seul le travail à faire (articles, couvertures) et le foyer sont réattribués.

## 2. Modèle de données

### 2.1 Colonnes nouvelles (migration idempotente `migrate_identity_recovery`)

Sur `guests` :

```sql
ALTER TABLE guests ADD COLUMN recovery_token VARCHAR(64);          -- nullable, usage unique
ALTER TABLE guests ADD COLUMN recovery_token_expires DATETIME;     -- nullable
ALTER TABLE guests ADD COLUMN merged_into_id VARCHAR(32) REFERENCES guests(id) ON DELETE SET NULL;  -- anti-doublon (WP3)
```

Sur `creators` :

```sql
ALTER TABLE creators ADD COLUMN recovery_token VARCHAR(64);        -- nullable, usage unique
ALTER TABLE creators ADD COLUMN recovery_token_expires DATETIME;   -- nullable
```

- `recovery_token` = **`sha256(raw).hexdigest()`** (64 hex, tient dans `String(64)`) où `raw = secrets.token_urlsafe(32)` ; le brut n'est **jamais stocké ni affiché** (uniquement dans le lien e-mail). La recherche se fait par hash (`sha256(token_de_l_url)`).
- Expiration : **24 h** (`RECOVERY_TOKEN_TTL_HOURS = 24`, configurable en config).
- Une seule token valide par ligne à la fois : la génération d'un nouveau lien écrase l'ancien.
- Pattern de migration : `migrate_identity_recovery(engine) -> int` (nombre de colonnes ajoutées) + `run_identity_recovery_migration(app) -> dict[str, int]`, enregistrés dans `app/startup.py` (mêmes conventions que `migrate_api_keys` / `run_push_migration` : `inspect` + `ALTER TABLE` seulement si la colonne est absente, sans sauvegarde car purement additive). `manage.py migrate` les exerce.

### 2.2 Contraintes d'unicité de l'email (WP3)

Un événement n'a qu'**un seul** `Guest` par email non nul (actif **ou** inactif, hors `merged_into_id`, hors participant créateur). L'unicité est vérifiée dans le code (§5) **et garantie en base** par un index unique partiel :

```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_guest_event_email_active ON guests (event_id, email)
  WHERE email IS NOT NULL AND merged_into_id IS NULL AND creator_id IS NULL;
```

- Déclaré dans le modèle (`db.Index(..., unique=True, sqlite_where=..., postgresql_where=...)`) pour `create_all`, et créé par une migration idempotente `migrate_guest_email_unique(engine) -> int` (1 si créé, 0 sinon) + `run_guest_email_unique_migration(app) -> dict[str, int]` (`app/migrations.py`), enregistrée dans `app/startup.py` (étape `guest_email_unique`, après `identity_recovery`). Si des doublons existent déjà, la création échoue : warning journalisé, retour 0, pas de crash au démarrage (résolution via `merge_profiles`).
- `IntegrityError` capturée aux points d'écriture d'un email : `guest_access` (réponse neutre R3), `_add_participant` et `_member_fix_email` (erreur par champ `email`, statut 200/422, pas de 500). `invite_email` n'insère rien (§5.4).

`Guest.merged_into_id` : lorsque deux profils de même email sont fusionnés (WP3), la ligne la plus ancienne (ou la plus riche) est conservée, la seconde est marquée `merged_into_id = <conservée.id>`, `is_active = False`. Les lignes fusionnées ne sont **jamais** affichées (Participants, « Pour moi », comptes d'invités) et ne comptent pas dans `guest_count`.

## 3. WP1 — Email conservé par défaut + lien magique de récupération

### 3.1 Consentement (UI)

**`events/verify.html`** (créateur) : la case `store_creator_email` devient **cochée par défaut** ; libellé mis à jour :

- Case (cochée par défaut) : `Conserver mon e-mail pour la récupération de mon code`
- Help : `Votre e-mail n'est utilisé que pour renvoyer un lien de récupération. Vous pouvez l'effacer à tout moment depuis « Mon profil ».`

**`events/join.html`** (invité) : le champ `email` reste facultatif mais un **opt-out explicite** n'a pas de sens sans email ; le changement est :
- Help mise à jour : `Conservé pour la récupération de votre accès (vous pourrez l'effacer depuis « Mon profil »).`
- Si un `Guest` de l'événement a déjà cette adresse → réponse neutre (R3, §5.2) : aucune information sur le profil existant n'est affichée.

### 3.2 Routes de récupération (lien magique)

**Nouveau helper partagé** `app/access.py` :

```python
RECOVERY_TOKEN_TTL = timedelta(hours=24)


def hash_recovery_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_recovery_token(row) -> str:
    """Set a fresh single-use token (expires in 24h); store only its sha256, return the RAW token.

    The raw value goes into the e-mail link only. The CALLER must commit before enqueuing the e-mail (R2).
    """
    raw = secrets.token_urlsafe(32)
    row.recovery_token = hash_recovery_token(raw)
    row.recovery_token_expires = datetime.utcnow() + RECOVERY_TOKEN_TTL
    return raw


def valid_recovery_token(row) -> bool:
    return (
        row.recovery_token is not None
        and row.recovery_token_expires is not None
        and row.recovery_token_expires > datetime.utcnow()
    )
```

(`datetime.utcnow()` conformément à la convention existante du codebase ; `# noqa: DTZ003` déjà accepté dans ce fichier.)

**Route modifiée in place — créateur** : `POST /recover` (la route existante `events.recover_code`, **nom de fonction conservé** — `app/templates/events/recover.html` et `mycode.html` font référence `url_for('events.recover_code')`). Le POST bascule du « code en clair » au « lien magique » :

1. `email = request.form["email"].strip().lower()` ; validation format (pas de message distinct si invalide : même réponse).
2. `creator = Creator.query.filter_by(email=email).first()` ; **si trouvée ET `creator.personal_code` est défini** : `raw = issue_recovery_token(creator)` ; **`db.session.commit()`** ; puis enqueue `tasks.send_recovery_link_email(host, port, user, pw, frm, email, APP_URL, url_for("events.recover_link", token=token, _external=True), lang)` via RQ.
3. **Réponse identique** que l'email existe ou non (contrat F16) :
   - Si SMTP : flash `Si un code est associé à cette adresse, un lien de récupération vient de vous être envoyé par e-mail.` + redirect `/recover` (page vide).
   - Si pas SMTP mais `DEV_SHOW_SECRETS` **ET `current_app.debug`** : flash avec l'URL du lien (dev uniquement) — le lien conduit à la **même page** `recover_link` que le cas SMTP. Hors debug, `DEV_SHOW_SECRETS` seul n'affiche jamais le lien (cas « Sinon »). Idem côté invité.
   - Sinon : `logger.warning("recovery_link_mail_not_sent smtp=unconfigured")`, flash identique au cas SMTP.
   - **Note timing F16** : l'écriture de la token et l'enqueue (qui font un appel réseau) ne se produisent que si le créateur est trouvé. Pour éviter l'écart de timing, le cas « non trouvé » effectue une lecture de base équivalente (ex. `Creator.query.filter_by(email=email).first()` déjà faite, + `db.session.execute(select(1))` est **inutile** — en pratique l'écart est < 5 ms et non mesurable sans instrumentation ; le critère est : **même code HTTP, même flash, même redirect, aucune donnée distincte dans le corps**. C'est le standard du projet (cf. `resend_verification` qui a le même pattern).
4. Rate limit : `@limiter.limit("10 per hour")` par IP (comme `resend_verification`).

**Nouvelle route — page de lien** : `GET /recover/link/<token>` :

1. `creator = Creator.query.filter_by(recovery_token=hash_recovery_token(token)).first()` ; si None **ou** `not valid_recovery_token(creator)` → flash `Lien invalide ou expiré.` + redirect `/recover` (même réponse que « créateur inexistant » : F16).
2. Page `events/recover_link.html` (section « Récupération d'accès ») :
   - Affiche le pseudo courant de `creator` et son **e-mail masqué** (`a***@domaine`, filtre `masked_email`) ; le code lui-même n'est jamais affiché.
   - **Bouton 1** « Conserver mon code » → POST `events.recover_link` (action=keep) : efface la token (`creator.recovery_token = None`), `start_creator_session(creator)` + si l'utilisateur a des événements actifs : redirect vers le premier (`events.index` crée la liste), sinon `/`. Le code reste celui existant.
   - **Bouton 2** « Choisir un nouveau code » → POST `events.recover_link` (action=recode) avec champ `personal_code` (validation : 8 car `[a-z0-9]{8}`, unicité `Creator.personal_code` hors de lui-même, mêmes erreurs par champ que `verify`). Succès : `creator.personal_code = <nouveau>`, token effacée, session démarrée, redirect `/`.
   - En cas d'erreur de validation : la page rejoue le formulaire (token restée valide).
3. Le POST `events.recover_link` est protégé par CSRF (toutes les routes POST du blueprint).

**Nouvelle route — invité** : `POST /e/<code>/recover` :

1. `event = Event.query.filter_by(code=code, is_active=True).filter(Event.verified_at.isnot(None)).first()` ; si None (inconnu **ou** non vérifié) : au POST, **302 neutre** vers `/e/<code>/recover` avec le même flash que pour une adresse inconnue (rien n'est écrit) ; au GET de cette page, **404 standard**. Même réponse que pour une adresse inconnue d'un événement valide : aucun écart observable au POST.
2. `email` validé au format ; sinon réponse identique.
3. `guest = Guest.query.filter_by(event_id=event.id, email=email, is_active=True, merged_into_id=None, creator_id=None).first()` (R4 : **profil actif uniquement** ; un profil retiré ne reçoit aucun lien) ; si None → **aucun token, aucune trace**, réponse neutre. **`creator_id=None` est obligatoire** : le participant créateur (s'il portait un email) est hors périmètre de la récupération invité — sa récupération passe par `Creator.email` (§3.2 créateur). Un lien invité sur ce profil fuirait le pseudo du créateur et permettrait de modifier le code de sa ligne participant.
4. Sinon : `raw = issue_recovery_token(guest)` ; **`db.session.commit()`** ; puis enqueue `tasks.send_guest_recovery_link_email(host, port, user, pw, frm, email, event.title, url_for("events.guest_recover_link", token=..., _external=True), lang)`.
5. Réponse identique (F16) : flash `Si une adresse est associée à cet événement, un lien de récupération vient de vous être envoyé par e-mail.` + redirect `/e/<code>/recover` (page d'attente, pas de confirmation d'existence). Rate limit `@limiter.limit("10 per hour")` par IP (clé par défaut de Flask-Limiter : l'IP seule, pas IP+événement).

**Nouvelle route — page de lien invité** : `GET /e/<code>/guest-recover/<token>` :

1. `guest = Guest.query.filter_by(recovery_token=hash_recovery_token(token), event_id=event.id, is_active=True, merged_into_id=None).first()` ; si None (dont profil retiré), ou token expiré → flash `Lien invalide ou expiré.` + redirect `/e/<code>/mycode` (F16).
2. Page `events/guest_recover_link.html` (même composants que `recover_link`) :
   - Affiche le pseudo + code masqué du `Guest`.
   - « Conserver mon code » → POST `events.guest_recover_link` (action=keep) : token effacée, `start_guest_session(code, guest)`, redirect dashboard. **Aucune réactivation** (R4).
   - « Choisir un nouveau code » : validation 4–8 car `[a-z0-9]+` + unicité dans l'événement (`Guest.event_id == event.id, code == …, merged_into_id == None` **et** hors du code créateur de l'événement — même règle que `guest_access`) ; succès : `guest.code = <nouveau>`, token effacée, session, redirect dashboard. Une 2e requête `recode` avec le même lien (token consommé) est refusée et ne change pas le code.
   - **Profil retiré (R4)** : il ne peut pas se réactiver lui-même (ni par `/recover`, ni par lien, ni par `guest_access`). Seul le créateur réactive, via l'action `reinvite` (§3.4) ; seul le profil redevient actif (son ancien foyer reste détaché sous « Participant retiré »).

**Emails (nouveaux dans `app/tasks.py`)** :

- `send_recovery_link_email(..., link, lang)` : sujet `Reprenez l'accès à holishared`, corps : lien + « Ce lien expire dans 24 heures. Si vous n'avez pas demandé ce lien, vous pouvez ignorer cet e-mail. »
- `send_guest_recovery_link_email(..., event_title, link, lang)` : même contrat, mention du titre de l'événement. Le sujet de l'e-mail créateur reste « Reprenez l'accès à holishared ».
- `send_recovery_email` (ancien, code en clair) : **supprimé** (D2), les tests associés remplacés.

### 3.3 « Mon profil » — section Accès & récupération (`events/me.html`)

Nouveau `section` (après le foyer, avant notifications) `data-testid="access-card"` :

- Ligne « Mon e-mail » : valeur masquée (`a***@domaine`) ou `Non renseigné` si absent.
- **Invité** :
  - Bouton « Renvoyer le lien de récupération » (visible si email présent) → POST `events.me` (action=`recovery_link`) : envoie le lien au proprio (même helper que §3.2, sans vérification de format puisque l'email est déjà stocké), flash `Lien de récupération envoyé à votre adresse.` ; sans SMTP : flash warning « L'envoi d'emails n'est pas configuré sur ce serveur. », aucun token, aucun envoi, aucune entrée de journal `participant.recovery_sent` (même contrôle que `members`) ; le journal est écrit **avant** le commit du token (helpers qui commitent avant l'enqueue), donc jamais perdu (**rate limit 10/h par IP, appliqué à cette seule action** — les autres POST de `me` ne sont pas comptés ; 429 au-delà ; commit avant enqueue, R2).
  - Bouton « Effacer mon e-mail » (`data-confirm` : « Sans e-mail, vous ne pourrez plus récupérer votre accès. Confirmer ? ») → POST `events.me` (action=`erase_email`) : `participant.email = None` **et `clear_recovery_token(participant)`** (RGPD : plus de lien en vol), flash. Droits : le participant seul (jamais le créateur sur son propre profil via cette route — le créateur gère le sien ailleurs, voir 3.4).
- **Créateur** (son propre profil, `ctx.is_creator`) :
  - Affichage du `current_user.email` masqué. **Pas de miroir** : le participant créateur (`Guest.creator_id` non nul) ne porte **jamais** d'email en production (`ensure_creator_guest` ne l'écrit pas) — la récupération du créateur lit `Creator.email` uniquement. Les actions ci-dessous opèrent sur `Creator.email` seul.
  - Bouton « Renvoyer le lien de récupération » (visible si email présent) → POST `events.me` (action=`recovery_link`) : token sur `Creator` + `send_recovery_link_email` (même helper que §3.2), rate limit 10/h.
  - Bouton « Effacer mon e-mail » (`data-confirm` idem) → POST `events.me` (action=`erase_email`) : `current_user.email = None` **et `clear_recovery_token(current_user)`**.
- `me()` (route GET/POST) : les actions `recovery_link` / `erase_email` sont ajoutées au POST existant (l'action est dans `request.form["action"]` ; l'absence d'action = le comportement actuel du renommage). Droits : le participant courant uniquement (l'invité sur son propre profil, le créateur sur le sien) ; un invité ne peut pas toucher `Creator.email`.

### 3.4 Page Participants — email & renvoi de lien (`events/members.html`)

- Chaque ligne de participant (invité) affiche l'**email masqué** (ou `—` si absent) : `_masked_email(g.email)`.
- **Correction d'email** (créateur) : bouton « Corriger l'email » → sheet `events-member-email-sheet` avec champ `email` (validation format + jetable, `_check_email`) ; POST `events.members` (action=`fix_email`) : `guest.email = <nouveau ou vide>` ; flash `Email enregistré pour %(name)s.`. Droits : créateur seul (action existante du handler `members`, `ctx.is_creator` déjà exigé).
- **Renvoyer le lien de récupération** (créateur, par participant **actif**) : bouton `data-testid="send-recovery-link"` → POST `events.members` (action=`recovery_link`, `guest_id`) ; **rate limit 20/h par IP sur cette seule action** (429 au-delà) ; si `guest.email` : token + commit + enqueue + flash `Lien de récupération envoyé à %(name)s.` ; sinon : flash warning `Aucun email pour %(name)s — corrigez son email d'abord.` (pas d'erreur 500, pas d'envoi). Si pas SMTP : flash warning « L'envoi d'emails n'est pas configuré sur ce serveur. » (état honnête, comme `invite_email`).
- **Réinviter un participant retiré (R4)** : la page Participants liste aussi, sous « Participants retirés », les profils `is_active=False`, `merged_into_id IS NULL`, `creator_id IS NULL`, chacun avec un bouton `data-testid="reinvite-participant"` → POST `events.members` (action=`reinvite`, `guest_id`). **Créateur seul** (403 sinon). Cible : même événement, inactive, non fusionnée, non-créateur — sinon 404. `can_add_guest(event)` faux → erreur globale `Limite d'invités atteinte.` (statut 422, rien n'est modifié). Sinon : `is_active = True`, et si `guest.email` : `raw = issue_recovery_token(guest)` + commit + enqueue du lien invité (sans email ou sans SMTP : réactivation seule, l'ancien code personnel refonctionne) ; journal `participant.reinvited` (target = nom) ; flash `%(name)s a été réinvité·e.`. Le foyer d'origine n'est **pas** rattaché de nouveau (`guest_id` reste NULL, « Participant retiré » dans les Frais) : un nouveau foyer est créé au premier enregistrement de « Mon foyer ». C'est le **seul** chemin de réactivation.
- Le bouton existant « Renvoyer l'invitation » est **conservé** (c'est l'invitation de re-join ; le lien de récupération est pour l'existant).

### 3.5 Journal (i18n)

Nouvelles actions dans `app/i18n.py` :

| action | phrase (msgid FR) |
|--------|-------------------|
| `participant.email_fixed` | `%(actor)s a corrigé l'email de %(target)s` |
| `participant.recovery_sent` | `%(actor)s a envoyé un lien de récupération à %(target)s` |
| `participant.restored` | `%(actor)s a récupéré son accès (réactivation)` — **plus émis** (R4) ; msgid conservé pour l'historique |
| `participant.reinvited` | `%(actor)s a réinvité un participant` (label « Participant réinvité » ; `ACTION_LABELS` + `ACTION_SENTENCES` dans `app/i18n.py`) |
| `account.email_erased` | `%(actor)s a effacé son email` |
| `account.code_changed` | `%(actor)s a modifié son code personnel` |
| `participant.deleted` | `%(actor)s a supprimé %(target)s de l'événement` |
| `participant.merged` | `%(actor)s a fusionné les profils %(source)s et %(target)s` |
| `household.merged` | **plus émis** (R5 : aucun foyer n'est fusionné/supprimé) ; msgid conservé pour l'historique |

**Note** : `participant.deleted` existe déjà (utilisé par `remove` actuel) — le msgid est conservé tel quel si déjà présent, sinon ajouté. Les 3 dernières lignes sont nécessaires car §4.3 et §5.5 les émettent via `log_event`.

Mises à jour du catalogue `.pot/.po/.mo` FR/EN après chaque lot.

## 4. WP2 — Suppression d'un membre avec réattribution

### 4.1 Route

`POST /e/<code>/members` (action=`delete`) — **créateur uniquement** (le handler exige déjà `ctx.is_creator` pour tout POST).

Champs du formulaire (sheet `events-member-delete-sheet`, ouvert depuis le bouton « Supprimer » de la ligne — le bouton « Retirer » actuel est **conservé** et devient l'option « Retirer sans réattribution ») :

- `guest_id` (caché)
- `reassign_to` : `select` — option `""` = `Ne pas réattribuer` + un item par participant actif (y compris le participant créateur, excluant la cible) ; valeur = `Guest.id` de la cible
- `data-confirm` : « Supprimer définitivement %(name)s de l'événement ? Ses articles et son foyer seront transférés selon votre choix. Cette action est irréversible. »

### 4.2 Semique — ce qui est réattribué (table de décision)

| Donnée | `reassign_to` = cible | `reassign_to` = « Personne » | Rationale |
|--------|----------------------|------------------------------|-----------|
| `ListItem.assigned_to_id` (= cible) | → `cible.id` | → `None` | Travail à faire, pas de l'histoire (D4) |
| `ListMealCoverage.covered_by` / `ListActivityCoverage.covered_by` (= cible) | → `cible.id` | → `None` | Cohérence « Pour moi » |
| Foyer `Household.guest_id` (= cible) | **Transfert** si `cible` n'a pas de foyer : `household.guest_id = cible.id` (id du foyer inchangé). **Si `cible` a déjà un foyer : le foyer source n'est PAS fusionné** (R5) : il est détaché (`guest_id = None`, « Participant retiré ») et garde toutes ses Expense/Transfer/PaymentRequest ; le foyer de `cible` est inchangé | **Détaché** (`guest_id = None`) ; l'affichage dans les Frais passe à `Participant retiré` (voir 4.4) | Les soldes de chaque foyer restent identiques avant/après (D3, R5) |
| `ActivityRSVP` / `PollVote` (de la cible) | **inchangés** (jamais transférés, D4) | inchangés | Intégrité du vote |
| Chat, journal, médias, `Activity.created_by`, `Meal.created_by`, etc. | inchangés | inchangés | Historique immuable (ADR-004) |
| `PushSubscription` / `ApiKey` | supprimés | supprimés | Sécurité (déjà le cas au retrait) |

### 4.3 Comportement de suppression (implémentation)

```
def _delete_participant(ctx) -> Response:
    event, target (Guest actif de l'événement, can_delete ok), reassign_to
    # 1. compteurs pour la confirmation (déjà affichés dans le sheet)
    # 2. réattribution (si reassign_to non vide) :
    target_items = ListItem.query.filter(assigned_to_id=target.id) + listes de l'événement
    coverage rows covered_by=target.id → cible
    household = Household.query.filter_by(guest_id=target.id, event_id=event.id).first()
    if household is not None:
        if reassign_to:
            target_hh = Household.query.filter_by(guest_id=reassign_to, event_id=event.id).first()
            if target_hh is None:
                household.guest_id = reassign_to
            else:
                household.guest_id = None    # R5 : pas de fusion, foyer « Participant retiré »
        else:
            household.guest_id = None    # foyer « Participant retiré »
    # 3. RSVP/votes/chat/journal/médias : rien à faire
    # 4. purge : PushSubscription + ApiKey + clear_recovery_token(target)  (R6a)
    # 5. target.is_active = False ; log_event "participant.deleted" (details = display_name de la cible ou "sans réattribution")
    # 6. flash de récap : « X supprimé·e. N articles transférés à Y, foyer transféré ou conservé (« Participant retiré »). » — toutes les chaînes (flash ET `details` du journal) via `_()` avec placeholders nommés (R6g), pas de f-string FR.
```

- ~~`_merge_households`~~ **supprimé (R5)** : aucun foyer n'est recollé ni supprimé. Fusion de membres et suppression ne font que détacher le foyer source (`guest_id = None`) ; ses Expense/Transfer/PaymentRequest restent sur lui, donc les soldes de tous les foyers sont inchangés (`_settlement` est calculé à chaque rendu, aucun cache en base). Le choix « fusionner » devient « conserver le foyer orphelin ».
- Conséquence : plus de transferts « internes » à neutraliser ; un foyer orphelin reste un débiteur/créditeur à part entière dans « Qui doit à qui ».

### 4.4 Affichage du foyer orphelin dans les Frais

`app/costs/index.html` (cartes foyers + « Qui doit à qui ») : quand `household.guest_id` est None → le libellé affiché est `Participant retiré` (msgids dédiés) ; le foyer reste éligible aux soldes/transferts (il a une identité stable). Aucun autre changement dans l'algorithme.

### 4.5 « Retirer » (existant) vs « Supprimer »

- **Retirer** (`action=remove`, existant) : comportement actuel inchangé (`is_active=False`, foyer conservé/supprimé selon les liens) — reste le chemin rapide.
- **Supprimer** (`action=delete`, nouveau) : retrait **+** choix de réattribution. Les deux sont sur la même page Participants (2 boutons par ligne).

### 4.6 Suppression d'un foyer avec réaffectation (amendement 2026-10-19)

`POST /e/<code>/costs/households/<h_id>/delete` (`costs.delete_household`, créateur seul via `can_delete`) accepte un champ optionnel `reassign_to` (select « Réaffecter à » de la feuille « Modifier le foyer » : les **autres** foyers du même événement ; libellé associé). Aucun avertissement de poids : seuls les foyers restants comptent.

- **Sans cible** : comportement inchangé (bloqué avec message si le foyer est cité par une dépense/transfert/demande ; supprimé sinon).
- **Cible invalide** (foyer inconnu, d'un autre événement, ou le foyer lui-même) : 404, aucune écriture.
- **Cible valide X** (foyer source S) :
  - `Expense.paid_by_household_id` S → X ; `Transfer` / `PaymentRequest` (`from`/`to`) S → X ; tout transfert/demande qui devient X → X est **supprimé** (solde nul) ;
  - `Expense.custom_split` : la clé S est sommée dans la clé X (puis retirée) ;
  - **Parts recalculées** (règle produit) : aucun foyer n'absorbe les personnes de S. Les parts des dépenses partagées sont recalculées à l'affichage sur les foyers **restants**, avec **leurs propres poids** (le poids de S disparaît des répartitions par défaut) ; les dépenses payées par S sont créditées à X. Les soldes des autres foyers peuvent donc changer ; ils se calculent à la main : `part(h) = montant × poids(h) / somme des poids restants` ;
  - travail à faire : si S a un participant propriétaire (`guest_id`), ses articles et couvertures passent au propriétaire de X (`None` si X est orphelin) via `app.utils.reassign_work` (même helper que §4.3) ; un foyer S orphelin (`guest_id` nul) n'a rien à réattribuer de ce côté ;
  - S est supprimé ; journal `household.merged` (cible = X, détail = « %(name)s absorbé ») ; un seul commit ; flash de récap (N dépenses, M transferts/demandes, K articles) ; chaînes via `_()` avec placeholders nommés.
- `household.merged` est donc de nouveau émis (par ce seul flux) ; le retrait/fusion de **membres** (§4.2, §5.5) ne fusionne toujours aucun foyer (R5).

## 5. WP3 — Anti-doublon au re-join

### 5.1 Règle d'unicité logique

Un événement a **un seul** `Guest` par email non nul (actif ou inactif, hors `merged_into_id`, hors participant créateur) — garanti par l'index §2.2. Points d'écriture d'un email :

1. `events.guest_access` (auto-join) — réponse neutre si l'adresse est connue (§5.2)
2. `events._add_participant` (ajout par le créateur) et `events._member_fix_email` — erreur par champ (§5.3)
3. `events.invite_email` n'insère aucun `Guest` (§5.4)

### 5.2 `guest_access` — comportement au POST (R3, remplace l'ancien flux merge/new)

Après validation du format des champs et **avant** `can_add_guest`, le code unique et `join_creation_allowed()` : si `email` est non vide et `_email_guest(event, email)` existe (profil **actif OU retiré**, hors fusionné/créateur) :

| Profil existant | Token / e-mail | Création de `Guest` | Réponse |
|---|---|---|---|
| actif | `issue_recovery_token` + commit + enqueue du lien invité (§3.2) | aucune | neutre |
| retiré (`is_active=False`) | **rien** | aucune | **la même** neutre |

- **Réponse neutre (identique, octet pour octet hors cookie)** : flash `Si cette adresse est connue, un lien de connexion vient d'être envoyé.` + `302` vers `GET /e/<code>/join`. Le formulaire est re-présenté vierge.
- **Aucune fuite** : ni pseudo, ni `guest_id`, ni indice sur le code (même masqué), ni compteurs, ni champ caché `guest_id`, ni bouton merge/new. `dup_profile`, `merge_target`, `merge_items`, `merge_has_household`, `_merge_item_count`, `_join_reactivate` et la section `data-testid="merge-existing"`/`dup-profile` de `join.html` sont **supprimés** ; `action=merge|new` n'existent plus (valeur ignorée).
- Un e-mail **inconnu** crée le profil normalement (redirect dashboard) : l'oracle résiduel « connu/inconnu » est inhérent à l'auto-inscription ouverte (atténué par `join_creation_allowed`, 20/h/IP) — hors périmètre.
- `IntegrityError` à l'insertion (course contre un autre join de même email) → `rollback`, même réponse neutre, aucun 500.
- Plus aucune réactivation par le join (R4).

### 5.3 `_add_participant` et `_member_fix_email` (créateur de confiance)

- Si l'email saisi existe déjà (actif ou inactif) : erreur par champ sur `email` : `Cette adresse a déjà un profil dans cet événement.` ; pas de 2e profil. `IntegrityError` → `rollback` + même erreur (statut 200 pour `add`, 422 pour `fix_email`), pas de 500. `can_add_guest` vérifié (déjà en place).

### 5.4 `invite_email`

- Profil **actif** pour l'adresse : flash warning `%(name)s participe déjà à cet événement.`, pas d'envoi, pas de token.
- Profil **retiré** pour l'adresse (R4) : **aucun token, aucun e-mail, aucune réactivation** ; flash warning `Un profil retiré existe pour cette adresse : utilisez « Réinviter » dans les participants retirés.` (le créateur est de confiance, la révélation est sans risque). Seule l'action `reinvite` (§3.4) réactive.
- Aucun profil : invitation classique (inchangé, `can_add_guest` vérifié).
- Cette route n'émet donc plus aucun token.

### 5.5 Fusion de profils (colonne `merged_into_id`)

Le scénario « 2 profils de même email déjà créés dans le passé » (avant B038) est **résolu manuellement par le créateur** dans la page Participants :

- Un profil est signalé avec un badge `email dupliqué` si un autre profil de l'événement (**actif ou retiré**, hors fusionnés et participant créateur) a le même email non nul — cas hérité typique : un profil retiré et un profil actif. Un formulaire de fusion est proposé sur chaque ligne d'un groupe de doublons : sur un profil actif, le profil absorbé peut être actif ou retiré et le profil conservé est **toujours un profil actif** ; sur un profil **retiré** (source fixée), le profil conservé peut être actif ou retiré (formulaire `retired-merge-form`, donc les paires retiré/retiré se fusionnent aussi). L'interface ne propose jamais la combinaison interdite (source actif → cible retirée). Les profils `merged_into_id` n'affichent pas de badge : leur email est effacé à la fusion. Tant que ces doublons existent, `migrate_guest_email_unique` ne crée pas l'index (retour 0) ; après la fusion il le crée.
- Action `merge_profiles` (créateur) : `source_id` (le profil à absorber) + `target_id` (le conservé) ; **contraintes** : même événement, **interdit : source actif → cible inactif** (`source.is_active and not target.is_active` → erreur globale `Un profil actif ne peut pas être fusionné dans un profil retiré.`, 422) ; sont donc permis : les deux actifs, source inactif (cible active ou inactive) ; `source.merged_into_id is None`, `target.merged_into_id is None`, ni l'un ni l'autre n'est le participant créateur (`creator_id is None`), emails non nuls et égaux (sinon : erreur par champ « Ces profils n'ont pas le même email ») :
  - `ListItem.assigned_to_id`, couvertures : source → target
  - Foyer : transfert de `guest_id` si target n'a pas de foyer, sinon le foyer source est **détaché** (`guest_id = None`, conservé avec ses liens, R5)
  - `display_name` : si le target est déjà nommé, la display_name du source est ignorée (pas d'écriture sur le target) — l'identité affichée est celle du profil conservé
  - RSVP/votes/chat : inchangés (les deux profils restent historiquement distincts — c'est l'histoire)
  - `source.merged_into_id = target.id ; source.is_active = False ; source.email = None`
  - Journal `participant.merged` (details : noms des deux profils)
- C'est le **seul** point d'entrée de `merged_into_id` ; le re-join (5.2) ne fusionne ni ne réactive jamais.

### 5.6 Impact sur les compteurs

- `Event.guest_count` : inchangé (déjà `is_active=True` seulement) ; les `merged_into_id` sont inactifs donc exclus.
- `can_add_guest` : inchangé.

## 6. Templates — liste des nouveaux/modifiés

| Fichier | Changement |
|---------|-----------|
| `events/recover.html` | Texte « lien de récupération » au lieu de « code » (D2) |
| `events/recover_link.html` | **nouveau** — page de lien créateur (pseudo, code masqué, 2 boutons) |
| `events/guest_recover.html` | **nouveau** — page d'attente de l'envoi (email + bouton, pas de confirmation d'existence) |
| `events/guest_recover_link.html` | **nouveau** — page de lien invité (idem 3.2) |
| `events/verify.html` | Case email cochée par défaut + help |
| `events/join.html` | Help email ; aucune section de profil existant (R3) |
| `events/me.html` | Section « Accès & récupération » (3.3) |
| `events/members.html` | Email masqué, boutons Corriger l'email / Lien de récupération / Supprimer (sheet delete avec `reassign_to`) ; badge email dupliqué + sheet merge_profiles (WP3) ; section « Participants retirés » + bouton `reinvite` (R4) |
| `costs/index.html` | Libellé `Participant retiré` pour foyer sans `guest_id` |

**Accessibilité (WCAG AA)** : toutes les sections nouvelles portent `aria-labelledby`/`data-testid` ; les selects ont un `<label>` ; le `data-confirm` est doublé d'un sheet accessible sur mobile (le pattern existant `events-member-delete-sheet` utilise un `<details>` + formulaire — même pattern que `members.html` actuel) ; pas d'info par la couleur seule (badge dupliqué = icône + texte).

## 7. Sécurité

- **F16 conservé** : `POST /recover`, `POST /e/<code>/recover`, `GET /e/<code>/guest-recover/<token>` et `GET /recover/link/<token>` renvoient **toujours la même réponse** quel que soit l'état (email inconnu / profil absent / token expiré / événement inexistant) ; le timing est uniformisé par le rate limit (pas de branche conditionnelle observable).
- **Cooldown par profil** : 5 min (`RECOVERY_LINK_COOLDOWN`, heure d'émission = `recovery_token_expires - RECOVERY_TOKEN_TTL`) sur les trois parcours publics anonymes (`join` avec adresse connue, `/recover`, `/e/<code>/recover`) : au-delà, rien n'est envoyé ni ré-émis et la réponse reste identique. Les actions explicites authentifiées (`me`, `members` recovery_link, `reinvite`) ne sont **pas** soumises au cooldown (seulement à leurs rate limits). Le join ajoute un plafond `10 per hour` par IP (compteur `join-recovery-link`, au-delà : même réponse neutre, aucun envoi, jamais de 429 qui révélerait l'adresse).
- **`DEV_SHOW_SECRETS` (`reveal_in_debug`)** : n'affiche jamais le lien sur les parcours publics anonymes (join, `/recover`, `/e/<code>/recover`), même avec `app.debug` ; seuls `reinvite` (créateur authentifié) peut l'afficher, en mode debug uniquement (`me` et `members` exigent SMTP).
- **Jobs RQ** : le job d'e-mail porte le token brut et les identifiants SMTP : `description="recovery-link"` (rien de sensible dans la description ni les logs du worker), `failure_ttl=3600`, `result_ttl=0`.
- **Risque accepté** : au join, un écart de temps résiduel peut distinguer un profil actif (token + enqueue) d'un profil retiré (rien) ; l'oracle « connu/inconnu » est déjà inhérent à l'auto-inscription ouverte, atténué par les limites par IP.
- Rate limits (par IP) : `10 per hour` pour `/recover`, `/e/<code>/recover` et `me` action=`recovery_link` ; `20 per hour` pour `members` action=`recovery_link`. Les limites `me`/`members` ne comptent que l'action concernée (`limiter.limit(..., deduct_when=...)` ou `limiter.limiter.hit` comme `join_creation_allowed`).
- Tokens : `secrets.token_urlsafe(32)` **stockés hachés (sha256, R1)**, usage unique (effacés après le lien, **et** à la suppression/retrait du profil et à l'effacement de l'e-mail, R6a), TTL 24 h, émission toujours suivie d'un commit avant l'enqueue (R2), **jamais** dans une réponse API (`app/api` : `GET /api/v1/events/<id>` n'expose pas `email` des guests ni tokens — vérifier par test).
- CSRF : toutes les routes POST passent par `csrf_token()` (pattern blueprint existant).
- Réactivation : uniquement par le créateur (`reinvite`, journal `participant.reinvited`, plafond `can_add_guest`) ; jamais en libre-service (R4).
- Pas de nouvelle donnée PII : l'email est déjà du PII optionnel ; les nouvelles colonnes sont des tokens serveur.

## 8. i18n

- Toutes les chaînes passent par `_()` / `lazy_gettext` ; les nouveaux msgids (≈ 25) ajoutés dans le `.pot` (extraction `pybabel extract`), traduits EN, `.mo` recompilés ; le test de garde i18n existant (page EN sans msgid FR) couvre les nouvelles pages.
- Les phrases du journal (3.5) passent par `ACTION_SENTENCES` / `ACTION_LABELS` de `app/i18n.py`.

## 9. Tests (écrits d'abord, par lot)

Fichier unique `tests/test_identity_b038.py` + extensions de `tests/test_events.py` si pertinent. Fixtures de `conftest.py` réutilisées (`app`, `client`, `creator`, `event`, `guest`, `guest_client`, `creator_client`, `db`).

### 9.1 WP1 (≈ 28 tests)

- `test_creator_recovery_email_by_default_is_stored` : verify avec case cochée (par défaut) → `creator.email` conservée.
- `test_creator_recovery_email_opt_out_erases` : case décochée → `creator.email is None`.
- `test_recover_unknown_email_returns_neutral_message` : email inconnu → 200, flash neutre, pas de token créé (DB vide de `recovery_token`).
- `test_recover_known_email_creates_single_use_token` : email connu → 1 token, expiration ≈ +24 h, email enqueued (RQ mocké).
- `test_recover_link_invalid_token_redirects_neutrally` : token faux/expiré → redirect `/recover`, flash générique.
- `test_recover_link_keep_code_starts_session` : lien valide, action=keep → session créateur démarrée, token effacée, redirect.
- `test_recover_link_recode_rejects_short_code` / `_rejects_duplicate_code` / `_accepts_valid_code` : erreurs par champ, unicité, succès (code changé, token effacée, session).
- `test_recover_link_reuse_is_rejected` : 2e GET après keep → flash invalide.
- `test_guest_recover_unknown_email_neutral` : email inconnu sur un événement → réponse neutre, pas de token.
- `test_guest_recover_known_email_token_and_link` : token sur le bon `Guest`, lien pointe sur `/e/<code>/guest-recover/<token>`.
- `test_guest_recover_link_wrong_event_token_rejected` : token d'un autre événement → refus neutre.
- `test_guest_recover_retired_profile_gets_no_link_and_cannot_reactivate` : profil retiré → aucun token ni lien ; lien déjà émis → refus neutre, `is_active` reste False (R4).
- `test_guest_recover_recode_uniqueness_in_event` : code déjà pris dans l'événement → erreur ; code créateur → erreur.
- `test_me_recovery_link_sends_to_own_email` : action=recovery_link depuis `me` → enqueued, pas d'erreur.
- `test_me_erase_email_removes_it` : invité → `guest.email is None` ; créateur → `current_user.email is None` (le participant créateur n'a pas d'email en base, rien d'autre à vérifier).
- `test_members_fix_email_by_creator` : action=fix_email (créateur) → email corrigé, journal `participant.email_fixed` ; guest → 403.
- `test_members_recovery_link_by_creator` : action=recovery_link → enqueued si email ; warning si absent ; warning si pas SMTP.
- `test_recover_rate_limited_after_10_attempts` : 429 après 10 envois/h.
- `test_api_does_not_expose_emails_or_tokens` : `GET /api/v1/events/<id>` → pas de champ `email`/`recovery_token` dans la réponse JSON.
- `test_recovery_email_template_translated` : EN/FR (msgids dans les 2 catalogues).
- Migration : `test_identity_recovery_migration_idempotent` : 2x `run_identity_recovery_migration` → colonnes présentes, aucune erreur ; `test_identity_recovery_migration_adds_columns` : sur une DB pré-B038 (colonnes absentes) → ajout.

### 9.2 WP2 (≈ 22 tests)

- `test_delete_participant_reassigns_items_to_target` : 3 articles de la cible → tous → `target.id`.
- `test_delete_participant_no_reassign_nulls_items` : articles → `assigned_to_id is None`.
- `test_delete_participant_reassigns_coverages` : `ListMealCoverage.covered_by` / `ListActivityCoverage.covered_by` → cible.
- `test_delete_participant_transfers_household_when_target_has_none` : foyer cible → `guest_id=cible`, id du foyer inchangé (les dépenses pointent toujours dessus).
- `test_delete_participant_keeps_source_household_when_target_has_one` : foyer source détaché (`guest_id None`), non supprimé, liens conservés (R5).
- `test_delete_participant_preserves_settlements` : dépenses inégales + Transfer + PaymentRequest ; `_settlement` identique avant/après (R5).
- `test_delete_participant_keeps_household_when_no_reassign` : `guest_id is None`, `name` inchangé ; les frais le rendent toujours dans l'index.
- `test_costs_index_shows_removed_participant_label` : rendu HTML de `costs/index` contient le msgid « Participant retiré » pour le foyer orphelin.
- `test_delete_participant_votes_and_rsvps_unchanged` : les votes/RSVP de la cible restent (jamais transférés, D4).
- `test_delete_participant_history_unchanged` : chat/journal/médias de la cible intacts.
- `test_delete_participant_revokes_push_and_api_keys` : purge PushSubscription + ApiKey.
- `test_delete_participant_deactivates_session` : le client de la cible, après suppression → redirect `/e/<code>/mycode`.
- `test_delete_participant_log_and_flash` : `participant.deleted` dans le journal avec details ; flash de récap (N articles transférés).
- `test_delete_requires_creator` : guest → 403.
- `test_delete_unknown_guest_404` : guest inactif/inconnu → 404.
- `test_remove_still_works_without_reassign_ui` : l'action `remove` (existante) est intacte (non-régression).
- `test_delete_cannot_target_creator_participant` : le participant créateur n'est pas dans le `select` (droits : `can_delete` l'exclut déjà — vérifier par le template).

### 9.3 WP3 (≈ 18 tests)

- `test_join_known_email_response_identical_active_and_retired` : même statut, même Location, même flash ; aucune fuite pseudo/`guest_id`/code (R3).
- `test_join_retired_email_never_reactivates` / `test_join_retired_email_sends_nothing` : aucun lien, aucune réactivation (R3/R4).
- `test_add_participant_duplicate_email_rejected` : créateur ajoute un email existant → erreur par champ + profil existant proposé.
- `test_invite_email_active_profile_no_send` : invitation d'un email actif → warning, rien d'envoyé.
- `test_members_shows_duplicate_email_badge` : 2 profils de même email → badge sur les 2.
- `test_merge_profiles_migrates_items_and_household` : action=merge_profiles → articles/couvertures/foyer sur la cible ; source `merged_into_id` + inactif + email effacé ; log `participant.merged`.
- `test_merged_guest_excluded_from_everywhere` : `merged_into_id` non nul → absent de Participants, « Pour moi », `guest_count`, API v1.
- `test_guest_count_ignores_merged` : `Event.guest_count` invariant après merge.
- `test_join_active_email_sends_recovery_link_neutrally` : lien envoyé au profil actif seulement (R3).
- i18n : `test_b038_strings_in_catalogs` (tous les msgids dans fr + en).
- `test_recover_page_neutral_rendering` : page `/e/<code>/recover` rendue sans fuite (aucun nom participant dans le HTML).

### 9.5 Amendement post-audit (R1-R6)

Dans les trois fichiers existants (`test_identity_b038.py`, `test_delete_b038.py`, `test_duplicate_b038.py`), sans nouveau fichier :

- R1/R2 : token haché en base (sha256 du token du lien == valeur stockée, brut absent), token retrouvé après `rollback` (commit prouvé) pour les 5 chemins d'émission ; usage unique (`recode` rejoué ne change pas le code) ; token expiré refusé.
- R3/R4 : cf. 9.3 ; `reinvite` (créateur seul, plafond `can_add_guest`, token émis, journal) ; aucune route ne réactive un profil retiré.
- R5 : soldes préservés à la suppression et à la fusion de profils (foyer orphelin conservé).
- R6 : token effacé à `delete`/`remove`/`erase_email` ; `merge_profiles` actif → inactif refusé (POST forgé) ; rate limits `me` 10/h et `members` 20/h ; index unique partiel + migration idempotente + `IntegrityError` sans 500 ; `DEV_SHOW_SECRETS` sans `app.debug` n'affiche pas le lien ; msgids i18n anglais ≠ msgid, français = msgid.

### 9.6 Réaffectation d'un foyer (§4.6)

Dans `tests/test_delete_b038.py` : soldes recalculés sur les foyers restants, valeurs calculées à la main (dépenses inégales + Transfer + PaymentRequest) ; recalcul selon les poids des foyers restants (un foyer à 2 adultes) ; articles (faits ou non) et couverture de repas du propriétaire de S → propriétaire de X ; aucune absorption de personnes ; paire X → X supprimée ; foyer source supprimé ; cibles interdites (autre événement / lui-même / inconnue) sans mutation ; non-créateur 403 ; sans cible : comportement inchangé ; foyer orphelin réaffectable ; cible sans propriétaire → articles désassignés ; `custom_split` fusionné ; formulaire avec select étiqueté.

### 9.7 Tour 3 (audit)

`test_identity_b038.py` : `description`/ttl des jobs RQ ; `/recover` et `/e/<code>/recover` ne révèlent jamais le lien (debug) ; cooldown silencieux sur ces deux routes (réponse identique, un seul envoi) ; actions explicites non bloquées ; 10 → 429 sur `/e/<code>/recover` ; `verify` décoché purge le token ; course sur l'unicité du code (`recode` créateur et invité) → erreur de champ ; `me` sans SMTP (aucun token/journal) ; journaux `participant.email_fixed`/`recovery_sent` persistants ; `reinvite` peut révéler le lien en debug. `test_duplicate_b038.py` : doublons hérités retiré + actif et retiré + retiré (badge, formulaire, fusion, puis index créé) ; token du profil absorbé effacé. `test_delete_b038.py` : récap exact de suppression.

### 9.4 Non-régression

- La suite complète (2201+ tests) passe après chaque lot.
- Tests existants touchés : `tests/test_recover_b019.py` (le lien magique remplace le code en clair ; `DEV_SHOW_SECRETS` n'affiche plus rien sur la route publique `/recover`, même en debug), `tests/test_creation_b019.py` (aide honnête au nouveau libellé de la case e-mail, D1) et `tests/test_tasks.py` (nouvelles tâches e-mail, sujet de récupération en français).

## 10. Lots et commits

| Lot | Contenu | Commits prévus |
|-----|---------|----------------|
| **L1** (WP1) | Colonnes de récupération + migration, `issue_recovery_token`/`valid_recovery_token`, routes `recover` (créateur) + lien, routes invité, section `me`, email/récup sur `members`, suppression de l'ancien email code-en-clair, i18n | `feat(models): recovery tokens for creators and guests (B038-L1)` · `feat(events): magic-link code recovery for creators and guests (B038-L1)` · `feat(ui): access & recovery sections in profile and participants (B038-L1)` · `chore(i18n): B038-L1 strings + .mo recompile` |
| **L2** (WP2) | `_delete_participant` (foyer détaché, pas de fusion), sheet delete avec `reassign_to`, libellé Frais « Participant retiré », i18n | `feat(events): member deletion with reassignment (B038-L2)` · `feat(costs): merged households + "removed participant" label (B038-L2)` · `chore(i18n): B038-L2 strings + .mo recompile` |
| **L3** (WP3) | Unicité logique email au re-join/ajout/invitation, `merge_profiles`, badge dupliqué, `merged_into_id`, i18n | `feat(events): duplicate-email guard and profile merge (B038-L3)` · `chore(i18n): B038-L3 strings + .mo recompile` |

Chaque lot : spec approuvée (ce document) → tests écrits d'abord (ils échouent) → codage → tests verts → ruff + mypy + pytest → audit code → gate → commit.

## 11. Hors périmètre (explicite)

- Paiement / changement de plan (B030).
- Suppression de compte **global** créateur (le `Creator` reste ; on supprime la participation à un événement — c'est le périmètre demandé).
- Réattribution des **votes/RSVP** (D4 : figés).
- Notification push lors d'un retrait (le retrait n'est pas un événement « pour tous » ; le journal suffit).
- Migration de la base existante : pas de réécriture d'historique ; les doublons existants sont résolus manuellement via `merge_profiles` (5.5).
