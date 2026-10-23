; Persistent formal memory. &das is bound in run.metta. Without that binding
; &das is an ordinary local space, so tests and runs without DAS still work.
; add-atom and remove-atom take their arguments as data: a parsed atom must be
; bound by let first, or the unevaluated (sread ...) call is stored instead.
; DAS cannot match a bare variable (das_space_no_dump), so every pattern here
; names a relation.

(= (das-store $str)
   (let $atom (sread $str)
     (add-atom &das $atom)))

(= (das-recall $str)
   (let $pattern (sread $str)
     (collapse (match &das $pattern $pattern))))

(= (das-forget $str)
   (let $atom (sread $str)
     (remove-atom &das $atom)))

; NAL and PLN knowledge is kept as (Belief <term> (stv f c)), at most one
; truth value per term. A different truth for a known term is merged with
; NAL revision; the same truth again is not stored twice, so re-deriving a
; conclusion does not inflate its confidence.

(= (belief-truths $term)
   (collapse (match &das (Belief $term $tv) $tv)))

(= (revise-truth $a $b)
   (case (catch (Truth_Revision $a $b))
     (((Error $type $ctx) $a)
      ($tv $tv))))

(= (store-belief $term $tv)
   (if (is-ground $term)
       (let $old (belief-truths $term)
         (if (is-member $tv $old)
             (Belief $term $tv)
             (let $merged (foldl-atom $old $tv $acc $prev (revise-truth $acc $prev))
               (progn (add-atom &das (Belief $term $merged))
                      (map-atom (exclude-item $merged $old) $stale (remove-atom &das (Belief $term $stale)))
                      (Belief $term $merged)))))
       (BELIEF_NOT_STORED_TERM_HAS_VARIABLES $term)))

(= (store-belief-pair $pair)
   (case $pair
     ((($term (stv $f $c)) (store-belief $term (stv $f $c)))
      ($_ (BELIEF_NOT_STORED_EXPECTED_TERM_AND_STV $pair)))))

(= (believe $str)
   (store-belief-pair (sread $str)))

(= (beliefs $str)
   (let $pattern (sread $str)
     (collapse (match &das (Belief $pattern $tv) ($pattern $tv)))))

; Premises and conclusions of |- and |~ calls made through the metta skill.
; The operator is compared as quoted data: a case pattern such as (|- $a $b)
; is compiled into a call of |- with unbound premises.
(= (store-inference $code $result)
   (case $code
     ((($op $a $b) (if (is-member $op (quote (|- |~)))
                       (map-atom (cons-atom $a (cons-atom $b $result)) $pair (store-belief-pair $pair))
                       ()))
      ($_ ()))))

; A DAS outage must not fail the skill that triggered the write.
(= (das-log-failure $what $rc)
   (case $rc
     (((Error $type $ctx) (log WARNING "das-memory" ($what $type)))
      ((Error $type) (log WARNING "das-memory" ($what $type)))
      ($ok $ok))))

(= (remember-inference $code $result)
   (das-log-failure BELIEFS_NOT_STORED (catch (store-inference $code $result))))

(= (das-remember $time $str)
   (das-log-failure MEMORY_NOT_STORED (catch (add-atom &das (Memory $time $str)))))

; Plain-language facts from conversation, in the DAS knowledge-base shape
; (Evaluation (Predicate (relation "value")) (Concept "subject")), the form DAS
; Sql2AtomsMapper gives a column value. A subject has at most one value per
; relation: a new value replaces the old one.
; DAS has no text search, so facts are recalled by exact subject name.

(= (current-message)
   (case (catch (get-state &prevmsg))
     (((Error $type $ctx) "")
      ((Error $type) "")
      ($msg $msg))))

; Predicate is also a PeTTa builtin that builds Prolog terms, so an Evaluation
; atom may only appear where it is not evaluated: add-atom, remove-atom and
; match patterns. Results are reported as (LEARNED subject relation value).

(= (relation-values $s $r)
   (collapse (match &das (Evaluation (Predicate ($r $found)) (Concept $s)) $found)))

(= (forget-value $s $r $v)
   (remove-atom &das (Evaluation (Predicate ($r $v)) (Concept $s))))

(= (store-fact $s $r $v)
   (let $old (relation-values $s $r)
     (if (is-member $v $old)
         (LEARNED $s $r $v)
         (progn (map-atom $old $stale (forget-value $s $r $stale))
                (add-atom &das (Evaluation (Predicate ($r $v)) (Concept $s)))
                (LEARNED $s $r $v)))))

(= (learn $str)
   (case (sread (py-call (helper.parse_fact $str (current-message))))
     ((($s $r $v) (store-fact $s $r $v))
      ($_ (FACT_NOT_LEARNED "expected one short fact: subject | relation | value" $str)))))

(= (learn-all $reply)
   (map-atom (sread (py-call (helper.extracted_facts $reply))) $fact (learn $fact)))

(= (unlearn $str)
   (case (sread (py-call (helper.parse_fact_key $str (current-message))))
     ((($s $r) (let $old (relation-values $s $r)
                 (progn (map-atom $old $stale (forget-value $s $r $stale))
                        (UNLEARNED $s $r $old))))
      ($_ (FACT_NOT_UNLEARNED "expected subject | relation" $str)))))

(= (describe-facts $facts $msg)
   (py-call (helper.describe_facts (repr $facts) $msg)))

; One DAS query per concept name, so the number of names bounds the delay per message.
(= (maxFactConcepts) 3)

(= (recall-facts $msg)
   (let $keys (sread (py-call (helper.fact_query_keys $msg (maxFactConcepts))))
     (case (catch (unique-atom (collapse (let $key (superpose $keys)
                                           (match &das (Evaluation (Predicate ($r $v)) (Concept $key)) ($key $r $v))))))
       (((Error $type $ctx) (progn (log WARNING "das-memory" (FACTS_NOT_RECALLED $type)) ()))
        ((Error $type) (progn (log WARNING "das-memory" (FACTS_NOT_RECALLED $type)) ()))
        ($facts $facts)))))
