; Round trip against a running DAS Command Router. Set OMEGA_DAS_ROUTER, for
; example 127.0.0.1:40009, to run it; without it the file reports one skipped
; check so the test runner still sees a pass. Everything it writes is stored
; under the subject "omega-live-test" and removed again.
;
;   OMEGA_DAS_ROUTER=127.0.0.1:40009 sh $PETTA_PATH/run.sh ./tests/das_live.metta

!(import! &self ./tests/lib/utils)
!(import! &self ../src/helper.py)
!(import! &self ./src/utils)
!(import! &self ./lib_nal)
!(import! &self ./lib_pln)
!(import! &self ./src/das_memory)
!(import! &self ./src/skills)

(= (live-router) (py-call (helper.getenv "OMEGA_DAS_ROUTER" "")))
(= (live-das) (py-call (helper.is_set (live-router))))

!(if (live-das) (bind! &das (new-das! (live-router))) ())

; Recalled facts carry who stated them and when; the time is dropped for comparison.
(= (without-time $facts)
   (map-atom $facts $fact (let ($s $r $v $who $when $f) $fact ($s $r $v $who))))

(= (live-tests)
   (progn
     (change-state! &prevmsg "omega-live-test: I like tea")
     (test (das-health) True)
     (unlearn "I | likes") ; leftovers of an earlier run that stopped halfway
     (test (learn "I | likes | tea") (LEARNED "omega-live-test" "likes" "tea"))
     (test (learn "I | likes | tea") (KNOWN "omega-live-test" "likes" "tea"))
     (test (without-time (recall-facts-by-keys ("omega-live-test"))) (("omega-live-test" "likes" "tea" "omega-live-test")))
     (test (without-time (recall-facts-by-keys ("tea"))) (("omega-live-test" "likes" "tea" "omega-live-test")))
     (test (without-time (recall-facts-for "omega-live-test" ("tea"))) (("omega-live-test" "likes" "tea" "omega-live-test")))
     (test (collapse (match &das (Stated (Evaluation (Predicate "likes") (List (Concept "omega-live-test") (Concept "tea"))) $who $when) $who))
           ("omega-live-test"))
     (test (== (beliefs "(Evaluation (Predicate \"likes\") (List (Concept \"omega-live-test\") $1))")
               (sread "(((Evaluation (Predicate \"likes\") (List (Concept \"omega-live-test\") (Concept \"tea\"))) (stv 1.0 0.9)))"))
           True)
     (test (learn "I | likes | coffee") (LEARNED "omega-live-test" "likes" "coffee"))
     ; DAS returns matches in no fixed order.
     (test (let $facts (without-time (recall-facts-by-keys ("omega-live-test")))
             ((size-atom $facts)
              (is-member ("omega-live-test" "likes" "tea" "omega-live-test") $facts)
              (is-member ("omega-live-test" "likes" "coffee" "omega-live-test") $facts)))
           (2 True True))
     ; One conjunction over two values finds the subject related to both.
     (test (let $facts (conjunction-facts ("tea" "coffee"))
             ((size-atom $facts)
              (is-member ("omega-live-test" "likes" "tea" "" "" 1.0) $facts)
              (is-member ("omega-live-test" "likes" "coffee" "" "" 1.0) $facts)))
           (2 True True))
     (test (conjunction-facts ("tea" "no-such-value")) ())
     ; A denial replaces the stated value with the term believed false; the bare
     ; Evaluation still answers a conjunction, and the denial takes it out.
     (test (deny "I | likes | coffee") (DENIED "omega-live-test" "likes" "coffee"))
     (test (let $facts (recall-facts-by-keys ("omega-live-test"))
             ((size-atom $facts)
              (is-member ("omega-live-test" "likes" "tea" 1.0) (map-atom $facts $f (let ($s $r $v $who $when $t) $f ($s $r $v $t))))
              (is-member ("omega-live-test" "likes" "coffee" 0.0) (map-atom $facts $f (let ($s $r $v $who $when $t) $f ($s $r $v $t))))))
           (2 True True))
     (test (conjunction-facts ("tea" "coffee")) ())
     (test (learn "I | likes | coffee") (LEARNED "omega-live-test" "likes" "coffee"))
     (test (let (UNLEARNED $s $r $values) (unlearn "I | likes")
             ($s $r (size-atom $values) (is-member "tea" $values) (is-member "coffee" $values)))
           ("omega-live-test" "likes" 2 True True))
     (test (recall-facts-by-keys ("omega-live-test" "tea" "coffee")) ())
     (test (collapse (match &das (Stated (Evaluation (Predicate "likes") (List (Concept "omega-live-test") $v)) $who $when) $v)) ())))

!(if (live-das)
     (live-tests)
     (test "skipped: OMEGA_DAS_ROUTER is not set" "skipped: OMEGA_DAS_ROUTER is not set"))
