"""Relink the unchanged published extension to exact-version minimal libpq."""

import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import zipfile

from tools.security_elf import inspect

root = Path.cwd()
out = root / ".artifacts/final-seven"
parent = json.loads((out / "driver-parent.json").read_text())
wheel = (
    root
    / ".artifacts/openssl-remediation/artifact-store/inputs/gateway-inputs/dev04/wheels"
    / parent["filename"]
)
assert hashlib.sha256(wheel.read_bytes()).hexdigest() == parent["sha256"]
work = out / "relink"
work.mkdir(exist_ok=False)
members = {}
old_exports = None
with zipfile.ZipFile(wheel) as archive:
    for entry in archive.infolist():
        path = Path(entry.filename)
        assert not path.is_absolute() and ".." not in path.parts
        assert stat.S_IFMT(entry.external_attr >> 16) != stat.S_IFLNK
        if not entry.is_dir():
            members[entry.filename] = archive.read(entry)
    old_exports = set(inspect(members["psycopg_binary.libs/libpq-53e4e5f8.so.5.18"])["exports"])
native_names = ["_psycopg.cpython-312-aarch64-linux-gnu.so", "pq.cpython-312-aarch64-linux-gnu.so"]
for name in native_names:
    (work / name).write_bytes(members["psycopg_binary/" + name])
script = """set -eu
dpkg -i /tools/debs/*.deb
for file in /io/*.so; do
 patchelf --replace-needed libpq-53e4e5f8.so.5.18 libpq-ezllmrouter1.so.5 "$file"
done
"""
(out / "relink-driver.sh").write_text(script)
base = json.loads((root / "deploy/local/inputs/os/debian13-arm64.lock.json").read_text())["bases"][
    "python"
]["config_sha256"]
subprocess.run(
    [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--network=none",
        "--user=0:0",
        "--security-opt=no-new-privileges:true",
        "--mount",
        "type=bind,source=" + str(out / "build-tools") + ",target=/tools,readonly",
        "--mount",
        "type=bind,source=" + str(work) + ",target=/io",
        "--mount",
        "type=bind,source=" + str(out / "relink-driver.sh") + ",target=/relink.sh,readonly",
        base,
        "sh",
        "/relink.sh",
    ],
    check=True,
    timeout=120,
)
pg = (out / "libpq-build/libpq-ezllmrouter1.so.5").read_bytes()
metadata = inspect(pg)
assert not old_exports - set(metadata["exports"]), sorted(old_exports - set(metadata["exports"]))
assert metadata["soname"] == "libpq-ezllmrouter1.so.5"
assert set(metadata["needed"]) <= {
    "libssl.so.3",
    "libcrypto.so.3",
    "libc.so.6",
    "libm.so.6",
    "ld-linux-aarch64.so.1",
}
assert not metadata["search_paths"]
new_info = "psycopg_binary-3.3.6+ezllmrouter1.dist-info/"
old_info = "psycopg_binary-3.3.6.dist-info/"
selected = {}
for name, raw in members.items():
    if name.startswith("psycopg_binary.libs/") or name.endswith("/RECORD"):
        continue
    if name.startswith(old_info):
        name = new_info + name[len(old_info) :]
    if name == new_info + "METADATA":
        text = raw.decode()
        assert "\nVersion: 3.3.6\n" in text
        raw = text.replace("\nVersion: 3.3.6\n", "\nVersion: 3.3.6+ezllmrouter1\n", 1).encode()
    elif name == new_info + "WHEEL":
        raw = b"Wheel-Version: 1.0\nGenerator: EzLLMRouter reviewed native relink\nRoot-Is-Purelib: false\nTag: cp312-cp312-linux_aarch64\n"
    elif name in {"psycopg_binary/" + entry for entry in native_names}:
        raw = (work / Path(name).name).read_bytes()
        elf = inspect(raw)
        assert elf["needed"] == ["libpq-ezllmrouter1.so.5", "libpthread.so.0", "libc.so.6"]
        assert not {symbol for symbol in elf["imports"] if symbol.startswith("PQ")} - set(
            metadata["exports"]
        )
    selected[name] = raw
selected["psycopg_binary.libs/libpq-ezllmrouter1.so.5"] = pg
selected[new_info + "licenses/POSTGRESQL-COPYRIGHT"] = (
    out / "libpq-build/source/postgresql-18.6/COPYRIGHT"
).read_bytes()
receipt = {
    "parent_wheel": parent,
    "libpq_version": "18.6",
    "gssapi": False,
    "ldap": False,
    "openssl": "shared reviewed OpenSSL 3.5.9+ezllmrouter1",
    "libpq_sha256": hashlib.sha256(pg).hexdigest(),
    "retained_libpq_exports": len(old_exports),
    "missing_exports": [],
    "removed_bundled_libraries": sorted(
        name for name in members if name.startswith("psycopg_binary.libs/")
    ),
}
selected[new_info + "EZLLMROUTER-NATIVE.json"] = (json.dumps(receipt, indent=2) + "\n").encode()
records = io.StringIO(newline="")
writer = csv.writer(records, lineterminator="\n")
for name, raw in sorted(selected.items()):
    writer.writerow(
        [
            name,
            "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip("="),
            len(raw),
        ]
    )
writer.writerow([new_info + "RECORD", "", ""])
selected[new_info + "RECORD"] = records.getvalue().encode()
target = out / "driver-wheel"
target.mkdir(exist_ok=False)
filename = "psycopg_binary-3.3.6+ezllmrouter1-cp312-cp312-linux_aarch64.whl"
with zipfile.ZipFile(target / filename, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for name, raw in sorted(selected.items()):
        entry = zipfile.ZipInfo(name, (2026, 11, 24, 0, 0, 0))
        entry.external_attr = (stat.S_IFREG | 0o644) << 16
        entry.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(entry, raw)
result = dict(
    parent,
    filename=filename,
    version="3.3.6+ezllmrouter1",
    bytes=(target / filename).stat().st_size,
    sha256=hashlib.sha256((target / filename).read_bytes()).hexdigest(),
)
(out / "driver-output.json").write_text(
    json.dumps(
        {
            "wheel": result,
            "receipt": receipt,
            "code": {
                name: hashlib.sha256(raw).hexdigest()
                for name, raw in selected.items()
                if name.endswith(".so") or ".so." in name
            },
        },
        indent=2,
    )
    + "\n"
)
print(
    json.dumps(
        {
            "wheel": result,
            "retained_libpq_exports": len(old_exports),
            "removed_bundled_libraries": len(receipt["removed_bundled_libraries"]),
        }
    )
)
