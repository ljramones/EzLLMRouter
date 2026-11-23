import hashlib, json, os, re, shutil, subprocess
from pathlib import Path

root = Path("/out")
records = json.loads(Path("/sources/openssl-parent-packages.json").read_text())
version = "3.5.9-1~deb13u1+ezllmrouter1"
target = root / "packages"
target.mkdir(exist_ok=False)
replacements = {
    "libssl3t64": {
        "libcrypto.so.3": "usr/lib/aarch64-linux-gnu/libcrypto.so.3",
        "libssl.so.3": "usr/lib/aarch64-linux-gnu/libssl.so.3",
    },
    "openssl-provider-legacy": {
        "providers/legacy.so": "usr/lib/aarch64-linux-gnu/ossl-modules/legacy.so"
    },
    "openssl": {"apps/openssl": "usr/bin/openssl"},
}
receipt = {
    "source": "openssl 3.5.9 Debian 3.5.9-1~deb13u1 plus reviewed upstream security patches",
    "patches": json.loads(Path("/sources/patch-provenance.json").read_text()),
    "dane_complete_diff_sha256": hashlib.sha256(
        Path("/sources/dane-complete.diff").read_bytes()
    ).hexdigest(),
    "dane_status": "Locally reviewed backport from open upstream PR 33634; complete diff includes its regression test",
    "security_regression_recipes": 13,
    "security_regression_tests": 601,
}
outputs = []
os.environ["SOURCE_DATE_EPOCH"] = "1795392000"
for row in records:
    name = row["package"]
    package = target / name
    subprocess.run(
        ["dpkg-deb", "--raw-extract", str(Path("/original") / row["filename"]), str(package)],
        check=True,
    )
    for source, destination in replacements[name].items():
        shutil.copyfile(root / "openssl-build" / source, package / destination)
    control = package / "DEBIAN/control"
    text = control.read_text()
    text = re.sub(r"^Version:.*$", "Version: " + version, text, flags=re.M)
    text = re.sub(r"^Source:.*\n", "", text, flags=re.M)
    text = "Source: openssl (" + version + ")\n" + text
    text = re.sub(r"^Maintainer:.*$", "Maintainer: EzLLMRouter maintainers", text, flags=re.M)
    control.write_text(text)
    document = package / "usr/share/doc" / name / "EZLLMROUTER-BACKPORT.json"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(json.dumps(receipt, indent=2) + "\n")
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
    filename = name + "_" + version + "_arm64.deb"
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
            str(target / filename),
        ],
        check=True,
    )
    output = dict(
        row,
        version=version,
        source_version=version,
        filename=filename,
        bytes=(target / filename).stat().st_size,
        sha256=hashlib.sha256((target / filename).read_bytes()).hexdigest(),
    )
    output["parent_url"] = output.pop("url")
    output["parent_sha256"] = row["sha256"]
    outputs.append(output)
(target / "packages.json").write_text(json.dumps(outputs, indent=2) + "\n")
