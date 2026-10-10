# Spec B035 — Import/Export XLSX des listes

## Périmètre

Exporter et importer les listes partagées (`SharedList`/`ListItem`) au format
`.xlsx`. Un seul module concerné : `lists`. Pas de CSV, pas d'import/export des
autres modules, pas de mapping personnalisé de colonnes, pas de mise à jour
d'une liste existante (l'import crée toujours de nouvelles listes).

## Export

- `GET /e/<code>/lists/export.xlsx` — toutes les listes de l'événement :
  une feuille par liste. Nom de feuille = titre de la liste, tronqué à 31
  caractères, collisions suffixées `-2`, `-3`…
- `GET /e/<code>/lists/<list_id>/export.xlsx` — une seule liste (1 feuille).
- Colonnes (en-tête ligne 1, localisé selon la langue active) :
  `Section | Item | Quantité | Assigné à | Fait`
  (mapping : `section`, `name`, `quantity`, `assigned_to`, `is_done` →
  « Oui »/« Non » localisés).
- Contenu UTF-8, accents préservés. Fichier généré en mémoire (BytesIO),
  téléchargement nommé `listes-<code>.xlsx` / `<titre-liste>.xlsx`.
- Droits : participant de l'événement (pattern `load_event_context`).

## Import

- `POST /e/<code>/lists/import` (multipart : fichier `.xlsx` + champ optionnel
  `title` pour le titre de la nouvelle liste, défaut = nom du fichier sans
  extension).
- Format attendu : même schéma que l'export. En-têtes reconnus FR/EN,
  insensibles à la casse et aux accents. Une feuille = une liste ; toutes les
  feuilles du classeur sont importées, sauf une feuille nommée `README`.
- Lignes : `name` requis (ligne ignorée + comptée sinon), `quantity` défaut
  « 1 », `is_done` reconnu via les valeurs localisées (« oui »/« yes »/« x »/
  « true »/« 1 »…), `assigned_to` texte libre (pas de résolution d'identité).
- Cellules formule : on lit la valeur calculée si présente, sinon on ignore
  (jamais d'exécution).
- **Rapport d'import** : flash i18n récapitulatif (X listes, Y items importés,
  Z lignes ignorées avec numéros).
- Limites : max 500 lignes par feuille, max 20 feuilles, fichier max 2 Mo.
  Dépassement → erreur propre i18n, rien n'est importé (transaction).

## Sécurité / accessibilité

- CSRF + rate limiting sur l'import (`@limiter.limit`, pattern existant).
- Validation extension `.xlsx` uniquement (pas de `.xls` legacy) ; lecture
  openpyxl en mode valeurs (pas d'exécution de contenu).
- Input fichier avec `<label>` (WCAG), message d'erreur accessible.
- i18n FR/EN de tous les messages (boutons, flash, en-têtes).

## Dépendance

- `openpyxl` ajouté à `requirements.txt` ET `pyproject.toml`.

## Tests

`tests/test_lists_xlsx.py` :
- Export : contenu (valeurs, accents, en-têtes localisés), une feuille par
  liste, collisions de noms de feuilles, export single-list.
- Import : round-trip export → import (identique), en-têtes FR/EN,
  lignes invalides ignorées + rapport, `is_done` multi-locale, limites
  (500/20/2 Mo) → rien importé, fichier non-xlsx → rejet, CSRF absent → rejet.
- Droits : participant OK, inconnu 404/403 (pattern existant).
- i18n : messages présents dans les 2 catalogs.

## Définition de « terminé »

1. `ruff check . && ruff format --check .` → vert
2. `mypy app/` → vert
3. `pytest` → vert (nouveau + régression)
4. `CHANGELOG.md`, `TASKS.md` (lot ✅), `DEV_LOG.md` mis à jour
5. Commits atomiques Conventional Commits (scope `lists`)
