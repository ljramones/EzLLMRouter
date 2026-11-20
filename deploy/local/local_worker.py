"""Normal-stop restart wrapper for the unchanged isolated Choice B worker."""

from choice_b_wire import socket_path
from socket_lease import remove_stale_socket


if __name__ == "__main__":
    remove_stale_socket(socket_path("worker"))
    from choice_b_worker import main

    main()
