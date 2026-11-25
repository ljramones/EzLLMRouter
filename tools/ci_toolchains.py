"""Install only the exact, hash-verified Java/.NET archives reviewed for CI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import tempfile
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, build_opener
import zipfile

ROOT = Path(__file__).resolve().parents[1]
POLICY = ".github/toolchain-inputs.json"
PLATFORMS = {"Linux-X64", "macOS-ARM64", "Windows-X64"}
HOSTS = {
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
    "builds.dotnet.microsoft.com",
}
MAX_ARCHIVE = 1024**3
MAX_EXPANDED = 4 * 1024**3


def artifact_identity(name: str, version: str, platform: str) -> tuple[str, str, str]:
    if name == "java":
        arch, system, extension = {
            "Linux-X64": ("x64", "linux", "tar.gz"),
            "macOS-ARM64": ("aarch64", "mac", "tar.gz"),
            "Windows-X64": ("x64", "windows", "zip"),
        }[platform]
        filename = f"OpenJDK17U-jdk_{arch}_{system}_hotspot_{version.replace('+', '_')}.{extension}"
        url = (
            "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-"
            + quote(version, safe="")
            + "/"
            + filename
        )
        home = "jdk-" + version + ("/Contents/Home" if system == "mac" else "")
    else:
        rid, extension = {
            "Linux-X64": ("linux-x64", "tar.gz"),
            "macOS-ARM64": ("osx-arm64", "tar.gz"),
            "Windows-X64": ("win-x64", "zip"),
        }[platform]
        filename = f"dotnet-sdk-{version}-{rid}.{extension}"
        url = f"https://builds.dotnet.microsoft.com/dotnet/Sdk/{version}/{filename}"
        home = "."
    return filename, url, home


def https_url(value: str) -> str:
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or url.hostname not in HOSTS
        or url.username
        or url.password
        or url.port not in (None, 443)
        or url.fragment
    ):
        raise ValueError("toolchain URL must use an approved HTTPS publisher")
    return value


class PublisherRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, https_url(newurl))


def relative_name(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
        raise ValueError("toolchain archive path escapes its installation")
    return path


def load_policy(root: Path = ROOT) -> dict:
    policy = json.loads((root / POLICY).read_text())
    if policy["format_version"] != 1:
        raise ValueError("unsupported CI toolchain policy")
    for name, algorithm, width in (("java", "sha256", 64), ("dotnet", "sha512", 128)):
        tool = policy[name]
        pattern = r"17\.\d+\.\d+(?:\.\d+)?\+\d+" if name == "java" else r"10\.0\.\d{3}"
        if not re.fullmatch(pattern, tool["version"]) or set(tool["artifacts"]) != PLATFORMS:
            raise ValueError("toolchain needs an exact version and all reviewed CI platforms")
        if not re.fullmatch("[0-9a-f]{64}", tool["metadata_sha256"]):
            raise ValueError("toolchain publisher metadata identity is missing")
        for platform, artifact in tool["artifacts"].items():
            https_url(artifact["url"])
            filename = artifact["filename"]
            if (
                (filename, artifact["url"], artifact["home"])
                != artifact_identity(name, tool["version"], platform)
                or set(artifact) & {"sha256", "sha512"} != {algorithm}
                or not re.fullmatch("[0-9a-f]{" + str(width) + "}", artifact[algorithm])
            ):
                raise ValueError("unreviewed CI toolchain archive identity")
            relative_name(artifact["home"])
    return policy


def verify_archive(path: Path, artifact: dict) -> None:
    algorithms = set(artifact) & {"sha256", "sha512"}
    if len(algorithms) != 1:
        raise ValueError("toolchain archive needs one unambiguous reviewed digest")
    algorithm = algorithms.pop()
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ARCHIVE:
        raise ValueError("invalid toolchain archive")
    with path.open("rb") as stream:
        observed = hashlib.file_digest(stream, algorithm).hexdigest()
    if observed != artifact[algorithm]:
        raise ValueError("toolchain archive hash differs from reviewed publisher identity")


def download(artifact: dict, path: Path) -> None:
    opener = build_opener(PublisherRedirect())
    with opener.open(https_url(artifact["url"]), timeout=60) as response, path.open("xb") as out:
        https_url(response.url)
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_ARCHIVE:
                raise ValueError("toolchain archive exceeds download bound")
            out.write(chunk)


def extract_archive(path: Path, destination: Path) -> None:
    destination.mkdir()
    if path.name.endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > 100_000 or sum(m.file_size for m in members) > MAX_EXPANDED:
                raise ValueError("toolchain archive exceeds extraction bounds")
            for member in members:
                target = destination / relative_name(member.filename)
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError("symbolic links are not permitted in Windows archives")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
    else:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            if len(members) > 100_000 or sum(m.size for m in members) > MAX_EXPANDED:
                raise ValueError("toolchain archive exceeds extraction bounds")
            for member in members:
                relative_name(member.name)
                if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                    raise ValueError("special files are not permitted in toolchain archives")
            archive.extractall(destination, members=members, filter="data")


def install(name: str, policy: dict, platform: str, temporary: Path, archive: Path | None) -> Path:
    tool = policy[name]
    artifact = tool["artifacts"][platform]
    stage = Path(tempfile.mkdtemp(prefix="ezllmrouter-" + name + "-", dir=temporary))
    try:
        if archive is None:
            archive = stage / artifact["filename"]
            download(artifact, archive)
        verify_archive(archive, artifact)
        payload = stage / "payload"
        extract_archive(archive, payload)
        home = payload / artifact["home"]
        executable = home / ("bin/java" if name == "java" else "dotnet")
        if platform == "Windows-X64":
            executable = executable.with_suffix(".exe")
        if not executable.is_file() or not executable.resolve().is_relative_to(payload.resolve()):
            raise ValueError("verified archive does not contain the expected toolchain")
        return home.resolve()
    except BaseException:
        shutil.rmtree(stage)
        raise


def export_environment(name: str, home: Path) -> dict[str, str]:
    values = (
        {"JAVA_HOME": str(home)}
        if name == "java"
        else {
            "DOTNET_ROOT": str(home),
            "DOTNET_MULTILEVEL_LOOKUP": "0",
            "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
            "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        }
    )
    binary_dir = home / "bin" if name == "java" else home
    if any("\n" in value or "\r" in value for value in (*values.values(), str(binary_dir))):
        raise ValueError("invalid CI environment path")
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as output:
        output.write("".join(f"{key}={value}\n" for key, value in values.items()))
    with Path(os.environ["GITHUB_PATH"]).open("a", encoding="utf-8") as output:
        output.write(str(binary_dir) + "\n")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", choices=("java", "dotnet"))
    parser.add_argument("--archive", type=Path, help="verify an already downloaded archive")
    args = parser.parse_args()
    platform = os.environ["RUNNER_OS"] + "-" + os.environ["RUNNER_ARCH"]
    policy = load_policy()
    if platform not in PLATFORMS:
        parser.error("unreviewed CI runner platform: " + platform)
    home = install(args.tool, policy, platform, Path(os.environ["RUNNER_TEMP"]), args.archive)
    export_environment(args.tool, home)
    print(
        json.dumps(
            {
                "tool": args.tool,
                "version": policy[args.tool]["version"],
                "platform": platform,
                "home": str(home),
                "artifact": policy[args.tool]["artifacts"][platform],
            }
        )
    )


if __name__ == "__main__":
    main()
