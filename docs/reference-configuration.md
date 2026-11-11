# Reference — Configuration

Every tunable in Omega is declared as `(= (name) (empty))` and later bound by a `configure` call inside an `init*` function. The `configure` helper in `src/utils.metta` is:

```metta
(= (configure $name $default)
   (let $value (argk $name $default)
        (add-atom &self (= ($name) $value))))
```

This reads a command-line override via `argk` (`name=value` on the MeTTa command line) if present, otherwise falls back to the default.

## Loop (`src/loop.metta`, `initLoop`)

| Parameter | Default | Meaning |
|---|---|---|
| `maxNewInputLoops` | 50 | How many turns the agent keeps running after a new human message before idling. |
| `maxWakeLoops` | 1 | Extra turns granted on each scheduled wake-up. |
| `sleepInterval` | 1 (seconds) | Delay between loop iterations. |
| `LLM` | `gpt-5.4` | Model identifier passed to the provider. |
| `provider` | `Anthropic` | LLM provider — `Anthropic`, `OpenAI`, `ASICloud`, or `ASIOne`. |
| `maxOutputToken` | 6000 | Output cap passed to the provider. |
| `reasoningMode` | `medium` | Reasoning-effort hint passed to the provider (`reasoning_effort` on OpenAI-compatible endpoints). |
| `wakeupInterval` | 600 (seconds) | How long idle before the next scheduled wake-up. |
| `idleThinking` | `True` | Call the model on turns with no new or unanswered user message. `False` calls it only for a new message and the reply turns after it, which also disables scheduled wake-up work; `config/config.yaml` sets `False`. |
| `groundedAnswers` | `False` | Answer only from the facts recalled from DAS (`KNOWN_FACTS`) and reasoning over them. `websearch`, `shell` and `query` are left out of the skill list and refused when called, and a question about a name with nothing stored reads `KNOWN_FACTS: none, nothing is stored about <name>`. `config/config.yaml` sets `True`. |
| `relationVocabulary` | `True` | Map each learned relation to the shared vocabulary in `src/relations.py`, by alias and then by similarity with the local embedding model (`intfloat/e5-large-v2`), so agents writing to the same DAS store one predicate per meaning: "Koppen climate classification", "climate" and "climate type" all become `climate_classification`. A relation close to no entry keeps its own name; without the model only aliases apply. |
| `relationVocabularyThreshold` | `0.85` | Cosine similarity a relation needs to take a vocabulary name. |

## Memory (`src/memory.metta`, `initMemory`)

| Parameter | Default | Meaning |
|---|---|---|
| `maxFeedback` | 50000 (chars) | Ceiling on `LAST_SKILL_USE_RESULTS` text fed back into the prompt. |
| `maxRecallItems` | 20 | Items returned by `query`. |
| `maxEpisodeRecallLines` | 20 | Lines returned by `episodes`. |
| `maxHistory` | 30000 (chars) | Tail of `memory/history.metta` included in the prompt. |
| `memoryDirectory` | `./repos/Omega/memory` | Directory containing persistent memory files such as `history.metta`. |
| `chromaDbPath` | `./chroma_db` | ChromaDB persistence directory used for memory backup and restore. |
| `embeddingprovider` | `Local` | `Local` (Python-side model), or the id of a provider that serves an OpenAI-compatible `/embeddings` endpoint — `OpenAI` and `ASICloud` are known to. The gateway supplies that provider's key. |
| `embeddingModel` | empty | Model asked of a non-`Local` `embeddingprovider`. Empty means the provider default: `text-embedding-3-large` for `OpenAI`, `WhereIsAI/UAE-Large-V1` for `ASICloud`. |

## DAS (`run.metta`, `src/das_memory.metta`, `src/loop.metta`)

| Key | Default | Description |
|---|---|---|
| `dasRouter` | empty | `host:port` of the DAS Command Router that backs the `&das` space holding facts and beliefs, for example `host.docker.internal:40009`. `scripts/omega start --das <host:port>` sets it. Empty keeps `&das` an in-process space that does not persist across restarts. Read before the loop starts, so it must come from the command line, `OMEGA_dasRouter` or the config file. |
| `dasExternalFacts` | `True` | Also recall the facts other agents wrote as bare `Evaluation` atoms. Omega's own facts are read from `(Fact (Concept name) ...)` records, one indexed DAS query per name; the DAS pattern index cannot narrow a bare `Evaluation` by a name nested inside it, so each external read scans every `Evaluation` in every AtomDB, several per name. `config/config.yaml` sets `False`. |
| `autoLearnFacts` | `True` | Make one extra model call per user message to extract the facts it states (`FACT subject \| relation \| value`), the facts it denies (`NOT subject \| relation \| value`), the names it asks about (`LOOKUP name`) and the conditions it joins (`ALL`/`ANY value \| value`). |
| `factExtractionTokens` | 4000 | Output cap passed to the provider for that extraction call. Reasoning models spend most of it thinking; at 1000 `ornith-1.5:9b` ran out before answering. When the model runs out, the call is retried once with twice the cap; if that fails too the message is logged as `FACTS_NOT_EXTRACTED` and nothing is learned. |
| `factExtractionReasoning` | `reasoningMode` | Reasoning-effort hint for the extraction call only. The OpenAI-compatible provider sends it as `reasoning_effort`; Ollama accepts `none`, `low`, `medium`, `high` (`none` disables thinking, which is fast but sloppier). Providers that reject the parameter are detected once and the hint is dropped for the rest of the run. |

## Channels (`src/channels.metta`, `initChannels`)

| Parameter | Default | Meaning |
|---|---|---|
| `commchannel` | `irc` | Active channel — `irc`, `telegram`, `slack`, `mattermost`, or `websocket`. |
| `IRC_channel` | `##omega` | IRC channel to join. |
| `IRC_server` | `irc.quakenet.org` | IRC server hostname. |
| `IRC_port` | 6667 | IRC port. |
| `IRC_user` | `omega` | IRC nickname. |
| `TG_CHAT_ID` | *(empty)* | Legacy single-chat bootstrap/fallback, primarily for authentication-disabled deployments. With authentication enabled, the authenticated owner's DM becomes the proactive-message default. |
| `TG_ALLOWED_CHAT_IDS` | *(empty)* | Optional comma-separated initial allowed-chat set. The authenticated owner can add groups with `/bind` and remove them with `/unbind`; those changes are persisted in `memory/.channel/authenticated-group.json`, not written back to YAML. |
| `TG_POLL_TIMEOUT` | 20 | Telegram long-poll timeout in seconds. |
| `SL_CHANNEL_ID` | *(empty — auto-bind supported)* | Optional Slack channel ID where Omega reads/writes messages. Leave empty to auto-bind on first valid inbound auth/message. |
| `SL_POLL_INTERVAL` | 60 | Slack poll interval in seconds (minimum effective value is 60). |
| `MM_URL` | `https://chat.singularitynet.io` | Mattermost base URL. |
| `MM_CHANNEL_ID` | `8fjrmabjx7gupy7e5kjznpt5qh` | Target channel ID. |
| `WS_URL` | *(empty — set at runtime)* | WebSocket endpoint URL (`ws://` or `wss://`). Required when `commchannel=websocket`. |
| `WS_TOKEN` | *(empty — optional)* | Bearer token sent as `Authorization: Bearer <token>`. Leave empty for an unauthenticated endpoint. |

| Environment variable | Meaning |
|---|---|
| `TG_BOT_TOKEN` | Telegram bot token (from BotFather). |
| `OMEGA_AUTH_SECRET` | Enables the one-time owner-authentication handshake when non-empty. The owner sends `auth <secret>` in a private Telegram DM. |
| `MM_BOT_TOKEN` | Bot auth token. |
| `SL_BOT_TOKEN` | Slack bot token (`xoxb-...`). |

## Command-line overrides

Any `configure`d parameter can be overridden at startup:

```bash
metta run.metta provider=Anthropic LLM=claude-opus-4-6 commchannel=mattermost
```

Configuration values are resolved in this order: command-line `key=value`,
`OMEGA_<KEY>` environment variable, `config/config.yaml`, then the caller's
default. `TG_BOT_TOKEN` and `OMEGA_AUTH_SECRET` are read directly from the
environment and must be placed before the `metta`/`petta` command.

Telegram example:

```bash
TG_BOT_TOKEN=... OMEGA_AUTH_SECRET=... \
  metta run.metta commchannel=telegram
```

Slack example:

```bash
SL_BOT_TOKEN=xoxb-... metta run.metta commchannel=slack SL_CHANNEL_ID=C0123456789
```

WebSocket example:

```bash
metta run.metta commchannel=websocket WS_URL=wss://chat.example.com/agent WS_TOKEN=...
```

The `argk` helper parses `key=value` pairs from `argv`.
