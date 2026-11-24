"""Replace the authenticated Debian libzstd payload with the reviewed source build."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

root = Path("/codec")
package = root / "package"
version = "1.6.0-0+ezllmrouter1"
subprocess.run(
    ["dpkg-deb", "--raw-extract", "/review/inputs/libzstd1_1.5.7+dfsg-1_arm64.deb", str(package)],
    check=True,
)
library = package / "usr/lib/aarch64-linux-gnu"
for path in library.glob("libzstd.so.*"):
    path.unlink()
shutil.copyfile(root / "source/zstd-1.6.0/lib/libzstd.so.1.6.0", library / "libzstd.so.1.6.0")
subprocess.run(["strip", str(library / "libzstd.so.1.6.0")], check=True)
(library / "libzstd.so.1").symlink_to("libzstd.so.1.6.0")
control = package / "DEBIAN/control"
text = re.sub(r"^Version:.*$", "Version: " + version, control.read_text(), flags=re.M)
text = re.sub(r"^Source:.*\n", "", text, flags=re.M)
text = "Source: libzstd (" + version + ")\n" + text
text = re.sub(r"^Maintainer:.*$", "Maintainer: EzLLMRouter maintainers", text, flags=re.M)
control.write_text(text)
document = package / "usr/share/doc/libzstd1"
for name in ("LICENSE", "COPYING"):
    shutil.copyfile(root / "source/zstd-1.6.0" / name, document / ("UPSTREAM-" + name))
(document / "EZLLMROUTER-SOURCE.json").write_text(
    json.dumps(
        {
            "version": "1.6.0",
            "source_sha256": "2ba599ae2a257976278e7e71e998433a387bfd18aa7b78678229fd5d84f5e9b8",
            "source": "https://github.com/meta/zstd/releases/tag/v1.6.0",
            "fixed": "CVE-2026-124851",
            "parent_version": "1.5.7+dfsg-1",
        },
        indent=2,
    )
    + "\n"
)
(package / "DEBIAN/md5sums").write_text(
    "".join(
        hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()
        + "  "
        + path.relative_to(package).as_posix()
        + "\n"
        for path in sorted(package.rglob("*"))
        if path.is_file()
        and not path.is_symlink()
        and "DEBIAN" not in path.relative_to(package).parts
    )
)
os.environ["SOURCE_DATE_EPOCH"] = "1795478400"
subprocess.run(
    [
        "dpkg-deb",
        "--root-owner-group",
        "--uniform-compression",
        "--threads-max=1",
        "-Zxz",
        "-z9",
        "--build",
        str(package),
        str(root / "outputs" / ("libzstd1_" + version + "_arm64.deb")),
    ],
    check=True,
)
