"""Python 3.12 conditional-bytecode branch measurement without startup hooks."""

from __future__ import annotations

from collections.abc import Iterator
from collections import defaultdict
import dis
import hashlib
import json
from pathlib import Path
import sys
import threading
import types
import uuid

CONDITIONALS = {
    "FOR_ITER",
    "POP_JUMP_IF_FALSE",
    "POP_JUMP_IF_TRUE",
    "POP_JUMP_IF_NONE",
    "POP_JUMP_IF_NOT_NONE",
    "JUMP_IF_FALSE_OR_POP",
    "JUMP_IF_TRUE_OR_POP",
}


def codes(code: types.CodeType) -> Iterator[types.CodeType]:
    yield code
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            yield from codes(value)


def identity(code: types.CodeType) -> str:
    positions = repr(tuple(code.co_positions())).encode()
    return (
        f"{code.co_qualname}@{code.co_firstlineno}:"
        + hashlib.sha256(code.co_code + positions).hexdigest()[:12]
    )


def position(instruction: dis.Instruction) -> tuple[object, ...]:
    return tuple(
        getattr(instruction.positions, field, None)
        for field in ("lineno", "end_lineno", "col_offset", "end_col_offset")
    )


def conditional_targets(instructions: list[dis.Instruction]) -> dict[int, set[int]]:
    result = {}
    offsets = {item.offset: index for index, item in enumerate(instructions)}
    for index, instruction in enumerate(instructions):
        if instruction.opname not in CONDITIONALS:
            continue
        if index and instructions[index - 1].opname in {
            "WITH_EXCEPT_START",
            "CHECK_EXC_MATCH",
            "CHECK_EG_MATCH",
        }:
            continue
        target = int(instruction.argval)
        if instruction.opname == "FOR_ITER" and instructions[offsets[target]].opname == "END_FOR":
            target = instructions[offsets[target] + 1].offset
        result[instruction.offset] = {target, instructions[index + 1].offset}
    return result


def branch_aliases(code: types.CodeType) -> dict[tuple[int, int], tuple[int, int]]:
    """Map compiler copies of a while predicate to its original physical exits."""
    instructions = list(dis.get_instructions(code))
    by_offset = {item.offset: item for item in instructions}
    following = {
        left.offset: right.offset
        for left, right in zip(instructions, instructions[1:], strict=False)
    }
    targets = conditional_targets(instructions)
    backwards = [
        item
        for item in instructions
        if item.opname in {"JUMP_BACKWARD", "JUMP_BACKWARD_NO_INTERRUPT"}
        and by_offset[int(item.argval)].opname != "FOR_ITER"
    ]

    def reaches_body(source: int, body: int) -> bool:
        pending, visited = [source], set()
        while pending:
            offset = pending.pop()
            if offset == body:
                return True
            if offset in visited or offset > body:
                continue
            visited.add(offset)
            instruction = by_offset[offset]
            if instruction.opname in {"RETURN_VALUE", "RETURN_CONST", "RAISE_VARARGS", "RERAISE"}:
                continue
            if instruction.opname in {
                "JUMP_FORWARD",
                "JUMP_BACKWARD",
                "JUMP_BACKWARD_NO_INTERRUPT",
            }:
                successors = [int(instruction.argval)]
            else:
                successors = [following[offset]] if offset in following else []
                if instruction.opcode in dis.hasjrel or instruction.opcode in dis.hasjabs:
                    successors.append(int(instruction.argval))
            pending.extend(target for target in successors if offset < target <= body)
        return False

    def destination_token(offset: int) -> tuple[object, ...]:
        seen = set()
        while offset not in seen and by_offset[offset].opname in {
            "EXTENDED_ARG",
            "JUMP_FORWARD",
            "JUMP_BACKWARD",
            "JUMP_BACKWARD_NO_INTERRUPT",
        }:
            seen.add(offset)
            offset = (
                following[offset]
                if by_offset[offset].opname == "EXTENDED_ARG"
                else int(by_offset[offset].argval)
            )
        instruction = by_offset[offset]
        return instruction.opname, position(instruction), instruction.argrepr

    aliases = {
        (source, destination): (source, destination)
        for source, destinations in targets.items()
        for destination in destinations
    }
    candidates: dict[tuple[object, ...], list[int]] = defaultdict(list)
    for source, destinations in targets.items():
        instruction = by_offset[source]
        if instruction.opname == "FOR_ITER":
            continue
        family = {
            "POP_JUMP_IF_TRUE": "truth",
            "POP_JUMP_IF_FALSE": "truth",
            "POP_JUMP_IF_NONE": "none",
            "POP_JUMP_IF_NOT_NONE": "none",
        }.get(instruction.opname, instruction.opname)
        key = family, position(instruction)
        current = {destination_token(target): target for target in destinations}
        if position(instruction)[0] is not None and len(current) == len(destinations):
            for earlier in candidates[key]:
                # The first test is outside the loop body; its compiler copy is
                # inside a backward edge. Distinct body decisions and for loops
                # are never merged just because their locations look similar.
                if not any(
                    earlier < int(jump.argval) <= source < jump.offset
                    and reaches_body(earlier, int(jump.argval))
                    for jump in backwards
                ):
                    continue
                original = {destination_token(target): target for target in targets[earlier]}
                if current.keys() == original.keys():
                    for token, destination in current.items():
                        aliases[source, destination] = aliases[earlier, original[token]]
                    break
        candidates[key].append(source)
    return aliases


def branches(code: types.CodeType) -> dict[str, dict[str, object]]:
    result = {}
    for child in codes(code):
        instructions = {item.offset: item for item in dis.get_instructions(child)}
        for source, destination in set(branch_aliases(child).values()):
            instruction = instructions[source]
            key = f"{identity(child)}:{source}->{destination}"
            result[key] = {
                "function": child.co_qualname,
                "from": getattr(instruction.positions, "lineno", None),
                "to": getattr(instructions[destination].positions, "lineno", None),
                "opcode": instruction.opname,
            }
    return result


class BranchCoverage:
    def __init__(self, output: Path, prefixes: tuple[str, ...]) -> None:
        self.output, self.prefixes = output, prefixes
        self.observed: dict[int, set[tuple[int, int]]] = {}
        self.enabled: list[types.CodeType] = []
        self.identities: dict[int, str] = {}
        self.targets: dict[int, dict[int, set[int]]] = {}
        self.destinations: dict[int, dict[int, set[int]]] = {}
        self.aliases: dict[int, dict[tuple[int, int], tuple[int, int]]] = {}
        self.lines: dict[str, set[int]] = defaultdict(set)
        self.initializing = threading.RLock()
        self.active = False

    def _start(self, code: types.CodeType, _offset: int) -> object:
        if self.active and code.co_filename.startswith(self.prefixes):
            # Hashing/disassembly can release the GIL. A concurrent first call
            # must wait for initialization and must never reset recorded hits.
            with self.initializing:
                if id(code) not in self.identities:
                    self.enabled.append(code)
                    self.identities[id(code)] = identity(code)
                    self.observed[id(code)] = set()
                    expected: dict[int, set[int]] = {}
                    self.aliases[id(code)] = branch_aliases(code)
                    for source, target in self.aliases[id(code)].values():
                        expected.setdefault(source, set()).add(target)
                    self.targets[id(code)] = expected
                    self.destinations[id(code)] = {}
                    events = sys.monitoring.events
                    sys.monitoring.set_local_events(self.tool_id, code, events.BRANCH | events.LINE)
        # PY_START is global, so otherwise every call outside the source roots
        # also pays for this callback. Local LINE/BRANCH events remain enabled.
        return sys.monitoring.DISABLE

    def _branch(self, code: types.CodeType, source: int, destination: int) -> object | None:
        alias = self.aliases[id(code)].get((source, destination))
        if not self.active or alias is None:
            return sys.monitoring.DISABLE
        source, destination = alias
        self.observed[id(code)].add(alias)
        seen = self.destinations[id(code)].setdefault(source, set())
        seen.add(destination)
        # DISABLE applies to the source instruction, not one of its exits.
        # Keep observing it until both exits have been recorded.
        if self.targets[id(code)][source] <= seen:
            return sys.monitoring.DISABLE
        return None

    def _line(self, code: types.CodeType, line: int) -> object:
        if self.active:
            self.lines[code.co_filename].add(line)
        return sys.monitoring.DISABLE

    def __enter__(self) -> BranchCoverage:
        monitoring = sys.monitoring
        self.tool_id = next(
            (tool for tool in (1, 3, 4, 5) if monitoring.get_tool(tool) is None), -1
        )
        if self.tool_id < 0:
            raise RuntimeError("no free Python monitoring tool for branch coverage")
        monitoring.use_tool_id(self.tool_id, "ezllmrouter-branches")
        self.active = True
        monitoring.register_callback(self.tool_id, monitoring.events.PY_START, self._start)
        monitoring.register_callback(self.tool_id, monitoring.events.BRANCH, self._branch)
        monitoring.register_callback(self.tool_id, monitoring.events.LINE, self._line)
        monitoring.set_events(self.tool_id, monitoring.events.PY_START)
        return self

    def __exit__(self, *_error: object) -> None:
        self.active = False
        monitoring = sys.monitoring
        monitoring.set_events(self.tool_id, 0)
        for code in self.enabled:
            monitoring.set_local_events(self.tool_id, code, 0)
        monitoring.register_callback(self.tool_id, monitoring.events.PY_START, None)
        monitoring.register_callback(self.tool_id, monitoring.events.BRANCH, None)
        monitoring.register_callback(self.tool_id, monitoring.events.LINE, None)
        monitoring.free_tool_id(self.tool_id)
        self.output.mkdir(parents=True, exist_ok=True)
        rows: dict[str, list[str]] = {}
        for code in self.enabled:
            values = rows.setdefault(code.co_filename, [])
            values.extend(
                f"{self.identities[id(code)]}:{source}->{destination}"
                for source, destination in self.observed[id(code)]
            )
        rows = {name: sorted(set(values)) for name, values in rows.items()}
        (self.output / f"branches-{uuid.uuid4().hex}.json").write_text(
            json.dumps({"format": "ezllmrouter-logical-branches-v2", "files": rows})
        )
