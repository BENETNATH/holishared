# ADR-001 : SQLite pour la v1

## Statut
Accepté (2026-10-04)

## Contexte
Choix du SGBD pour la v1 de holishared.

## Décision
SQLite via Flask-SQLAlchemy.

## Raisons
- Zéro infrastructure (pas de daemon, pas de port)
- Un seul fichier à sauvegarder
- Suffisant pour < 1000 événements actifs
- Migration Postgres possible plus tard (SQLAlchemy abstract)

## Conséquences
- Pas de concurrence write/write (suffisant pour l'usage)
- Backup = copie du fichier
- Pas de full-text search natif (FTS5 si besoin)
