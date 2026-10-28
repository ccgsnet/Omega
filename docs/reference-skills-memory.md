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
- The same collection also holds one `FACT subject | relation | value` document per fact learned from conversation (see below), so `query` may return those lines too.

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

`&das` is bound to a DAS Command Router in `run.metta` when `dasRouter` is set (`scripts/omega start --das host.docker.internal:40009`, `OMEGA_dasRouter`, or `config.yaml`). Without it `&das` is a local in-process space, so the skills below still work but nothing persists across restarts. At start `das-health` runs one query and logs `DAS_UNREACHABLE` if the router does not answer. DAS has no full-space dump: every pattern must name a relation, never a bare `$x`.

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

Users never write atoms. For each new user message the loop makes one separate model call (`extract-from-message` in `src/loop.metta`, enabled by `autoLearnFacts`) that returns `FACT subject | relation | value` lines for the facts the user states about one subject, a named person or thing or a kind of thing (`human | similar to | monkey`, `banana | is a | fruit`), `NOT subject | relation | value` lines for the facts the user denies or says are no longer so ("Team B is not playing the 2026 championship" gives `NOT Team B | is playing | 2026 championship`, the fact in its positive form). A FACT line whose subject and value appear in a negated clause of the message (`is not`, `n't`, `no longer`) is stored as a denial even when the model wrote FACT, and `LOOKUP name` lines for the named things the user asks about; requests, commands and rules with a condition ("cities with more than 500k people are big") give `NONE`. The reply is logged as `FACTS_EXTRACTED`. Messages that can state or ask nothing skip the call: `auth`, direct skill calls, and messages under three words that are not questions. A reasoning model can spend the whole `factExtractionTokens` budget thinking and answer nothing; the call is then made once more with twice the budget, and if that fails too the message is logged as `FACTS_NOT_EXTRACTED` and nothing is learned from it. `factExtractionReasoning` sets the effort of this call apart from the agent's `reasoningMode`. Facts are stored with `learn`, denials with `deny`, before the agent sees the message. `learn` is not offered to the model as a skill: when it was, small models stored the same facts a second time, retyped with misspelled names and the user as subject. The agent only has `unlearn`, to remove a fact that is no longer true.

| Function | Example | Effect |
|---|---|---|
| `learn` (loop and plugins) | `(learn "I \| favorite color \| purple")` | Store the fact below. `I`, `me`, `my` and `user` become the sender's nick. A relation may hold several values (`human similar_to monkey` and `human similar_to chimp`), so a new value is added beside the old ones and nothing is forgotten without `unlearn`; recall lists the newest first. A relation of several words loses a leading `is`/`are`, so `is similar to` and `similar to` are one relation. A subject of more than 4 words, a relation of more than 3 or a value of more than 6 is rejected, so a sentence is never stored as a fact. Reports `(LEARNED "subject" relation "value")`, or `(KNOWN ...)` when the fact was already stored. |
| `deny` (loop) | `(deny "Team B \| is playing \| 2026 championship")` | Store the same term believed false, `(stv 0.0 0.9)`, with its `Stated` link. A value already stored as true is replaced by the denial, and a later `learn` of the value replaces the denial again, so "I no longer live in Lisbon, I moved to Porto" leaves `lives_in lisbon` at 0.0 and `lives_in porto` at 1.0. Reports `(DENIED ...)` or `(KNOWN ...)`. |
| `unlearn` (skill) | `(unlearn "I \| favorite color")` | Remove every value of that subject and relation, with their provenance. |

A fact is a belief over the binary PLN form that the `lib_pln` rules match:

```metta
(Belief (Evaluation (Predicate "favorite_color") (List (Concept "arturgontijo") (Concept "purple"))) (stv 1.0 0.9))
(Stated (Evaluation (Predicate "favorite_color") (List (Concept "arturgontijo") (Concept "purple"))) "arturgontijo" "2026-10-23 08:36:14")
```

Relation, subject and value are lowercase strings; a multi-word relation is joined by `_` (`similar_to`), a multi-word value keeps its spaces. The predicate name is a string because DAS tells `(Predicate similar_to)` from `(Predicate "similar_to")` and other agents on the same router (see `docs/development/das-integration-review.md`, "Conventions shared with other DAS agents") write the string form; the nested `Evaluation` is a link of its own in DAS, so those agents find Omega's facts with a bare `(Evaluation (Predicate "similar_to") (List (Concept "human") $1))` pattern. `Stated` records who said it and when. Because subject and value are both `Concept`s, a fact is found from either side, and `beliefs` returns it as a `|~` premise: `(beliefs "(Evaluation (Predicate \"likes\") (List (Concept \"ana\") $1))")`. `Predicate` is also a PeTTa builtin, so an evaluated `(Predicate ...)` fails; the loop builds the term from text and reasoning code must take fact premises from `beliefs` results, as in `(let ($p) (beliefs "...") (let ($q) (beliefs "...") (|~ $p $q)))`. "ana likes fruit" and `(Inheritance (Concept "banana") (Concept "fruit"))` then give "ana likes banana" at `(stv 1.0 0.81)`.

Each new fact is also written to the Chroma collection as the document `FACT subject | relation | value`, so similarity search can find the subject of a fact from a differently worded message. DAS stays the source of truth: a document whose fact was unlearned only costs one empty query.

For a new message the loop queries DAS for the sender's nick and up to `maxFactConcepts` (3) other names: the `LOOKUP` names first (a name of several words such as `Oslo people` also gives `oslo`, where the fact most likely lives; a generic kind such as `team` in `Team A` is not a second key), then the subjects of `FACT`/`NOT` lines, so a statement that names no LOOKUP still recalls the thing it just stated. An indexed `FACT` subject is added only as another spelling of a LOOKUP name (`brasília` for `brasilia`), so the nearest document after learning about Team B does not replace a question about Team A. Capitalised message words fill in when extraction named nothing; a follow-up that names nothing (`Try again`) keeps the previous keys. Recall reads both forms for every name: the facts Omega learned come from one conjunction of `Belief` and `Stated` per side, `(, (Belief (Evaluation (Predicate $r) (List (Concept "team b") (Concept $v))) (stv $f $c)) (Stated (Evaluation ...) $who $when))`, so each match carries its source and its truth; the bare `(Evaluation ...)` atoms written by other agents are read with the name as the user wrote it and in Title Case too, and come without a source. A fact found both ways keeps only its sourced copy (`merge_facts`). If the first round only returns Omega's lowercase spelling, a second round reads the other agents' capitalisation (`Team A` for `team a`). Each match is a six-tuple: "who likes purple?" finds `("arturgontijo" "favorite_color" "purple" "arturgontijo" "2026-10-23 08:36:14" 1.0)`, and a fact of another agent `("Team B" "jersey_color" "red" "" "" 1.0)`. The matches go into the prompt as sentences addressed to the sender, newest first, for example `KNOWN_FACTS: your favorite color is blue (said by you on 2026-10-23 08:36:14); france's capital is paris (said by ana on 2026-10-23 09:02:10).`, which is what lets the agent answer "who told you that?". A denied fact (strength below 0.5) is worded in the negative: `team b is not playing 2026 championship`, `you do not like tea`, `your favorite color is not blue`. Beliefs derived by `|-`/`|~` have no `Stated` link and are reached through `beliefs`. A DAS failure is logged and gives no facts.

A question that joins conditions is answered the same implicit way, so the agent never has to write a query. The extraction call returns `ALL value | value` for conditions joined with *and* ("which team has a blue logo and won in 2009" gives `ALL blue | 2009`) and `ANY value | value` for *or*. `ANY` values become recall keys like names, and the union of their facts is the OR. `ALL` values run one DAS conjunction (`conjunction-facts`): `(, (Evaluation (Predicate $r1) (List (Concept $s) (Concept "blue"))) (Evaluation (Predicate $r2) (List (Concept $s) (Concept "2009"))))`, a subject related to both values whatever the relations, over bare `Evaluation` atoms so learned facts and other agents' facts count alike. The result goes into `KNOWN_FACTS` as `team a's logo color is blue; team a's won national championship is 2009` and is logged as `DAS_CONJUNCTION`. The kind of thing asked for (`which team`) is never a condition; an attribute the model named instead of the stored value (`ALL logo | Brasília` for "its logo blue") is replaced by the neighboring word in the message (`blue`). A value is tried lowercase, as spelled in the message and, when it has several words, word by word (`2009 championship` is stored as `2009`). The router takes two clauses per conjunction and a nested one returns nothing through the PeTTa client, so a third value is paired with the first and only subjects seen with every value are kept. Because the bare `Evaluation` of a denied fact still exists in DAS, the conjunction's matches are checked against the subjects' `Belief`s first and the denied ones are dropped (`without-denied`), so a team that *is not* playing the 2026 championship is not an answer to "which team in red is playing it".

The nested `Evaluation` of a denied fact is a plain link to another agent reading bare patterns, so it looks true to them. Agents sharing the router should read the `Belief` when truth matters; see `docs/development/das-integration-review.md`.

`tests/das_live.metta` runs the learn, recall, belief, conjunction, deny, unlearn round trip against a real router when `OMEGA_DAS_ROUTER` is set, and reports one skipped check otherwise.
