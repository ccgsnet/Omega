(= (maxNewInputLoops) (empty))
(= (maxWakeLoops) (empty))
(= (sleepInterval) (empty))
(= (provider) (empty))
(= (maxOutputToken) (empty))
(= (reasoningMode) (empty))
(= (wakeupInterval) (empty))
(= (memoryDirectory) (empty))
(= (spamShield) (empty)) ; TODO: this parameter is considered deprecated
(= (autoLearnFacts) (empty))
(= (factExtractionTokens) (empty))
(= (factExtractionReasoning) (empty))
(= (idleThinking) (empty))

(= (initLoop)
   (progn (configure maxNewInputLoops 50) ;20
          (configure maxWakeLoops 1)
          (configure spamShield False)
          (configure sleepInterval 1) ;10
          (configure provider Anthropic)
          (configure maxOutputToken 6000)
          (configure reasoningMode medium)
          (configure wakeupInterval 600) ;600=10 minutes
          (configure autoLearnFacts True)
          (configure factExtractionTokens 4000)
          (configure factExtractionReasoning (reasoningMode))
          (configure idleThinking True)
          (configure memoryDirectory
               (joinPath ((py-call (helper.projectRootDirectory)) memory)))
          (change-state! &prevmsg "")
          (change-state! &lastresults "")
          (change-state! &loops (maxNewInputLoops))
          (change-state! &replyTurns 0)
          (change-state! &pendingResults "")
          (change-state! &knownFacts "none")
          (change-state! &lastFactKeys ())
          (change-state! &nextWakeAt (+ (get_time) (wakeupInterval)))
          ))

; Turns a user message stays unanswered-visible while the agent gathers
; results with other skills before replying.
(= (maxReplyTurns) 5)

; With idleThinking False the model is called only for a new message and the
; reply turns after it. Idle turns otherwise cost a full prompt each, which a
; local server answers one at a time ahead of the next message, and small
; models fill them with "no new message" lines that pile up in HISTORY.

; Facts a user states and the names a user asks about are extracted by one
; separate model call before the agent sees the message, so storing and recall
; do not depend on the agent choosing a skill. Messages that can state or ask
; nothing, such as auth, skill calls and short acknowledgements, skip the call.
; A reasoning model may spend the whole output budget thinking and answer
; nothing; the provider then returns its token-limit message, and the call is
; made once more with twice the budget before the message is given up as
; FACTS_NOT_EXTRACTED. The effort is factExtractionReasoning, by default the
; agent's reasoningMode.
(= (extraction-call $msg $tokens)
   (case (catch (llmProviderChat (py-call (helper.fact_extraction_prompt $msg)) $tokens (factExtractionReasoning)))
     (((Error $type $ctx) (progn (log WARNING "das-memory" (FACTS_NOT_EXTRACTED $type)) "NONE"))
      ((Error $type) (progn (log WARNING "das-memory" (FACTS_NOT_EXTRACTED $type)) "NONE"))
      ($reply $reply))))

(= (extract-from-message $msg)
   (if (and (autoLearnFacts) (py-call (helper.needs_fact_extraction $msg)))
       (let $reply (extraction-call $msg (factExtractionTokens))
         (if (py-call (helper.is_token_limit_reply $reply))
             (let $retry (extraction-call $msg (* 2 (factExtractionTokens)))
               (if (py-call (helper.is_token_limit_reply $retry))
                   (progn (log WARNING "das-memory" (FACTS_NOT_EXTRACTED "reasoning used the whole token budget twice" (* 2 (factExtractionTokens))))
                          "NONE")
                   $retry))
             $reply))
       "NONE"))

(= (learn-from-reply $reply)
   (das-log-failure FACTS_NOT_LEARNED
     (catch (let $learned (learn-all $reply)
              (progn (map-atom $learned $fact (index-fact $fact))
                     (log INFO "das-memory" (FACTS_EXTRACTED: $reply LEARNED: $learned))
                     $learned)))))

; The names queried in DAS for a message besides the sender: the LOOKUP names
; and the subjects of FACT/NOT lines (a statement often has no LOOKUP), a
; spelling of those names from the FACT index (brasília for brasilia), and
; capitalised message words only when the extraction named nothing. A follow-up
; that names nothing keeps the previous keys, so "Try again" does not inherit
; the last learned fact about someone else.
(= (recall-keys $msg $reply)
   (sread (py-call (helper.recall_keys $msg
                                       (py-call (helper.extracted_lookups $reply $msg (maxFactConcepts)))
                                       (indexed-fact-keys $msg (maxFactConcepts))
                                       (maxFactConcepts)
                                       (repr (get-state &lastFactKeys))))))

; Facts are recalled by name, and a question that joins conditions with and
; also runs one DAS conjunction over its values (ALL in the extraction reply);
; a question joining them with or looks up each value (ANY), which is the
; union of their facts. An ALL value that names the attribute ("logo") instead
; of the stored value ("blue") is rewritten from the message before the query.
; The ALL values are looked up as names as well, so a conjunction that still
; misses finds the facts of each value; and the subjects those facts name,
; which the message did not, are read in full (expand-subjects). A
; same_<attribute>_as fact carries the other side's value of the attribute
; over, so "miami same_state_as orlando" with "orlando state florida" also
; reads "miami's state is florida", even when each was stored by another agent.
; A message that only states facts asks nothing, so it is answered from the
; facts just stored and DAS is not queried. send skips a reply equal to the
; last one, which holds within one message only: a new message may get the same
; words again.
(= (remember-message $msg)
   (let* (($_ (change-state! &lastsend ""))
          ($reply (extract-from-message $msg))
          ($learned (learn-from-reply $reply))
          ($keys (recall-keys $msg $reply))
          ($_ (change-state! &lastFactKeys $keys)))
     (if (py-call (helper.is_statement $reply $msg))
         (change-state! &knownFacts (py-call (helper.describe_learned (repr $learned) $msg)))
         (recall-for-message $msg $reply $keys))))

(= (recall-for-message $msg $reply $keys)
   (let* (($speaker (sread (py-call (helper.speaker_literal $msg))))
          ($_ (log INFO "das-memory" (DAS_RECALL_KEYS $keys)))
          ($facts (recall-facts-for $speaker $keys))
          ($joint (conjunction-facts (sread (py-call (helper.extracted_conjunction $reply $msg)))))
          ($found (unique-atom (union-atom $facts $joint)))
          ($more (expand-subjects $found $keys $speaker))
          ($merged (py-call (helper.merge_facts (repr (union-atom $found $more)))))
          ($known (sread (py-call (helper.infer_shared_facts $merged)))))
     (change-state! &knownFacts (py-call (helper.describe_known_facts (repr $known) (repr $keys) $msg)))))

; Small models often send idle chatter such as "No new user input." despite the
; prompt, so a send is only run while a user message is waiting for a reply.
; Plugins call send directly and are not affected.
(= (run-skill $s $replyopen)
   (if (and (groundedAnswers) (py-call (helper.is_ungrounded_call (repr $s))))
       (SKILL_DISABLED "stated facts are stored automatically and answers come only from KNOWN_FACTS; just reply with send")
       (if (or $replyopen (not (py-call (helper.is_send_call (repr $s)))))
           (eval $s)
           (SEND_SKIPPED "no new or unanswered user message"))))

(= (initKnowledge)
   (progn (log INFO "loop" "Initializing knowledge base")
          (log INFO "loop" (py-call (rag.init_knowledge (embeddingprovider))))
          ()))

(= (getContext)
   (string-safe (py-str ("PROMPT: " (getPrompt (provider)) " SKILLS: " (getSkills)
                         (newline) (getPromptExtensions) (newline)
                         " OUTPUT_FORMAT: Up to 5 lines. One skill per line. No quotes around args. No prose." (newline)
                         " A user reply is the send skill followed by the reply." (newline)
                         " Write a reply as a person chatting: plain sentences, or a few short points on separate lines starting with -; never a list in brackets, never the user's name or the word noted in front." (newline)
                         " Do not call send when there is no new or unanswered user message." (newline)
                         " Skill results arrive in the next turn: do not send an answer that depends on a skill called in the same turn." (newline)
                         " For UNANSWERED-HUMAN-MSG, send the answer built from its RESULTS_GATHERED_FOR_IT. Do not repeat a skill call already shown there." (newline)
                         " KNOWN_FACTS are learned facts related to the user message, written to the user: your means the user's, never yours." (newline)
                         " Answer questions from KNOWN_FACTS in the same person, for example: Your favorite color is blue. Never invent a fact that is not there." (newline)
                         " When KNOWN_FACTS starts with just stored, the user only told you something: acknowledge just that in one short sentence, for example: send Got it, Miami is called the Magic City. Do not repeat earlier answers or other facts. When KNOWN_FACTS says nothing was stored, tell the user you could not store it and ask them to say it more simply." (newline)
                         (groundedRule)
                         " Use unlearn only to remove a fact that is no longer true." (newline)
                         " SAVE_PERMANENT_FILES_DIR: " (memoryDirectory)
                         " LAST_SKILL_USE_RESULTS: " (last_chars (get-state &lastresults) (maxFeedback))
                         " HISTORY: " (getHistory) 
                         " TIME: " (get_time_as_string)))))

(= (groundedRule)
   (if (groundedAnswers)
       (py-str (" KNOWN_FACTS is all you know, read from DAS: answer only with those facts and what follows from them by reasoning, never from your own knowledge or the web; there is no query to run."
                " When KNOWN_FACTS says nothing is stored about a name, tell the user you do not know anything about it yet." (newline)))
       ""))

(= (addTelegramPromptExtension)
   (if (== (commchannel) telegram)
       (let $path (joinPath ((memoryDirectory) "tg_prompt.txt"))
            (if (exists-file $path)
                (add-prompt-extension tg-prompt (read-file $path))
                (progn (log WARN "loop" (TELEGRAM_PROMPT_NOT_FOUND: $path))
                       ())))
       ()))

(= (getPromptExtensions)
   (join (newline) (collapse (prompt-extension $_))))

; dynamic prompt extension placeholder to eliminate error when no extension is added
(= (prompt-extension placeholder) (empty))

(= (HandleError $msg $cmd $sexpr)
   (case $sexpr (((Error $a $b) (let $new (append (get-state &error) (($msg $cmd)))
                                          (progn (change-state! &error $new) (ALERT_FAILED $a $b))))
                 ($else $sexpr))))

(= (omega)
   (omega 1))
(= (omega $k)
   (progn (if (== $k 1) (progn (initConfig)
                               (initLoop)
                               (initLogger)
                               (applySecurityPolicy)
                               (initMemory)
                               (das-health)
                               (initKnowledge)
                               (initPlugins)
                               (initChannels)
                               (addTelegramPromptExtension)
                               (commChannelSend (version))
                               (llmProviderStart (provider)))
                        (change-state! &loops (- (get-state &loops) 1)))
          (let $prompt (getContext)
               (progn (log INFO "loop" (---------iteration $k))
                      (heartbeat $k)
                      (let* (($msgrcv (string-safe (repr (receive))))
                             ($msgnew (prog1 (and (> (string_length $msgrcv) 0) (!= $msgrcv (get-state &prevmsg)))
                                             (if (> (string_length $msgrcv) 0) (change-state! &prevmsg $msgrcv) _)))
                             ($msg (get-state &prevmsg))
                             ($_ (if (and (> $k 1) $msgnew)
                                     (change-state! &loops (maxNewInputLoops)) _)))
                            (if (and (> (get-state &loops) 0)
                                     (or (idleThinking) (or $msgnew (> (get-state &replyTurns) 0))))
                                (let* (($gathered (get-state &pendingResults))
                                       ($_ (if $msgnew (remember-message $msg) _))
                                       ($facts (get-state &knownFacts))
                                       ($replyopen (or $msgnew (> (get-state &replyTurns) 0)))
                                       ($lastmessage (if $msgnew
                                                         (HUMAN-MSG: $msg KNOWN_FACTS: $facts)
                                                         (if (> (get-state &replyTurns) 0)
                                                             (UNANSWERED-HUMAN-MSG: $msg KNOWN_FACTS: $facts RESULTS_GATHERED_FOR_IT: $gathered)
                                                             " No new user message. Do not call send.")))
                                       ($_ (change-state! &nextWakeAt (+ (get_time) (wakeupInterval))))
                                       ($_ (log INFO "loop" $lastmessage))
                                       ($send (py-str ($prompt :-:-:-: $lastmessage)))
                                       ($_ (log INFO "loop" (CHARS_SENT: (string_length $send) $send)))
                                       ($respi (llmProviderChat $send (maxOutputToken) (reasoningMode)))
                                       ($resp (py-call (helper.balance_parentheses $respi $replyopen)))
                                       ($response (if (== "(" (first_char $resp)) $resp (progn (log INFO "loop" $resp) (repr (REMEMBER:OUTPUT_NOTHING_ELSE_THAN: ((skill arg) ...))))))
                                       ($sexpr (catch (sread $response)))
                                       ($_ (change-state! &error ()))
                                       ($mcerr (HandleError MULTI_COMMAND_FAILURE_NOTHING_WAS_DONE_PLEASE_CORRECT_PARENTHESES_AND_USE_QUOTES_AND_RETRY $response $sexpr))
                                       ($_ (log INFO "loop" (RESPONSE: $sexpr)))
                                       ($results (if (== $mcerr $sexpr)
                                                      (RESULTS: (collapse (let $s (superpose $sexpr)
                                                                           (let $precheck (HandleError UNKNOWN_SKILL_CALL $s $s)
                                                                             (COMMAND_RETURN: ($s (if (== $precheck $s)
                                                                                                    (HandleError SINGLE_COMMAND_ERROR_NOTHING_WAS_DONE_PLEASE_FIX_AND_RETRY $s (catch (let $R (run-skill $s $replyopen) (py-call (helper.normalize_string $R)))))
                                                                                                    $precheck)))))))
                                                      (RESULTS: $mcerr)))
                                       ($_ (log INFO "loop" (RESPONSE: $results)))
                                       ($turnresults (string-safe (repr $results)))
                                       ($_ (change-state! &pendingResults (if $msgnew
                                                                              $turnresults
                                                                              (if (> (get-state &replyTurns) 0)
                                                                                  (last_chars (py-str ((get-state &pendingResults) " " $turnresults)) (maxFeedback))
                                                                                  ""))))
                                       ($_ (change-state! &replyTurns (if (py-call (helper.answered_user $response))
                                                                          0
                                                                          (if $msgnew
                                                                              (maxReplyTurns)
                                                                              (max 0 (- (get-state &replyTurns) 1)))))))
                                      (let $feedback (if (py-call (helper.unknown_skill_only $response))
                                                         (py-call (helper.unknown_skill_reminder))
                                                         $response)
                                           (progn (if (or $msgnew  (not (== $sexpr ()))) (addToHistory $msg $feedback $sexpr $msgnew) _)
                                                  (change-state! &lastresults (if (py-call (helper.unknown_skill_only $response))
                                                                                  $feedback
                                                                                  (string-safe (repr $results)))))))
                                (if (> (get_time) (get-state &nextWakeAt))
                                    (change-state! &loops (+ 1 (maxWakeLoops))) _)))
                      (sleep (sleepInterval))
                      (cut)
                      (gc)
                      (omega (+ 1 $k))))))
