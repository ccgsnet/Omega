# Reference — Memory Skills

Defined in `src/memory.metta` and `src/das_memory.metta`, catalogued in `src/skills.metta`.

All memory skills accept quoted string arguments. Variables are only permitted in DAS recall patterns (`das-recall`, `beliefs`).

---

## `remember`

### Signature
```metta
(remember "string")
```

### Purpose
Store a string in long-term embedding memory as the triplet `(timestamp, atom, embedding)`.

### Parameters
- `string` — the text to remember. Use short, self-contained phrases for best recall.

### Returns
The result of the ChromaDB write (internally). The agent treats a successful call as an effectful step.

### Examples
```metta
(remember "user prefers dark mode")
(remember "to deploy: run make release then docker push")
```

### Notes / Limits
- Text is passed through `string-safe` before embedding, which escapes newlines, quotes, and apostrophes.
- Embedding provider is selected by `embeddingprovider`, the model by `embeddingModel`.
- Nothing deduplicates automatically — repeated `remember` calls store multiple items.
- The same text is also added to `&das` as `(Memory "timestamp" "text")`. A DAS failure is logged as a warning and does not fail the call.

---

## `query`

### Signature
```metta
(query "string")
```

### Purpose
Return up to `maxRecallItems` memory entries whose embeddings are closest to the embedding of `string`.

### Parameters
- `string` — a short descriptive phrase. Over-long queries dilute similarity scores.

### Returns
A list-shaped result containing the nearest memory items.

### Examples
```metta
(query "deployment steps")
(query "user preferences")
```

### Notes / Limits
- `maxRecallItems` default is 20 (see `initMemory`).
- Similarity is purely embedding-based; exact string match is not guaranteed.

---

## `episodes`

### Signature
```metta
(episodes "YYYY-MM-DD HH:MM:SS")
```

### Purpose
Return `maxEpisodeRecallLines` lines of the episodic trace centered on the given timestamp.

### Parameters
- `timestamp` — must match the format produced by `get_time_as_string`.

### Returns
A block of lines from `memory/history.metta`.

### Examples
```metta
(episodes "2026-04-15 14:30:00")
```

### Notes / Limits
- Implemented by `helper.around_time`.
- Useful for answering questions like "what was I doing around X?"

---

## `pin`

### Signature
```metta
(pin "string")
```

### Purpose
Append a working-memory note to the episodic trace so the next turn can see it in `HISTORY`.

### Parameters
- `string` — the note. Typical uses: intermediate results, plans for the next turn, checklists.

### Returns
Success / failure of the append.

### Examples
```metta
(pin "candidates: A) Launch Day B) We're Live C) Out Now")
(pin "next step: pick best candidate and send")
```

### Notes / Limits
- `pin` is not semantically indexed — it only influences the next few turns through the rolling `HISTORY` window (`maxHistory` characters).
- For anything you want to recall days later, use `remember` instead.

---

## DAS formal memory

`&das` is bound to a DAS Command Router in `run.metta` with `(bind! &das (new-das! (host:port)))`. Without that line `&das` is a local in-process space, so the skills below still work but nothing persists across restarts. DAS has no full-space dump: every pattern must name a relation, never a bare `$x`.

| Skill | Example | Effect |
|---|---|---|
| `das-store` | `(das-store "(Similarity \"human\" \"mammal\")")` | Add one atom. |
| `das-recall` | `(das-recall "(Similarity \"human\" $1)")` | Return every atom matching the pattern. |
| `das-forget` | `(das-forget "(Similarity \"human\" \"mammal\")")` | Remove one atom. |
| `believe` | `(believe "((--> sam animal) (stv 1.0 0.9))")` | Store a NAL/PLN belief. |
| `beliefs` | `(beliefs "(--> sam $1)")` | Return `(term (stv f c))` pairs, ready as `\|-` / `\|~` premises. |

Beliefs are stored as `(Belief term (stv f c))`, one truth value per term. Storing the same truth again is a no-op; a different truth is merged with NAL revision (`Truth_Revision`) and replaces the old one. Terms containing variables, such as `$1` in an implication, are not stored.

Every `metta` call whose expression is `(|- p1 p2)` or `(|~ p1 p2)` stores both premises and every conclusion as beliefs. A DAS failure is logged as a warning and the inference result is still returned.

### Conversational facts

Users never write atoms. For each new user message the loop asks the model, in a separate call, for the facts the user states about one named person or thing (`FACT subject | relation | value` lines; general rules and questions give `NONE`; the reply is logged as `FACTS_EXTRACTED`) and stores each with `learn` before the agent sees the message (`autoLearnFacts` in `src/loop.metta`). The agent itself uses `learn` and `unlearn` only to correct facts.

| Skill | Example | Effect |
|---|---|---|
| `learn` | `(learn "I \| favorite color \| purple")` | Store `(Evaluation (Predicate (favorite_color "purple")) (Concept "arturgontijo"))`. `I`, `me`, `my` and `user` become the sender's nick. A new value for the same subject and relation replaces the old one. A subject of more than 4 words, a relation of more than 3 or a value of more than 6 is rejected, so a sentence is never stored as a fact. |
| `unlearn` | `(unlearn "I \| favorite color")` | Remove every value of that subject and relation. |

Facts are `(Evaluation (Predicate (relation "value")) (Concept "subject"))`, the form DAS `Sql2AtomsMapper` gives a column value, such as `(Predicate (public.feature public.feature.name "2L_r3"))`. `Predicate` and `Concept` wrap one element, as in hyperon-experimental and the DAS examples, so the generic pattern `(Evaluation (Predicate $p) (Concept $c))` matches facts too. DAS matches a relation directly with `(Predicate (favorite_color $v))` and a value with `(Predicate ($r "purple"))`. `learn` reports `(LEARNED "subject" relation "value")`, because `Predicate` is also a PeTTa builtin and an evaluated `(Predicate ...)` fails. The relation is a lowercase symbol with multi-word names joined by `_`; subject and value are lowercase strings, and a multi-word value keeps its spaces. For a new message the loop looks up the sender's nick and the first `maxFactConcepts` (3) content words as concepts, and adds the matches to the prompt as sentences addressed to the sender, for example `KNOWN_FACTS: your favorite color is blue; france's capital is paris.` Recall is by exact subject name only: a fact about `france` is found by "capital of France", but `purple` is not found by "who likes purple". Each name is one DAS query; a DAS failure is logged and gives no facts.
