"""Read-only presentation of mail, annotations, and provenance for the corpus viewer."""

from collections import defaultdict
from dataclasses import dataclass
from difflib import unified_diff
from itertools import islice
import json


VIEWS = (
    ("email", "当前邮件"),
    ("history", "往来历史"),
    ("assessment", "标注与证据"),
    ("sources", "来源与改编"),
    ("json", "原始 JSON"),
)

_MAIL_HEADERS = {
    "subject": "主题",
    "from": "发件人",
    "to": "收件人",
    "cc": "抄送",
    "reply_to": "回复地址",
    "sent_at": "发送时间",
    "attachments": "附件",
}
_LABELS = {"benign": "正常", "malicious": "恶意"}
_SOURCE_KINDS = {
    "redacted-source": "原始材料脱敏",
    "source-adapted": "基于来源改编",
    "synthetic": "合成",
    "source": "来源材料",
}


def _object(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "；".join(_text(item) for item in value)
    return json.dumps(value, ensure_ascii=False)


def _path(parent, child):
    return parent + "/" + str(child).replace("~", "~0").replace("/", "~1")


def record_json(record, *, input_only=False):
    """Serialize the whole record or exactly the classifier input."""
    return json.dumps(record.get("input", {}) if input_only else record, ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class _Citation:
    key: str
    path: str
    quote: str

    @property
    def anchor(self):
        return "anchor:" + self.key

    @property
    def is_evidence(self):
        return self.key.startswith("e")


class _Document:
    def __init__(self):
        self.parts = []

    def add(self, text, tag="body", path=None):
        if text:
            self.parts.append((text, tag, path))

    def line(self, text, tag="body"):
        self.add(text + "\n", tag)

    def field(self, label, value):
        if value is not None and value != "" and value != [] and value != {}:
            self.add(label + "  ", "meta")
            self.line(_text(value))

    def sections(self, citations=None):
        sections = []
        for text, tag, path in self.parts:
            locations = citations.get(path) if citations else None
            if not locations:
                sections.append((text, tag))
                continue

            # Split at every boundary so even overlapping quotes can be located by
            # their own anchor tags. Each individual anchor stays contiguous.
            boundaries = sorted({0, len(text)} | {i for start, end, _ in locations for i in (start, end)})
            for start, end in zip(boundaries, boundaries[1:]):
                active = [cite for left, right, cite in locations if left <= start < right]
                tags = [tag, "evidence"] if any(cite.is_evidence for cite in active) else [tag]
                tags += [cite.anchor for cite in active]
                sections.append((text[start:end], tuple(tags) if active else tag))
        return sections


def _inline_mail_value(doc, value, path, tag):
    """Keep each displayed source string intact so its quotes can be located."""
    if isinstance(value, str):
        doc.add(value, tag, path)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            if i:
                doc.add("；", tag)
            _inline_mail_value(doc, item, _path(path, i), tag)
    elif isinstance(value, dict) and ("address" in value or "name" in value):
        first = True
        for key, left, right in (
            ("name", "", ""), ("address", "<", ">"), ("role", "· ", ""), ("type", "(", ")"),
        ):
            if value.get(key):
                if not first:
                    doc.add(" " + left, tag)
                _inline_mail_value(doc, value[key], _path(path, key), tag)
                if not first:
                    doc.add(right, tag)
                first = False
    else:
        doc.add(_text(value), tag)


def _mail(doc, email, base_path, *, history=False):
    if not email:
        doc.line("没有可显示的邮件。", "meta")
        return
    if history:
        title = email.get("subject")
        if isinstance(title, str) and title:
            doc.add(title, "title", _path(base_path, "subject"))
        else:
            doc.add("（无主题）", "title")
        doc.line("")
    for field, label in _MAIL_HEADERS.items():
        if (history and field == "subject") or not email.get(field):
            continue
        doc.add(label + "  ", "meta")
        _inline_mail_value(doc, email[field], _path(base_path, field), "body")
        doc.line("")
    doc.line("\n正文", "section")
    body = email.get("body")
    if isinstance(body, str) and body:
        doc.add(body, "body", _path(base_path, "body"))
    elif body is not None and body != "":
        doc.add(_text(body))
    else:
        doc.line("（无正文）", "meta")


def _mail_document(source, view):
    doc = _Document()
    if view == "email":
        _mail(doc, _object(source.get("current_email")), "/input/current_email")
        return doc

    context = source.get("business_context")
    if context:
        doc.line("业务背景", "section")
        if isinstance(context, str):
            doc.add(context, "body", "/input/business_context")
        else:
            doc.add(_text(context))
        doc.line("\n")

    history = _list(source.get("history"))
    if not history:
        doc.line("这封邮件没有历史往来。", "meta")
    for index, email in enumerate(history):
        if index:
            doc.line("\n")
        doc.line(f"历史邮件 {index + 1} / {len(history)}", "section")
        _mail(doc, _object(email), f"/input/history/{index}", history=True)
    return doc


def _evidence_items(target):
    for i, item in enumerate(_list(target.get("evidence"))):
        item = _object(item)
        if item:
            yield i, item


def _evidence_citations(index, item):
    for i, span in enumerate(_list(item.get("spans"))):
        span = _object(span)
        yield _citation(f"e{index}:{i}", span.get("path"), span.get("quote"))


def _citation(key, path, quote):
    return _Citation(key, path if isinstance(path, str) else "", quote if isinstance(quote, str) else "")


def _grounding_citation(kind, index, item):
    return _citation(f"{kind}:{index}", item.get("input_path"), item.get("input_quote"))


def _all_citations(target, provenance):
    for index, item in _evidence_items(target):
        yield from _evidence_citations(index, item)
    grounding = _object(provenance.get("grounding"))
    for kind in ("fact_map", "adaptations"):
        for index, item in enumerate(_list(grounding.get(kind))):
            yield _grounding_citation(kind, index, _object(item))


def _valid_citations(fields, citations):
    by_path = defaultdict(list)
    for cite in citations:
        if cite.quote and cite.path in fields:
            start = fields[cite.path].find(cite.quote)
            if start >= 0:
                by_path[cite.path].append((start, start + len(cite.quote), cite))
    return by_path


def _citation_link(doc, cite, destinations, links):
    # Keep provenance pointers and annotation quotes available even if a legacy
    # quote does not match the visible original text.
    if not cite.quote and not cite.path:
        return
    if cite.quote:
        doc.line(cite.quote, "quote")
    if cite.key in destinations:
        if links is not None:
            link = "link:" + cite.key
            links[link] = (destinations[cite.key], cite.anchor)
            doc.line("查看原文  ↗", ("link", link))
    elif cite.path:
        doc.line("无法定位原文", "meta")
    if cite.path:
        doc.line(cite.path, "meta")


def _annotation_document(target, destinations, links):
    doc = _Document()
    if not target:
        doc.line("这条记录没有标注。", "meta")
        return doc
    doc.line("分类结果", "section")
    _label_line(doc, target)
    if target.get("safe_action"):
        doc.line("\n建议操作", "section")
        doc.line(_text(target["safe_action"]))
    evidence = list(_evidence_items(target))
    doc.line("\n判定证据", "section")
    if not evidence:
        doc.line("没有记录判定证据。", "meta")
    for index, item in evidence:
        if index:
            doc.line("")
        code = _text(item.get("code") or "未记录证据代码")
        doc.line(f"{index + 1} · {code}", "subsection")
        if item.get("detail"):
            doc.line(_text(item["detail"]))
        for cite in _evidence_citations(index, item):
            _citation_link(doc, cite, destinations, links)
    return doc


def _label_line(doc, target):
    label = _text(target.get("label") or "未标注")
    name = _LABELS.get(label)
    doc.line(f"{name}  ·  {label}" if name else label, label if name else "meta")


def _section_items(doc, title, rows, heading, fields):
    rows = [_object(row) for row in _list(rows)]
    if not rows:
        return
    doc.line("\n" + title, "section")
    for index, row in enumerate(rows, 1):
        if index > 1:
            doc.line("")
        doc.line(_text(heading(row, index)), "subsection")
        for key, label in fields:
            doc.field(label, row.get(key))


def _grounding_document(doc, grounding, destinations, links):
    doc.line("\n研究与改编", "section")
    doc.field("主题", grounding.get("theme"))
    context = _object(grounding.get("context"))
    for key, label in (("region", "地区"), ("period", "时期"), ("setting", "设定")):
        doc.field(label, context.get(key))
    source_material = _object(grounding.get("source_material"))
    doc.field("材料类型", source_material.get("type"))
    doc.field("原始渠道", source_material.get("original_channel"))
    doc.field("材料引用", source_material.get("source_ids"))
    doc.field("处理方式", grounding.get("transformations"))
    doc.field("改编范围", grounding.get("adaptation_scope"))
    retrieval = _object(grounding.get("retrieval"))
    doc.field("检索日期", retrieval.get("searched_at"))
    doc.field("检索词", retrieval.get("queries"))
    doc.field("补充核查", retrieval.get("additional_checks"))

    for key, title, fields in (
        ("fact_map", "原文依据", (("source_id", "来源"), ("locator", "出处"), ("source_claim", "可核对事实"))),
        ("adaptations", "改编明细", (("basis_source_ids", "参考来源"), ("change", "改动"), ("reason", "原因"))),
    ):
        items = _list(grounding.get(key))
        if not items:
            continue
        doc.line("\n" + title, "section")
        for index, item in enumerate(items):
            item = _object(item)
            if not item:
                continue
            if index:
                doc.line("")
            doc.line(f"{title} {index + 1}", "subsection")
            for field, label in fields:
                doc.field(label, item.get(field))
            _citation_link(doc, _grounding_citation(key, index, item), destinations, links)


def _provenance_document(provenance, destinations, links):
    doc = _Document()
    if not provenance:
        doc.line("这条记录没有来源信息。", "meta")
        return doc
    kind = _text(provenance.get("kind") or "")
    if kind:
        doc.line(_SOURCE_KINDS.get(kind, kind), "section")
    doc.field("合成范围", provenance.get("synthetic_scope"))

    _section_items(
        doc, "引用来源", provenance.get("sources"),
        lambda row, i: row.get("title") or f"来源 {i}",
        (
            ("id", "引用编号"), ("publisher", "发布方"), ("roles", "用途"), ("supports", "支持内容"),
            ("locator", "出处"), ("jurisdiction", "适用地区"), ("published_at", "发布日期"),
            ("updated_at", "更新日期"), ("effective_at", "生效日期"), ("event_period", "活动时间"),
            ("accessed_at", "访问日期"), ("url", "来源网址"),
        ),
    )
    _section_items(
        doc, "相关机构", provenance.get("entities"),
        lambda row, i: row.get("name") or f"机构 {i}",
        (("type", "类型"), ("role", "角色"), ("source_ids", "引用来源")),
    )
    _section_items(
        doc, "标识符与账户", provenance.get("identifiers"),
        lambda row, i: row.get("value") or f"标识符 {i}",
        (
            ("kind", "类型"), ("owner", "所有者"), ("bank", "开户行"), ("code_system", "编码体系"),
            ("usage_scope", "使用范围"), ("basis", "记录依据"), ("source_ids", "引用来源"),
        ),
    )
    grounding = _object(provenance.get("grounding"))
    if grounding:
        _grounding_document(doc, grounding, destinations, links)
    return doc


def detail_sections(record, view, *, highlight=False, links=None):
    """Return ordered text/tag pairs and populate any source-navigation links."""
    if view == "json":
        return [(record_json(record), "code")]

    source = _object(record.get("input"))
    target = _object(record.get("target"))
    provenance = _object(record.get("provenance"))

    if view in ("email", "history"):
        doc = _mail_document(source, view)
        if not highlight:
            return doc.sections()
        fields = {path: text for text, _, path in doc.parts if path}
        return doc.sections(_valid_citations(fields, _all_citations(target, provenance)))

    destinations = {}
    for destination in ("email", "history"):
        doc = _mail_document(source, destination)
        fields = {path: text for text, _, path in doc.parts if path}
        for locations in _valid_citations(fields, _all_citations(target, provenance)).values():
            for _, _, cite in locations:
                destinations[cite.key] = destination

    if view == "assessment":
        return _annotation_document(target, destinations, links).sections()
    if view == "sources":
        return _provenance_document(provenance, destinations, links).sections()
    raise ValueError(f"未知的详情页：{view}")


_MISSING = object()


def _compare_lines(value):
    if value is _MISSING:
        return ["（无此字段）"]
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    return text.split("\n")


def _compare_field(doc, label, before, after):
    if before == after:
        return False
    doc.line("\n" + label, "section")
    changes = unified_diff(_compare_lines(before), _compare_lines(after), n=2, lineterm="")
    for change in islice(changes, 2, None):
        tag = "diff" if change.startswith("@@") else {"-": "removed", "+": "added"}.get(change[0], "body")
        doc.line(change, tag)
    return True


def comparison_sections(record, counterpart):
    """Compare the actual input fields of the two records in a pair."""
    doc = _Document()
    doc.line("配对记录", "section")
    for label, item in (("− 当前", record), ("+ 对照", counterpart)):
        doc.field(label, item.get("id") or "（无编号）")
        _label_line(doc, _object(item.get("target")))
    before = _object(record.get("input"))
    after = _object(counterpart.get("input"))
    before_mail = _object(before.get("current_email"))
    after_mail = _object(after.get("current_email"))
    compared = False
    for field in dict.fromkeys((*_MAIL_HEADERS, "body", *before_mail, *after_mail)):
        name = _MAIL_HEADERS.get(field, "正文" if field == "body" else field)
        compared |= _compare_field(doc, name, before_mail.get(field, _MISSING), after_mail.get(field, _MISSING))
    for field in dict.fromkeys(("business_context", "history", *before, *after)):
        if field == "current_email" and (before_mail or after_mail):
            continue
        name = {"business_context": "业务背景", "history": "往来历史", "current_email": "当前邮件"}.get(field, field)
        compared |= _compare_field(doc, name, before.get(field, _MISSING), after.get(field, _MISSING))
    if not compared:
        doc.line("\n两条记录的分类器输入相同。", "meta")
    return doc.sections()
