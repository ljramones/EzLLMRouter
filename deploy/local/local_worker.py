"""Normal-stop restart wrapper for the unchanged isolated Choice B worker."""

from socket_lease import remove_stale_socket


if __name__ == "__main__":
    remove_stale_socket("/link/worker.sock")
    from choice_b_worker import main

    main()
