"""Python 3.12 conditional-bytecode branch measurement without startup hooks."""

from __future__ import annotations

from collections.abc import Iterator
from collections import defaultdict
import dis
import hashlib
import json
from pathlib import Path
import sys
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


def branches(code: types.CodeType) -> dict[str, dict[str, object]]:
    result = {}
    for child in codes(code):
        instructions = list(dis.get_instructions(child))
        lines = {
            instruction.offset: getattr(instruction.positions, "lineno", None)
            for instruction in instructions
        }
        for index, instruction in enumerate(instructions):
            if instruction.opname not in CONDITIONALS:
                continue
            if index and instructions[index - 1].opname in {
                "WITH_EXCEPT_START",
                "CHECK_EXC_MATCH",
                "CHECK_EG_MATCH",
            }:
                # Compiler exception dispatch is outside the conditional-exit metric.
                continue
            target = int(instruction.argval)
            if instruction.opname == "FOR_ITER":
                end = next(i for i, item in enumerate(instructions) if item.offset == target)
                # BRANCH reports the instruction after END_FOR, not END_FOR itself.
                if instructions[end].opname == "END_FOR":
                    target = instructions[end + 1].offset
            for destination in {target, instructions[index + 1].offset}:
                key = f"{identity(child)}:{instruction.offset}->{destination}"
                result[key] = {
                    "function": child.co_qualname,
                    "from": getattr(instruction.positions, "lineno", None),
                    "to": lines.get(destination),
                    "opcode": instruction.opname,
                }
    return result


class BranchCoverage:
    def __init__(self, output: Path, prefixes: tuple[str, ...]) -> None:
        self.output, self.prefixes = output, prefixes
        self.observed: dict[int, set[tuple[int, int]]] = {}
        self.enabled: list[types.CodeType] = []
        self.identities: dict[int, str] = {}
        self.lines: dict[str, set[int]] = defaultdict(set)
        self.active = False

    def _start(self, code: types.CodeType, _offset: int) -> None:
        if (
            self.active
            and code.co_filename.startswith(self.prefixes)
            and id(code) not in self.identities
        ):
            self.enabled.append(code)
            self.identities[id(code)] = identity(code)
            self.observed[id(code)] = set()
            events = sys.monitoring.events
            sys.monitoring.set_local_events(self.tool_id, code, events.BRANCH | events.LINE)

    def _branch(self, code: types.CodeType, source: int, destination: int) -> None:
        if self.active:
            self.observed[id(code)].add((source, destination))

    def _line(self, code: types.CodeType, line: int) -> None:
        if self.active:
            self.lines[code.co_filename].add(line)

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
        (self.output / f"branches-{uuid.uuid4().hex}.json").write_text(json.dumps(rows))
