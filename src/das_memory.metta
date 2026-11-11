; Persistent formal memory. &das is bound in run.metta. Without that binding
; &das is an ordinary local space, so tests and runs without DAS still work.
; add-atom and remove-atom take their arguments as data: a parsed atom must be
; bound by let first, or the unevaluated (sread ...) call is stored instead.
; DAS cannot match a bare variable (das_space_no_dump), so every pattern here
; names a relation. The router has two more limits the skills guard against:
; an add_atom or delete_atom whose atom contains a variable has crashed the
; HTTP server, and a query without a variable is rejected.

(= (das-store $str)
   (let $atom (sread $str)
     (if (is-ground $atom)
         (add-atom &das $atom)
         (DAS_STORE_REJECTED "an atom with variables cannot be stored" $atom))))

(= (das-recall $str)
   (let $pattern (sread $str)
     (if (is-ground $pattern)
         (DAS_RECALL_REJECTED "a query needs a variable such as $1; to check one fact match it as a belief: beliefs <fact>" $pattern)
         (collapse (match &das $pattern $pattern)))))

(= (das-forget $str)
   (let $atom (sread $str)
     (if (is-ground $atom)
         (remove-atom &das $atom)
         (DAS_FORGET_REJECTED "an atom with variables cannot be removed" $atom))))

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

; host:port of the DAS Command Router, "" for none. Read directly so run.metta
; can bind &das before the loop configures anything.
(= (dasEndpoint)
   (py-call (helper.normalize_string (configGetByKey dasRouter ""))))

(= (dasConfigured)
   (py-call (helper.is_set (dasEndpoint))))

; GET /ping tells an HTTP server that is down from a query that fails, then a
; query that names a relation, so an unreachable router fails here and not in
; the first user turn.
(= (das-health)
   (if (py-call (helper.das_ping (dasEndpoint)))
       (case (catch (collapse (match &das (Belief (Evaluation (Predicate $r) (List (Concept "__health__") (Concept $v))) $tv) $r)))
         (((Error $type $ctx) (progn (log WARNING "das-memory" (DAS_UNREACHABLE $type)) False))
          ((Error $type) (progn (log WARNING "das-memory" (DAS_UNREACHABLE $type)) False))
          ($ok (progn (log INFO "das-memory" "DAS space answers queries") True))))
       (progn (log WARNING "das-memory" (DAS_HTTP_DOWN (dasEndpoint) "GET /ping did not answer PONG")) False)))

; Plain-language facts from conversation are stored in the binary PLN form
; (Evaluation (Predicate "relation") (List (Concept "subject") (Concept "value"))),
; the shape the lib_pln rules match. Other agents on the same router find the
; fact with the same bare Evaluation pattern; the string predicate name and
; lowercase concept names are the convention shared with them. A relation may
; hold several values ("human similar_to monkey" and "human similar_to chimp"
; are both true), so a new value is added beside the old ones and nothing is
; forgotten without unlearn. Facts are stored as the bare term alone (see
; relation-values below); the earlier Belief/Stated/Fact form, which gave each
; fact a truth and a source, is kept commented as FACT-RECORDS.

(= (current-message)
   (case (catch (get-state &prevmsg))
     (((Error $type $ctx) "")
      ((Error $type) "")
      ($msg $msg))))

; The truth given to a fact a user states, and to one the user denies.
(= (factTruth) (stv 1.0 0.9))
(= (deniedTruth) (stv 0.0 0.9))

; Predicate is also a PeTTa builtin that builds Prolog terms, so the fact term
; is parsed from text and only ever bound by let or placed in add-atom,
; remove-atom and match patterns. learn reports (LEARNED subject relation value)
; and deny (DENIED subject relation value).

(= (fact-term $s $r $v)
   (sread (py-call (helper.fact_term $s $r $v))))

; A learned fact is stored as its bare term alone,
; (Evaluation (Predicate "relation") (List (Concept "subject") (Concept "value"))),
; the form other agents on the router write, so every agent reads every fact
; the same way. There is no truth or source: a denied fact is removed rather
; than believed false, and recall cannot say who stated a fact or when.
; The DAS pattern index keys a link by its top-level targets only, so a query
; naming a concept inside the List reads every Evaluation and matches each in
; the query engine.
;
;; FACT-RECORDS (rollback): the earlier form kept each fact as
;; (Belief term (stv f c)), (Stated term "who" "when") and one
;; (Fact (Concept "name") term (stv f c) (Stated "who" "when")) record per
;; name, the name a top-level target, so one indexed query returned a name's
;; facts with truth and source. To restore it, uncomment every ";; FACT-RECORDS"
;; definition in this file and remove the bare-Evaluation one that follows it.
;;
;; (= (relation-values $s $r)
;;    (collapse (match &das (Fact (Concept $s) (Evaluation (Predicate $r) (List (Concept $s) (Concept $found))) $tv $src) $found)))
;;
;; (= (relation-truths $s $r)
;;    (collapse (match &das (Fact (Concept $s) (Evaluation (Predicate $r) (List (Concept $s) (Concept $found))) (stv $f $c) $src) ($found $f))))
;;
;; (= (forget-value $s $r $v)
;;    (let $term (fact-term $s $r $v)
;;      (progn (map-atom (collapse (match &das (Belief $term $tv) $tv)) $tv (remove-atom &das (Belief $term $tv)))
;;             (map-atom (collapse (match &das (Stated $term $who $when) ($who $when))) $p
;;                       (let ($who $when) $p (remove-atom &das (Stated $term $who $when))))
;;             (map-atom (collapse (match &das (Fact $key $term $tv $src) ($key $tv $src))) $p
;;                       (let ($key $tv $src) $p (remove-atom &das (Fact $key $term $tv $src))))
;;             (catch (remove-atom &das $term)))))
;;
;; (= (store-fact-as $s $r $v $tv $report)
;;    (let* (((stv $strength $confidence) $tv)
;;           ($truths (relation-truths $s $r)))
;;      (if (is-member ($v $strength) $truths)
;;          (KNOWN $s $r $v)
;;          (let* (($_ (if (is-member $v (relation-values $s $r)) (forget-value $s $r $v) ()))
;;                 ($term (fact-term $s $r $v))
;;                 ($who (sread (py-call (helper.speaker_literal (current-message)))))
;;                 ($when (get_time_as_string))
;;                 ($_ (add-atom &das (Belief $term $tv)))
;;                 ($_ (add-atom &das (Stated $term $who $when)))
;;                 ($_ (add-atom &das (Fact (Concept $s) $term $tv (Stated $who $when))))
;;                 ($_ (if (== $s $v) () (add-atom &das (Fact (Concept $v) $term $tv (Stated $who $when))))))
;;            ($report $s $r $v)))))

(= (relation-values $s $r)
   (collapse (match &das (Evaluation (Predicate $r) (List (Concept $s) (Concept $found))) $found)))

; Every stored value is true: (("tea" 1.0) ("coffee" 1.0)).
(= (relation-truths $s $r)
   (map-atom (relation-values $s $r) $found ($found 1.0)))

(= (forget-value $s $r $v)
   (let $term (fact-term $s $r $v)
     (catch (remove-atom &das $term))))

; A stated fact is added and a denied one removed, with no query first: the
; handle is the hash of the term, so adding a stored fact again changes
; nothing, and removing one that is not stored is caught.
(= (store-fact-as $s $r $v $tv $report)
   (let* (((stv $strength $confidence) $tv)
          ($term (fact-term $s $r $v)))
     (if (> $strength 0.5)
         (progn (add-atom &das $term) ($report $s $r $v))
         (progn (catch (remove-atom &das $term)) ($report $s $r $v)))))

(= (store-fact $s $r $v) (store-fact-as $s $r $v (factTruth) LEARNED))

(= (learn $str)
   (case (sread (py-call (helper.parse_fact $str (current-message))))
     ((($s $r $v) (store-fact $s $r $v))
      ($_ (FACT_NOT_LEARNED "expected one short fact: subject | relation | value" $str)))))

; A fact the user denies, stored as the term believed false.
(= (deny $str)
   (case (sread (py-call (helper.parse_fact $str (current-message))))
     ((($s $r $v) (store-fact-as $s $r $v (deniedTruth) DENIED))
      ($_ (FACT_NOT_LEARNED "expected one short fact: subject | relation | value" $str)))))

(= (learn-all $reply)
   (union-atom (map-atom (sread (py-call (helper.extracted_facts $reply (current-message)))) $fact (learn $fact))
               (map-atom (sread (py-call (helper.extracted_denials $reply (current-message)))) $fact (deny $fact))))

(= (unlearn $str)
   (case (sread (py-call (helper.parse_fact_key $str (current-message))))
     ((($s $r) (let $old (relation-values $s $r)
                 (progn (map-atom $old $stale (forget-value $s $r $stale))
                        (UNLEARNED $s $r $old))))
      ($_ (FACT_NOT_UNLEARNED "expected subject | relation" $str)))))

(= (describe-facts $facts $msg)
   (py-call (helper.describe_facts (repr $facts) $msg)))

; Concept names looked up per message besides the sender. Each name is two
; queries, plus more when external facts are read, so this bounds the delay
; per message.
(= (maxFactConcepts) 3)

; Facts about $key and facts whose value is $key, as
; ("subject" "relation" "value" "who" "when" strength), who and when empty
; and the strength 1.0 for a bare Evaluation. With dasExternalFacts the other
; spellings other agents use are read as well. Other agents keep the spelling of the user, so
; the key is tried as written in the message and in Title Case besides
; lowercase. A three-place record (subject, value, value) is read as one value.
; Both forms run every time, because a name may have facts from both sides
; ("team a" learned here and loaded by another agent); a learned fact's own
; nested Evaluation also answers the bare query, and merge_facts drops that
; copy in favour of the one with its source and truth.

;; FACT-RECORDS (rollback):
;; (= (stated-facts-about $key)
;;    (collapse (match &das (Fact (Concept $key) (Evaluation (Predicate $r) (List (Concept $s) (Concept $v))) (stv $f $c) (Stated $who $when))
;;                     ($s $r $v $who $when $f))))
;;
;; (= (stated-facts-of $name)
;;    (collapse (match &das (Fact (Concept $name) (Evaluation (Predicate $r) (List (Concept $name) (Concept $v))) (stv $f $c) (Stated $who $when))
;;                     ($name $r $v $who $when $f))))

; The learned facts naming $key, as subject and as value: two queries.
(= (stated-facts-about $key)
   (collapse (superpose ((match &das (Evaluation (Predicate $r) (List (Concept $key) (Concept $v))) ($key $r $v "" "" 1.0))
                         (match &das (Evaluation (Predicate $r) (List (Concept $s) (Concept $key))) ($s $r $key "" "" 1.0))))))

; The learned facts with $name as subject: one query.
(= (stated-facts-of $name)
   (collapse (match &das (Evaluation (Predicate $r) (List (Concept $name) (Concept $v))) ($name $r $v "" "" 1.0))))

; Other agents keep the user's spelling ("Team A"); trying it besides the
; lowercase one Omega writes costs up to nine more queries per name, so
; dasExternalFacts False skips it when only Omega agents write.
(= (readExternalFacts)
   (py-call (helper.is_enabled (configGetByKey dasExternalFacts True))))

; superpose takes a bound list, not a call: the variants are bound first. A
; user function inside a superpose list is collected as one list, so the match
; calls are written out.
(= (external-facts-about $key)
   (let $names (sread (py-call (helper.name_variants $key (current-message))))
     (let $name (superpose $names)
       (superpose ((match &das (Evaluation (Predicate $r) (List (Concept $name) (Concept $v))) ($name $r $v "" "" 1.0))
                   (match &das (Evaluation (Predicate $r) (List (Concept $s) (Concept $name))) ($s $r $name "" "" 1.0))
                   (match &das (Evaluation (Predicate $r) (List (Concept $name) (Concept $v) (Concept $w)))
                          (let $joined (sread (py-call (helper.join_values $v $w))) ($name $r $joined "" "" 1.0))))))))

(= (facts-about $key)
   (let $stated (stated-facts-about $key)
     (if (readExternalFacts)
         (let $external (collapse (external-facts-about $key))
           (superpose (union-atom $stated $external)))
         (superpose $stated))))

(= (external-subject-facts $name)
   (collapse (superpose ((match &das (Evaluation (Predicate $r) (List (Concept $name) (Concept $v))) ($name $r $v "" "" 1.0))
                         (match &das (Evaluation (Predicate $r) (List (Concept $name) (Concept $v) (Concept $w)))
                                (let $joined (sread (py-call (helper.join_values $v $w))) ($name $r $joined "" "" 1.0)))))))

; The facts of one subject spelled as stored, as subject only: one query, and
; two more when external facts are read.
(= (subject-facts $name)
   (let $stated (stated-facts-of $name)
     (if (readExternalFacts)
         (union-atom $stated (external-subject-facts $name))
         $stated)))

; A fact recalled from its value side names a subject the message did not:
; "Team A founded_in Brasília" for the key "brasília". The question is usually
; about that subject ("which team from Brasília has a blue logo"), so the rest
; of its facts are read next, for up to maxFactConcepts such subjects, each as
; stored and lowercase (another agent's "Team A", Omega's "team a"). Subjects
; that were keys, or the sender, are already read in full, except the other
; spelling of a key whose facts came back only under Omega's lowercase form.
(= (expand-subjects $facts $keys $speaker)
   (let $subjects (sread (py-call (helper.new_subjects (repr $facts) (repr $keys) $speaker (maxFactConcepts) (current-message) (readExternalFacts))))
     (if (== $subjects ())
         ()
         (let $more (recall-failure
                      (catch (unique-atom (collapse (let $subject (superpose $subjects)
                                                      (let $found (subject-facts $subject) (superpose $found)))))))
           (progn (log INFO "das-memory" (DAS_EXPANDED $subjects FOUND: (size-atom $more)))
                  $more)))))

; Arguments are evaluated before a call, so the nondeterministic query must be
; collapsed inside the function that logs a failure, not passed to one.
(= (query-failure $rc)
   (case $rc
     (((Error $type $ctx) (progn (log WARNING "das-memory" (FACTS_NOT_RECALLED $type)) ()))
      ((Error $type) (progn (log WARNING "das-memory" (FACTS_NOT_RECALLED $type)) ()))
      ($answers $answers))))

; Recalled fact tuples, with the sourceless copy of a learned fact dropped.
(= (recall-failure $rc)
   (let $facts (query-failure $rc)
     (if (== $facts ()) () (sread (py-call (helper.merge_facts (repr $facts)))))))

(= (recall-facts-by-keys $keys)
   (recall-failure (catch (unique-atom (collapse (let $key (superpose $keys) (facts-about $key)))))))

; The sender is looked up as a subject only; the other names from both sides.
(= (recall-facts-for $speaker $keys)
   (recall-failure
     (catch (let $own (stated-facts-of $speaker)
              (let $others (collapse (let $key (superpose $keys) (facts-about $key)))
                (unique-atom (union-atom $own $others)))))))

; A question about something that must meet several conditions at once, such
; as "which team has a blue logo and won in 2009", is extracted as
; ALL blue | 2009 and answered by one DAS conjunction: a subject related to
; both values, whatever the relation names. The matched facts join the
; recalled ones, so the agent reads "team a's logo color is blue; team a's
; won national championship is 2009" and does not have to write a query.
; The router accepts a conjunction of two clauses, and a nested one answers
; but the client returns nothing, so a third value is paired with the first
; and conjunction_facts keeps the subjects seen with every value.
; The queries are built as text and read with sread, so the shared $s binds
; across the clauses of each pattern. The bare Evaluation of a denied fact
; also answers, so the beliefs of each matched subject are read and a fact
; believed false does not count as meeting its condition.
(= (conjunction-facts $values)
   (if (== $values ())
       ()
       (let $queries (sread (py-call (helper.conjunction_queries (repr $values) (current-message))))
         (let $found (recall-failure
                       (catch (unique-atom (collapse (let ($pattern $template) (superpose $queries)
                                                       (let $facts (match &das $pattern $template) (superpose $facts)))))))
           (let $true (without-denied $found)
             (let $kept (sread (py-call (helper.conjunction_facts (repr $true) (repr $values) (current-message))))
               (progn (log INFO "das-memory" (DAS_CONJUNCTION $values FOUND: $kept))
                      $kept)))))))

(= (subject-beliefs $subjects)
   (collapse (let $subject (superpose $subjects)
               (match &das (Belief (Evaluation (Predicate $r) (List (Concept $subject) (Concept $v))) (stv $f $c)) ($subject $r $v $f)))))

;; FACT-RECORDS (rollback):
;; (= (without-denied $facts)
;;    (if (== $facts ())
;;        ()
;;        (let $subjects (sread (py-call (helper.fact_subjects (repr $facts))))
;;          (let $beliefs (query-failure (catch (subject-beliefs $subjects)))
;;            (sread (py-call (helper.drop_denied (repr $facts) (repr $beliefs))))))))

; A denied fact is removed rather than believed false, so no stored fact is denied.
(= (without-denied $facts) $facts)

; Recall from the words of the message alone, used when no extraction reply is available.
(= (recall-facts $msg)
   (recall-facts-by-keys (sread (py-call (helper.fact_query_keys $msg (maxFactConcepts))))))
