!(import! &self ./tests/lib/utils)
!(import! &self ../src/helper.py)
!(import! &self ./src/utils)
!(import! &self ../src/config.py)
!(import! &self ./src/config)
!(import! &self ./lib_nal)
!(import! &self ./lib_pln)
!(import! &self ./src/das_memory)
!(import! &self ./src/skills)

; &das is not bound here, so it is a local space with the same add/match/remove calls.

!(test (progn
         (das-store "(Similarity \"human\" \"mammal\")")
         (das-recall "(Similarity \"human\" $1)"))
       ((Similarity "human" "mammal")))

!(test (progn
         (das-forget "(Similarity \"human\" \"mammal\")")
         (das-recall "(Similarity \"human\" $1)"))
       ())

; An atom with a variable has crashed the router's HTTP server, and a ground
; query is rejected by it, so the skills refuse both before any call.
!(test (das-store "(Similarity \"human\" $1)")
       (DAS_STORE_REJECTED "an atom with variables cannot be stored" (Similarity "human" $1)))
!(test (das-forget "(Similarity $1 \"mammal\")")
       (DAS_FORGET_REJECTED "an atom with variables cannot be removed" (Similarity $1 "mammal")))
!(test (das-recall "(Similarity \"human\" \"mammal\")")
       (DAS_RECALL_REJECTED "a query needs a variable such as $1; to check one fact match it as a belief: beliefs <fact>" (Similarity "human" "mammal")))
!(test (das-health) True)

!(test (progn
         (believe "((--> garfield cat) (stv 1.0 0.9))")
         (believe "((--> garfield cat) (stv 1.0 0.9))")
         (beliefs "(--> garfield $1)"))
       (((--> garfield cat) (stv 1.0 0.9))))

!(test (let $expected (Truth_Revision (stv 1.0 0.9) (stv 0.0 0.9))
         (progn
           (believe "((--> tweety flyer) (stv 1.0 0.9))")
           (believe "((--> tweety flyer) (stv 0.0 0.9))")
           (== (beliefs "(--> tweety flyer)") (((--> tweety flyer) $expected)))))
       True)

!(test (progn
         (believe "((==> (--> $1 bird) (--> $1 flyer)) (stv 1.0 0.9))")
         (beliefs "(==> $1 $2)"))
       ())

!(test (progn
         (metta "(|- ((--> sam cat) (stv 1.0 0.9)) ((--> cat animal) (stv 1.0 0.9)))")
         (beliefs "(--> sam animal)"))
       (((--> sam animal) (stv 1.0 0.81))))

!(test (== (collapse (superpose ((beliefs "(--> sam cat)") (beliefs "(--> cat animal)") (beliefs "(--> animal sam)"))))
           (collapse (superpose ((((--> sam cat) (stv 1.0 0.9)))
                                 (((--> cat animal) (stv 1.0 0.9)))
                                 (((--> animal sam) (stv 1.0 0.44751381215469616)))))))
       True)

!(test (progn
         (metta "(|~ ((Implication (Inheritance $1 (IntSet Feathered)) (Inheritance $1 Bird)) (stv 1.0 0.9)) ((Inheritance Pingu (IntSet Feathered)) (stv 1.0 0.9)))")
         (beliefs "(Inheritance Pingu Bird)"))
       (((Inheritance Pingu Bird) (stv 1.0 0.81))))

!(test (metta "(+ 1 2)")
       (repr (swrite 3)))

!(test (metta "(car-atom (a b))")
       (repr (swrite a)))

!(change-state! &prevmsg "arturgontijo: My favorite color is purple")

; Recalled facts carry who stated them and when; the time is dropped for comparison.
(= (without-time $facts)
   (map-atom $facts $fact (let ($s $r $v $who $when $f) $fact ($s $r $v $who))))

!(test (learn "I | favorite_color | purple")
       (LEARNED "arturgontijo" "favorite_color" "purple"))

!(test (without-time (recall-facts "arturgontijo: what is my favorite color?"))
       (("arturgontijo" "favorite_color" "purple" "arturgontijo")))

; A second value for the same relation is added beside the first: nothing is
; forgotten without unlearn.
!(test (progn
         (learn "I | favorite_color | dark blue")
         (learn "I | favorite | food pizza")
         (without-time (recall-facts "bob: which color does arturgontijo like?")))
       (("arturgontijo" "favorite_color" "purple" "arturgontijo") ("arturgontijo" "favorite_color" "dark blue" "arturgontijo") ("arturgontijo" "favorite" "food pizza" "arturgontijo")))
!(test (collapse (match &das (Stated (Evaluation (Predicate "favorite_color") (List (Concept "arturgontijo") (Concept "purple"))) $who $when) $who))
       ("arturgontijo"))

; A fact already stored is reported as known, not stored twice.
!(test (learn "I | favorite_color | dark blue")
       (KNOWN "arturgontijo" "favorite_color" "dark blue"))
!(test (collapse (match &das (Belief (Evaluation (Predicate "favorite_color") (List (Concept "arturgontijo") (Concept "dark blue"))) $tv) $tv))
       ((stv 1.0 0.9)))

; A fact is a belief in the lib_pln binary form. Predicate is a PeTTa builtin,
; so the expected atom is parsed rather than written in the test.
!(test (== (beliefs "(Evaluation (Predicate \"favorite_color\") (List (Concept \"arturgontijo\") (Concept \"dark blue\")))")
           (sread "(((Evaluation (Predicate \"favorite_color\") (List (Concept \"arturgontijo\") (Concept \"dark blue\"))) (stv 1.0 0.9)))"))
       True)

; Facts are also found through their value, except for the sender, who is a subject only.
!(test (without-time (recall-facts-by-keys ("dark blue")))
       (("arturgontijo" "favorite_color" "dark blue" "arturgontijo")))
!(test (without-time (recall-facts-for "arturgontijo" ("dark blue")))
       (("arturgontijo" "favorite_color" "purple" "arturgontijo") ("arturgontijo" "favorite_color" "dark blue" "arturgontijo") ("arturgontijo" "favorite" "food pizza" "arturgontijo")))
!(test (recall-facts-for "dark blue" ())
       ())

; unlearn removes every value of the relation, with their provenance.
!(test (progn
         (unlearn "I | favorite_color")
         (without-time (recall-facts "arturgontijo: what is my favorite color?")))
       (("arturgontijo" "favorite" "food pizza" "arturgontijo")))
!(test (collapse (match &das (Stated (Evaluation (Predicate "favorite_color") (List (Concept "arturgontijo") $v)) $who $when) $v))
       ())

; "is similar to" and "similar to" are one relation, and both values are kept.
!(test (progn
         (learn "human | is similar to | monkey")
         (learn "human | similar to | chimp")
         (without-time (recall-facts-by-keys ("human"))))
       (("human" "similar_to" "monkey" "arturgontijo") ("human" "similar_to" "chimp" "arturgontijo")))

; Facts written by other agents are bare Evaluations with the user's spelling
; and no source. They are recalled when no Stated fact names the key, with the
; key as written in the message, and a three-place record reads as one value.
!(change-state! &prevmsg "ana: What do you know about Team B?")
!(test (progn
         (das-store "(Evaluation (Predicate \"jersey_color\") (List (Concept \"Team B\") (Concept \"red\")))")
         (das-store "(Evaluation (Predicate \"championship_victories\") (List (Concept \"Team B\") (Concept \"2022\") (Concept \"17\")))")
         (das-store "(Evaluation (Predicate \"founded_in\") (List (Concept \"Team C\") (Concept \"Divinópolis\")))")
         (recall-facts-by-keys ("team b")))
       (("Team B" "jersey_color" "red" "" "" 1.0) ("Team B" "championship_victories" "2022 17" "" "" 1.0)))
!(test (recall-facts-by-keys ("divinópolis"))
       (("Team C" "founded_in" "Divinópolis" "" "" 1.0)))
!(test (== (describe-facts (recall-facts-by-keys ("team b")) "ana: What do you know about Team B?")
           (py-call (helper.normalize_string "Team B's jersey color is red; Team B's championship victories is 2022 17.")))
       True)
; A name with facts learned here and facts loaded by another agent gives both:
; the learned one with its source, the others without.
!(test (progn
         (learn "Team B | supporters | 90000")
         (without-time (recall-facts-by-keys ("team b"))))
       (("team b" "supporters" "90000" "ana") ("Team B" "jersey_color" "red" "") ("Team B" "championship_victories" "2022 17" "")))
!(change-state! &prevmsg "arturgontijo: My favorite color is purple")

; AND and OR queries over facts through the metta skill, as the skill hints show them.
!(test (progn
         (learn "monkey | inherits from | mammal")
         (learn "chimp | inherits from | mammal")
         (learn "human | similar to | ent")
         (learn "ent | inherits from | plant")
         (metta "(collapse (match &das (, (Belief (Evaluation (Predicate \"similar_to\") (List (Concept \"human\") (Concept $x))) $t1) (Belief (Evaluation (Predicate \"inherits_from\") (List (Concept $x) (Concept \"mammal\"))) $t2)) $x))"))
       (repr (swrite ("monkey" "chimp"))))
!(test (metta "(unique-atom (collapse (superpose ((match &das (Belief (Evaluation (Predicate \"inherits_from\") (List (Concept $x) (Concept \"mammal\"))) $t) $x) (match &das (Belief (Evaluation (Predicate \"inherits_from\") (List (Concept $x) (Concept \"plant\"))) $t) $x)))))")
       (repr (swrite ("monkey" "chimp" "ent"))))

; A question joining conditions with and is answered by one conjunction over
; its values, whatever the relations, with the value as spelled in the message
; tried too. A third value narrows the subjects further, and no subject means
; no facts. The conjunction matches bare Evaluations: in DAS the Evaluation
; inside every learned Belief is a link of its own, so learned facts are found
; as well; this local space has no nested links, so the bare forms are stored.
!(change-state! &prevmsg "ana: Who is similar to a monkey and to a chimp?")
!(test (progn
         (das-store "(Evaluation (Predicate \"similar_to\") (List (Concept \"human\") (Concept \"monkey\")))")
         (das-store "(Evaluation (Predicate \"similar_to\") (List (Concept \"human\") (Concept \"chimp\")))")
         (das-store "(Evaluation (Predicate \"inherits_from\") (List (Concept \"monkey\") (Concept \"mammal\")))")
         (das-store "(Evaluation (Predicate \"inherits_from\") (List (Concept \"chimp\") (Concept \"mammal\")))")
         (conjunction-facts (sread (py-call (helper.extracted_conjunction "LOOKUP monkey\nALL monkey | chimp" (current-message))))))
       (("human" "similar_to" "monkey" "" "" 1.0) ("human" "similar_to" "chimp" "" "" 1.0)))
!(test (conjunction-facts ("mammal" "chimp")) ())
!(test (progn
         (das-store "(Evaluation (Predicate \"similar_to\") (List (Concept \"monkey\") (Concept \"Human\")))")
         (change-state! &prevmsg "ana: Who inherits from mammal and is similar to Human?")
         (conjunction-facts ("mammal" "human")))
       (("monkey" "inherits_from" "mammal" "" "" 1.0) ("monkey" "similar_to" "Human" "" "" 1.0)))
!(test (progn
         (das-store "(Evaluation (Predicate \"lives_in\") (List (Concept \"monkey\") (Concept \"jungle\")))")
         (conjunction-facts ("mammal" "human" "jungle")))
       (("monkey" "inherits_from" "mammal" "" "" 1.0) ("monkey" "similar_to" "Human" "" "" 1.0) ("monkey" "lives_in" "jungle" "" "" 1.0)))
!(test (conjunction-facts ("mammal" "human" "sea")) ())
!(test (conjunction-facts ()) ())
!(change-state! &prevmsg "arturgontijo: My favorite color is purple")

; A fact stated by another user is recalled with that user as its source.
!(change-state! &prevmsg "bob: The capital of France is Paris")
!(test (progn
         (learn "France | capital | Paris")
         (without-time (recall-facts "ana: what is the capital of France?")))
       (("france" "capital" "paris" "bob")))
!(change-state! &prevmsg "arturgontijo: My favorite color is purple")

; A learned fact is a |~ premise when taken from beliefs: "likes fruit" and
; "banana is a fruit" give "likes banana".
!(test (progn
         (learn "I | likes | fruit")
         (believe "((Inheritance (Concept \"banana\") (Concept \"fruit\")) (stv 1.0 0.9))")
         (== (let ($p) (beliefs "(Evaluation (Predicate \"likes\") (List (Concept \"arturgontijo\") $1))")
               (let ($q) (beliefs "(Inheritance (Concept \"banana\") $1)")
                 (|~ $p $q)))
             (sread "(((Evaluation (Predicate \"likes\") (List (Concept \"arturgontijo\") (Concept \"banana\"))) (stv 1.0 0.81)))")))
       True)

!(test (learn "purple")
       (FACT_NOT_LEARNED "expected one short fact: subject | relation | value" "purple"))

!(test (progn
         (learn "The capital of Brazil has more than one million people actual")
         (recall-facts-by-keys ("the")))
       ())

!(test (progn
         (learn-all "FACT I | favorite_color | blue, FACT I | favorite_food | pasta")
         (without-time (recall-facts "arturgontijo: what are my favorites?")))
       (("arturgontijo" "favorite" "food pizza" "arturgontijo") ("arturgontijo" "likes" "fruit" "arturgontijo")
        ("arturgontijo" "favorite_color" "blue" "arturgontijo") ("arturgontijo" "favorite_food" "pasta" "arturgontijo")))

!(test (learn-all "NONE")
       ())

; A denied fact is the same term believed false, with its source. Denying a
; stated value replaces it and leaves the relation's other values; stating it
; again replaces the denial. Recall reads the denial as "is not", and the
; conjunction does not count a denied fact as meeting its condition.
!(change-state! &prevmsg "bob: Team B is not playing the 2026 championship.")
!(test (learn-all "FACT Team A | is playing | 2026 championship\nNOT Team B | is playing | 2026 championship")
       ((LEARNED "team a" "is_playing" "2026 championship") (DENIED "team b" "is_playing" "2026 championship")))
!(test (deny "Team B | is playing | 2026 championship")
       (KNOWN "team b" "is_playing" "2026 championship"))
!(test (== (beliefs "(Evaluation (Predicate \"is_playing\") (List (Concept \"team b\") $1))")
           (sread "(((Evaluation (Predicate \"is_playing\") (List (Concept \"team b\") (Concept \"2026 championship\"))) (stv 0.0 0.9)))"))
       True)
!(test (map-atom (recall-facts-by-keys ("2026 championship")) $fact (let ($s $r $v $who $when $f) $fact ($s $v $f)))
       (("team a" "2026 championship" 1.0) ("team b" "2026 championship" 0.0)))
!(test (== (describe-facts (("team b" "is_playing" "2026 championship" "bob" "" 0.0)) "bob: Is Team B playing the 2026 championship?")
           (py-call (helper.normalize_string "team b is not playing 2026 championship (said by you).")))
       True)
!(test (progn
         (learn "Team B | is playing | 2027 championship")
         (learn "Team B | is playing | 2026 championship")
         (relation-truths "team b" "is_playing"))
       (("2027 championship" 1.0) ("2026 championship" 1.0)))
!(test (progn
         (deny "Team B | is playing | 2026 championship")
         (relation-truths "team b" "is_playing"))
       (("2027 championship" 1.0) ("2026 championship" 0.0)))
!(test (progn
         (das-store "(Evaluation (Predicate \"is_playing\") (List (Concept \"team b\") (Concept \"2026 championship\")))")
         (das-store "(Evaluation (Predicate \"is_playing\") (List (Concept \"team b\") (Concept \"2027 championship\")))")
         (das-store "(Evaluation (Predicate \"jersey_color\") (List (Concept \"team b\") (Concept \"red\")))")
         (conjunction-facts ("red" "2026 championship")))
       ())
!(test (conjunction-facts ("red" "2027 championship"))
       (("team b" "jersey_color" "red" "" "" 1.0) ("team b" "is_playing" "2027 championship" "" "" 1.0)))

; A fact found from its value side names a subject the message did not; the
; rest of that subject's facts are read, as stored and lowercase, and subjects
; that were keys or the sender are not read again.
!(change-state! &prevmsg "arturgontijo: Which team has its logo blue and is from Brasília?")
!(test (progn
         (das-store "(Evaluation (Predicate \"founded_in\") (List (Concept \"Team A\") (Concept \"Brasília\")))")
         (das-store "(Evaluation (Predicate \"logo_color\") (List (Concept \"Team A\") (Concept \"blue\")))")
         (learn "Team A | coach | Ana")
         (let $facts (recall-facts-by-keys ("logo" "brasília"))
           (let $more (expand-subjects $facts ("logo" "brasília") "arturgontijo")
             ($facts (sread (py-call (helper.new_subjects (repr $facts) (repr ("logo" "brasília")) "arturgontijo" 3)))
                     (without-time $more)))))
       ((("Team A" "founded_in" "Brasília" "" "" 1.0))
        ("Team A" "team a")
        (("Team A" "founded_in" "Brasília" "") ("Team A" "logo_color" "blue" "")
         ("team a" "is_playing" "2026 championship" "bob") ("team a" "coach" "ana" "arturgontijo"))))
!(test (expand-subjects (("Team A" "founded_in" "Brasília" "" "" 1.0) ("arturgontijo" "likes" "tea" "arturgontijo" "" 1.0))
                        ("team a") "arturgontijo")
       ())
!(test (== (describe-facts (sread (py-call (helper.merge_facts (repr (("Team A" "founded_in" "Brasília" "" "" 1.0)
                                                                       ("Team A" "founded_in" "Brasília" "" "" 1.0)
                                                                       ("Team A" "logo_color" "blue" "" "" 1.0))))))
                           (current-message))
           (py-call (helper.normalize_string "Team A's founded in is Brasília; Team A's logo color is blue.")))
       True)
!(unlearn "Team A | coach")
!(change-state! &prevmsg "arturgontijo: My favorite color is purple")

!(test (progn
         (learn-all "FACT Brazil | capital | Brasília")
         (without-time (recall-facts "ana: what is the capital of Brazil?")))
       (("brazil" "capital" "brasília" "arturgontijo")))

; The description names the source of each fact, so "who told you?" has an answer.
; py-call returns Python text as an atom, so the expected text is converted the same way.
!(test (== (describe-facts (("arturgontijo" "favorite_color" "blue" "arturgontijo" "2026-10-23 13:38:48")
                            ("brazil" "capital" "brasília" "ana" "2026-10-23 13:39:00"))
                           "arturgontijo: what is my favorite color?")
           (py-call (helper.normalize_string "brazil's capital is brasília (said by ana on 2026-10-23 13:39:00); your favorite color is blue (said by you on 2026-10-23 13:38:48).")))
       True)
