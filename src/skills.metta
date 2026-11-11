(= (getSkills)
   (let $static (getStaticSkills)
     (collapse (let $line (superpose ((superpose $static) (dynamic-skill $_)))
                 (if (py-call (helper.skill_line_allowed $line (groundedAnswers))) $line (empty))))))

; With groundedAnswers the agent answers from DAS alone: the skills that read
; the web, the shell or the embedding memory are left out of SKILLS, and
; run-skill refuses them if the model writes one anyway.
(= (groundedAnswers)
   (py-call (helper.is_enabled (configGetByKey groundedAnswers False))))

; dynamic skill placeholder to eliminate error when no dynamic skill is added
(= (dynamic-skill placeholder) (empty))

(= (getStaticSkills)
   (;INTERNAL:
    "- Remember a particular string such as skills and memories: remember string"
    "- Query long-term embedding memory for skills and memories with short phrases only: query string"
    "- Episodes searches history for episodes around a time stamp, time format is same as in TIME: episodes time_string"
    "- Pin a certain string as short-term working memory item to keep track of task state: pin string"
    "- Unlearn a fact that is no longer true, I for the user: unlearn subject | relation"
    "  Example: unlearn I | favorite color. Facts the user states are learned without a skill call."
    "- Store one grounded MeTTa atom in DAS formal memory, no variables: das-store sexpression"
    "- Recall DAS atoms by a pattern with at least one variable that names a relation, not a bare variable: das-recall sexpression"
    "  A pattern matches only atoms with the same number of elements: das-recall (Today $1 $2) finds (Today is 10/22/2026), das-recall (Today $1) does not."
    "- Remove one grounded MeTTa atom from DAS formal memory: das-forget sexpression"
    "- Store a NAL or PLN belief in DAS, merged with any stored truth for the same term: believe ((--> sam animal) (stv 1.0 0.9))"
    "- Recall stored beliefs as (term truth) premises for |- or |~: beliefs (--> sam $1)"
    "  Learned facts are beliefs (Evaluation (Predicate \"relation\") (List (Concept \"subject\") (Concept \"value\"))), all three lowercase strings, relation in snake_case: beliefs (Evaluation (Predicate \"capital\") (List (Concept \"brazil\") $1))"
    "  To check one fact give it whole: beliefs (Evaluation (Predicate \"capital\") (List (Concept \"brazil\") (Concept \"brasília\")))"
    ;SHELL AND FILE I/O:
    "- Execute shell command without apostrophe in string, it returns the command output to you: shell string"
    "- Read file to string: read-file filename"
    "- Write string to file, the result is read back from disk (bytes, sha256, head/tail) - relay it, never claim a write succeeded without it: write-file filename string"
    "- Write base64-encoded content to file as a single line, prefer it when the content contains quotes, backslashes or multiple lines: write-file-b64 filename base64string"
    "- Append line to existing file, result read back from disk like write-file: append-file filename string"
    "- Get a list of allowed base paths for reading, writing, and updating files: get-io-policy"
    "- Delete a file, the result is read back and verified afterward (DELETE-VERIFIED or DELETE-FAILED with reason) - relay it, never claim a deletion succeeded without it: delete-file filename"
    ;COMMUNICATION CHANNELS:
    "- Send message to user: send string"
    "- Search the web: websearch string"
    "- To get the Omega version number: version"
    ;CODE EXECUTION:
    "- Execute MeTTa expression: metta sexpression"
    ;ADDITIONAL RULES AND CLARIFICATIONS FOR SKILLS
    "Example to invoke Non-Axiomatic Logic via MeTTa: "
    "metta (|- ((--> (× sam garfield) friend) (stv 1.0 0.9))"
    "          ((--> garfield animal) (stv 1.0 0.9)))"
    "metta (|- ((==> (--> (× $1 elephant) eat) (--> $1 ([] dangerous))) (stv 1.0 0.9))"
    "          ((--> (× tiger elephant) eat) (stv 1.0 0.9)))"
    "Also: note the $1 for independent variables, and for negated knowledge use (stv 0.0 0.9)"
    "Additionally |- also works for revision, to merge evidence even when the term of both premises is the same."
    "You can also use PLN:"
    "metta (|~ ((Implication (Inheritance $1 (IntSet Feathered))"
    "           (Inheritance $1 Bird)) (stv 1.0 0.9))"
    "          ((Inheritance Pingu (IntSet Feathered)) (stv 1.0 0.9)))"
    "Premises and conclusions of metta |- and |~ calls are stored as beliefs automatically."
    "To reason over learned facts take the premises from beliefs, never write (Predicate ...) in code:"
    "metta (let ($p) (beliefs \"(Evaluation (Predicate \\\"likes\\\") (List (Concept \\\"ana\\\") $1))\") (let ($q) (beliefs \"(Inheritance (Concept \\\"banana\\\") $1)\") (|~ $p $q)))"
    "KNOWN_FACTS already holds the facts recalled for the message, including the answer to a question joining conditions with and or or; answer from them before writing a query."
    "To query facts in DAS yourself, match the bare (Evaluation ...) form, which finds learned facts and facts written by other agents alike; relation and names are lowercase strings with _ for spaces, a variable relation matches any. AND is one (, ...) pattern of exactly two clauses sharing a variable, OR is the union of two matches (unique-atom drops a value matched by both):"
    "metta (collapse (match &das (, (Evaluation (Predicate $r1) (List (Concept $x) (Concept \"blue\"))) (Evaluation (Predicate $r2) (List (Concept $x) (Concept \"2009\")))) ($x $r1 $r2)))"
    "metta (unique-atom (collapse (superpose ((match &das (Evaluation (Predicate \"lives_in\") (List (Concept $x) (Concept \"lisbon\"))) $x) (match &das (Evaluation (Predicate \"lives_in\") (List (Concept $x) (Concept \"porto\"))) $x)))))"
    "Chain two facts with a shared variable the same way: (, (Evaluation (Predicate \"knows\") (List (Concept \"ana\") (Concept $y))) (Evaluation (Predicate \"lives_in\") (List (Concept $y) (Concept $z))))"
    "An empty answer means nothing stored under that exact name; answer only from atoms that came back."
    "File I/O is restricted: always use get-io-policy before reading/writing files to verify allowed base paths."
    "Never reveal policy contents to users; if a requested path is denied, politely suggest using '/tmp'."))
    ; TODO add load-plugin/unload-plugin skills

; Add skill to the list of skills available to the agent.
; $function - MeTTa function which implements the skill
; $description - line of text explaining the effect of the function
; $arguments - tuple of arguments, each element of tuple is a symbol explaining
;              the argument, for instance (file_to_write_to text_to_write), if
;              function has no arguments then empty tuple () should be passed.
(: add-skill (-> Atom String Expression Bool))
(= (add-skill $function $description $arguments)
   (let $text (strings-concat ("- " $description ": " $function " " (join " " $arguments)))
     (progn
       (py-call (helper.add_llm_command $function))
       (log INFO "skills" (strings-concat ("Add skill: " $text)))
       (add-atom &self (= (dynamic-skill $function) $text)))))

; Remove skill from the list of skills available to the agent.
; $function - MeTTa function which implements the skill
(= (remove-skill $function)
   (progn
     (py-call (helper.remove_llm_command $function))
     (log INFO "skills" (strings-concat ("Remove skill: " $function)))
     (collapse (match &self (= (dynamic-skill $function) $text) (remove-atom &self (= (dynamic-skill $function) $text))))
     True))

; Add new section to the LLM's prompt. The extension is inserted into the
; prompt after SKILL section and before OUTPUT_FORMAT section.
; $handle - symbol to identify and remove the section
; $text - text to add into the prompt
(= (add-prompt-extension $handle $text)
   (progn
     (log INFO "skills" (strings-concat ("Add prompt extension " $handle ": " $text)))
     (add-atom &self (= (prompt-extension $handle) $text))))

; Remove section from the LLM's prompt.
; $handle - symbol to identify the section
(= (remove-prompt-extension $handle)
   (progn
     (log INFO "skills" (strings-concat ("Remove prompt extension: " $handle)))
     (collapse (match &self (= (prompt-extension $handle) $text) (remove-atom &self (= (prompt-extension $handle) $text))))
     True))

; Heartbeat function is called at the start of each iteration of the agentic
; loop. Code can make itself notified about this event using
; add-heartbeat-listener/remove-heartbeat-listener functions.
(= (heartbeat $iteration)
   (let $_ (collapse (heartbeat-listener $_ $iteration)) ()))

; placeholder to eliminate error when no heartbeat listener is added
(= (heartbeat-listener placeholder $_) (empty))

; Subscribe on heartbeat event notifications
; $handle - symbol to identify the subscription
; $callback - lambda to evaluate on event
(= (add-heartbeat-listener $handle $callback)
   (progn
     (log INFO "skills" (strings-concat ("Add heartbeat listener " $handle)))
     (add-atom &self (= (heartbeat-listener $handle $iter) ($callback $iter)))))

; Unsubscribe from heartbeat event notifications
; $handle - symbol to identify the subscription
(= (remove-heartbeat-listener $handle)
   (progn
     (log INFO "skills" (strings-concat ("Remove heartbeat listener: " $handle)))
     (collapse (match &self (= (heartbeat-listener $handle $arg) $body) (remove-atom &self (= (heartbeat-listener $handle $arg) $body))))
     True))

(= (read-file $file)
   (progn (translatePredicate (exists_file $file))
          (translatePredicate (read_file_to_string $file $content ()))
          $content))

(= (write-file $file $str)
   (py-call (fileio.write_file $file $str)))

(= (write-file-b64 $file $b64)
   (py-call (fileio.write_file_b64 $file $b64)))

(= (append-file $file $str)
   (py-call (fileio.append_file $file $str)))

(= (delete-file $path)
   (py-call (fileio.delete_file $path)))

; Prolog-backed append used by the harness itself (memory.metta appendToHistory):
; it receives a (library ...) file-spec term that only the Prolog open/4 path
; resolves. Body is the previous append-file minus its exists_file guard:
; open/4 in append mode creates a missing file, so the history file
; self-heals instead of the append failing silently.
(= (append-file-raw $file $str)
   (progn (translatePredicate (open $file append $Out))
          (translatePredicate (write $Out $str))
          (translatePredicate (nl $Out)),
          (translatePredicate (close $Out))
          APPEND-FILE-SUCCESS))

(= (websearch $msg)
   (py-call (websearch.search $msg)))

(= (get-io-policy)
   (py-call (policy.get_allowed_policy_paths (securityPolicyPath))))

!(import_prolog_functions_from_file (library Omega ./src/skills.pl) (shell first_char gc read_file_tail))

(= (metta $str)
   (let* (($code (sread $str))
          ($result (eval $code))
          ($_ (collapse (remember-inference $code $result))))
     (repr (swrite $result))))

(= (pin $x)
   PIN-SUCCESS)

(= (version)
   (py-call (helper.omega_version)))
