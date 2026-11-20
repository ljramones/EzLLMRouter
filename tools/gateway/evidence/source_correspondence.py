"""Compare selected published-wheel Python files with the inspected sdist."""

if not __package__:
    import sys
    from pathlib import Path

    for _parent in Path(__file__).resolve().parents:
        if (_parent / "tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent))
            break
        if (_parent / "server/tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent / "server"))
            break


from pathlib import Path
import hashlib
import json
import sys
import tarfile
import zipfile


SELECTED = (
    "litellm/__init__.py",
    "litellm/proxy/proxy_server.py",
    "litellm/llms/openai/openai.py",
    "litellm/llms/openai/common_utils.py",
    "litellm/llms/custom_httpx/http_handler.py",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: source_correspondence.py SDIST WHEEL OUTPUT")
    sdist, wheel, output = map(Path, sys.argv[1:])
    if (
        sha(sdist.read_bytes())
        != "f1a274db0b2bcc78c34ed34c06df2c1dcd0dc038469193684927f6bb2cab2d97"
    ):
        raise ValueError("sdist digest mismatch")
    if (
        sha(wheel.read_bytes())
        != "beb5044645144308b39560049c0f68875ad7de07e681ad0b73e2bc6c3705ba61"
    ):
        raise ValueError("wheel digest mismatch")
    rows = []
    with tarfile.open(sdist, "r:gz") as source, zipfile.ZipFile(wheel) as package:
        for name in SELECTED:
            member = source.extractfile("litellm-1.105.1/" + name)
            if member is None:
                raise ValueError("missing sdist file " + name)
            original, published = member.read(), package.read(name)
            rows.append(
                {
                    "path": name,
                    "sdist_sha256": sha(original),
                    "wheel_sha256": sha(published),
                    "equal": original == published,
                }
            )
        native = package.read("litellm/rust_bridge/_native.abi3.so")
    result = {
        "sdist_sha256": sha(sdist.read_bytes()),
        "wheel_sha256": sha(wheel.read_bytes()),
        "selected_python_files": rows,
        "native_member": {
            "path": "litellm/rust_bridge/_native.abi3.so",
            "bytes": len(native),
            "sha256": sha(native),
            "source_to_binary_proof": False,
        },
    }
    output.write_text(json.dumps(result, indent=2) + "\n")
    if not all(row["equal"] for row in rows):
        raise ValueError("selected Python source differs from sdist")
    print(
        json.dumps(
            {
                "selected_files": len(rows),
                "equal": True,
                "native_sha256": result["native_member"]["sha256"],
            }
        )
    )


if __name__ == "__main__":
    main()
