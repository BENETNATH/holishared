# ADR-003 : Zéro PII pour les invités

## Statut
Accepté (2026-10-04)

## Contexte
Modèle d'accès pour les invités (pas de compte).

## Décision
L'invité se connecte avec un code perso (8 chars) généré à la première visite.
Seul le `display_name` est stocké. Pas d'email, pas de téléphone, pas de compte.

## Raisons
- Privacy-first : l'invité n'a pas de trace numérique
- Simplicité : pas de flow d'inscription
- RGPD : pas de donnée personnelle à protéger
- Isolation : le code est lié à un événement, pas global

## Conséquences
- Pas de récupération de code (perdu = re-join)
- Pas de notification email aux invités (Web Push uniquement)
- Le display_name est le seul identifiant visible
