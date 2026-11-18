"""Check an installed client from a separate, temporary consumer environment."""
import importlib.metadata
import json
import pathlib
import sys

import duranki_client

consumer = pathlib.Path(sys.argv[1]).resolve(strict=True)
resolved = pathlib.Path(duranki_client.__file__).resolve(strict=True)
assert resolved.is_relative_to(consumer / "lib"), resolved
assert duranki_client.__version__ == "0.0.0"
dist = importlib.metadata.distribution("mach33-duranki-client")
assert not dist.requires, dist.requires
print(json.dumps({"version": duranki_client.__version__, "resolved": str(resolved), "consumer": str(consumer), "python": sys.executable, "requires": dist.requires}))
