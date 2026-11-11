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

; Plain-language facts from conversation are beliefs over the binary PLN form
; (Evaluation (Predicate "relation") (List (Concept "subject") (Concept "value"))),
; the shape the lib_pln rules match, so a learned fact is a premise for |~ and
; (beliefs "(Evaluation (Predicate \"capital\") (List (Concept \"brazil\") $1))")
; finds it. The nested Evaluation is itself a link in DAS, so other agents on
; the same router find the fact with a bare Evaluation pattern; the string
; predicate name and lowercase concept names are the convention shared with them. A relation may hold several values ("human similar_to monkey" and
; "human similar_to chimp" are both true), so a new value is added beside the
; old ones and nothing is forgotten without unlearn; recall lists the newest
; first. Each fact carries (Stated term "nick" "time") provenance.
; A fact the user denies ("Team B is not playing the 2026 championship") is
; the same term believed at (stv 0.0 0.9), so |~ and beliefs see a false
; premise rather than a relation called not_playing, and recall reads it as
; "team b is not playing 2026 championship". Stating the fact again with the
; other truth replaces that one value and leaves the relation's other values.

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
; for a new fact and (KNOWN subject relation value) for one already stored.

(= (fact-term $s $r $v)
   (sread (py-call (helper.fact_term $s $r $v))))

; The DAS pattern index keys a link by its top-level targets only, so a pattern
; whose names sit inside the nested Evaluation, as every Belief, Stated and bare
; Evaluation query here does, reads every link of that type and matches each in
; the query engine. A learned fact is therefore also written as one record per
; name it holds, (Fact (Concept "name") <term> <truth> (Stated "who" "when")),
; with the name a top-level target: one indexed query returns a name's facts,
; both sides, with truth and source. Belief and Stated stay the facts' form for
; |~, beliefs and other agents; the records are kept in step with them.
(= (relation-values $s $r)
   (collapse (match &das (Fact (Concept $s) (Evaluation (Predicate $r) (List (Concept $s) (Concept $found))) $tv $src) $found)))

; The values of a relation with the strength each is believed at: (("tea" 1.0) ("coffee" 0.0)).
(= (relation-truths $s $r)
   (collapse (match &das (Fact (Concept $s) (Evaluation (Predicate $r) (List (Concept $s) (Concept $found))) (stv $f $c) $src) ($found $f))))

; In DAS the Evaluation nested in a removed Belief stays as a link of its own
; and would be read back as a fact from another agent, so it is removed too;
; in a local space it is not a separate atom and the removal is a no-op.
(= (forget-value $s $r $v)
   (let $term (fact-term $s $r $v)
     (progn (map-atom (collapse (match &das (Belief $term $tv) $tv)) $tv (remove-atom &das (Belief $term $tv)))
            (map-atom (collapse (match &das (Stated $term $who $when) ($who $when))) $p
                      (let ($who $when) $p (remove-atom &das (Stated $term $who $when))))
            (map-atom (collapse (match &das (Fact $key $term $tv $src) ($key $tv $src))) $p
                      (let ($key $tv $src) $p (remove-atom &das (Fact $key $term $tv $src))))
            (catch (remove-atom &das $term)))))

; A value already believed at the same strength is KNOWN; one believed at the
; other strength is replaced, so "is not playing" after "is playing" leaves
; one fact, the newer, and the relation's other values stay.
(= (store-fact-as $s $r $v $tv $report)
   (let* (((stv $strength $confidence) $tv)
          ($truths (relation-truths $s $r)))
     (if (is-member ($v $strength) $truths)
         (KNOWN $s $r $v)
         (let* (($_ (if (is-member $v (relation-values $s $r)) (forget-value $s $r $v) ()))
                ($term (fact-term $s $r $v))
                ($who (sread (py-call (helper.speaker_literal (current-message)))))
                ($when (get_time_as_string))
                ($_ (add-atom &das (Belief $term $tv)))
                ($_ (add-atom &das (Stated $term $who $when)))
                ($_ (add-atom &das (Fact (Concept $s) $term $tv (Stated $who $when))))
                ($_ (if (== $s $v) () (add-atom &das (Fact (Concept $v) $term $tv (Stated $who $when))))))
           ($report $s $r $v)))))

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

; Concept names looked up per message besides the sender. Each name is one
; indexed query, plus scans when external facts are read, so this bounds the
; delay per message.
(= (maxFactConcepts) 3)

; Facts about $key and facts whose value is $key, as
; ("subject" "relation" "value" "who" "when" strength).
; Learned facts are read from the Fact records of $key, so each comes with its
; truth (1.0 stated, 0.0 denied) and its source, which answers "who told you
; that?" and "when?" with no further query. With dasExternalFacts the bare
; Evaluation form is read as well: that is what other agents on the same
; router write, with no source and taken as true, and also where beliefs
; derived by |- or |~ end up. Other agents keep the spelling of the user, so
; the key is tried as written in the message and in Title Case besides
; lowercase. A three-place record (subject, value, value) is read as one value.
; Both forms run every time, because a name may have facts from both sides
; ("team a" learned here and loaded by another agent); a learned fact's own
; nested Evaluation also answers the bare query, and merge_facts drops that
; copy in favour of the one with its source and truth.

; The learned facts naming $key, either side, from its Fact records: one indexed query.
(= (stated-facts-about $key)
   (collapse (match &das (Fact (Concept $key) (Evaluation (Predicate $r) (List (Concept $s) (Concept $v))) (stv $f $c) (Stated $who $when))
                    ($s $r $v $who $when $f))))

; The learned facts with $name as subject. The subject is bound in the nested
; term as well, which the query engine checks on the records the index returned.
(= (stated-facts-of $name)
   (collapse (match &das (Fact (Concept $name) (Evaluation (Predicate $r) (List (Concept $name) (Concept $v))) (stv $f $c) (Stated $who $when))
                    ($name $r $v $who $when $f))))

; Bare Evaluations are what other agents on the router write, with no Fact
; record. Reading them scans every Evaluation in every AtomDB, several times
; per name, so dasExternalFacts False skips it when only Omega agents write.
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

; The facts of one subject spelled as stored, as subject only: one indexed
; query, and two scans when external facts are read.
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

(= (without-denied $facts)
   (if (== $facts ())
       ()
       (let $subjects (sread (py-call (helper.fact_subjects (repr $facts))))
         (let $beliefs (query-failure (catch (subject-beliefs $subjects)))
           (sread (py-call (helper.drop_denied (repr $facts) (repr $beliefs))))))))

; Recall from the words of the message alone, used when no extraction reply is available.
(= (recall-facts $msg)
   (recall-facts-by-keys (sread (py-call (helper.fact_query_keys $msg (maxFactConcepts))))))
