# Spec B036 — Dashboard « Pour moi » : sections de listes repliables

## Problème

La carte « Pour moi » de l'accueil n'affiche que les listes où le visiteur a
des articles attribués (titre en petit lien). Les autres listes sont
invisibles : impossible de s'y retrouver (quelles listes existent, où en est
chacune) sans ouvrir la page Listes.

## Périmètre

Un seul fragment : `events/_my_items.html` (carte « Pour moi »), ses données
(`home_items()` dans `app/lists/__init__.py`) et la conservation de l'état
replié/ouvert côté client (`app/static/js/ui/htmx.js`). La carte « À répartir »
est inchangée. Pas de changement de routes, de droits ou de modèle.

## Comportement

- Chaque liste de l'événement devient une **section repliable** (`<details>`)
  dans la carte « Pour moi », dans l'ordre de création des listes.
- En-tête de section (`<summary>`, cible tactile ≥ 44 px) :
  - titre de la liste, lien vers `lists.detail` (le clic sur le titre navigue,
    le clic ailleurs sur l'en-tête replie/déplie) ;
  - badge de progression **de la liste entière** `fait/total` (ex. `3/10`),
    même sémantique que les cartes de la page Listes.
- Corps de section :
  - mes articles non cochés (cases à cocher HTMX, identiques à l'existant) ;
  - « Déjà pris » (N) : `<details>` imbriqué avec mes articles cochés
    (identique à l'existant) ;
  - si je n'ai aucun article non coché dans la liste :
    - si j'ai des articles cochés : « Rien à faire — N déjà pris. » + « Déjà pris » ;
    - sinon : « Aucun article à votre charge dans cette liste. »
- **État ouvert par défaut** : la section est ouverte si j'ai au moins un
  article non coché dans la liste, repliée sinon (gain d'espace).
- **Conservation de l'état** : après un re-rendu HTMX du fragment
  (coche/décoche/attribution), l'état ouvert/fermé choisi par l'utilisateur
  est restauré (carte JS `listId -> open` mise à jour avant le swap,
  réappliquée après). Sans JS, l'état serveur (règle ci-dessus) s'applique.
- Aucune liste dans l'événement : état vide « Aucune liste pour l'instant. »
  (remplace l'état vide actuel, qui supposait l'existence de listes).
- Compteur d'en-tête de carte inchangé : `pris/total` sur **mes** articles.

## Données

`home_items()` renvoie `lists` (remplace `groups`) : une entrée par liste de
l'événement, dans l'ordre de création :

```python
{"list": SharedList, "done": int, "total": int, "open": [ListItem], "done_mine": [ListItem]}
```

- `done`/`total` : progression de la liste entière via `_list_stats()`
  (une seule requête, pattern existant de `lists.index`).
- `open`/`done_mine` : mes articles (non cochés / cochés), vides si aucun.
- `total`/`taken` (compteur carte), `unassigned`, `unassigned_total` : inchangés.

## Tests (TDD)

- Toutes les listes rendues en sections (2 listes : une avec mes articles,
  une sans) — titre + lien + progression de chaque liste.
- Progression = liste entière (articles d'autres participants comptés).
- Section ouverte si j'ai des articles non cochés ; repliée sinon
  (uniquement cochés, ou aucun article).
- Corps : « Aucun article à votre charge dans cette liste. » quand aucun
  article à mon nom ; « Rien à faire — N déjà pris. » quand uniquement cochés.
- État vide « Aucune liste pour l'instant. » sans liste.
- Fragment HTMX après toggle/claim : toutes les sections présentes, compteur
  carte à jour (tests existants adaptés au nouveau testid `my-list`).
- `my-items-count`, `my-items-done`, `unassigned-*` : comportement inchangé.

## i18n

Nouvelles chaînes FR (source) + traductions EN :
- « Aucune liste pour l'instant. »
- « Aucun article à votre charge dans cette liste. »
- « Rien à faire — %(n)d déjà pris. » / pluriel « Rien à faire — %(n)d déjà pris. »
  (une seule forme, `%(n)d`)

## Hors périmètre

- Carte « À répartir » (inchangée).
- Page Listes et détail de liste (inchangés).
- Pas de tri/filtre des sections, pas de persistance de l'état replié en base.
