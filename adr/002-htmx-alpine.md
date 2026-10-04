# ADR-002 : HTMX + Alpine.js (pas de SPA)

## Statut
Accepté (2026-10-04)

## Contexte
Choix du frontend pour un SaaS de planification.

## Décision
SSR Flask + HTMX pour l'interactivité + Alpine.js pour le state client léger.

## Raisons
- Pas de build step (pas de webpack/vite)
- Pas de framework JS lourd (React/Vue)
- Accessibilité native (HTML sémantique)
- PWA plus simple (app shell = HTML)
- Lighthouse scores élevés par défaut
- Maintenance : un seul langage (Python + HTML)

## Conséquences
- Pas de re-render client (polling HTMX pour le chat)
- Templates Jinja = source de vérité
- Alpine pour les interactions locales (dropdowns, modals)
