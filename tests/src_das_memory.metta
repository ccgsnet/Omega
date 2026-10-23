!(import! &self ./tests/lib/utils)
!(import! &self ../src/helper.py)
!(import! &self ./src/utils)
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

!(test (learn "I | favorite_color | purple")
       (LEARNED "arturgontijo" favorite_color "purple"))

!(test (recall-facts "arturgontijo: what is my favorite color?")
       (("arturgontijo" favorite_color "purple")))

!(test (progn
         (learn "I | favorite_color | dark blue")
         (learn "I | favorite | food pizza")
         (recall-facts "bob: which color does arturgontijo like?"))
       (("arturgontijo" favorite_color "dark blue") ("arturgontijo" favorite "food pizza")))

!(test (collapse (match &das (Evaluation (Predicate (favorite_color "purple")) $c) $c))
       ())

!(test (progn
         (unlearn "I | favorite_color")
         (recall-facts "arturgontijo: what is my favorite color?"))
       (("arturgontijo" favorite "food pizza")))

!(test (progn
         (learn "France | capital | Paris")
         (recall-facts "bob: what is the capital of France?"))
       (("france" capital "paris")))

!(test (learn "purple")
       (FACT_NOT_LEARNED "expected one short fact: subject | relation | value" "purple"))

!(test (progn
         (learn "The capital of Brazil has more than one million people actual")
         (collapse (match &das (Evaluation (Predicate $p) (Concept "the")) $p)))
       ())

!(test (progn
         (learn-all "FACT I | favorite_color | blue, FACT I | favorite_food | pasta")
         (recall-facts "arturgontijo: what are my favorites?"))
       (("arturgontijo" favorite "food pizza") ("arturgontijo" favorite_color "blue") ("arturgontijo" favorite_food "pasta")))

!(test (learn-all "NONE")
       ())

!(test (progn
         (learn-all "FACT Brazil | capital | Brasília")
         (recall-facts "ana: what is the capital of Brazil?"))
       (("brazil" capital "brasília")))

; py-call returns Python text as an atom, so the expected text is converted the same way.
!(test (== (describe-facts (recall-facts "arturgontijo: what is my favorite color?") "arturgontijo: what is my favorite color?")
           (py-call (helper.normalize_string "your favorite is food pizza; your favorite color is blue; your favorite food is pasta.")))
       True)
