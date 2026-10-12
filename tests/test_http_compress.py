"""Tests for JsonGZipContentEncoding HTTP compression transform."""

import gzip
import json
import os
import sys
import tempfile
import unittest

from tornado import testing, web

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from webserver.http_compress import JsonGZipContentEncoding


class LargeJsonHandler(web.RequestHandler):
    def get(self):
        # 正文 > 2KB，self.write(dict)
        self.write({"message": "x" * 2500, "count": 123})


class LargeTextHandler(web.RequestHandler):
    def get(self):
        self.set_header("Content-Type", "text/plain; charset=utf-8")
        self.write("hello plain text " * 200)


class LargeEpubHandler(web.RequestHandler):
    def get(self):
        self.set_header("Content-Type", "application/epub+zip")
        self.write(b"PK\x03\x04" + b"fake-epub-data" * 300)


class HttpCompressTest(testing.AsyncHTTPTestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.test_file_path = os.path.join(self.tmp_dir.name, "sample.txt")
        with open(self.test_file_path, "wb") as f:
            f.write(b"0123456789abcdefghijklmnopqrstuvwxyz" * 100)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.tmp_dir.cleanup()

    def get_app(self):
        return web.Application(
            [
                (r"/large-json", LargeJsonHandler),
                (r"/large-text", LargeTextHandler),
                (r"/large-epub", LargeEpubHandler),
                (r"/static/(.*)", web.StaticFileHandler, {"path": self.tmp_dir.name}),
            ],
            transforms=[JsonGZipContentEncoding],
        )

    def test_json_compressed_with_accept_encoding(self):
        expected_data = {"message": "x" * 2500, "count": 123}
        resp = self.fetch(
            "/large-json",
            decompress_response=False,
            headers={"Accept-Encoding": "gzip"},
            raise_error=False,
        )
        self.assertEqual(resp.code, 200)
        self.assertEqual(resp.headers.get("Content-Encoding"), "gzip")
        self.assertIn("Accept-Encoding", resp.headers.get("Vary", ""))
        decompressed = gzip.decompress(resp.body)
        self.assertEqual(json.loads(decompressed.decode("utf-8")), expected_data)

    def test_json_not_compressed_without_accept_encoding(self):
        expected_data = {"message": "x" * 2500, "count": 123}
        resp = self.fetch(
            "/large-json",
            decompress_response=False,
            raise_error=False,
        )
        self.assertEqual(resp.code, 200)
        self.assertNotIn("Content-Encoding", resp.headers)
        self.assertEqual(json.loads(resp.body.decode("utf-8")), expected_data)

    def test_non_json_not_compressed(self):
        # text/plain
        resp_text = self.fetch(
            "/large-text",
            decompress_response=False,
            headers={"Accept-Encoding": "gzip"},
            raise_error=False,
        )
        self.assertEqual(resp_text.code, 200)
        self.assertNotIn("Content-Encoding", resp_text.headers)
        self.assertTrue(resp_text.body.startswith(b"hello plain text"))

        # application/epub+zip
        resp_epub = self.fetch(
            "/large-epub",
            decompress_response=False,
            headers={"Accept-Encoding": "gzip"},
            raise_error=False,
        )
        self.assertEqual(resp_epub.code, 200)
        self.assertNotIn("Content-Encoding", resp_epub.headers)
        self.assertTrue(resp_epub.body.startswith(b"PK\x03\x04fake-epub-data"))

    def test_range_request_not_compressed(self):
        resp = self.fetch(
            "/static/sample.txt",
            decompress_response=False,
            headers={"Range": "bytes=10-19", "Accept-Encoding": "gzip"},
            raise_error=False,
        )
        self.assertEqual(resp.code, 206)
        self.assertNotIn("Content-Encoding", resp.headers)
        self.assertEqual(resp.body, b"abcdefghij")
        self.assertEqual(len(resp.body), 10)

    def test_json_etag_and_304(self):
        resp1 = self.fetch(
            "/large-json",
            decompress_response=False,
            headers={"Accept-Encoding": "gzip"},
            raise_error=False,
        )
        self.assertEqual(resp1.code, 200)
        etag = resp1.headers.get("Etag")
        self.assertTrue(bool(etag))

        resp2 = self.fetch(
            "/large-json",
            decompress_response=False,
            headers={"If-None-Match": etag, "Accept-Encoding": "gzip"},
            raise_error=False,
        )
        self.assertEqual(resp2.code, 304)
        self.assertEqual(resp2.body, b"")


if __name__ == "__main__":
    unittest.main()
