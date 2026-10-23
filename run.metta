!(import! &self (library lib_import))
!(git-import! "https://github.com/singnet/Omega.git")
!(import! &self (library Omega lib_omega))

!(bind! &das (new-das! (host.docker.internal:40009)))

!(omega)
