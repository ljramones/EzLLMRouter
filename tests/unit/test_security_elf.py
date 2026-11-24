"""Native dependency review rejects dangerous or ambiguous ELF metadata."""

from copy import deepcopy
import struct
import unittest

from tools.security_elf import application_closure, inspect


def fixture(imported="regexec", needed="libc.so.6"):
    names = b"\0" + imported.encode() + b"\0" + needed.encode() + b"\0"
    strings_at, symbols_at, dynamic_at, sections_at = 256, 384, 448, 512
    raw = bytearray(768)
    raw[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into(
        "<HHIQQQIHHHHHH", raw, 16, 3, 183, 1, 0, 64, sections_at, 0, 64, 56, 2, 64, 4, 0
    )
    for index, address in enumerate((0, 4096)):
        struct.pack_into("<IIQQQQQQ", raw, 64 + index * 56, 1, 5, 0, address, 0, 64, 64, 4096)
    raw[strings_at : strings_at + len(names)] = names
    struct.pack_into("<IBBHQQ", raw, symbols_at, 1, 0x12, 0, 0, 0, 0)
    struct.pack_into("<qQ", raw, dynamic_at, 1, 2 + len(imported))
    struct.pack_into(
        "<IIQQQQIIQQ", raw, sections_at + 64, 0, 3, 0, 0, strings_at, len(names), 0, 0, 1, 0
    )
    struct.pack_into(
        "<IIQQQQIIQQ", raw, sections_at + 128, 0, 11, 0, 0, symbols_at, 24, 1, 0, 8, 24
    )
    struct.pack_into("<IIQQQQIIQQ", raw, sections_at + 192, 0, 6, 0, 0, dynamic_at, 16, 1, 0, 8, 16)
    return raw


class ELFReviewTests(unittest.TestCase):
    def test_imports_dependencies_and_segment_order_are_read_without_execution(self):
        row = inspect(fixture())
        self.assertEqual(row["imports"], ["regexec"])
        self.assertEqual(row["needed"], ["libc.so.6"])
        self.assertTrue(row["loads_ordered"])
        self.assertIsNone(inspect(b"ordinary data"))
        raw = fixture()
        struct.pack_into("<Q", raw, 64 + 56 + 16, 0)
        struct.pack_into("<Q", raw, 64 + 16, 4096)
        self.assertFalse(inspect(raw)["loads_ordered"])

    def test_wrong_architecture_truncated_tables_and_bad_string_links_fail_closed(self):
        for change in ("architecture", "offset", "link", "string", "truncate"):
            raw = fixture()
            if change == "architecture":
                struct.pack_into("<H", raw, 18, 62)
            elif change == "offset":
                struct.pack_into("<Q", raw, 40, 2**63)
            elif change == "link":
                struct.pack_into("<I", raw, 512 + 128 + 40, 99)
            elif change == "string":
                struct.pack_into("<I", raw, 384, 999)
            else:
                raw = raw[:80]
            with self.subTest(change=change), self.assertRaises(ValueError):
                inspect(raw)

    def test_transitive_glob_or_regex_callers_are_included_in_the_gate(self):
        application = inspect(fixture("malloc", "libvendor.so"))
        vendor = inspect(fixture("regexec"))
        libc = dict(inspect(fixture("malloc")), needed=[])
        objects = {
            "/usr/local/lib/application.so": application,
            "/vendor/libvendor.so": vendor,
            "/lib/libc.so.6": libc,
        }
        result = application_closure(objects)
        self.assertEqual(result["restricted_callers"], {"/vendor/libvendor.so": ["regexec"]})
        objects["/vendor/libvendor.so"]["imports"] = ["glob"]
        self.assertEqual(
            application_closure(objects)["restricted_callers"], {"/vendor/libvendor.so": ["glob"]}
        )

    def test_missing_optional_modules_are_unloadable_and_ambiguous_libraries_fail(self):
        application = inspect(fixture("malloc", "liboptional.so"))
        result = application_closure({"/usr/local/lib/optional.so": application})
        self.assertEqual(
            result["unloadable_roots"], {"/usr/local/lib/optional.so": ["liboptional.so"]}
        )
        objects = {
            "/usr/local/lib/optional.so": application,
            "/one/liboptional.so": deepcopy(application),
            "/two/liboptional.so": deepcopy(application),
        }
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            application_closure(objects)
