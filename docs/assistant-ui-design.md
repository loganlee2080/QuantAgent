# Chat UI Upgrade: assistant-ui Design

Design summary for replacing the current custom MUI chat with [assistant-ui](https://www.assistant-ui.com), connected to our existing Flask backend.

---

## 1. Goal

- **UI:** Use assistant-ui for all chat presentation: floating entry (AssistantModal) bottom-right, Thread (messages + composer) inside the modal.
- **Backend:** Keep existing Flask API (`/api/chat`, `/api/chat/stream`), LangChain session memory, and Binance execution as the single source of truth. No backend rewrite.
- **Connection:** A custom runtime (or thin adapter) in the frontend that calls our APIs and feeds assistant-ui’s thread state.

---

## 2. UI Pattern: AssistantModal

- **Entry:** One floating trigger (e.g. bot icon) fixed bottom-right (`AssistantModalPrimitive.Anchor` + `Trigger`).
- **Open state:** Click opens a Radix Popover; content is the full **Thread** (viewport, message list, composer, scroll-to-bottom).
- **Reference:** [AssistantModal docs](https://www.assistant-ui.com/docs/ui/assistant-modal).

So: one bubble bottom-right → open → same Thread we drive with our backend.

---

## 3. Transport: Option A – Custom Runtime Only (Chosen)

We use **Option A** (custom runtime only), not Option B (AI SDK transport in frontend).

| Aspect | Option A – Custom runtime | Option B – AI SDK transport (frontend only) |
|--------|----------------------------|---------------------------------------------|
| Dependencies | Fewer (no AI SDK) | More (AI SDK in frontend) |
| Control | Full (our types, our mapping) | Constrained by SDK stream/message format |
| Complexity | One integration point | Two (assistant-ui + AI SDK) |

**Custom runtime responsibilities:**

- Implement assistant-ui’s **runtime interface** (append user message, set/stream assistant message, error, cancel).
- On send: `POST /api/chat` or `POST /api/chat/stream` with `{ message, mode, session_id }`.
- On response (or SSE): map backend payload into assistant-ui’s message/part format and update the thread.
- Handle streaming (if using SSE), cancel (AbortController), and errors.

Backend stays unchanged; the runtime is the only bridge.

---

## 4. Option A Implementation Checklist

Things that are easy to miss:

| Item | Notes |
|------|--------|
| **Runtime contract** | Implement the full interface assistant-ui expects (see docs/typings). |
| **session_id** | Store (e.g. in runtime or ref); send on every request; optionally persist (e.g. localStorage) for same conversation after refresh. |
| **Mode** | Backend expects `mode` (chat / suggest / execute). UI needs a mode selector; runtime includes it in the request body. |
| **Response → message mapping** | Map `{ reply, executed, orders_csv?, ... }` (or SSE) into assistant-ui message/part shape. |
| **Streaming** | If using `/api/chat/stream`: consume SSE, feed deltas (or final text) into runtime; match runtime’s streaming API. |
| **Cancel** | “Stop” must abort in-flight fetch (AbortController) and set assistant message to cancelled/stopped. |
| **Errors** | Map network and server errors to assistant-ui error state for the message (no stuck “running”). |
| **History hydration** | Optional: on load, GET `/api/chat/history?session_id=...` and hydrate thread so history survives refresh. |
| **Who adds user message** | Clarify: usually the UI adds the user message on submit; runtime only adds the assistant reply (and errors). |
| **Provider wiring** | Wrap app (or modal) in the provider that receives this custom runtime; Thread must be under that provider. |
| **Attachments** | If composer has attachments, either disable for v1 or add backend support and map in runtime. |
| **Types** | Use assistant-ui’s TypeScript types for the runtime so all required methods are implemented correctly. |

---

## 5. Order Display: Markdown Only

- **Decision:** Show suggested orders as **markdown** in the assistant message (e.g. markdown table), not a custom order-block component.
- Backend keeps returning `reply` that includes that markdown; the Thread renders it with **MarkdownText** (or equivalent).
- No custom “order block” type; orders are just part of the assistant’s text. Simple and native.

---

## 6. Execute Logic: Human-in-the-Loop Tool Approval

- **Decision:** Model “execute these orders” as a **tool call** that requires user approval before the backend runs trades, following assistant-ui’s [Part 3: Approval UI](https://www.assistant-ui.com/docs/runtimes/langgraph/tutorial/part-3) pattern.

**Flow:**

1. Backend (or agent) decides to execute and **emits a tool call** (e.g. `execute_orders`) with order payload (or reference).
2. Backend **interrupts** before calling Binance and waits for a **tool result** (approve/reject).
3. Frontend shows a **tool UI** via `makeAssistantToolUI`: order summary + **Execute** / **Cancel**.
4. User clicks Execute → frontend sends **tool result** (e.g. `{ approve: true }`; optionally final order list if editable).
5. Backend receives tool result, runs execution (e.g. `binance_trade_api`), returns the outcome as the tool result (success/error, fills).
6. Same tool UI can show the final state (e.g. “Transaction confirmed” or error), similar to `TransactionConfirmationFinal` in the tutorial.

**Backend implications:**

- Conversation must support **tool calls** and **tool results** as first-class messages (e.g. assistant message with `tool_calls`, follow-up with `tool_result`).
- When the model/logic wants to execute, it **does not** call Binance immediately; it emits the tool call and **stops**.
- A **follow-up** (next request or same session step) carries the tool result; only then does the backend run execution and return the real tool result.

This can be implemented with a LangGraph-style interrupt (e.g. node that calls `execute_orders` → interrupt → resume on tool result) or an equivalent request/response contract that carries tool_calls and tool_result.

---

## 7. Implementation: 3 Phases (Code & Test Under Control)

Incremental rollout so each phase is shippable and testable before moving on.

### Phase 1 – Foundation (UI + basic chat, no execute)

**Scope**

- Add assistant-ui: Provider, AssistantModal (floating bubble bottom-right), Thread (messages + composer).
- Custom runtime: implement assistant-ui runtime interface; on send call `POST /api/chat` with `{ message, mode, session_id }`; map backend `{ reply }` into one assistant message; no streaming yet.
- session_id: generate once per runtime (e.g. UUID), store in runtime/ref, send every request.
- Mode: include in request (chat / suggest); hide or stub “execute” for this phase.
- Order display: markdown only — backend returns markdown in `reply`; Thread renders with MarkdownText. No custom order block, no execute button.
- Keep existing ChatPanel (or hide it behind a flag) so we can compare/fallback.

**Out of scope in Phase 1**

- Streaming, cancel, history hydration, execute flow, tool calls.

**Deliverables**

- Floating bubble opens modal with Thread.
- User can send a message and see one assistant reply.
- Same session_id used for follow-up messages (conversation continuity).
- Orders (if any) appear as markdown in the reply.

**Test criteria**

- [ ] Open modal → type → send → reply appears in thread.
- [ ] Second message in same session gets contextual reply (memory).
- [ ] Reply with markdown table renders correctly.
- [ ] No regression: existing app (tables, data) still works; chat either replaced or behind feature flag.

**Exit condition:** Phase 1 merged and stable before starting Phase 2.

---

### Phase 2 – Robustness & history

**Scope**

- Streaming: switch to `POST /api/chat/stream` (or keep non-streaming); if streaming, consume SSE and feed deltas into runtime; match runtime’s streaming API.
- Cancel: “Stop” aborts in-flight request (AbortController) and marks assistant message as stopped.
- Errors: map network/server errors to assistant-ui message error state (no stuck “running”).
- session_id persistence: store in localStorage (or equivalent) so the same conversation survives refresh.
- History hydration: add `GET /api/chat/history?session_id=...` (if not exists); on modal open or app load, fetch history and hydrate thread so past messages appear.

**Out of scope in Phase 2**

- Execute flow, tool calls, human-in-the-loop.

**Deliverables**

- Streaming (optional but recommended), cancel, and error handling working.
- Refresh keeps same session and optionally shows history in thread.

**Test criteria**

- [ ] Long reply streams token-by-token (if streaming); or single reply still works.
- [ ] Stop button cancels request and shows assistant message as stopped.
- [ ] Server/network error shows in thread, not infinite loading.
- [ ] After refresh, same session_id; history (if implemented) visible in thread.

**Exit condition:** Phase 2 merged and stable before starting Phase 3.

---

### Phase 3 – Execute (human-in-the-loop)

**Scope**

- Backend: support tool_calls and tool_result in conversation; when “execute” is chosen, emit `execute_orders` tool call and interrupt before calling Binance; resume on tool result (approve/reject), then run execution and return result.
- Frontend: register `execute_orders` with `makeAssistantToolUI`; approval UI (summary + Execute / Cancel); on confirm, send tool result; show final state (success/error) in same tool UI.
- Mode “execute” can be exposed or inferred from tool flow.

**Out of scope in Phase 3**

- Additional tools (only `execute_orders` for now).

**Deliverables**

- User can approve or cancel order execution from inside the thread.
- Backend executes only after approval; result shown in tool UI.

**Test criteria**

- [ ] Suggest flow returns markdown orders; when user asks to execute, tool call appears with approval UI.
- [ ] Cancel leaves thread in consistent state; no orders sent.
- [ ] Execute sends tool result; backend runs execution; success/error shown in tool UI.
- [ ] Positions/data refresh after execution (existing hooks).

**Exit condition:** Phase 3 merged; full flow (suggest → approve → execute) and tests passing.

---

### Phase summary

| Phase | Focus | Backend change | Test gate |
|-------|--------|----------------|-----------|
| **1** | AssistantModal + Thread + custom runtime, markdown orders | None | Chat works, reply + markdown, session continuity |
| **2** | Streaming, cancel, errors, session persistence, history | Optional: GET history | Stream/cancel/errors, refresh + history |
| **3** | Execute via tool approval (human-in-the-loop) | tool_calls, tool_result, interrupt | Approve/cancel/execute, result in thread |

Do not start the next phase until the current phase’s test criteria are met and code is in a good state.

---

## 8. Architecture Summary

| Layer | Role |
|-------|------|
| **Backend** | Unchanged in Phase 1–2. In Phase 3: add tool_calls/tool_result and interrupt-before-execute for human-in-the-loop. |
| **Connection** | Custom runtime (Option A): fetch to our APIs, map responses/SSE into assistant-ui thread state; one thread ↔ one `session_id`. |
| **assistant-ui** | Provider at root; AssistantModal (floating bubble) containing Thread; in Phase 3, custom tool UI for `execute_orders`. |
| **Order display** | Markdown only in assistant message. |
| **Execute UX** | Phase 3: human-in-the-loop `execute_orders` tool, approval UI in thread, backend waits for tool result then runs execution. |

---

## 9. References

- [AssistantModal](https://www.assistant-ui.com/docs/ui/assistant-modal) – Floating chat bubble, bottom-right.
- [Part 3: Approval UI](https://www.assistant-ui.com/docs/runtimes/langgraph/tutorial/part-3) – Human-in-the-loop tool approval with `makeAssistantToolUI`.
- assistant-ui runtimes (custom backend): use **Custom runtime** path; no AI SDK required for Option A.

## 10. Troubleshooting

### Content Security Policy (CSP) and `script-src` blocked

**Is it common?** Yes. Many React/Vite apps and libraries (including some used by assistant-ui, e.g. Zustand or dev tooling) can trigger CSP when they or the bundler use `eval()`, `new Function()`, or string forms of `setTimeout`/`setInterval`. Browsers then report `script-src` as blocking that code.

**What’s going on:** CSP blocks evaluation of arbitrary strings as JavaScript. So anything that relies on `eval()`, `new Function()`, or `setTimeout(codeString)` can be blocked if your policy doesn’t allow it.

**How to fix it:**

1. **Allow eval in development (recommended for this app):** Add `'unsafe-eval'` to the `script-src` directive. This project already does that in `frontend/index.html`:
   ```html
   <meta http-equiv="Content-Security-Policy"
     content="default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; ..." />
   ```
   If you still see “script-src blocked”, something else is setting CSP (e.g. a reverse proxy or server header). Add or relax `script-src` there so it includes `'unsafe-eval'` for the same origin.

2. **Avoid relaxing CSP:** Prefer not using `eval()`/`new Function()`/string timers in your own code. You usually cannot remove them from third‑party or bundler code, so in practice dev builds often need `'unsafe-eval'`.

**Security note:** Allowing `'unsafe-eval'` weakens protection against script injection. Use it only for trusted dev/build environments or where the trade-off is acceptable; in production you can try a stricter CSP and only relax it if a dependency requires it.