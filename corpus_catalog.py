"""Read and search local VIGILYX JSON corpora without retaining parsed records."""

from collections import Counter, defaultdict
from concurrent.futures import CancelledError
from contextlib import contextmanager
from itertools import islice
import json
import os
from pathlib import Path
import re
from typing import NamedTuple
import unicodedata


_CORPUS_CHUNK_SIZE = 64 * 1024
_JSON_WHITESPACE = re.compile(rb"[ \t\r\n]*")
_JSON_STRUCTURE = re.compile(rb'[][{}"]')
_JSON_QUOTE = re.compile(rb'"')
_JSON_BACKSLASHES = re.compile(rb"[\\]*")
_UTF8_BOM = b"\xef\xbb\xbf"


def _reject_json_constant(name):
    raise ValueError(f"无效的 JSON 值 {name}")


class CorpusFileChangedError(ValueError):
    """The file has changed since this reader opened it."""


def file_version(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _changed():
    return CorpusFileChangedError("语料文件已更改，请重新读取")


@contextmanager
def _open_snapshot(path, expected_version=None):
    try:
        source = open(path, "rb", buffering=0)
    except FileNotFoundError:
        if expected_version is not None:
            raise _changed() from None
        raise

    with source:
        version = file_version(os.fstat(source.fileno()))
        if expected_version is not None and expected_version != version:
            raise _changed()
        try:
            yield source, version
        finally:
            try:
                path_version = file_version(path.stat())
            except FileNotFoundError:
                raise _changed() from None
            if version != file_version(os.fstat(source.fileno())) or version != path_version:
                raise _changed()


def _decode_object(data, record_number, offset):
    try:
        return json.loads(data.decode("utf-8"), parse_constant=_reject_json_constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError(f"第 {record_number} 条记录格式无效（字节偏移 {offset}）：{exc}") from exc


class _ReverseCorpusStream:
    """Read fixed-size blocks from the end toward the start of the file."""

    def __init__(self, source, end, cancelled=None):
        self.source = source
        self.buffer_end = end
        self.buffer = b""
        self.position = 0
        self.cancelled = cancelled
        self.refill()

    @property
    def offset(self):
        return self.buffer_end - self.position - 1

    def refill(self):
        if self.cancelled is not None and self.cancelled():
            raise CancelledError()
        self.buffer_end -= len(self.buffer)
        start = max(0, self.buffer_end - _CORPUS_CHUNK_SIZE)
        size = self.buffer_end - start
        self.source.seek(start)
        block = self.source.read(size)
        if len(block) != size:
            raise _changed()
        self.buffer = block[::-1]
        self.position = 0
        return bool(self.buffer)

    def skip_whitespace(self):
        while self.position < len(self.buffer) or self.refill():
            self.position = _JSON_WHITESPACE.match(self.buffer, self.position).end()
            if self.position < len(self.buffer):
                return self.buffer[self.position]
        return None

    def read_object(self, record_number):
        last_offset = self.offset
        part_start = self.position
        parts = []
        stack = []
        in_string = False
        quote_backslashes = None

        while True:
            if quote_backslashes is not None:
                end = _JSON_BACKSLASHES.match(self.buffer, self.position).end()
                quote_backslashes += end - self.position
                self.position = end
                if end < len(self.buffer):
                    # An odd number of backslashes before a quote escapes it.
                    # Keep counting across blocks until we see another byte.
                    if quote_backslashes % 2 == 0:
                        in_string = not in_string
                    quote_backslashes = None

            markers = _JSON_QUOTE if in_string else _JSON_STRUCTURE
            match = markers.search(self.buffer, self.position)
            if match is None:
                parts.append(self.buffer[part_start:])
                if not self.refill():
                    raise ValueError(f"第 {record_number} 条记录缺少开始括号（结束字节偏移 {last_offset}）")
                part_start = 0
                continue

            self.position = match.end()
            token = self.buffer[match.start()]
            if token == ord('"'):
                quote_backslashes = 0
            elif token == ord("}"):
                stack.append(ord("{"))
            elif token == ord("]"):
                stack.append(ord("["))
            else:
                if stack.pop() != token:
                    raise ValueError(
                        f"第 {record_number} 条记录的括号不匹配（字节偏移 {self.offset + 1}）"
                    )
                if not stack:
                    parts.append(self.buffer[part_start:self.position])
                    break

        # Restore byte order before decoding so split UTF-8 characters
        # are joined before the decoder sees them.
        return _decode_object(b"".join(parts)[::-1], record_number, self.offset + 1)


def _reverse_records(source, end, first_number=1, cancelled=None):
    """Yield each record, its byte span and the next record's ending byte."""
    stream = _ReverseCorpusStream(source, end, cancelled)
    if first_number == 1:
        if stream.skip_whitespace() != ord("]"):
            raise ValueError("语料文件必须以 JSON 数组形式保存")
        stream.position += 1

    record_number = first_number
    token = stream.skip_whitespace()
    while token != ord("["):
        if token != ord("}"):
            raise ValueError(f"第 {record_number} 条记录应为 JSON 对象（字节偏移 {stream.offset}）")
        record_end = stream.offset + 1
        record = stream.read_object(record_number)
        record_start = stream.offset + 1

        token = stream.skip_whitespace()
        if token == ord("["):
            # Validate the file prefix before yielding the last record.
            _check_prefix(stream)
            yield record, record_start, record_end, None
            return
        if token != ord(","):
            raise ValueError(f"数组缺少逗号或开始括号（字节偏移 {stream.offset}）")
        stream.position += 1
        token = stream.skip_whitespace()
        record_number += 1
        if token != ord("}"):
            raise ValueError(f"第 {record_number} 条记录应为 JSON 对象（字节偏移 {stream.offset}）")
        yield record, record_start, record_end, stream.offset + 1

    _check_prefix(stream)


def _check_prefix(stream):
    stream.position += 1
    if stream.skip_whitespace() is None:
        return
    if stream.offset == len(_UTF8_BOM) - 1:
        stream.source.seek(0)
        if stream.source.read(len(_UTF8_BOM)) == _UTF8_BOM:
            return
    raise ValueError(f"数组开始前存在额外内容（字节偏移 {stream.offset}）")


class CorpusPages:
    """Read pages from the end of a JSON array before the index is ready."""

    def __init__(self, path, page_size=50):
        if page_size < 1:
            raise ValueError("每页条数必须大于零")
        self.path = Path(path)
        self.page_size = page_size
        self._page_ends = [None]
        self._file_version = None

    @property
    def version(self):
        return self._file_version

    def read_page(self, index):
        """Return (records, has_next) for a previously discovered page index."""
        if not 0 <= index < len(self._page_ends):
            raise IndexError("请先读取前一页")

        records = []
        next_end = None
        with _open_snapshot(self.path, self.version) as (source, version):
            end = version[2] if index == 0 else self._page_ends[index]
            first_number = index * self.page_size + 1
            entries = _reverse_records(source, end, first_number)
            for record, _, _, next_end in islice(entries, self.page_size):
                records.append(record)

        self._file_version = version
        if next_end is not None and index + 1 == len(self._page_ends):
            self._page_ends.append(next_end)
        return records, next_end is not None


class RecordSummary(NamedTuple):
    ordinal: int
    record_id: str
    subject: str
    sender: str
    label: str
    domain: str
    difficulty: str
    language: str
    pair_id: str


def _object(value):
    return value if isinstance(value, dict) else {}


def _text(value):
    if value is None:
        return ""
    return str(value)


def summarize(record, ordinal):
    """Create a display row using its zero-based position from the array end."""
    email = _object(_object(record.get("input")).get("current_email"))
    sender = email.get("from")
    if isinstance(sender, dict):
        name = _text(sender.get("name"))
        address = _text(sender.get("address"))
        sender = f"{name} <{address}>" if name and address else name or address
    return RecordSummary(
        ordinal=ordinal,
        record_id=_text(record.get("id")) or str(ordinal + 1),
        subject=_text(email.get("subject")),
        sender=_text(sender),
        label=_text(_object(record.get("target")).get("label")),
        domain=_text(record.get("domain")),
        difficulty=_text(record.get("difficulty")),
        language=_text(record.get("language")),
        pair_id=_text(record.get("pair_id")),
    )


_FACETS = "label", "domain", "difficulty", "language"
_ORDERS = "newest", "oldest", "subject"


def _normalize(value):
    return unicodedata.normalize("NFKC", value).casefold()


def _search_values(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _search_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _search_values(child)
    elif value is not None:
        yield _text(value)


class _IndexedRecord(NamedTuple):
    row: RecordSummary
    start: int
    end: int
    input_text: str
    metadata_text: str


class CorpusCatalog:
    """An in-memory search catalog for one version of a local corpus file."""

    def __init__(self, path, version, entries):
        self.path = path
        self.version = version
        self._entries = tuple(entries)
        self.facets = {
            field: dict(Counter(getattr(entry.row, field) for entry in self._entries))
            for field in _FACETS
        }
        pairs = defaultdict(list)
        for entry in self._entries:
            if entry.row.pair_id:
                pairs[entry.row.pair_id].append(entry.row)
        self._pairs = {key: tuple(rows) for key, rows in pairs.items()}

    @classmethod
    def build(cls, path, *, cancelled=None, progress=None, expected_version=None):
        """Scan a JSON array and retain byte spans and normalized search values."""
        path = Path(path)
        entries = []
        with _open_snapshot(path, expected_version) as (source, version):
            size = version[2]
            for ordinal, (record, start, end, _) in enumerate(
                _reverse_records(source, size, cancelled=cancelled)
            ):
                row = summarize(record, ordinal)
                input_text = "\n".join((row.record_id, *_search_values(record.get("input"))))
                metadata = {
                    key: value for key, value in record.items()
                    if key not in {"input", "target", "provenance", "id"}
                }
                entries.append(_IndexedRecord(
                    row, start, end, _normalize(input_text), _normalize("\n".join(_search_values(metadata))),
                ))
                if progress is not None and ordinal % 128 == 0:
                    progress(size - start, size)
            if cancelled is not None and cancelled():
                raise CancelledError()
        if progress is not None:
            progress(size, size)
        return cls(path, version, entries)

    def __len__(self):
        return len(self._entries)

    def select(self, query="", filters=None, order="newest", *, blind=False):
        """Return matching rows; all whitespace-separated terms must occur."""
        if order not in _ORDERS:
            raise ValueError(f"不支持的排序方式：{order}")
        terms = _normalize(query).split()
        active_filters = tuple(
            (field, value)
            for field, value in (filters or {}).items()
            if field in _FACETS and value is not None and (not blind or field != "label")
        )
        rows = []
        for entry in self._entries:
            row = entry.row
            if any(getattr(row, field) != value for field, value in active_filters):
                continue
            if terms and not all(
                term in entry.input_text or (not blind and term in entry.metadata_text)
                for term in terms
            ):
                continue
            rows.append(row)
        if order == "oldest":
            rows.reverse()
        elif order == "subject":
            rows.sort(key=lambda row: (not row.subject, _normalize(row.subject)))
        return tuple(rows)

    def paired_with(self, row):
        return tuple(other for other in self._pairs.get(row.pair_id, ()) if other != row)

    def read_records(self, rows):
        """Read the selected full records in the caller's order."""
        records = []
        with _open_snapshot(self.path, self.version) as (source, _):
            for row in rows:
                entry = self._entries[row.ordinal]
                if entry.row != row:
                    raise ValueError("该记录不属于当前语料索引")
                source.seek(entry.start)
                length = entry.end - entry.start
                data = source.read(length)
                if len(data) != length:
                    raise _changed()
                records.append(_decode_object(data, row.ordinal + 1, entry.start))
        return records
