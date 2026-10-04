# Spec B008 — Blueprint Chat

**Statut** : SPEC
**Date** : 2026-10-04
**Lot** : B008
**Dépendances** : B001 (models, extensions)

---

## 1. Périmètre

Chat par événement, polling HTMX (pas de WebSocket en v1).
Chaque événement a son propre chat, isolé.

**Hors périmètre** :
- WebSocket (v2)
- Messages éphémères
- Partage de fichiers dans le chat

---

## 2. Modèle

```python
class ChatMessage(db.Model):
    __tablename__ = "chat_messages"
    id: str (32, PK, hex)
    content: str (Text, NOT NULL, max 2000)
    created_at: datetime (default utcnow, index)
    guest_id: str (32, FK guests.id, nullable)  # NULL si créateur
    author_name: str (100, NOT NULL)  # denormalized
    author_type: str (20, NOT NULL)  # "creator" | "guest"
    event_id: str (32, FK events.id, NOT NULL, index)
```

---

## 3. Routes

### 3.1 — Historique

```
GET /e/<code>/chat
```

- Accès : créateur ou guest en session
- Charge les 50 derniers messages (tri created_at DESC, inversé pour affichage ASC)
- Variables : event, messages, guest

### 3.2 — Envoi

```
POST /e/<code>/chat/send
```

- Accès : créateur ou guest en session
- Champ : `content` (1-2000 chars, strip)
- Si vide → flash "Message vide."
- Crée le ChatMessage
- Log ActivityLog : action="chat.message", target=content[:50]
- Redirect → GET /e/<code>/chat (ou HTMX partial si HX-Request)

### 3.3 — Suppression (modération)

```
POST /e/<code>/chat/<msg_id>/delete
```

- Permission : créateur de l'événement OU auteur du message
- Log : "chat.message_deleted"

---

## 4. Templates

### `chat/index.html`
- Zone de messages (scrollable, max-height 60vh)
- Chaque message : avatar (initiale), nom, heure, contenu
- Formulaire d'envoi en bas (input + bouton)
- Auto-scroll en bas
- Polling HTMX : `hx-get` toutes les 5s sur `#messages`

### `chat/_messages.html` (partial HTMX)
- Fragment HTML des messages (pour le polling)

---

## 5. Tests (tests/test_chat.py)

- test_index_renders_for_creator
- test_index_renders_for_guest
- test_index_404_invalid_code
- test_index_redirects_no_access
- test_send_message_success
- test_send_message_empty
- test_send_message_too_long
- test_send_message_logs
- test_send_as_guest
- test_delete_own_message
- test_delete_message_as_creator
- test_delete_forbidden_for_other
- test_delete_404_invalid_id
- test_history_shows_50_max

**Total : 14 tests**

---

## 6. Fichiers

| Fichier | Action |
|---------|--------|
| `app/models.py` | Ajouter ChatMessage |
| `app/chat/__init__.py` | Créer blueprint |
| `app/templates/chat/index.html` | Créer |
| `app/templates/chat/_messages.html` | Créer |
| `tests/test_chat.py` | Créer (14 tests) |
| `app/__init__.py` | Register blueprint |
