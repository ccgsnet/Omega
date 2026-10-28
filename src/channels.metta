;configured at runtime:
(= (commchannel) (empty))

;Connect all the channels:
(= (initChannels)
   (progn (log INFO "channels" "Initializing channels")
          (configure commchannel irc)
          (commChannelStart (commchannel))))

(= (commChannelStart $commchannel)
   (py-call (channels.commChannelStart $commchannel)))

(= (commChannelReceive)
   (py-call (channels.commChannelReceive)))

(= (commChannelSend $message)
   (py-call (channels.commChannelSend $message)))

;Receive the latest user message considering all communication channels:
(= (receive)
   (commChannelReceive))

;Send a message to all communication channels. The text is cleaned of the
;format noise small models leak into replies (escape markers, quotes around
;the whole answer, an appended skill call, the user's question repeated) and
;nothing is sent when nothing is left.
!(change-state! &lastsend "")
(= (send $msg)
   (let $reply (py-call (helper.clean_reply $msg (current-message)))
     (if (py-call (helper.is_set $reply))
         (if (!= $reply (get-state &lastsend))
             (progn (change-state! &lastsend $reply)
                    (let $safemsg (string-replace $reply "\n" "\\n")
                         (let $temp (cut) (commChannelSend $safemsg)))) _)
         (SEND_SKIPPED "empty reply"))))
