"""Narrow interface checks for the qualified profile's lower-severity reviews."""

from __future__ import annotations

from tools.security_resolutions import canonical

CASES = {
    "DEBIAN-CVE-2026-42250": ("bzip2", "fixed_startup_tools"),
    "DEBIAN-CVE-2017-18018": ("coreutils", "fixed_startup_tools"),
    "DEBIAN-CVE-2025-5278": ("coreutils", "fixed_startup_tools"),
    "DEBIAN-CVE-2026-56391": ("coreutils", "fixed_startup_tools"),
    "DEBIAN-CVE-2026-56392": ("coreutils", "fixed_startup_tools"),
    "DEBIAN-CVE-2026-102473": ("dash", "fixed_startup_tools"),
    "DEBIAN-CVE-2026-102474": ("dash", "fixed_startup_tools"),
    "DEBIAN-CVE-2026-53910": ("diffutils", "fixed_startup_tools"),
    "DEBIAN-CVE-2026-91094": ("dpkg", "fixed_startup_tools"),
    "DEBIAN-CVE-2011-4116": ("perl", "fixed_startup_tools"),
    "DEBIAN-CVE-2026-15534": ("perl", "fixed_startup_tools"),
    "DEBIAN-CVE-2013-4392": ("systemd", "unused_systemd"),
    "DEBIAN-CVE-2023-31437": ("systemd", "unused_systemd"),
    "DEBIAN-CVE-2023-31438": ("systemd", "unused_systemd"),
    "DEBIAN-CVE-2023-31439": ("systemd", "unused_systemd"),
    "DEBIAN-CVE-2026-15059": ("systemd", "unused_systemd"),
    "DEBIAN-CVE-2026-16742": ("systemd", "unused_systemd"),
    "DEBIAN-CVE-2026-40228": ("systemd", "unused_systemd"),
    "DEBIAN-CVE-2026-115819": ("glibc", "no_wide_scanf"),
    "DEBIAN-CVE-2026-121757": ("glibc", "fixed_text_encodings"),
    "DEBIAN-CVE-2026-121758": ("glibc", "fixed_text_encodings"),
    "DEBIAN-CVE-2026-124024": ("glibc", "fixed_text_encodings"),
    "DEBIAN-CVE-2025-6141": ("ncurses", "no_termcap_parser"),
    "DEBIAN-CVE-2026-121481": ("openssl", "no_native_encodeblock"),
    "DEBIAN-CVE-2026-35190": ("openssl", "tcp_client_only"),
    "DEBIAN-CVE-2026-88822": ("openssl", "no_incoming_quic"),
    "DEBIAN-CVE-2026-95690": ("openssl", "tcp_client_only"),
    "DEBIAN-CVE-2021-45346": ("sqlite3", "trusted_database_inputs"),
    "DEBIAN-CVE-2026-115456": ("gcc-16", "no_native_charconv"),
    "DEBIAN-CVE-2026-125709": ("gcc-16", "no_untrusted_file_streams"),
}


def valid(identifier: str, proofs: dict) -> bool:
    """Require complete bound objects before applying any additional decision.

    Text, tool, transport and database cases additionally rely on the reviewed
    exact owned source and qualification already validated by load_policy.
    Their review reasons describe the missing application entry point; merely
    having no imported symbol does not establish those conditions.
    """
    if identifier not in CASES:
        return True
    condition = CASES[identifier][1]
    for proof in proofs.values():
        objects = proof.get("elf_objects")
        if not objects or canonical(objects) != proof["elf_sha256"]:
            return False
        closure = proof["closure"]["objects"]
        imports = {symbol for path in closure for symbol in objects[path]["imports"]}
        if condition == "unused_systemd" and any(
            objects[path]["soname"] in {"libsystemd.so.0", "libudev.so.1"} for path in closure
        ):
            return False
        if condition == "no_wide_scanf" and any(
            any(name in symbol for name in ("wscanf", "fwscanf", "swscanf")) for symbol in imports
        ):
            return False
        if condition == "no_native_charconv" and any("from_chars" in symbol for symbol in imports):
            return False
        if condition == "no_untrusted_file_streams":
            callers = {
                path
                for path in closure
                if any(
                    any(
                        name in symbol
                        for name in ("basic_filebuf", "basic_fstream", "basic_ofstream")
                    )
                    for symbol in objects[path]["imports"]
                )
            }
            if callers - {"/usr/local/bin/node"}:
                return False
            if callers:
                report = proof.get("node_report", {})
                if (
                    any(report.get(key) is not False for key in ("fatal", "signal", "exception"))
                    or report.get("node_options") not in {"", "--use-bundled-ca"}
                    or report.get("entrypoint") != ["docker-entrypoint.sh"]
                    or report.get("command")
                    not in (
                        ["node", "-e", "setInterval(()=>{},3600000)"],
                        ["node", "/app/consumer/dev09_js_actor.cjs"],
                    )
                ):
                    return False
        if condition == "no_native_encodeblock" and "EVP_EncodeBlock" in imports:
            return False
        if condition == "no_termcap_parser" and (
            any(objects[path]["soname"] in {"libtic.so.5", "libtic.so.6"} for path in closure)
            or any("_nc_parse_entry" in objects[path]["exports"] for path in closure)
            or imports & {"_nc_parse_entry", "_nc_read_termcap_entry", "_nc_captoinfo"}
        ):
            return False
    return True
