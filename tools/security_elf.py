"""Read native dependencies and load segments without executing an ELF object."""

from __future__ import annotations

import struct


def inspect(raw: bytes) -> dict | None:
    if not raw.startswith(b"\x7fELF"):
        return None

    def area(offset: int, size: int) -> bytes:
        if not 0 <= offset <= offset + size <= len(raw):
            raise ValueError("ELF area outside object")
        return raw[offset : offset + size]

    def unpack(format: str, offset: int) -> tuple:
        return struct.unpack(format, area(offset, struct.calcsize(format)))

    if area(4, 3) != b"\x02\x01\x01":
        raise ValueError("unsupported ELF encoding")
    header = unpack("<HHIQQQIHHHHHH", 16)
    if header[1] != 183 or header[2] != 1 or header[7] != 64:
        raise ValueError("ELF is not the reviewed AArch64 format")
    if (header[9] and header[8] != 56) or (header[11] and header[10] != 64):
        raise ValueError("unsupported ELF table entry size")
    if not header[11] or header[11] > 16384 or header[9] > 16384:
        raise ValueError("missing or oversized ELF tables")

    loads = []
    for index in range(header[9]):
        entry = unpack("<IIQQQQQQ", header[4] + index * header[8])
        if entry[0] == 1:
            if entry[5] > entry[6] or entry[3] + entry[6] >= 2**64:
                raise ValueError("invalid ELF load segment")
            area(entry[2], entry[5])
            loads.append((entry[3], entry[3] + entry[6]))
    ordered = bool(loads) and all(
        previous[0] <= current[0] and previous[1] <= current[1]
        for previous, current in zip(loads, loads[1:], strict=False)
    )
    sections = [
        unpack("<IIQQQQIIQQ", header[5] + index * header[10]) for index in range(header[11])
    ]

    def strings(section: tuple) -> bytes:
        if not 0 <= section[6] < len(sections):
            raise ValueError("invalid ELF string table link")
        linked = sections[section[6]]
        if linked[1] != 3:
            raise ValueError("ELF link is not a string table")
        return area(linked[4], linked[5])

    def text(table: bytes, offset: int) -> str:
        if not 0 <= offset < len(table):
            raise ValueError("ELF string outside table")
        end = table.find(b"\0", offset)
        if end < 0:
            raise ValueError("unterminated ELF string")
        return table[offset:end].decode("utf-8")

    imports, exports, needed, search, sonames = set(), set(), [], [], []
    for section in sections:
        if section[1] not in {6, 11}:
            continue
        names = strings(section)
        size = 16 if section[1] == 6 else 24
        if section[9] != size or section[5] % size:
            raise ValueError("invalid ELF dynamic entry size")
        for offset in range(section[4], section[4] + section[5], size):
            if section[1] == 11:
                name, info, _other, defined, _value, _size = unpack("<IBBHQQ", offset)
                if name and not defined and info >> 4 in {1, 2}:
                    imports.add(text(names, name))
                elif name and defined and info >> 4 in {1, 2}:
                    exports.add(text(names, name))
            else:
                tag, value = unpack("<qQ", offset)
                if tag == 1:
                    needed.append(text(names, value))
                elif tag == 14:
                    sonames.append(text(names, value))
                elif tag in {15, 29}:
                    search.append(text(names, value))
    if len(sonames) > 1 or len(needed) != len(set(needed)):
        raise ValueError("ambiguous ELF dependency identity")
    return {
        "machine": "aarch64",
        "type": header[0],
        "loads_ordered": ordered,
        "imports": sorted(imports),
        "exports": sorted(exports),
        "needed": needed,
        "search_paths": search,
        "soname": sonames[0] if sonames else None,
    }


def application_closure(objects: dict[str, dict]) -> dict:
    roots = {path for path in objects if path.startswith(("/usr/local/", "/app/", "/opt/"))}
    if not roots:
        raise ValueError("missing application native objects")
    names: dict[str, set[str]] = {}
    for path, row in objects.items():
        for name in {path.rsplit("/", 1)[1], row["soname"]} - {None}:
            names.setdefault(name, set()).add(path)
    closure, unloadable = set(), {}
    for root in sorted(roots):
        visited, missing, pending = set(), set(), [root]
        while pending:
            path = pending.pop()
            if path in visited:
                continue
            visited.add(path)
            for name in objects[path]["needed"]:
                candidates = names.get(name, set())
                if len(candidates) > 1:
                    raise ValueError("ambiguous native dependency: " + name)
                if not candidates:
                    missing.add(name)
                pending.extend(candidates - visited)
        if missing:
            unloadable[root] = sorted(missing)
        else:
            closure.update(visited)
    restricted = {
        "glob",
        "glob64",
        "__glob",
        "__glob64",
        "regcomp",
        "regexec",
        "re_compile_pattern",
        "re_search",
        "re_match",
        "re_search_2",
        "re_match_2",
    }
    callers = {
        path: sorted(set(objects[path]["imports"]) & restricted)
        for path in sorted(closure)
        if set(objects[path]["imports"]) & restricted
    }
    quic_symbols = {
        "SSL_set_incoming_stream_policy",
        "SSL_accept_stream",
        "SSL_new_stream",
        "OSSL_QUIC_client_method",
        "OSSL_QUIC_client_thread_method",
    }
    quic_callers = {
        path: sorted(set(objects[path]["imports"]) & quic_symbols)
        for path in sorted(closure)
        if set(objects[path]["imports"]) & quic_symbols
    }
    return {
        "roots": sorted(roots),
        "objects": sorted(closure),
        "unloadable_roots": unloadable,
        "restricted_callers": callers,
        "quic_callers": quic_callers,
    }
