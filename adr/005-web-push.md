# ADR-005 : Notifications Web Push (VAPID, pywebpush, RQ)

## Statut
Accepté (2026-10-07)

## Contexte
Les participants veulent être prévenus d'un message, d'un sondage ou d'une demande de remboursement sans
ouvrir l'application. Pas de compte forcé ni de service tiers de notification : la PWA est déjà installée.

## Décision
- **Web Push standard (VAPID)** : clés générées par `manage.py`, clé publique exposée à la page, clé privée
  uniquement côté serveur et worker.
- **pywebpush** pour le chiffrement et l'envoi ; la clé privée (PKCS8 base64url de `manage.py`) est chargée
  par `py_vapid.Vapid.from_string`, sans régénération.
- **RQ** : un job `send_push` par abonnement, sans contexte Flask. La clé privée et la base viennent de
  l'environnement du worker et ne transitent pas par Redis. Mise en file après le commit.
- **Abonnement par appareil** : unicité (événement, endpoint) car un navigateur renvoie le même endpoint pour
  tous les événements ; préférences (messages, sondages, remboursements, aperçu) par appareil.
- **Aucune donnée sensible dans le payload** : nom de l'événement, texte tronqué à 90 caractères (ou texte
  générique sans aperçu), lien profond ; jamais d'e-mail ni de montant. Langue = celle du navigateur de l'abonné.
- **Dégradation silencieuse** : sans clés VAPID, sans Redis, ou en cas d'erreur, journalisation seule ; les
  abonnements 404/410 sont supprimés par le worker.

## Conséquences
- Le texte transite par le service de push du navigateur (Google, Mozilla, Apple) : indiqué dans la feuille
  de confidentialité ; abonnement révocable à tout moment, supprimé avec le participant ou l'événement.
- Le worker doit partager la base SQLite (volume) et recevoir `VAPID_*`.
- iOS : permission seulement en PWA installée ; états explicites, non testables en CI.
