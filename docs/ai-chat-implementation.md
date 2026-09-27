# AI Chat Assistant — Implementation Strategy

Blueprint for the marketplace AI assistant ("Sally" on RentDirect). This document
is written to be portable — copy the pattern to a new project by swapping the
domain content (system prompt, tools, knowledge copy) and keeping the plumbing.

## Architecture Overview

```
Browser chat widget  ──POST /api/v1/chat/stream──▶  Django endpoint
        (SSE)                                          │
        ◀── data: {"type":"delta"...} ─────────────────┤
                                                       ▼
                                   ┌─────────────────────────────┐
                                   │ ai_chat.py                  │
                                   │  1. resolve session/history │
                                   │  2. LLM tool-calling loop   │
                                   │     (max N rounds)          │
                                   │  3. run DB-backed tools     │
                                   │  4. stream reply via SSE    │
                                   │  5. persist session         │
                                   └─────────────────────────────┘
                                                     │
                                              model error ──▶ next model in
                                              (any failure)    fallback chain
```

**Model fallback chain** — `AI_CHAT_MODEL` (primary) then `AI_CHAT_FALLBACK_MODELS`
in order. Any request-level error (HTTP error, timeout, throttle/429, malformed
response) moves to the next model. While streaming, a model is retried only if it
failed *before* emitting any content — once text is delivered we never retry, so
the client never sees duplicated output. If the whole chain fails (or no provider
is configured), the user gets a generic "try again" reply with `mode: "error"` —
there is no canned-text fallback.

## Files

| File | Role |
|---|---|
| `apps/api/core/ai_chat.py` | All assistant logic: prompt, tools, LLM calls, SSE streaming, sessions, fallback |
| `apps/api/core/ai_knowledge.py` | Static narrative site copy for the `get_marketplace_info` tool |
| `apps/api/config/settings/base.py` | `AI_CHAT_*` / `OPENROUTER_API_KEY` env contract |
| `apps/api/core/urls.py` | `AiChatViewSet` → `POST /api/v1/chat`, `POST /api/v1/chat/stream` |
| `apps/web/src/components/AiSearchChat.tsx` | React chat widget (SSE consumer) |
| `infra/terraform/locals.tf` | `AI_CHAT_*` env for ECS |
| `infra/terraform/envs/secrets/.env.<env>` | `OPENROUTER_API_KEY` / `AI_CHAT_API_KEY` in `TF_VAR_api_secure_environment` |

## Provider Contract

Any OpenAI-compatible `/chat/completions` endpoint works — OpenRouter, Ollama,
Gemini's OpenAI-compat endpoint, etc.

* `POST {AI_CHAT_BASE_URL}/chat/completions` with `model`, `messages`, `tools`,
  `tool_choice: "auto"`, `temperature`, optional `reasoning`.
* `Authorization: Bearer <AI_CHAT_API_KEY>` when a key is set.
* OpenRouter also gets `HTTP-Referer` (WEB_PUBLIC_URL) and `X-Title` headers.
* Streaming uses SSE (`stream: true`); deltas are decoded as UTF-8 manually —
  providers often omit the charset and requests would mangle ₦/em-dashes.

## Settings / Environment

| Var | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | – | Shortcut: setting this alone enables OpenRouter defaults |
| `AI_CHAT_BASE_URL` | `https://openrouter.ai/api/v1` | Provider endpoint |
| `AI_CHAT_API_KEY` | `OPENROUTER_API_KEY` | Bearer token |
| `AI_CHAT_MODEL` | `nvidia/nemotron-3-ultra-550b-a55b:free` | Primary model |
| `AI_CHAT_FALLBACK_MODELS` | comma list | Ordered backups (see below) |
| `AI_CHAT_REASONING` | `true` | Request `reasoning.enabled` |
| `AI_CHAT_TIMEOUT_SECONDS` | `45` | Per-request timeout |
| `AI_CHAT_MAX_TOOL_ROUNDS` | `4` | Max tool-call rounds per message |
| `AI_CHAT_SEARCH_LIMIT` | `12` | Max results a search tool returns |
| `AI_CHAT_MAX_MESSAGES` | `20` | Session history window |
| `AI_CHAT_MAX_MESSAGE_CHARS` | `2000` | Per-message cap |
| `AI_CHAT_SESSION_TTL_SECONDS` | `7200` | Cache-backed session lifetime |

### Model chain (free OpenRouter models, ≥1M context, tool support)

| Priority | Model |
|---|---|
| 1 (default) | `nvidia/nemotron-3-ultra-550b-a55b:free` |
| 2 | `nvidia/nemotron-3.5-lightning:free` |
| 3 | `thinkingmachines/inkling:free` |
| 4 | `thinkingmachines/inkling-small:free` |
| 5 | `stealth/space-bunny-alpha` |

Refresh the list from:
`https://openrouter.ai/models?max_output_price=0&input_modalities=text&max_price=0&context=1000000`

## Tool-Calling Loop

`TOOL_LIST` describes function tools in OpenAI schema; `_execute_tool()` dispatches
them against live DB/service functions — never hardcoded data.

Loop (`run_ai_chat` / `iter_ai_chat_events`):

1. System prompt + user history → `_chat_completion()` / `_iter_chat_completion()`.
2. If the model returns `tool_calls`: execute each, append `role: "tool"` results,
   stream a `listings` event with fresh cards, loop again.
3. If the model returns plain text and `_factual_intent()` recognized a factual
   question that skipped tools, `_inject_grounding_tool()` runs the correct tool
   server-side and lets the model rephrase real data (anti-hallucination).
4. Final text is markdown-stripped (`_plain_text`) and streamed/sent with `done`.

## Sessions & Contracts

* **New contract**: client sends `{message, session_id?}`; history lives server-side
  in Django cache under `ai_chat_session:<id>`. The server issues `session_id` in a
  `session` SSE event and the `done` payload.
* **Legacy contract**: `{messages: [...]}` — assistant turns are dropped
  (forged assistant messages are a prompt-injection vector), no persistence.
* `session["filters"]` carries search filters forward so refinements
  ("only furnished", "cheaper ones") keep prior constraints;
  `_merge_search_filters` resets them on fresh/global-scope questions and
  reconciles stale `min_price`/`max_price` bounds.

## SSE Event Protocol

| Event | Payload | Meaning |
|---|---|---|
| `session` | `session_id` | Emitted first; client stores it |
| `segment` | – | New tool round started — client clears the draft bubble |
| `delta` | `text` | Streamed reply chunk |
| `listings` | `listings, total_count, filters` | Search tool ran — refresh result grid |
| `done` | `reply, listings, filters, total_count, mode, session_id` | Final message; `mode` is `ai` or `error` |

## Endpoint Hardening

* `production_ratelimit` — 30 POST/min per IP on both endpoints.
* Public (`AllowAnyUnlessFrozen`) but read-only: tools only query the public
  listings queryset.
* The system prompt forbids revealing exact addresses/PII; tool payloads exclude
  internal objects (`listing_objects` is stripped before being sent to the model).
* Replies are plain text; `_plain_text` strips markdown the UI can't render.

## Porting to a New Project

1. Copy `ai_chat.py`; rename the assistant and rewrite `SYSTEM_PROMPT` rules.
2. Replace `TOOL_LIST` + `*_tool()` implementations with the project's public
   queryset/serializer, keeping result keys (`<items>`, `<item>_objects`,
   `filters`, `total_count`).
3. Replace the `_fallback_filters` keyword tables (used for grounding) and the
   narrative copy in `ai_knowledge.py`.
4. Copy the `AI_CHAT_*` settings block, env wiring (`locals.tf`,
   `secrets/.env.*`, `.env*` files), and the React chat component; adjust the
   SSE item event name (`listings`/`tutors`) if you rename it.
5. Keep the plumbing untouched: `_chat_models` fallback chain, stream/done SSE
   contract, session persistence, grounding injection, rate limiting, and the
   `_unavailable_result` error path.
