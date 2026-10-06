# Audit UI/UX — holishared

Date : 2026-10-06 · Branche : `ui/tailwind-refonte` (aucun code modifié)

## Méthode et limites

- Lecture : `base.html`, `main.css` (structure + métriques), `events/dashboard`, `events/index`, `planning/index`, `meals/index` (JS drag & drop), extraits `costs/index`.
- Observation : app lancée sur une base de démo jetable (port 8499, hors base réelle), Chrome headless, 390×844 (mobile) et 1280×800 (desktop), thème clair, 19 pages × 2 tailles. Mesures automatiques : débordement horizontal, cibles tactiles < 40 px, erreurs console.
- **Non vérifié** :
  - Thème sombre : capturé nulle part.
  - Appareil tactile réel : aucun test.
  - Drag & drop : analysé dans le code, pas rejoué.
  - Pages non examinées en détail : modale repas, galerie média avec photos, formulaire sondage, formulaire infos, `join`, `recover`, paywall freemium.
- Les emojis s'affichent en carrés vides dans mes captures : c'est probablement la police du serveur de test, pas un défaut avéré. À confirmer sur un vrai appareil.
- Aucune erreur console JS relevée sur les 38 pages (aucune page n'a eu `error` ou `warning` dans la console).

## 1. Navigation mobile (priorité n°1)

| # | Constat | Cause | Gravité |
|---|---|---|---|
| N1 | La barre du bas n'existe que dans un événement (`body.has-tabbar` si `current_event`). Sur `/`, `/e/`, `/e/new` : pas de tabbar, seulement 2 liens texte sous l'en-tête. | `base.html:16` | Haute |
| N2 | **Débordement horizontal de la page** : dashboard 497 px (cause probable : bouton « Supprimer définitivement… » coupé à droite sur la capture, élément exact non identifié par la mesure), page liste **1562 px** (bande de chips repas). Sur mobile le navigateur dézoome ou fait défiler la page : la barre `position: fixed` paraît mal placée ou coupée. C'est très probablement la source du « pas toujours visible ». | `.mgmt-danger-btn` sans retour à la ligne ; `.meal-chip-form` hors conteneur scrollable | **Critique** |
| N3 | Seulement 4 onglets + « Plus ». **Repas** (module central) et Sondages/Chat/Média/Infos sont derrière « Plus ». Le menu « Plus » est une modale centrée avec fond sombre, pas une feuille ancrée en bas. | `base.html:154-201` | Haute |
| N4 | « Plus » n'indique pas qu'il contient la page courante. L'onglet reste gris quand on est sur Repas/Chat/Média/Sondages/Infos (état actif perdu). | pas de classe `active` sur `#plus-btn` | Haute |
| N5 | Pied de page (« holishared — Planification… », badge confidentialité) présent sur chaque page, sous le contenu, avec un gros padding réservé à la barre du bas : de la place perdue pour un contenu sans valeur d'usage. (Les captures pleine page montrent la barre au milieu de l'écran : c'est un artefact de capture, `position: fixed` mesuré en bas du viewport sur les 15 pages d'événement, donc pas un défaut.) | `main.container{padding-bottom}` + footer | Basse |
| N6 | En-tête mobile chargé : logo seul + pilule événement tronquée (« Vacances … » à 11 caractères) + avatar + sélecteur FR + thème. Le nom de l'événement n'est jamais lisible en entier. | `max-width: 11ch` | Moyenne |
| N7 | Le changement de langue sur mobile bascule FR↔EN en un tap, sans dropdown : comportement différent du desktop, non annoncé. | JS `base.html:273-282` | Basse |
| N8 | Desktop : 9 pilules dont une répète le titre de l'événement (déjà présent juste au-dessus dans l'en-tête). Doublon. | `nav-event` + `header-event` | Basse |
| N9 | Breakpoint desktop/mobile à 768 px : entre 768 et ~1000 px (tablette portrait), 9 pilules sur une ligne risquent de déborder. Non mesuré. | — | À vérifier |

## 2. Interactions (cliquable, tactile, états)

| # | Constat | Gravité |
|---|---|---|
| I1 | **Liste des événements** : seul le titre (`<a>`) est cliquable, pas la carte entière (`events/index.html`). Même motif à vérifier sur les cartes dashboard et liste (`.card` avec lien interne). | Haute |
| I2 | **Drag & drop des repas** : API HTML5 native (`dragstart/dragover/drop`). Sur écran tactile son comportement dépend du navigateur (appui long, pas de défilement automatique pendant le glisser, aperçu non maîtrisé) : non fiable et non découvrable. Aucune alternative (« Déplacer vers… »), ni clavier. Le texte d'aide parle de « swap ». (Non rejoué sur appareil réel : à valider en recette.) | **Critique** (mobile) |
| I3 | Cibles tactiles sous 40 px : jusqu'à 18 éléments sur le dashboard mobile, 15 sur la liste et sur « Membres ». Exemple : bouton de suppression d'article, chips, « Voir »/« Copier ». | Haute |
| I4 | Chat : un gros bouton plein « Supprimer » orange sous **chaque** message. Il écrase le contenu et ressemble à l'action principale. | Haute |
| I5 | Listes : « Je m'occupe » en bouton plein sur chaque ligne + ✕ plein. Cinq articles = cinq gros boutons terracotta, aucune hiérarchie. Les cases à cocher font ~16 px. | Haute |
| I6 | Dashboard : « Mes items » utilise une case à cocher native non stylée, plus grande que les autres cases de l'app, qui soumet le formulaire à chaque changement (`onchange="this.form.submit()"`) avec rechargement complet. | Moyenne |
| I7 | `confirm()` navigateur pour les suppressions (événement, foyer, dépense…). Pas de feedback cohérent ni d'annulation (undo). | Moyenne |
| I8 | Code personnel masqué par défaut : pour le voir il faut cliquer « Voir ». Le code lui-même est aussi cliquable en secret (`role=button`), mais rien ne l'indique. | Basse |
| I9 | Pas de retour visuel de chargement sur les soumissions HTMX/formulaires (pas de spinner, pas de désactivation du bouton → double envoi possible). | Moyenne |

## 3. Mise en page et défauts visuels

- **V1 — Formulaires (« /planning/new », « /e/new », etc.)** : ce sont des formulaires de back-office. Champs empilés en pleine largeur, une colonne, tous au même poids, hauteur de champ ~68 px sur mobile. Sur desktop : grille de 2 colonnes qui s'arrête à mi-largeur (champs ~320 px dans une zone de 1000 px), titre pleine largeur au-dessus : l'alignement est incohérent. Champs de date/heure natifs affichant `jj/mm/aaaa` et `--:--`. « Nombre minimum de participants » et « Apporter » sont mis au même niveau que « Titre ». Aucune hiérarchie entre l'essentiel (titre, date, heure) et le facultatif (description, lieu, effectif, « Apporter »).
- **V2 — Formulaire rapide de planning** : 3 champs empilés très hauts (le champ titre fait ~190 px de haut à cause de la règle de grille) à la fin de la page, sous toutes les activités. Le formulaire complet fait doublon avec lui et un lien « Plus d'options ».
- **V3 — Dashboard** :
  - Quatre cartes de statut de contenu très inégal (« Sondages ouverts » à moitié vide, « À répartir » avec une seule phrase) ; en desktop la grille 2 colonnes laisse un trou à droite du chat.
  - Le « code personnel » en bandeau terracotta prend la place du contenu utile, avant toute information sur l'événement.
  - Les boutons d'actions rapides (4) sont tous `secondary` : aucun n'est mis en avant.
  - « Zone de gestion » (suppression définitive) est affichée en permanence en bas pour le créateur, avec un bouton de 100+ caractères.
- **V4 — Frais** (page la plus lourde, 2900 px sur mobile) :
  - Le formulaire « Ajouter une dépense » est ouvert d'office, avant le solde ou la liste.
  - Les cartes « Qui doit à qui » affichent « F. → A. » : les noms sont réduits à une initiale, illisibles.
  - Le solde (« -163.75 € ») et l'équilibre des « Foyers » reprennent la même information trois fois (solde perso, qui doit à qui, foyers).
  - Ratio « 1.0/0.5 » affiché brut, sans explication.
  - Montants à 2 décimales avec point (`842.00`, `-163.75`) alors que l'interface est en français.
  - Les noms des dépenses sont tronqués (« Courses su… »).
- **V5 — Repas** : le calendrier est lisible, mais :
  - Le texte d'aide en haut est un paragraphe de 3 lignes.
  - Les cases vides n'ont aucun signe d'action (pas de « + »).
  - Les cases sont grandes (~65 px de haut) pour un titre de 20 caractères.
  - Aucun indicateur par cellule (courses faites ? qui cuisine ?).
- **V6 — Liste** : les chips de repas défilent horizontalement hors de la page (débordement de 1562 px, voir N2) et le bouton « Supprimer la liste » en rouge plein est collé sous la liste, visible d'emblée.
- **V7 — Sondages** : trois radios en « pilules » + « Voter » sur une ligne qui passe à la suivante ; résultats (0 %) affichés avant d'avoir voté ; barre de progression vide ×3 inutile.
- **V8 — Membres / Invitations** :
  - Deux pages séparées pour presque le même objet (membres ≈ invités).
  - Une carte par membre avec code + boutons + gros « Retirer » rouge : 5 membres = 1700 px.
  - Page « Invitations » : jauge 5/10, lien, QR code, formulaire e-mail, liste de codes bruts sans nom (`guest000 pas d'email`).
- **V9 — Accueil / landing** : très aérée mais sans valeur ajoutée (pas de preuve visuelle, pas d'aperçu). Les cartes « Créer » et « Accéder » ont des poids visuels inversés (« Créer » en bordure orange, « Accéder » en carte blanche avec bouton plein).
- **V10 — Typographie / espacement** : titres de page 36 px et sections 24 px, tailles très proches ; interlignes inégaux ; l'unique couleur d'accent (terracotta) sert à la fois aux actions primaires, aux liens, aux badges, aux avatars, aux états actifs et aux boutons destructifs « Supprimer »/« Retirer » en rouge : la couleur ne distingue plus rien.

## 4. Organisation de l'information et parcours (à reprendre page par page)

**Principes à appliquer** : une page = une tâche principale, une action primaire visible, le reste regroupé ou dépriorisé ; l'écran d'accueil de l'événement répond à « que se passe-t-il maintenant et que dois-je faire ? ».

| Page | Problème de logique / flow | Direction |
|---|---|---|
| Accueil événement | Mélange hub, code perso, résumé du jour, sondages, tâches, chat, infos et zone de danger. Le chat est chargé en HTMX à la volée (`hx-trigger=load`). Rien ne dit « quoi faire maintenant ». | Héros : titre + dates + compte à rebours/« aujourd'hui », puis 3 blocs max (programme, à faire pour moi, derniers messages). Code perso, partage et gestion déplacés dans un menu « Événement ». |
| Mes événements | Liste brute, sans statut (à venir/en cours/passé), sans vue des invités actifs. | Cartes entièrement cliquables avec statut et dates. |
| Création événement | 1 seul écran de 5 champs + e-mail de vérification, avec le détail de la validation noyé en bas. | Étapes courtes (quoi/quand → qui) ; vérification e-mail expliquée avant. |
| Planning | Liste d'activités par jour + formulaire d'ajout + RSVP **en bas de page, dans une section distincte** (« Indiquez votre participation » reliste toutes les activités). | RSVP intégré à chaque carte d'activité ; ajout via bouton flottant/feuille ; formulaire avancé en feuille. |
| Repas | Tout se fait via une modale + drag ; le lien avec les listes de courses est dans une page tierce. | Vue par jour (swipe) sur mobile ; état « courses » par repas ; déplacement via menu. |
| Listes | Deux écrans (index → détail), chips de repas, claim/unclaim par bouton sur chaque ligne. | Vue « à acheter / pris / fait », assignation en un geste, regroupement par section. |
| Infos (logistique) | Trois pages de formulaire pour des fiches de texte (adresse, code d'accès…). | Cartes inline, édition sur place, copie en un tap. |
| Sondages | Création sur page dédiée ; résultats visibles avant le vote. | Création rapide en feuille ; résultats après vote ; clôture explicite. |
| Frais | Voir V4 : trop d'informations équivalentes, formulaire ouvert d'office. | En-tête « Mon solde » + « Je dois / on me doit » ; ajout d'une dépense en feuille ; détails dépliables. |
| Média | Non examiné avec contenu. | À auditer avec des photos. |
| Chat | Pas de zone de saisie ancrée en bas, suppression en gros bouton. | Saisie collée au bas de l'écran, action de suppression discrète (appui long/menu). |
| Membres + Invitations | Deux pages au rôle proche. | Fusionner en « Participants » (liste + inviter). |
| Footer + modale confidentialité | Présents sur chaque page, y compris sous la tabbar. | Déplacer dans « Événement/À propos ». |

## 5. Internationalisation (cible : 100 % traduit)

Source : français dans le code, anglais dans `translations/en/LC_MESSAGES/messages.po` (+ `messages.pot`).

- **Catégories de frais en anglais brut dans l'interface française** : `costs/index.html:70-75` affiche `{{ cat | capitalize }}` → « General / Food / Transport / Lodging / Activities / Other » ; le titre de l'icône (`title="{{ exp.category }}"`, ligne 235) et la « Répartition par catégorie » (« Lodging », « Food ») affichent aussi la clé interne. Aucune traduction.
- **Messages `flash()` non traduits** : **58 sur 94** appels ne passent pas par `_()` (`events/__init__.py`, `auth/__init__.py`, etc.). Exemples : « Code invalide (8 caractères). », « Lien invalide ou expiré. », « Limite d'invités atteinte. », « Format d'email invalide. ». Ils s'affichent en français quand l'utilisateur est en anglais.
- **Catalogue EN** : 397 entrées, **8 sans traduction** (« Créateur », « Ton groupe (ménage) », « Cochez les activités déjà préparées. », le texte d'aide des repas, « OK »…), **30 « fuzzy »** (non validées, donc ignorées à la compilation : « Navigation », « Ajouter une dépense », « Foyers », « Supprimer cette dépense ? »…), 13 identiques au français (certaines légitimes : « Chat », « Email »).
- **Texte en dur** : libellé `Français` du sélecteur de langue (légitime) ; JS du bouton « Voir »/« Masquer » : `'Voir'` en dur (`base.html:389`) ; `FEATURE_LABELS` et « Fonctionnalité avancée » en dur dans `freemium.py`. Les emojis servent d'icônes sans alternative textuelle traduite.
- **Formats** : montants (`842.00`) et dates dans les formulaires ne suivent pas la locale.
- `app/translations/` n'existe pas : les traductions sont dans `translations/` à la racine. À vérifier que la config Babel (`BABEL_TRANSLATION_DIRECTORIES`) pointe bien dessus (l'app lance l'anglais sans erreur, donc oui).
- Aucune vérification des pages non capturées (`join`, `recover`, e-mails d'invitation, PDF d'export, paywall) : les e-mails sont probablement aussi en français uniquement.

## 6. CSS / dette technique (conditionne la migration Tailwind)

- 1 fichier `main.css` de **5391 lignes**, ajouté par couches (« Lot 1 », « Lot 5 »…). Sélecteurs définis plusieurs fois (`.card`, `.flash` ×3, `.progress-fill`, `.item-name`, `.code-input`, `select`, `h4`, `.tag-ok`…) → l'ordre de déclaration décide du rendu.
- 6 breakpoints différents (420, 480, 600, 640, 768, 900) ; la navigation bascule à 768, les tableaux à 640, les formulaires de frais à 420/600.
- Tokens riches (couleurs, rayons, ombres, espacements, typo) mais ~11 couleurs en dur hors tokens et 8 `style=""` inline ; 8 `!important`.
- Trois familles d'icônes mélangées : SVG (navigation), emojis (boutons, titres), caractères (＋ → ✓).
- Alpine.js embarqué (`alpine.min.js`) mais le JS réel est du vanilla dupliqué dans les templates : copie de code, thème, menu « Plus », modale confidentialité, partage… tout dans `base.html` (≈ 180 lignes) et `dashboard.html`.
- Accessibilité de base présente (labels, `aria-*`, focus visible) mais : `role=menu` sur « Plus » sans gestion des flèches ; modales sans piège de focus ; pas de `prefers-contrast`.
- Tests : 15 fichiers couvrent les routes et la logique, aucun test d'interface ni de rendu → une refonte visuelle n'a pas de filet automatique.

## 7. Synthèse par priorité

**P0 — bloque l'usage mobile**
1. Débordements horizontaux (dashboard, liste) → barre de navigation instable (N2).
2. Drag & drop repas inutilisable au tactile (I2).
3. Barre du bas : 4 onglets + Plus, Repas caché, état actif perdu, absente hors événement (N1, N3, N4).
4. Catégories de frais en anglais ; 58 flashes non traduits (section 5).

**P1 — ergonomie**
5. Cartes entièrement cliquables (I1) ; cibles tactiles ≥ 44 px (I3).
6. Hiérarchie des boutons (I4, I5, V10) : un seul bouton plein par écran, destructifs discrets.
7. Formulaires (V1, V2) : sections, champs adaptés au mobile, feuille d'ajout rapide.
8. Dashboard et Frais à repenser (V3, V4).

**P2 — cohérence**
9. Fusion Membres/Invitations, déplacement du footer, icônes uniformes, feedback de chargement, remplacement de `confirm()`.

## 8. Recommandations pour la suite

- Choix déjà faits par l'utilisateur : tabbar 5 onglets + « Plus », drag tactile + bouton « Déplacer », migration Tailwind en big-bang (sur la branche `ui/tailwind-refonte`).
- Avant tout codage (conforme à `AGENTS.md`) : écrire une spec par lot (`specs/B0xx-*.md`). Proposition d'ordre :
  1. Socle : Tailwind (build local, pas de CDN), tokens, composants, shell mobile + barre du bas.
  2. i18n complète (catégories, flashes, fuzzy) — indépendant du CSS, faisable en parallèle.
  3. Accueil événement + Mes événements.
  4. Planning (liste + formulaires), Repas (drag tactile + déplacer), Listes.
  5. Frais, Sondages, Infos, Chat, Média, Participants.
  6. Pages d'authentification/landing, e-mails, PDF.
- Prévoir un script de captures automatisé (comme celui de cet audit) en mobile/desktop et clair/sombre pour comparer avant/après à chaque lot.

Captures et rapports bruts de cet audit : `/tmp/claude-1000/-home-petitdadm--nanobot-workspace-saas/1471d40b-bd76-4825-bc2d-194897399640/scratchpad/` (`shots/`, `report-mobile.json`, `report-desktop.json`, `seed.py`, `shoot.mjs`).

---

## 9. Registre des défauts de flux et de logique (lecture exhaustive du code)

Source : lecture complète des 36 templates et des 10 modules Python. Chaque entrée porte un identifiant `F..` que les specs de lot référencent. « Prod » = bloque ou dégrade une mise en production.

### Accès, comptes, session
- **F01 (Prod)** `events.access_by_code` exige exactement 8 caractères et ne connaît que le code personnel du créateur, alors que `verify`/`join` acceptent 4 à 8 caractères. Un créateur avec un code de 6 caractères ne peut pas se reconnecter depuis l'accueil. Un invité qui a perdu l'URL n'a aucun moyen de retrouver son événement : il n'existe pas de « mes événements » côté invité.
- **F15 (Prod)** La session invité n'est pas permanente (cookie de session navigateur) alors que la page « Rejoindre » promet que le code sert à se reconnecter. `PERMANENT_SESSION_LIFETIME` (24 h) n'est effectif que si `session.permanent = True`. L'invité mobile perd l'accès à la fermeture du navigateur.
- **F16 (Prod)** `recover_code` sans SMTP affiche le code personnel dans un message flash : toute personne connaissant l'e-mail obtient le code. C'est le cas de l'instance de staging (SMTP vide). Les messages distinguent « compte inconnu » de « envoyé » (énumération d'e-mails). Tutoiement (« Ton code ») incohérent avec le vouvoiement ailleurs.
- **F17** La répartition des erreurs par champ se fait par recherche de sous-chaînes françaises (`'Titre' in e`, `'Date' in e`…) dans `events/create.html` et `planning/form.html` : elle casse dès que les messages sont traduits.
- **F22** Le créateur n'a pas de pastille dans l'en-tête (pas de session invité) ; son nom vient de `email.split('@')[0].title()`. Après `verify`, l'e-mail est effacé sauf opt-in : le créateur dépend alors uniquement de son code.
- **F09** Les modules non connectés renvoient vers `/join` pour Frais et Média, vers `/mycode` pour les autres : comportement incohérent.

### Participants, partage, pages orphelines
- **F02 (Prod)** `events.invite` redirige vers le tableau de bord quand la limite d'invités est atteinte : la page Invitations, qui contient la carte d'upgrade, est inaccessible précisément à ce moment (la branche `at_limit` du gabarit est morte). Le compteur inclut le créateur.
- **F03** Le bouton « Partager » du tableau de bord copie l'URL du tableau de bord (`/e/<code>`), qui renvoie un nouvel arrivant vers « Votre code » et non vers « Rejoindre ». Le lien d'invitation réel (`/join`) n'est accessible qu'au créateur dans « Invitations ».
- **F04** Pages inaccessibles depuis l'interface : Membres (`events.members`), Journal (`events.log`), Export PDF (`events.export_pdf`). `main/dashboard.html` est un gabarit placeholder inutilisé (« Le SaaS est opérationnel »).
- **F21** Un membre ajouté par le créateur dans « Membres » n'a pas de foyer : il n'apparaît pas dans les Frais.
- **F18** Le Journal affiche les codes d'action techniques (`activity.created`), limité à 100 lignes sans pagination ni filtre (TASKS B002 promettait pagination et filtres).

### Planning, repas, listes
- **F10** `min_headcount` et `bring_items` sont saisis mais jamais affichés ; aucun décompte de RSVP, alors que `Activity.confirmed_count` existe. Le créateur ne peut pas répondre (« Le créateur ne fait pas de RSVP. ») bien qu'il soit participant partout ailleurs (vote, foyer). Les activités sont listées deux fois (liste + section RSVP).
- **F11** Dans les listes, quantité, section et attribution ne sont pas saisissables (le formulaire rapide n'envoie que le nom) alors que l'affichage les gère ; `list_type` n'est jamais défini. Un article ne peut être coché qu'après « Je m'occupe » (deux étapes) ; ceux pris par quelqu'un d'autre ne sont cochables par personne. L'attribution est comparée par nom d'affichage (`item.assigned_to == actor_name`, repli « Créateur » en dur). Chaque action recharge la page et perd la position de défilement. `autofocus` ouvre le clavier au chargement sur mobile. Suppression d'article réservée au créateur.
- **F25** Repas : seulement déjeuner/dîner, aucun détail (qui cuisine, convives), échange via un créneau temporaire `"tmp"`.

### Frais
- **F06 (Prod)** Une demande de paiement perd sa note : le formulaire envoie `note`, le serveur lit `message`, le gabarit affiche `pr.note` (attribut inexistant).
- **F07 (Prod)** Le sélecteur de devise n'a pas de champ de taux : un montant en USD est compté comme des euros (taux 1.0). La date de la dépense n'est pas saisie ; `format_date(None)` affiche la date du jour, qui change chaque jour.
- **F08** Le formulaire « Transfert » n'apparaît qu'une fois un transfert enregistré (`{% if transfers %}`). « Ajouter un foyer » et le ratio sont réservés au créateur dans l'interface mais ouverts à tous côté serveur ; un invité ne peut pas supprimer sa propre erreur de saisie ; les dépenses personnelles des autres foyers sont visibles de tous ; formats de nombres mêlés (`0,00 €` / `142.50`) ; « € » en dur malgré les devises.

### Sondages, infos, chat, média
- **F05** Aucun bouton pour clore un sondage (route `voting.close` jamais appelée) ni pour en supprimer un ; les résultats sont visibles avant le vote.
- **F12** Infos : champ « Ordre d'affichage » numérique exposé à l'utilisateur ; catégories affichées dans l'ordre alphabétique des clés ; le tableau de bord réaffiche la liste complète.
- **F14** Chat : le polling toutes les 5 s fait défiler la liste jusqu'en bas à chaque rafraîchissement (impossible de relire l'historique) ; l'aperçu du tableau de bord charge 50 messages pour en montrer 3 ; envoi sans HTMX (rechargement complet).
- **F13 (Prod)** Média : une photo à la fois, limite de 10 envois par heure ; la grille charge les originaux (jusqu'à 50 Mo) sans miniature ; HEIC accepté mais non affichable par la plupart des navigateurs (photos d'iPhone cassées) ; pas de visionneuse (précédent/suivant), de téléchargement ni de carte ; coordonnées brutes ; messages d'envoi non traduits.

### Plateforme
- **F19 (Prod)** Appels à l'action factices présentés comme réels : « Passer à Vacances+ », « Essai de 14 jours, sans carte », bouton « Générer le PDF » non branché. `freemium/pdf_export.html` contient `{{ event.title }}` à l'intérieur d'une chaîne `_()` : le titre ne s'interpole pas.
- **F20** Pas de gestionnaire d'erreur 500 ni de page hors ligne ; le service worker sert `/static/` en cache d'abord avec un nom de cache manuel (`holishared-v3`) : risque récurrent de CSS périmé (déjà arrivé, commit 7b05bb0) ; `alpine.min.js` est mis en cache mais jamais chargé (htmx seul est chargé).
- **F24** Couplage des tests : ~102 assertions sur du texte HTML (`assert b"…"`), une sur la classe `meal-card`, une sur `<ul class="nav-links">`. Toute refonte doit adapter ces tests de façon traçable (jamais les supprimer).

## 10. Principes produit pour un niveau « professionnel »

1. Une page = une tâche principale ; une seule action primaire visible ; les actions rares ou destructives sont dépriorisées et confirmées.
2. Mobile d'abord : zone du pouce, cibles ≥ 44 px, aucune barre de défilement horizontale, barre du bas toujours visible, feuilles ancrées en bas.
3. Toute action fréquente (cocher, voter, répondre, envoyer) se fait en un geste, sans rechargement complet, avec retour immédiat et annulation possible.
4. Chaque donnée saisie est affichée là où elle sert ; aucune donnée collectée sans usage visible (F10, F11, F12).
5. Aucun appel à l'action factice en production ; l'état « bientôt » est dit comme tel (F19).
6. Interface entièrement traduite (FR/EN), formats de dates et de nombres localisés, aucun code technique visible.
7. Accessibilité WCAG 2.1 AA vérifiée automatiquement (contraste, étiquettes, focus, clavier) en clair et en sombre.
8. Fiabilité : états vides, chargement, erreur et hors ligne conçus ; erreurs de formulaire indiquées par champ sans dépendre du texte.
9. Sécurité et vie privée : aucune fuite de code ou d'e-mail, sessions durables mais maîtrisées, rate limits adaptés à l'usage réel.

### Compléments (lecture du service worker et du manifest)
- **F20 (suite)** Le service worker est enregistré depuis `/static/js/service-worker.js` sans en-tête `Service-Worker-Allowed` : sa portée par défaut est `/static/js/`. Il ne contrôle donc aucune page de l'application, ne peut ni mettre en cache ni servir une page hors ligne, et sa règle « cache d'abord » ne concerne que les requêtes déclenchées depuis sa propre portée. À servir depuis la racine (`/sw.js`) pour la portée `/`.
- **F26** Aucune implémentation Web Push : seules les clés VAPID sont générées (`manage.py`, `.env.example`) ; pas de modèle d'abonnement, d'endpoint, de gestionnaire `push` dans le service worker, ni de dépendance `pywebpush`. TASKS B014 n'a jamais été réalisé.
- **F27** Un sondage ne peut porter que sur des options textuelles libres : impossible de départager des activités existantes du Planning (pas de lien option → activité, pas de statut d'activité retenue / non retenue).
