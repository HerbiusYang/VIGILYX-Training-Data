"""Regression tests for indexing, searching and seeking to corpus records."""

from concurrent.futures import CancelledError
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from corpus_catalog import CorpusCatalog, CorpusFileChangedError, CorpusPages


class CorpusCatalogTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "corpus.json"

    def write_corpus(self, records, *, bom=False, indent=None):
        prefix = "\ufeff \t" if bom else ""
        content = prefix + json.dumps(records, ensure_ascii=False, indent=indent) + "\r\n\t"
        self.path.write_bytes(content.encode("utf-8"))

    def test_seeks_to_exact_records_across_blocks(self):
        records = [
            {"id": "first", "data": [{"quotes": '\\"\\\\\\\"[你好]'}, {}]},
            {"id": "second", "input": {"current_email": {"body": "重复文本" * 40}}},
            {"id": "third", "data": ["\t", "\\", '"}']},
            {"id": "fourth", "data": "🗂️"},
        ]
        self.write_corpus(records, bom=True, indent=2)
        for chunk_size in (5, 13, 41):
            with self.subTest(chunk_size=chunk_size), patch("corpus_catalog._CORPUS_CHUNK_SIZE", chunk_size):
                pages = CorpusPages(self.path, page_size=2)
                self.assertEqual(pages.read_page(0), (records[-1:1:-1], True))
                self.assertEqual(pages.read_page(1), (records[1::-1], False))
                catalog = CorpusCatalog.build(self.path, expected_version=pages.version)
                rows = catalog.select()
                self.assertEqual(catalog.read_records(rows), records[::-1])
                self.assertEqual(catalog.read_records([rows[3], rows[0]]), [records[0], records[3]])

    def test_terms_facets_order_pairs_and_blind_search(self):
        older = {
            "id": "REC-42",
            "input": {
                "current_email": {"subject": "Ｃontract", "from": {"address": "buyer@example.test"}},
                "history": [{"body": "此前交付了备件"}],
            },
            "target": {"label": "benign", "evidence": [{"detail": "target-only-value"}]},
            "provenance": {"note": "provenance-only-value"},
            "scenario": "metadata-only-value",
            "pair_id": "PAIR-2",
            "domain": "finance",
        }
        newer = {
            "id": "REC-42",
            "input": {"current_email": {"subject": "Account"}},
            "target": {"label": "malicious"},
            "provenance": {"note": "another source"},
            "pair_id": "PAIR-2",
            "domain": "finance",
        }
        self.write_corpus([older, newer])
        catalog = CorpusCatalog.build(self.path)
        newest, oldest = catalog.select()
        self.assertEqual(catalog.facets["label"], {"malicious": 1, "benign": 1})
        self.assertEqual(catalog.facets["domain"], {"finance": 2})
        self.assertEqual(catalog.select(order="oldest"), (oldest, newest))
        self.assertEqual(catalog.select(order="subject"), (newest, oldest))
        self.assertEqual(catalog.select("contract  备件 BUYER@example.test"), (oldest,))
        self.assertEqual(catalog.select("REC-42", {"label": "benign", "domain": "finance"}), (oldest,))
        self.assertEqual(catalog.select("metadata-only-value"), (oldest,))
        self.assertEqual(catalog.select("metadata-only-value", blind=True), ())
        self.assertEqual(catalog.select("target-only-value"), ())
        self.assertEqual(catalog.select("provenance-only-value"), ())
        self.assertEqual(catalog.select(filters={"label": "benign"}, blind=True), (newest, oldest))
        self.assertEqual(catalog.paired_with(newest), (oldest,))

    def test_stale_versions_rejected_after_atomic_replacement(self):
        self.write_corpus([{"id": "a"}])
        pages = CorpusPages(self.path)
        pages.read_page(0)
        catalog = CorpusCatalog.build(self.path, expected_version=pages.version)
        replacement = self.path.with_suffix(".tmp")
        replacement.write_bytes(self.path.read_bytes())
        os.replace(replacement, self.path)
        with self.assertRaises(CorpusFileChangedError):
            pages.read_page(0)
        with self.assertRaises(CorpusFileChangedError):
            CorpusCatalog.build(self.path, expected_version=pages.version)
        with self.assertRaises(CorpusFileChangedError):
            catalog.read_records(catalog.select())

    def test_malformed_array_and_nonstandard_number_are_rejected(self):
        for content in (b'[{},]', b'[{},{]', b'[1,{}]', b'[{"x":NaN}]', b'x[{}]'):
            with self.subTest(content=content):
                self.path.write_bytes(content)
                with self.assertRaises(ValueError):
                    CorpusCatalog.build(self.path)

    def test_empty_corpus(self):
        self.write_corpus([], bom=True)
        self.assertEqual(CorpusPages(self.path).read_page(0), ([], False))
        catalog = CorpusCatalog.build(self.path)
        self.assertEqual(len(catalog), 0)
        self.assertEqual(catalog.select(), ())
        self.assertEqual(catalog.read_records([]), [])

    def test_build_can_cancel(self):
        self.write_corpus([{"id": "a"}])
        with self.assertRaises(CancelledError):
            CorpusCatalog.build(self.path, cancelled=lambda: True)


if __name__ == "__main__":
    unittest.main()
