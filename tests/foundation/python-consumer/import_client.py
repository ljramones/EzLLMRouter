"""Check an installed client from a separate, temporary consumer environment."""

import importlib.metadata
import json
import pathlib
import sys

import ezllmrouter_client

consumer = pathlib.Path(sys.argv[1]).resolve(strict=True)
resolved = pathlib.Path(ezllmrouter_client.__file__).resolve(strict=True)
assert resolved.is_relative_to(consumer / "lib"), resolved
assert ezllmrouter_client.__version__ == "0.3.0"
dist = importlib.metadata.distribution("cognitivedynamics-ezllmrouter-client")
assert dist.requires == ["httpx==0.28.1"], dist.requires
print(
    json.dumps(
        {
            "version": ezllmrouter_client.__version__,
            "resolved": str(resolved),
            "consumer": str(consumer),
            "python": sys.executable,
            "requires": dist.requires,
        }
    )
)
