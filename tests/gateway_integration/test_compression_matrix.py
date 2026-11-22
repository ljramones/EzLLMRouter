"""Generated compressed-provider replies must be complete and bounded during decode."""

import gzip
import json
import random
import unittest
from unittest.mock import patch
import zlib

import httpx

from ezllmrouter_server.gateway.choice_b_sender import RESPONSE_LIMIT, read_response
from tests.generated_inputs import settings


class RawStream(httpx.AsyncByteStream):
    def __init__(self, raw, chunk=13, error=False):
        self.raw, self.chunk, self.error = raw, chunk, error
        self.closed, self.reads = False, 0

    async def __aiter__(self):
        for offset in range(0, len(self.raw), self.chunk):
            self.reads += 1
            yield self.raw[offset : offset + self.chunk]
            if self.error:
                raise OSError("controlled upstream interruption")

    async def aclose(self):
        self.closed = True


def encoded(raw, mode):
    if mode == "gzip":
        return gzip.compress(raw, mtime=0)
    if mode == "raw-deflate":
        encoder = zlib.compressobj(wbits=-15)
        return encoder.compress(raw) + encoder.flush()
    return zlib.compress(raw) if mode == "deflate" else raw


class CompressionMatrixTests(unittest.IsolatedAsyncioTestCase):
    def response(self, raw, mode="identity", *, chunk=13, length=None, error=False):
        stream = RawStream(raw, chunk, error)
        headers = {"Content-Encoding": "deflate" if mode == "raw-deflate" else mode}
        if length is not None:
            headers["Content-Length"] = str(length).encode("latin-1")
        return httpx.Response(200, headers=headers, stream=stream), stream

    async def test_valid_fragmented_members_preserve_exact_bytes_through_the_limit(self):
        for mode in ("identity", "gzip", "deflate", "raw-deflate"):
            for size in (0, 1, RESPONSE_LIMIT - 1, RESPONSE_LIMIT):
                with self.subTest(encoding=mode, decoded_bytes=size):
                    raw = b"x" * size
                    body = encoded(raw, mode)
                    response, stream = self.response(
                        body, mode, chunk=1 if size < 2 else 13, length=len(body)
                    )
                    self.assertEqual(await read_response(response), raw)
                    self.assertTrue(stream.closed)

    async def test_truncated_compressed_members_are_never_returned_as_complete(self):
        raw = b'{"output":"synthetic result","usage":1}'
        for mode in ("gzip", "deflate", "raw-deflate"):
            body = encoded(raw, mode)
            for removed in (1, 2, 4, 8):
                with self.subTest(encoding=mode, removed=removed):
                    response, stream = self.response(body[:-removed], mode)
                    with self.assertRaises(ValueError):
                        await read_response(response)
                    self.assertTrue(stream.closed)

    async def test_trailing_or_concatenated_members_cannot_hide_a_second_payload(self):
        for mode in ("gzip", "deflate", "raw-deflate"):
            for suffix in (b"trailing", encoded(b"second", mode)):
                with self.subTest(encoding=mode, second_member=suffix != b"trailing"):
                    response, stream = self.response(encoded(b"first", mode) + suffix, mode)
                    with self.assertRaises(ValueError):
                        await read_response(response)
                    self.assertTrue(stream.closed)

    async def test_decode_output_is_bounded_before_allocation_of_a_compression_bomb(self):
        limits = []
        original = zlib.decompressobj

        class Decoder:
            def __init__(self, *args, **kwargs):
                self.inner = original(*args, **kwargs)

            def decompress(self, raw, max_length=0):
                limits.append(max_length)
                return self.inner.decompress(raw, max_length)

            def __getattr__(self, name):
                return getattr(self.inner, name)

        for mode in ("gzip", "deflate", "raw-deflate"):
            response, stream = self.response(
                encoded(b"x" * (RESPONSE_LIMIT * 16), mode), mode, chunk=65536
            )
            with patch.object(zlib, "decompressobj", Decoder):
                with self.assertRaises(ValueError):
                    await read_response(response)
            self.assertTrue(stream.closed)
        self.assertTrue(limits)
        self.assertTrue(all(0 < limit <= RESPONSE_LIMIT + 1 for limit in limits), limits)

    async def test_encoded_length_and_encoding_errors_close_without_reading(self):
        for encoding in ("br", "gzip,deflate", "", "unknown"):
            response, stream = self.response(b"body", encoding)
            with self.subTest(encoding=encoding), self.assertRaises(ValueError):
                await read_response(response)
            self.assertEqual(stream.reads, 0)
            self.assertTrue(stream.closed)
        for length in (-1, "+4", "", "²", RESPONSE_LIMIT + 1):
            response, stream = self.response(b"body", length=length)
            with self.subTest(length=length), self.assertRaises(ValueError):
                await read_response(response)
            self.assertEqual(stream.reads, 0)
            self.assertTrue(stream.closed)

    async def test_declared_length_mismatch_and_read_faults_never_return_partial_success(self):
        response, stream = self.response(b"body", length=5)
        with self.assertRaises(ValueError):
            await read_response(response)
        self.assertTrue(stream.closed)
        response, stream = self.response(b"body", error=True)
        with self.assertRaises(OSError):
            await read_response(response)
        self.assertTrue(stream.closed)

    async def test_preconsumed_responses_require_identity_and_exact_bounded_bytes(self):
        for size in (0, RESPONSE_LIMIT, RESPONSE_LIMIT + 1):
            response = httpx.Response(200, content=b"x" * size)
            if size > RESPONSE_LIMIT:
                with self.assertRaises(ValueError):
                    await read_response(response)
            else:
                self.assertEqual(await read_response(response), b"x" * size)
            self.assertTrue(response.is_closed)
        response = httpx.Response(200, content=b"x", headers={"Content-Length": "2"})
        with self.assertRaises(ValueError):
            await read_response(response)
        response = httpx.Response(200, content=b"x" * (RESPONSE_LIMIT + 1))
        del response.headers["Content-Length"]
        with self.assertRaises(ValueError):
            await read_response(response)
        response = httpx.Response(
            200, content=gzip.compress(b"x"), headers={"Content-Encoding": "gzip"}
        )
        with self.assertRaises(ValueError):
            await read_response(response)

    async def test_empty_invalid_and_corrupt_compression_never_becomes_success(self):
        for mode in ("gzip", "deflate", "raw-deflate"):
            valid = encoded(b"payload", mode)
            for raw in (b"", b"x", b"invalid", valid[:-1] + bytes([valid[-1] ^ 255])):
                response, stream = self.response(raw, mode)
                with self.subTest(mode=mode, raw=raw), self.assertRaises(ValueError):
                    await read_response(response)
                self.assertTrue(stream.closed)
        response, stream = self.response(b"x" * (RESPONSE_LIMIT + 1), chunk=65536)
        with self.assertRaises(ValueError):
            await read_response(response)
        self.assertTrue(stream.closed)

    async def test_seeded_compression_preserves_complete_members_and_rejects_cut_trailers(self):
        seed, count = settings()
        rng = random.Random(seed)
        for index in range(count):
            raw = json.dumps({"index": index, "text": "é😀\n" * rng.randrange(1, 20)}).encode()
            mode = rng.choice(("gzip", "deflate", "raw-deflate"))
            body = encoded(raw, mode)
            response, stream = self.response(body, mode, chunk=rng.randrange(1, 19))
            with self.subTest(seed=seed, index=index, mode=mode):
                self.assertEqual(await read_response(response), raw)
                self.assertTrue(stream.closed)
                response, stream = self.response(body[:-1], mode, chunk=3)
                with self.assertRaises(ValueError):
                    await read_response(response)
                self.assertTrue(stream.closed)
