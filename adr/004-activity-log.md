# ADR-004 : Tracabilité via ActivityLog en base

## Statut
Accepté (2026-10-04)

## Contexte
Besoin de tracer chaque action sur un événement, visible par tous les participants.

## Décision
Table `activity_logs` en base, écrite à chaque action significative.
Route dédiée `/e/<code>/log` pour l'affichage.

## Raisons
- Visible par tous (pas un log serveur réservé à l'admin)
- Auditable (SQL, exportable)
- Pas d'infrastructure externe (pas de Kafka, pas de ELK)
- Isolation par événement (FK event_id)
- Performance : index sur event_id + created_at

## Conséquences
- Volume : ~5-20 logs/jour/événement (négligeable)
- Pas de suppression (log immuable)
- Le log est un feature, pas un debug tool
