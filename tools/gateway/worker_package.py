"""Build the isolated worker package from an explicit dependency-free helper list."""

from pathlib import Path
import shutil


def source_mapping() -> list[tuple[str, str]]:
    sources = {
        "__init__.py": "worker/ezllmrouter_worker/__init__.py",
        "__main__.py": "worker/ezllmrouter_worker/__main__.py",
        "worker.py": "worker/ezllmrouter_worker/worker.py",
        "ipc.py": "server/src/ezllmrouter_server/gateway/choice_b_wire.py",
        "resources.py": "server/src/ezllmrouter_server/runtime_resources.py",
        "connection_resources.py": "server/src/ezllmrouter_server/connection_resources.py",
        "execution_resources.py": "server/src/ezllmrouter_server/execution_resources.py",
        "observability.py": "server/src/ezllmrouter_server/observability.py",
        "execution_policy.py": "server/src/ezllmrouter_server/execution_policy.py",
        "socket_lease.py": "deploy/local/socket_lease.py",
    }
    return [(source, "worker/ezllmrouter_worker/" + name) for name, source in sources.items()]


def stage_worker(root: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    for source, target in source_mapping():
        shutil.copy2(root / source, destination / Path(target).name)
