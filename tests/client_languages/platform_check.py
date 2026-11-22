"""Build current packages and exercise fresh consumers on macOS and Windows.

This is current-source qualification, not released-version skew or Windows service support.
Run in the locked development environment with Node/TypeScript, Go, JDK, .NET and Rust.
Only the owned HTTP fixture binds sockets; no provider or deployed service is used.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.client_languages.check_javascript import npm_command


def run(argv, *, cwd=ROOT, env=None, capture=False):
    print("Running:", " ".join(map(str, argv)), flush=True)
    result = subprocess.run(
        list(map(str, argv)),
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        timeout=600,
    )
    return result.stdout


def jdk(tool, arguments):
    # JDK 17 Windows launchers can replace non-ACP command-line characters with '?'.
    # A UTF-8 argument file carries the actual Unicode paths into the Java tool.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="jdk-",
        suffix=".args",
        dir=ROOT / ".artifacts",
        delete=False,
    ) as stream:
        path = Path(stream.name)
        stream.write("\n".join(json.dumps(str(value), ensure_ascii=False) for value in arguments))
    try:
        option = "-Dfile.encoding=UTF-8" if tool == "java" else "-J-Dfile.encoding=UTF-8"
        run([tool, option, "@" + str(path)])
    finally:
        path.unlink()


def python_client(consumer):
    run(["uv", "build", "--offline", "--wheel", "--out-dir", consumer, ROOT / "clients/python"])
    wheels = list(consumer.glob("*.whl"))
    if len(wheels) != 1:
        raise AssertionError("exactly one current Python client wheel required")
    library = consumer / "lib"
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            sys.executable,
            "--target",
            library,
            "--no-index",
            "--no-deps",
            wheels[0],
        ]
    )
    # Fresh client package; its HTTPX/HTTPcore dependencies come from the locked dev env.
    code = """
import json, pathlib, runpy, sys, unittest
sys.path.insert(0, sys.argv[1])
sys.path.insert(1, sys.argv[2])
runpy.run_path(sys.argv[2] + '/tests/foundation/python-consumer/import_client.py', run_name='consumer')
from tests.client_languages.build_cases import evaluate
cases = json.loads(pathlib.Path(sys.argv[2], 'tests/client_languages/cases.json').read_text())
for case in cases:
    assert evaluate(case) == case['expected'], case['name']
suite = unittest.defaultTestLoader.loadTestsFromNames([
    'tests.unit.test_decoder_corpus', 'tests.unit.test_transport_resilience'])
result = unittest.TextTestRunner(verbosity=2).run(suite)
assert result.wasSuccessful() and result.testsRun == 3
print(f'Installed Python consumer: {len(cases)} contracts, 536 decoder and 28 HTTP/TLS cases passed.')
"""
    # import_client.py expects argv[1] to identify the consumer, not its lib directory.
    code = code.replace(
        "runpy.run_path(", "sys.argv[1] = str(pathlib.Path(sys.argv[1]).parent)\nrunpy.run_path("
    )
    run([sys.executable, "-c", code, library, ROOT], cwd=consumer)
    return {"wheel_sha256": hashlib.sha256(wheels[0].read_bytes()).hexdigest()}


def javascript_client(consumer):
    run([sys.executable, "-I", "-S", ROOT / "tests/client_languages/check_javascript.py"])
    run([sys.executable, "-I", "-S", ROOT / "tests/client_languages/check_javascript.py", "--http"])
    packed = json.loads(
        run(
            [
                *npm_command(),
                "pack",
                ROOT / "clients/js",
                "--offline",
                "--ignore-scripts",
                "--pack-destination",
                consumer,
                "--json",
            ],
            capture=True,
        )
    )
    (consumer / "package.json").write_text('{"private":true,"type":"module"}', encoding="utf-8")
    archive = consumer / packed[0]["filename"]
    run(
        [
            *npm_command(),
            "install",
            "--prefix",
            consumer,
            "--offline",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
            "--no-package-lock",
            archive,
        ]
    )
    for name in ("consumer.mts", "consumer.cts"):
        shutil.copy2(ROOT / "tests/client_languages/typescript" / name, consumer / name)
    compiler = ROOT / "tests/playwright/node_modules/typescript/bin/tsc"
    for options, files in [
        (
            ["--module", "NodeNext", "--moduleResolution", "NodeNext"],
            ["consumer.mts", "consumer.cts"],
        ),
        (["--module", "commonjs", "--moduleResolution", "node"], ["consumer.cts"]),
    ]:
        run(
            [
                "node",
                compiler,
                "--strict",
                "--noEmit",
                "--target",
                "ES2022",
                "--lib",
                "ES2022",
                *options,
                *files,
            ],
            cwd=consumer,
        )
    return {"npm_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}


def java_client(_consumer):
    client = ROOT / "clients/java"
    build = client / "build"
    classes, tests = _consumer / "classes", build / "test-classes"
    classes.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)
    jdk(
        "javac",
        [
            "-encoding",
            "UTF-8",
            "--release",
            "17",
            "-Xlint:all",
            "-Werror",
            "-d",
            classes,
            *sorted((client / "src/main/java").rglob("*.java")),
        ],
    )
    shutil.copytree(client / "src/main/resources", classes, dirs_exist_ok=True)
    archive = build / "ezllmrouter-client-0.3.0.jar"
    jdk("jar", ["--create", "--file", archive, "-C", classes, "."])
    installed = _consumer / archive.name
    shutil.copy2(archive, installed)
    jdk(
        "javac",
        [
            "-encoding",
            "UTF-8",
            "--release",
            "17",
            "-Xlint:all",
            "-Werror",
            "-cp",
            installed,
            "-d",
            tests,
            *sorted((client / "src/test/java").rglob("*.java")),
        ],
    )
    # The Java 17 native launcher also uses the Windows code page. Manifest file
    # URLs carry Unicode without requiring non-ASCII native command-line bytes.
    with tempfile.TemporaryDirectory(prefix="jdk-launcher-", dir=ROOT / ".artifacts") as directory:
        manifest = Path(directory) / "MANIFEST.MF"
        manifest.write_text(
            "Manifest-Version: 1.0\nMain-Class: com.cognitivedynamics.ezllmrouter.ClientTest\n"
            + "Class-Path: "
            + installed.as_uri()
            + " "
            + tests.as_uri()
            + "/\n\n",
            encoding="utf-8",
        )
        launcher = Path(directory) / "consumer.jar"
        jdk("jar", ["--create", "--file", launcher, "--manifest", manifest])
        jdk("java", ["-ea", "-jar", launcher, ROOT / "tests/client_languages/cases.json"])
    http("java")
    return {"jar_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}


def dotnet_client(consumer):
    client = ROOT / "clients/dotnet"
    project = client / "EzLLMRouter.Client/EzLLMRouter.Client.csproj"
    tests = client / "EzLLMRouter.Client.Tests/EzLLMRouter.Client.Tests.csproj"
    packages = client / "build/packages"
    run(["dotnet", "restore", project, "--configfile", client / "NuGet.Config"])
    run(
        [
            "dotnet",
            "pack",
            project,
            "--no-restore",
            "--configuration",
            "Release",
            "--output",
            packages,
        ]
    )
    reference = "-p:ClientPackageDirectory=" + str(packages)
    run(
        [
            "dotnet",
            "restore",
            tests,
            "--source",
            packages,
            "--packages",
            consumer / "packages",
            "--force",
            reference,
        ]
    )
    run(["dotnet", "build", tests, "--no-restore", "--configuration", "Release", reference])
    run(
        [
            "dotnet",
            client / "EzLLMRouter.Client.Tests/bin/Release/net10.0/EzLLMRouter.Client.Tests.dll",
            ROOT / "tests/client_languages/cases.json",
        ]
    )
    http("dotnet")
    return {"nuget_sha256": hashlib.sha256(next(packages.glob("*.nupkg")).read_bytes()).hexdigest()}


def go_client(consumer):
    run(["go", "test", "-count=1", "./..."], cwd=ROOT / "clients/go")
    module = "github.com/ljramones/EzLLMRouter/clients/go"
    source = (ROOT / "clients/go").as_posix()
    (consumer / "go.mod").write_text(
        f'module platformconsumer\n\ngo 1.22.0\n\nrequire {module} v0.0.0\nreplace {module} => "{source}"\n',
        encoding="utf-8",
    )
    (consumer / "main.go").write_text(
        'package main\nimport _ "' + module + '"\nfunc main() {}\n', encoding="utf-8"
    )
    run(["go", "build", "."], cwd=consumer)
    http("go")
    return {"consumer": "fresh Go module with explicit local module replacement"}


def rust_client(consumer):
    manifest = ROOT / "clients/rust/Cargo.toml"
    os.environ["RUSTUP_TOOLCHAIN"] = tomllib.loads(
        (ROOT / "clients/rust/rust-toolchain.toml").read_text()
    )["toolchain"]["channel"]
    runtime = run(["cargo", "--version"], capture=True).strip()
    run(["cargo", "test", "--manifest-path", manifest, "--all-targets"])
    run(
        [
            "cargo",
            "clippy",
            "--offline",
            "--manifest-path",
            manifest,
            "--all-targets",
            "--",
            "-D",
            "clippy::correctness",
        ]
    )
    run(["cargo", "package", "--offline", "--manifest-path", manifest, "--allow-dirty"])
    archive = Path(os.environ["CARGO_TARGET_DIR"]) / "package/ezllmrouter-client-0.3.0.crate"
    with tarfile.open(archive) as package:
        package.extractall(consumer, filter="data")
    (consumer / "src").mkdir()
    (consumer / "src/main.rs").write_text(
        "use ezllmrouter_client::Client;\nfn main() { let _ = std::mem::size_of::<Client>(); }",
        encoding="utf-8",
    )
    path = (consumer / "ezllmrouter-client-0.3.0").as_posix()
    (consumer / "Cargo.toml").write_text(
        '[package]\nname="platform-consumer"\nversion="0.0.0"\nedition="2021"\n'
        + "[dependencies]\nezllmrouter-client={path="
        + json.dumps(path)
        + "}\n",
        encoding="utf-8",
    )
    run(["cargo", "check", "--offline", "--manifest-path", consumer / "Cargo.toml"])
    http("rust")
    return {"crate_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "runtime": runtime}


def http(language):
    run(
        [
            sys.executable,
            "-I",
            "-S",
            ROOT / "tests/client_languages/http_fixture.py",
            "--client",
            language,
        ]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    checks = {
        "python": python_client,
        "javascript": javascript_client,
        "go": go_client,
        "java": java_client,
        "dotnet": dotnet_client,
        "rust": rust_client,
    }
    parser.add_argument("--client", choices=checks, action="append")
    args = parser.parse_args()
    os.environ.setdefault("CARGO_TARGET_DIR", str(ROOT / ".cache/rust-target"))
    os.environ.setdefault("npm_config_cache", str(ROOT / ".cache/npm"))
    os.environ.setdefault("DOTNET_CLI_HOME", str(ROOT / ".cache/dotnet"))
    os.environ.setdefault("DOTNET_CLI_TELEMETRY_OPTOUT", "1")
    os.environ.setdefault("DOTNET_SKIP_FIRST_TIME_EXPERIENCE", "1")
    artifacts = ROOT / ".artifacts/platform-clients"
    artifacts.mkdir(parents=True, exist_ok=True)
    report = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version,
        "source_commit": run(["git", "rev-parse", "HEAD"], capture=True).strip(),
        "results": {},
    }
    try:
        for name in args.client or checks:
            started = time.monotonic()
            try:
                with tempfile.TemporaryDirectory(
                    prefix=name + "-客户端 ", dir=artifacts
                ) as directory:
                    evidence = checks[name](Path(directory))
                report["results"][name] = {"passed": True, **evidence}
            except Exception as error:
                traceback.print_exc()
                report["results"][name] = {"passed": False, "error_type": type(error).__name__}
            report["results"][name]["seconds"] = time.monotonic() - started
    finally:
        (artifacts / "summary.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    if len(report["results"]) != len(args.client or checks):
        raise AssertionError("missing client result")
    failures = [name for name, result in report["results"].items() if not result["passed"]]
    if failures:
        raise SystemExit("Platform client checks failed: " + ", ".join(failures))


if __name__ == "__main__":
    main()
