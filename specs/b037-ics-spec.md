# Spec B037 — Feed iCal en lecture (partageable)

## Problème

Les « non décideurs » du groupe (famille, accompagnants) veulent suivre le
programme sans compte ni code personnel. Un flux iCal en lecture, partageable
en un lien, résout ça : ils s'abonnent dans Google/Apple/Outlook et le
programme se met à jour tout seul.

## Périmètre

Un endpoint de lecture + un bouton « Calendrier » sur l'accueil. Pas de
module, pas de modèle, pas de dépendance (ICS généré en pur Python). Pas
d'écriture (le flux est en lecture seule par nature).

## Endpoint

- `GET /e/<code>/calendar.ics`
- Droits : `load_event_context(code, require="none")` — le code événement
  suffit (pas de code personnel, pas de session). Cohérent avec le modèle
  d'accès de l'app : le programme est une information partagée du groupe.
  Code inconnu ou événement non vérifié → 404 (pattern existant).
- Réponse : `Content-Type: text/calendar; charset=utf-8`,
  `Content-Disposition: inline; filename="holishared-<code>.ics"`,
  `Cache-Control: no-cache` (le programme change souvent ; les apps
  calendrier refetchent périodiquement).

## Contenu

- `VCALENDAR` : `VERSION:2.0`, `PRODID:-//holishared//FR`,
  `X-WR-CALNAME:` = titre de l'événement (échappé).
- Une `VEVENT` par **activité** (`status != "dropped"`), dans l'ordre
  date/heure :
  - sans heure : journée entière — `DTSTART;VALUE=DATE:YYYYMMDD`,
    `DTEND;VALUE=DATE:` = jour suivant ;
  - avec heure : `DTSTART:YYYYMMDDTHHMMSS` (heure locale flottante, sans
    TZID — convention des apps de vacances), `DTEND` = `end_time` si
    renseignée, sinon début + 1 h ;
  - `SUMMARY` = titre, `LOCATION` = lieu (si renseigné),
    `DESCRIPTION` = description (si renseignée).
- Une `VEVENT` par **repas** : `DTSTART` = date + 12:00 (Midi) / 20:00 (Soir)
  (même convention que la timeline de l'accueil), `DTEND` = +1 h,
  `SUMMARY` = « <libellé du créneau> — <titre> » (libellé localisé via
  `label(slot, "meal_slot")` selon Accept-Language).
- `UID` stable par objet : `holishared-<code>-act-<id>` /
  `holishared-<code>-meal-<id>` → les apps calendrier mettent à jour au lieu
  de dupliquer à chaque resynchronisation.
- `DTSTAMP` = maintenant (UTC, `YYYYMMDDTHHMMSSZ`).
- **Échappement ICS** des champs texte (SUMMARY/LOCATION/DESCRIPTION/
  X-WR-CALNAME) : `\` → `\\`, `;` → `\;`, `,` → `\,`, saut de ligne → `\n`.
- Événement sans activité ni repas : VCALENDAR valide sans VEVENT.

## Bouton « Calendrier » (accueil)

- Dans les actions rapides du héros, après « Partager » : bouton
  `ui-btn--secondary` avec icône calendrier, `data-copy` = URL du flux ICS
  (même pattern de copie que « Partager »).
- Chaîne i18n : « Calendrier » / « Calendar ».

## Tests (TDD)

Nouveau fichier `tests/test_ics.py` :
- 200 + `text/calendar` avec un code valide, **sans session** (client
  anonyme) ; 404 code inconnu ; 404 événement non vérifié.
- En-têtes : VERSION:2.0, PRODID, X-WR-CALNAME = titre (échappé).
- Activité journée entière : `DTSTART;VALUE=DATE` + DTEND jour suivant.
- Activité horaire : DTSTART/DTEND corrects ; end_time honorée ; sinon +1 h.
- Activité `dropped` absente.
- Repas : DTSTART 12:00 / 20:00 ; SUMMARY « Midi — <titre> ».
- Échappement : titre avec virgule/point-virgule/saut de ligne.
- UID stables entre deux fetchs ; distincts par objet.
- LOCATION/DESCRIPTION présents quand renseignés, absents sinon.
- Événement vide : VCALENDAR sans VEVENT.
- Bouton « Calendrier » : présent sur l'accueil, `data-copy` = URL ICS.

## i18n

- « Calendrier » → « Calendar » (bouton).
- Libellés de créneau existants (« Midi »/« Soir ») réutilisés via `label()`.

## Hors périmètre

- Pas de fuseau horaire configurable (heure locale flottante).
- Pas d'invitation, pas de RSVP, pas de sync bidirectionnelle.
- Pas de feed par sous-ensemble (activités seulement / repas seulement).
