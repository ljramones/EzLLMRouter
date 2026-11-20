"""Normal-stop restart wrapper for the isolated worker."""

from .ipc import socket_path
from .socket_lease import remove_stale_socket


if __name__ == "__main__":
    remove_stale_socket(socket_path("worker"))
    from .worker import main

    main()
