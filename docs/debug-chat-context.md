# Debugging chat context with the LLM

This doc explains how conversation context is stored, why it can appear "lost", and how to debug it.

## Two different stores

| Store | Path | Purpose |
|-------|------|--------|
| **AI suggestions log** | `data/binance/orders/ai_suggestions.jsonl` | Append-only log of every user message + Claude reply + optional orders CSV. **Global** (not per session). Used for audit / replay. |
| **Conversation history (context)** | `data/binance/chat_sessions/{session_id}.json` | Per-session chat history (LangChain). This is what the backend **injects into the prompt** so the LLM "remembers" the thread. |

The LLM only "sees" context from **chat_sessions**. The `ai_suggestions.jsonl` file is not read back into the prompt; it is only written for logging.

## Why "do you remember?" got "I don't have memory" (e.g. line 4 in ai_suggestions.jsonl)

When the user asked *"in this chat, do you remember what we are talking about? what currency we short?"* and Claude replied *"I don't have any memory of previous conversations"*, that means **the prompt sent to Claude did not contain the conversation history** for that request. Common causes:

1. **Different or missing `session_id`**  
   - Context is keyed by `session_id` (frontend sends it; stored in `localStorage` as `cq_chat_session_id`).  
   - If the user opened a **new tab**, **incognito**, or **cleared site data**, the frontend creates a new `session_id`, so the backend has no history for that ID.  
   - If the frontend did not send `session_id` for that request (e.g. old client or bug), backend gets `session_id=None` and does not load history.

2. **Server has no persistent disk**  
   - On **ephemeral** hosting (e.g. some Railway/Heroku setups), `data/binance/chat_sessions/` may be empty after a restart or on a different instance.  
   - So even with the same `session_id`, the server that handles the "remember?" request might not have the same files as the one that handled the earlier messages.

3. **LangChain chat history not available**  
   - Session files are written by `FileChatMessageHistory` from **langchain_community**. If `langchain-community` is not installed, the backend imports fail and no session files are created (directory stays empty).  
   - Fix: `pip install langchain-community` (and add to `requirements.txt`).  
   - On startup the backend logs either `Chat session storage: enabled at ...` or `Chat session storage: disabled (...). Install: pip install langchain-community`.

## How to debug

### 1. Check what the backend has for this session

Call the session API with the **same `session_id`** the frontend uses (you can read it from the browser: Application → Local Storage → `cq_chat_session_id`, or from the network tab when sending a chat message):

```bash
curl "http://localhost:8000/api/chat/session?session_id=YOUR_SESSION_ID"
```

Example response:

- `{"session_id": "sess_abc123", "has_history": true, "message_count": 6}` → backend has 6 messages for that session; they should be in the prompt.
- `{"session_id": "sess_abc123", "has_history": false, "message_count": 0}` → no history; that’s why the LLM said it has no memory.

If you don’t send a `session_id`, the response will show `has_history: false` and `message_count: 0`.

### 2. Watch backend logs when sending a message

When a chat request is handled, the backend logs one line like:

```
[backend_server] chat context: session_id='sess_xyz' has_history=True message_count=6
```

- **`has_history=False` or `message_count=0`** for the "remember?" message → context was empty for that request (see causes above).
- **`has_history=True`** but the model still says it doesn’t remember → then the issue is prompt shape or model behaviour; enable full prompt logging (step 3).

### 3. Log the full prompt sent to Claude

Set:

```bash
export DEBUG_CLAUDE_PROMPT=1
```

Then run the backend (e.g. `python scripts/backend_server.py`). For each chat request, the backend will print the **full** prompt to stderr, including the "Conversation history (most recent last):" block if it was added.

- If that block is **missing**, the problem is `session_id` or history load (step 1–2).  
- If that block **is present** with the right prior messages, the model was given context; you can then check wording or model behaviour.

### 4. Verify where history is stored

- **Local:**  
  `data/binance/chat_sessions/` should contain files named `{session_id}.json`.  
  Check that the file for your session exists and grows after each turn.

- **Hosted (e.g. Railway):**  
  If the filesystem is ephemeral, this directory may be empty after deploy or on another instance. To keep context across restarts, you’d need persistent storage (e.g. mounted volume or a different store like a database) and the same `session_id` from the client.

## Quick checklist when context seems lost

1. Call `GET /api/chat/session?session_id=<id>` and confirm `has_history` and `message_count`.
2. In backend logs, confirm `chat context: ... has_history=... message_count=...` for the request that failed.
3. If needed, run with `DEBUG_CLAUDE_PROMPT=1` and inspect whether "Conversation history" is in the prompt.
4. Ensure the same `session_id` is sent from the client for the whole thread and that the server can persist `data/binance/chat_sessions/`.
