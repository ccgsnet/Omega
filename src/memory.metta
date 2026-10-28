;Configured at runtime memory and history in amount of characters:
(= (maxFeedback) (empty))
(= (maxRecallItems) (empty))
(= (maxEpisodeRecallLines) (empty))
(= (maxHistory) (empty))
(= (embeddingprovider) (empty))

(= (initMemory)
   (progn (log INFO "memory" "Initializing memory")
          (log INFO "memory" "Facts and beliefs are kept in the &das space, indexed for similarity in Chroma")
          (configure maxFeedback 50000)
          (configure maxRecallItems 20)
          (configure maxEpisodeRecallLines 20)
          (configure maxHistory 30000)
          (configure embeddingprovider Local) ;OpenAI, ASICloud or Local
          (if (== (embeddingprovider) Local)
              (py-call (lib_llm_ext.initLocalEmbedding)) _)))

(= (getPrompt $provider)
   (let $model_prompt
         (library Omega (py-str ("./memory/prompt_" $provider ".txt")))
     (if (exists-file $model_prompt)
         (read-file $model_prompt)
         (let $default_prompt ;Safely read the default prompt. Return an empty string if the file does not exist.
               (library Omega ./memory/prompt.txt)
           (if (exists-file $default_prompt)
               (read-file $default_prompt)
               "")))))

(= (getHistory)
   (let $history_file
         (library Omega ./memory/history.metta)
     (if (exists-file $history_file) ;Safely read the history. Return an empty string if the file does not exist.
         (read_file_tail $history_file (maxHistory))
         "")))

(= (addToHistory $lastmessage $response $sexpr $msgnew)
   (if $msgnew
       (if (== (get-state &error) ())
           (appendToHistory ((get_time_as_string) (newline) "HUMAN_MESSAGE: " $lastmessage (newline) $response (newline)))
           (appendToHistory ((get_time_as_string) (newline) "HUMAN_MESSAGE: " $lastmessage (newline) $response (newline) ERROR_FEEDBACK: (get-state &error))))
       (if (== (get-state &error) ())
           (appendToHistory ((get_time_as_string) (newline) $response (newline)))
           (appendToHistory ((get_time_as_string) (newline) $response (newline) ERROR_FEEDBACK: (get-state &error))))))

(= (embed $str)
   (if (== (embeddingprovider) Local)
       (py-call (lib_llm_ext.useLocalEmbedding (string-safe $str)))
       (py-call (rag.cloud_embed (string-safe $str)))))

(= (appendToHistory $addition)
   (append-file-raw (library Omega ./memory/history.metta) (swrite $addition)))

(= (remember $str)
   (progn (py-call (lib_chromadb.remember $str (embed $str) (get_time_as_string)))
          REMEMBER-SUCCESS))

(= (query $str)
   (py-call (lib_chromadb.query (embed $str) (maxRecallItems))))

; Chroma is the similarity index over the facts in DAS: a new fact is stored as
; the document "FACT subject | relation | value", and a message's nearest FACT
; documents give the subjects to query in DAS. DAS stays the source of truth,
; so a document whose fact was unlearned only costs one empty query. A denied
; fact is indexed the same way: the document only leads to the subject, and
; DAS holds the truth.
(= (index-fact $learned)
   (case $learned
     (((LEARNED $s $r $v) (index-fact-document $s $r $v))
      ((DENIED $s $r $v) (index-fact-document $s $r $v))
      ($other $other))))

(= (index-fact-document $s $r $v)
   (das-log-failure FACT_NOT_INDEXED
     (catch (let $doc (py-call (helper.fact_index_text $s $r $v))
              (progn (py-call (lib_chromadb.remember $doc (embed $doc) (get_time_as_string)))
                     (INDEXED $s $r $v))))))

(= (indexed-fact-keys $msg $limit)
   (case (catch (py-call (helper.indexed_fact_subjects (repr (query $msg)) $limit)))
     (((Error $type $ctx) (progn (log WARNING "memory" (FACT_INDEX_NOT_QUERIED $type)) "()"))
      ((Error $type) (progn (log WARNING "memory" (FACT_INDEX_NOT_QUERIED $type)) "()"))
      ($keys $keys))))

(= (episodes $time)
   (py-call (helper.around_time $time (maxEpisodeRecallLines))))
