!(import! &self (library lib_import))
!(git-import! "https://github.com/singnet/Omega.git")
!(import! &self (library Omega lib_omega))

; The DAS space is bound before the loop starts; dasRouter comes from the
; command line, OMEGA_dasRouter or config.yaml. Empty leaves &das local.
!(initConfig)
!(if (dasConfigured)
     (bind! &das (new-das! (dasEndpoint)))
     (log INFO "das-memory" "dasRouter is empty: &das is an in-process space"))

!(omega)
