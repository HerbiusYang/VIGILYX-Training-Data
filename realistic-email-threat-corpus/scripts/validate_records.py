#!/usr/bin/env python3
"""Validate email-corpus JSON arrays or legacy JSONL without third-party packages.

Usage: python3 validate_records.py corpus.json [--strict] [--balanced]
       [--require-detailed] [--require-cn-context] [--require-grounding] [--require-raw-urls]
       [--require-render] [--require-current-year] [--labels malicious,benign] [--extra-codes code_a,code_b]

Records with schema_version="2.0" always receive v2 checks. --strict also
rejects legacy records. Exit status 1 means errors; warnings remain review items.
Sources and entity attribution are checked structurally, never verified online.
--require-grounding requires v2 source-adapted/redacted-source records with
retrieval metadata, material sources and exact fact-map/adaptation spans.
Grounding metadata or source-adapted kind also triggers grounding checks.
Body coverage is structural: one mapped quote is not full factual verification.
V2 preserves literal URLs and domains; personal e-mail addresses remain masked.
--require-raw-urls rejects legacy [URL_n] placeholders, not messages without links.
URLs are never fetched. URL privacy checks decode common percent escapes twice;
names, credentials, encoded payloads and source authenticity still require review.
A record-level "render" object declares fictional people/organizations and the
mailbox relationships that render_records.py turns into realistic surface text.
--require-render requires it plus sender/recipient mailboxes and sent_at values.
--require-current-year checks newly composed mail from January 1 through the
local run date. Originals retain their recorded dates.
Sources with origin "user_supplied" (a supplied original email) need no URL, and
retrieval may be omitted when every source in the record is user supplied.
provenance.detector_feedback marks a real false positive/negative; its label must
be the reviewed truth, not the detector's verdict, which stays out of input.

Detailed body metric: count only text before the first recognized quoted block.
Remove common standalone greetings, closing/signature/footer blocks, placeholders,
contact links and digit runs; count each whitespace-normalized paragraph once.
This heuristic cannot identify every boilerplate style or judge professionalism.
Units: zh=CJK characters; en=English words; zh-en=CJK + 2*English words.
Minimums: 350/220/350. Recommended maxima: 800/450/800; >2x warns.
"""
import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime
from urllib.parse import unquote, urlsplit

PROV_KINDS = {"source", "redacted-source", "synthetic", "source-adapted"}
SOURCE_ROLES = {"material", "context", "entity", "policy"}
MATERIAL_TYPES = {"email", "email_thread", "official_notice", "case_report", "business_document"}
GROUNDING_TRANSFORMATIONS = {"anonymization", "faithful_paraphrase", "translation", "format_adaptation", "excerpt", "scenario_adaptation"}
LANGS = {"zh", "en", "zh-en"}
DOMAINS = {"finance", "accounting", "shopping", "workplace"}
DIFFICULTIES = {"easy", "medium", "hard"}
HEADER_CODES = {"sender_domain_mismatch", "reply_to_mismatch", "display_name_mismatch"}
FORBIDDEN_V2_CODES = HEADER_CODES | {"sender_consistent"}
KNOWN_CODES = HEADER_CODES | {
    "payment_route_change", "credential_or_mfa_request", "approval_path_bypass",
    "channel_shift", "timeline_conflict", "unexpected_link_or_attachment",
    "secrecy_request", "history_contradiction", "sender_consistent",
    "process_consistent", "expected_next_step", "verification_via_known_channel",
    "matches_prior_reference", "refund_route_change", "advance_fee_request",
    "transaction_mismatch", "unsupported_charge_claim", "excessive_data_request",
}
RESERVED_TLDS = {"example", "invalid", "test", "localhost"}
RESERVED_SLDS = {"example.com", "example.net", "example.org"}
FILE_EXTS = {
    "pdf", "doc", "docx", "xls", "xlsx", "xlsm", "csv", "ppt", "pptx", "txt",
    "md", "zip", "rar", "7z", "gz", "tar", "jpg", "jpeg", "png", "gif", "bmp",
    "html", "htm", "exe", "js", "msg", "eml", "mbox", "iso", "img", "json",
    "xml", "ofd", "wps", "et", "dps", "lnk", "bat", "vbs", "py", "jsonl",
}
# ASCII boundaries allow identifiers immediately next to Chinese prose.
URL_RE = re.compile(r"(?<![A-Za-z0-9_])(?:https?|ftp)://([^\s/<>\"'）)\]，。]+)", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
DOMAIN_RE = re.compile(r"(?<![A-Za-z0-9_@.-])((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})(?![A-Za-z0-9_-])")
CN_ID_RE = re.compile(r"(?<![A-Za-z0-9_-])[0-9]{17}[0-9Xx](?![A-Za-z0-9_])")
DIGIT_RUN_RE = re.compile(r"(?<![A-Za-z0-9_-])[0-9][0-9 -]{10,}[0-9](?![A-Za-z0-9_])")
CN_MOBILE_RE = re.compile(r"(?<![A-Za-z0-9_-])1[3-9][0-9][- ]?[0-9]{4}[- ]?[0-9]{4}(?![A-Za-z0-9_])")
IBAN_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Z]{2}[0-9]{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?(?![A-Za-z0-9_])")
REDACTED_RE = re.compile(r"\[REDACTED:[A-Z_0-9]+\]")
TOKEN_RE = re.compile(r"\[(?:PERSON|EMAIL|PHONE|ACCOUNT|ORDER|URL)_[1-9][0-9]*\]")
EMAIL_TOKEN_RE = re.compile(r"\[EMAIL_[1-9][0-9]*\]")
LITERAL_EMAIL_RE = re.compile(r"[^\s<>\[\]@/?=&:#]+@[^\s<>\[\]@/?=&:#]+\.[^\s<>\[\]@/?=&:#]+", re.I)
URL_TOKEN_RE = re.compile(r"\[URL_[0-9]+\]", re.I)
# Recognize URL text without resolving it. Bare domains with a path/query are
# included so their resource names cannot inflate language or length metrics.
# Complete privacy tokens belong to the URL even though an unmatched ] ends a
# Markdown link. Keep subsequent path/query text inside the same scan segment.
URL_CHARACTER = r"(?:\[(?:[A-Z][A-Z0-9_]*_[0-9]+|REDACTED:[A-Z0-9_]+)\]|[^\s<>\"'）)\]，。])"
URL_TEXT_RE = re.compile(
    r"(?:https?|ftp)://" + URL_CHARACTER + r"+"
    r"|(?<![A-Za-z0-9_@.-])(?:www\." + URL_CHARACTER + r"+"
    r"|//[A-Za-z0-9]" + URL_CHARACTER + r"+"
    r"|(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}[/?#]" + URL_CHARACTER + r"*)", re.I,
)
SYNTHETIC_ACCOUNT_RE = re.compile(r"\[ACCOUNT_[0-9]+\]|SYN-ACCT(?:-|\b)", re.I)
SYN_ID_RE = re.compile(r"(?<![A-Za-z0-9_])(?:[A-Z]+-)?SYN-[A-Za-z0-9_-]+")
CJK_RE = re.compile(r"[一-鿿]")
LATIN_WORD_RE = re.compile(r"[A-Za-z]{2,}")
URGENCY_RE = re.compile(r"紧急|加急|尽快|马上|立即|今天(?:之内|内|下班前)|urgent|asap|immediately", re.I)
QUOTE_SPLIT_RE = re.compile(r"\n-{5,}\s*(?:原始邮件|转发邮件信息|Original Message|Forwarded message)", re.I)
QUOTE_START_RE = re.compile(
    r"^[ \t]*(?:[-_]{2,}[ \t]*(?:原始邮件|原邮件|转发邮件(?:信息)?|Original Message|Forwarded message)"
    r"|On [^\n]{1,240}wrote:[ \t]*$|在[^\n]{1,200}(?:写道|寫道)[：:][ \t]*$|>"
    r"|(?:From|发件人)[：:][^\n]*\n(?:[ \t]*\n)?[ \t]*(?:Sent|Date|发送时间|日期)[：:])",
    re.I | re.M,
)
ANY_TOKEN_RE = re.compile(r"\[(?:[A-Z][A-Z0-9_]*_[0-9]+|REDACTED:[A-Z0-9_]+)\]")
ENGLISH_WORD_RE = re.compile(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*")
GREETING_RE = re.compile(
    r"^(?:(?:您好|你好|大家好|各位(?:同事|客户|伙伴)?好|[^，。！？\n]{0,30}(?:您好|你好)|尊敬的[^\n]{1,40})[，,:：!！。]*"
    r"|(?:Dear|Hi|Hello|Good morning|Good afternoon|Good evening)\b[^\n]{0,70}[,:!：，]*)$", re.I,
)
CLOSING_RE = re.compile(
    r"^(?:谢谢(?:配合|支持|理解)?|感谢(?:配合|支持|理解)|此致|敬礼|顺颂商祺|顺祝商祺"
    r"|Best regards|Kind regards|Warm regards|Regards|Sincerely|Thank you|Thanks)[，,:：.!！。]*$", re.I,
)
FOOTER_RE = re.compile(
    r"^(?:免责声明|保密声明|CONFIDENTIAL(?:ITY)? NOTICE|This (?:email|message) (?:and any attachments )?"
    r"(?:is confidential|contains confidential)|发自我的|发送自我的|Sent from my|Sent from Outlook|Get Outlook for)", re.I,
)
CONTACT_LINE_RE = re.compile(r"^(?:电话|手机|传真|地址|邮箱|网址|Tel(?:ephone)?|Phone|Mobile|Fax|E-?mail|Website|Address)\s*[:：]", re.I)
DETAILED_METRICS = {"zh": ("cjk", 350, 800), "en": ("english_words", 220, 450), "zh-en": ("weighted_units", 350, 800)}
CN_CONTEXT_FIELDS = ("business_region", "transaction_scope", "currencies", "cross_border_context", "currency_context")
MONEY_NUMBER = r"[0-9]+(?:[,.][0-9]+)*"
MONEY_GAP = r"[\s:()\[\]]*[+-]?"
DISALLOWED_CURRENCY_CODES = (
    "GBP", "EUR", "HKD", "JPY", "AUD", "CAD", "SGD", "NZD", "CHF", "KRW", "TWD", "MOP",
    "INR", "RUB", "THB", "MYR", "IDR", "PHP", "VND", "AED", "SAR", "BRL", "ZAR", "MXN", "SEK", "NOK", "DKK",
)
DISALLOWED_MONEY_CODE_RE = re.compile(
    r"(?<![A-Za-z])(?:" + "|".join(DISALLOWED_CURRENCY_CODES) + r")" + MONEY_GAP + MONEY_NUMBER + r"(?![A-Za-z0-9])"
    + r"|(?<![A-Za-z0-9])" + MONEY_NUMBER + MONEY_GAP + r"(?:" + "|".join(DISALLOWED_CURRENCY_CODES) + r")(?![A-Za-z])", re.I,
)
DISALLOWED_MONEY_NAME_RE = re.compile(
    r"英镑|欧元|港币|港元|日元|日圆|日圓|澳元|澳币|澳幣|加元|加币|加幣|新加坡元|新加坡币|新元(?!素|数据)|新币|新幣|纽元|紐元|新西兰元|"
    r"瑞士法郎|瑞郎|韩元|韓元|新台币|新臺幣|澳门元|澳門元|澳门币|印度卢比|盧比|卢布|盧布|泰铢|泰銖|林吉特|印尼盾|越南盾|比索|"
    r"迪拉姆|里亚尔|雷亚尔|兰特|克朗|比特币|"
    r"(?<![A-Za-z])(?:pounds? sterling|British pounds?|euros?|Japanese yen|Hong Kong dollars?|Australian dollars?|Canadian dollars?|"
    r"Singapore dollars?|New Zealand dollars?|Swiss francs?|Korean won|Indian rupees?|Russian rubles?)(?![A-Za-z])", re.I,
)
DISALLOWED_MONEY_SIGN_RE = re.compile(r"[£€₩₹₽฿₫₱₴₺₿]|(?<![A-Za-z])(?:HK|AU|CA|SG|NZ|NT|A|C|S|R)\s*\$", re.I)
NATURAL_CURRENCY_CODE_RE = re.compile(
    r"(?<![A-Za-z])(?:USD|CNY|RMB)" + MONEY_GAP + MONEY_NUMBER + r"(?![A-Za-z0-9])"
    + r"|(?<![A-Za-z0-9])" + MONEY_NUMBER + MONEY_GAP + r"(?:USD|CNY|RMB)(?![A-Za-z])", re.I,
)
DOLLAR_AMOUNT_RE = re.compile(r"\$\s*[+-]?" + MONEY_NUMBER)
# Rendering contract: tokens in canonical input name a person/org/mailbox whose
# surface form is chosen later by render_records.py, independently of labels.
RENDER_TOKEN_RE = re.compile(r"\[([A-Z][A-Z_]*)_([1-9][0-9]*)\]")
TOKEN_OWNER = {"PERSON": "PERSON", "SURNAME": "PERSON", "GIVEN": "PERSON", "SIGNATURE": "PERSON",
               "ORG": "ORG", "ORGSHORT": "ORG", "DOMAIN": "ORG", "LOOKALIKE": "ORG",
               "EMAIL": "EMAIL", "USER": "USER", "PHONE": "PHONE"}
RENDER_SECTIONS = {"orgs": "ORG", "people": "PERSON", "mailboxes": "EMAIL", "users": "USER", "phones": "PHONE"}
ORG_KINDS = {"fictional", "real"}
ORG_TYPES = {"company", "school", "hospital"}
MAILBOX_DOMAINS = {"org", "freemail", "lookalike", "external", "observed"}
PHONE_KINDS = {"extension", "landline", "mobile", "hotline"}
SOURCE_ORIGINS = {"web", "user_supplied"}
FEEDBACK_OUTCOMES = {"false_positive", "false_negative"}
LOCAL_PART_RE = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,40}[a-z0-9])?")
HOSTNAME_RE = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, rid, msg):
        self.errors.append(f"ERROR [{rid}] {msg}")

    def warn(self, rid, msg):
        self.warnings.append(f"WARN  [{rid}] {msg}")


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def text_value(value):
    return value if isinstance(value, str) else ""


def reject_constant(value):
    raise ValueError(f"non-JSON numeric constant {value}")


def unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate object key {key!r}")
        result[key] = value
    return result


def parse_json(text):
    return json.loads(text, parse_constant=reject_constant, object_pairs_hook=unique_object)


def load(path, rep):
    try:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    except (OSError, UnicodeError) as exc:
        rep.error("file", f"cannot read UTF-8 input: {exc}")
        return []
    if not text.strip():
        rep.error("file", "dataset is empty")
        return []
    if text.lstrip().startswith("["):
        try:
            return parse_json(text)
        except (ValueError, RecursionError) as exc:
            rep.error("file", f"invalid JSON array: {exc}")
            return []
    records = []
    for n, line in enumerate(text.splitlines(), 1):
        if line.strip():
            try:
                records.append(parse_json(line))
            except (ValueError, RecursionError) as exc:
                rep.error(f"line {n}", f"invalid JSON: {exc}")
    return records


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from strings(value)


def is_reserved(host):
    """Accept a hostname or authority, parsing userinfo/ports before checking."""
    if not isinstance(host, str):
        return False
    try:
        parsed = urlsplit("//" + host)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        parsed.port  # Reject malformed ports instead of guessing the authority.
    except ValueError:
        return False
    parts = hostname.split(".")
    return parts[-1] in RESERVED_TLDS or ".".join(parts[-2:]) in RESERVED_SLDS


def luhn(digits):
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def privacy_segments(text):
    """Yield non-mutating scan views, separating literal links from other text.

    The last @ in a URL authority separates userinfo from host, not a mailbox.
    E-mail addresses inside userinfo, paths or queries are still scanned after
    up to two percent-decoding passes. This is deliberately not a URL crawler.
    """
    end = 0
    for match in URL_TEXT_RE.finditer(text):
        yield text[end:match.start()], False
        url = match.group(0)
        address = re.sub(r"^(?:https?|ftp)://|^//", "", url, flags=re.I)
        parts = re.split(r"([/?#])", address, maxsplit=1)
        authority = parts[0]
        if "@" in authority:
            userinfo, host = authority.rsplit("@", 1)
            authority = userinfo + " / " + host
        view = authority + "".join(parts[1:])
        for _ in range(2):
            decoded = unquote(view)
            if decoded == view:
                break
            view = decoded
        yield view, True
        end = match.end()
    yield text[end:], False


def sensitive_findings(text, allowed_identifiers=(), strict_numbers=False, allow_raw_urls=False):
    """Return heuristic findings; this is not a complete personal-data detector."""
    if allow_raw_urls:
        out = []
        for view, in_url in privacy_segments(text):
            if LITERAL_EMAIL_RE.search(view):
                out.append(("error", "literal e-mail address; use an [EMAIL_n] token"))
            out.extend(numeric_findings(view, allowed_identifiers, strict_numbers, in_url))
        return out
    out = []
    for match in URL_RE.finditer(text):
        if not is_reserved(match.group(1)):
            out.append(("error", f"non-reserved URL host '{match.group(1)}'"))
    rest = URL_RE.sub(" ", text)
    for match in EMAIL_RE.finditer(rest):
        if not is_reserved(match.group(1)):
            out.append(("error", f"non-reserved e-mail domain '{match.group(1)}'"))
    rest = EMAIL_RE.sub(" ", rest)
    for match in DOMAIN_RE.finditer(rest):
        host = match.group(1)
        if host.rsplit(".", 1)[-1].lower() in FILE_EXTS or is_reserved(host):
            continue
        severity = "error" if host.lower().startswith("www.") else "warn"
        out.append((severity, f"bare domain '{host}' is not reserved (review whether it is a domain)"))
    return out + numeric_findings(text, allowed_identifiers, strict_numbers)


def numeric_findings(text, allowed_identifiers=(), strict_numbers=False, in_url=False):
    out = []
    number_text = text
    for value in sorted(allowed_identifiers, key=len, reverse=True):
        # Exempt only complete declared values, never a numeric substring.
        # Declarations cannot hide an entire URL or its embedded private values.
        if URL_TEXT_RE.search(value) or LITERAL_EMAIL_RE.search(value):
            continue
        number_text = re.sub(r"(?<![A-Za-z0-9])" + re.escape(value) + r"(?![A-Za-z0-9])", " ", number_text)
    id_spans = [match.span() for match in IBAN_RE.finditer(number_text)]
    for match in CN_ID_RE.finditer(number_text):
        id_spans.append(match.span())
        severity = "error"
        if in_url:
            value = match.group(0)
            try:
                birthday = datetime.strptime(value[6:14], "%Y%m%d")
                plausible = value[0] != "0" and 1800 <= birthday.year <= date.today().year
            except ValueError:
                plausible = False
            severity = "error" if plausible else "warn"
        out.append((severity, "18-digit string that looks like a resident ID number" if severity == "error"
                    else "18-digit URL value; review whether it is a resource/tracking identifier or private data"))
    for match in DIGIT_RUN_RE.finditer(number_text):
        if any(a <= match.start() < b for a, b in id_spans):
            continue
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) < 12 or CN_MOBILE_RE.fullmatch(match.group(0).strip()):
            continue
        if 13 <= len(digits) <= 19 and luhn(digits):
            out.append(("warn" if in_url else "error", f"{len(digits)}-digit Luhn-valid number (possible payment card; review URL resource/parameter meaning)" if in_url
                        else f"{len(digits)}-digit Luhn-valid number (looks like a payment card)"))
        else:
            severity = "error" if strict_numbers and not in_url else "warn"
            out.append((severity, f"{len(digits)}-digit undeclared number (possible account number; review provenance)"))
    for match in CN_MOBILE_RE.finditer(number_text):
        out.append(("error" if strict_numbers else "warn", "unmasked mainland mobile number (replace with a token or mask)"))
    for match in IBAN_RE.finditer(number_text):
        out.append(("error" if strict_numbers else "warn", "undeclared IBAN-like string (review provenance)"))
    return out


def lang_counts(texts):
    joined = "\n".join(texts)
    for pattern in (URL_TEXT_RE, EMAIL_RE, DOMAIN_RE, REDACTED_RE, ANY_TOKEN_RE, SYN_ID_RE):
        joined = pattern.sub(" ", joined)
    return len(CJK_RE.findall(joined)), len(LATIN_WORD_RE.findall(joined))


def own_body(body):
    return QUOTE_START_RE.split(QUOTE_SPLIT_RE.split(body, maxsplit=1)[0], maxsplit=1)[0]


def substantive_counts(body):
    """Heuristic unique-paragraph counts, excluding common non-authored padding.

    All repeated normalized paragraphs count once. Repeats with at least 40
    weighted units are reported as nontrivial duplicates. English words include
    one-letter words and internal apostrophes/hyphens. No history or headers enter.
    """
    lines = []
    for raw in own_body(body).splitlines():
        line = raw.strip()
        if line == "--" or CLOSING_RE.fullmatch(line) or FOOTER_RE.match(line):
            break
        if re.fullmatch(r"\[PERSON_[0-9]+\]", line):
            if any(part.strip() for part in lines):
                break
            continue
        if GREETING_RE.fullmatch(line) or CONTACT_LINE_RE.match(line):
            continue
        lines.append(raw)
    cleaned = "\n".join(lines)
    # Strip the complete URL, not just the hostname (paths must not add words).
    cleaned = URL_TEXT_RE.sub(" ", cleaned)
    cleaned = DOMAIN_RE.sub(" ", cleaned)
    for pattern in (EMAIL_RE, ANY_TOKEN_RE, SYN_ID_RE):
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"[0-9]+(?:[ \t,./:\-]+[0-9]+)*", " ", cleaned)
    seen, cjk, words, duplicates = set(), 0, 0, 0
    for paragraph in re.split(r"\n[ \t]*\n", cleaned):
        normalized = " ".join(paragraph.split()).casefold()
        if not normalized:
            continue
        pcjk = len(CJK_RE.findall(normalized))
        pwords = len(ENGLISH_WORD_RE.findall(normalized))
        if normalized in seen:
            if pcjk + 2 * pwords >= 40:
                duplicates += 1
            continue
        seen.add(normalized)
        cjk += pcjk
        words += pwords
    return {"cjk": cjk, "english_words": words, "weighted_units": cjk + 2 * words,
            "duplicate_paragraphs": duplicates}


def check_sender(rid, where, sender, rep, v2=False, address_only=False):
    if isinstance(sender, str):
        if not sender.strip():
            rep.error(rid, f"{where} is empty")
        elif address_only and v2 and not EMAIL_TOKEN_RE.fullmatch(sender):
            rep.error(rid, f"{where} must be an [EMAIL_n] token")
    elif isinstance(sender, dict):
        name, addr = sender.get("name"), sender.get("address")
        for field, value in (("name", name), ("address", addr)):
            if field in sender and not nonempty(value):
                rep.error(rid, f"{where}.{field} must be a non-empty string")
        if not (nonempty(name) or nonempty(addr)):
            rep.error(rid, f"{where} needs a name or address")
        if nonempty(addr):
            if v2 and not EMAIL_TOKEN_RE.fullmatch(addr):
                rep.error(rid, f"{where}.address must be an [EMAIL_n] token")
            elif not v2 and not EMAIL_RE.fullmatch(addr) and not REDACTED_RE.search(addr):
                rep.warn(rid, f"{where}.address is not an e-mail address")
        if address_only and v2 and not nonempty(addr):
            rep.error(rid, f"{where}.address is required for a recipient")
    else:
        rep.error(rid, f"{where} must be a string or an object")


def check_message(message, rid, where, rep, v2, current=False, require_sent_at=False, as_of=None):
    if not isinstance(message, dict):
        rep.error(rid, f"{where} must be an object")
        return {}, ["", ""]
    if current or v2 or "from" in message:
        check_sender(rid, where + ".from", message.get("from"), rep, v2)
    if current or v2 or "subject" in message:
        if not isinstance(message.get("subject"), str):
            rep.error(rid, f"{where}.subject must be a string")
    if not nonempty(message.get("body")):
        rep.error(rid, f"{where}.body must be a non-empty string")
    for field in ("to", "cc"):
        if field not in message:
            continue
        recipients = message[field]
        if not isinstance(recipients, list):
            rep.error(rid, f"{where}.{field} must be a list")
        else:
            for i, recipient in enumerate(recipients):
                check_sender(rid, f"{where}.{field}[{i}]", recipient, rep, v2, True)
    if message.get("reply_to") is not None:
        check_sender(rid, where + ".reply_to", message["reply_to"], rep, v2, True)
    if "sent_at" in message:
        stamp = message["sent_at"]
        try:
            if not isinstance(stamp, str) or "T" not in stamp:
                raise ValueError("timestamp needs an ISO date and time")
            parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if (v2 or as_of is not None) and parsed.tzinfo is None:
                raise ValueError("timestamp needs a time zone")
            if as_of is not None and (parsed.year != as_of.year or parsed.date() > as_of):
                rep.error(rid, f"{where}.sent_at must be between {as_of.year}-01-01 and {as_of} "
                               f"under --require-current-year (got {parsed.date()})")
        except ValueError as exc:
            rep.error(rid, f"{where}.sent_at invalid ISO timestamp: {exc}")
    elif require_sent_at or as_of is not None:
        rep.error(rid, f"{where}.sent_at is required")
    if "attachments" in message:
        attachments = message["attachments"]
        if not isinstance(attachments, list):
            rep.error(rid, f"{where}.attachments must be a list")
        else:
            for i, attachment in enumerate(attachments):
                if not isinstance(attachment, dict) or not all(nonempty(attachment.get(k)) for k in ("name", "type")):
                    rep.error(rid, f"{where}.attachments[{i}] needs non-empty name and type strings")
    return message, [text_value(message.get("subject")), own_body(text_value(message.get("body")))]


def pointer_parts(path):
    if not isinstance(path, str) or not path.startswith("/input/"):
        raise ValueError("path must point inside /input")
    if re.search(r"~(?![01])", path):
        raise ValueError("invalid JSON Pointer escape")
    return [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]


def resolve_pointer(record, path):
    node = record
    for part in pointer_parts(path):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and re.fullmatch(r"0|[1-9][0-9]*", part) and int(part) < len(node):
            node = node[int(part)]
        else:
            raise ValueError("path does not resolve")
    return node


def check_spans(record, evidence, rid, where, rep):
    spans = evidence.get("spans")
    if not isinstance(spans, list) or not spans:
        rep.error(rid, f"{where}.spans must be a non-empty list")
        return
    for i, span in enumerate(spans):
        loc = f"{where}.spans[{i}]"
        if not isinstance(span, dict) or not nonempty(span.get("quote")):
            rep.error(rid, f"{loc} needs a path and non-empty quote")
            continue
        try:
            value = resolve_pointer(record, span.get("path"))
            if not isinstance(value, str):
                raise ValueError("target must be a string")
            if span["quote"] not in value:
                raise ValueError("quote is not an exact substring of the target")
        except ValueError as exc:
            rep.error(rid, f"{loc}: {exc}")


def check_provenance(prov, rid, rep):
    if prov.get("kind") == "synthetic" and not nonempty(prov.get("synthetic_scope")):
        rep.error(rid, "synthetic provenance requires a non-empty synthetic_scope")
    source_ids = set()
    sources = prov.get("sources")
    if not isinstance(sources, list) or not sources:
        rep.error(rid, "provenance.sources must be a non-empty list")
    else:
        for i, source in enumerate(sources):
            where = f"provenance.sources[{i}]"
            if not isinstance(source, dict):
                rep.error(rid, f"{where} must be an object")
                continue
            origin = source.get("origin", "web")
            if not isinstance(origin, str) or origin not in SOURCE_ORIGINS:
                rep.error(rid, f"{where}.origin must be one of {sorted(SOURCE_ORIGINS)} when present")
            # A supplied original email has no public address; it is still cited by ID.
            required = ("id", "title", "publisher", "accessed_at", "supports") + (() if origin == "user_supplied" else ("url",))
            for key in required:
                if not nonempty(source.get(key)):
                    rep.error(rid, f"{where}.{key} must be a non-empty string")
            if origin == "user_supplied" and "url" in source and not nonempty(source.get("url")):
                rep.error(rid, f"{where}.url must be a non-empty string when present")
            sid = source.get("id")
            if nonempty(sid):
                if sid in source_ids:
                    rep.error(rid, f"{where}.id is duplicated")
                source_ids.add(sid)
            if nonempty(source.get("url")):
                try:
                    parsed = urlsplit(source["url"])
                    if parsed.scheme not in ("https", "http") or not parsed.hostname or re.search(r"\s", source["url"]):
                        raise ValueError("expected an absolute HTTP(S) URL")
                    parsed.port
                except ValueError as exc:
                    rep.error(rid, f"{where}.url invalid: {exc}")
            if nonempty(source.get("accessed_at")):
                try:
                    value = source["accessed_at"]
                    datetime.fromisoformat(value.replace("Z", "+00:00")) if "T" in value else date.fromisoformat(value)
                except ValueError:
                    rep.error(rid, f"{where}.accessed_at must be an ISO date or timestamp")
    allowed_identifiers = []
    entities = prov.get("entities")
    entity_names = {entity["name"] for entity in entities
                    if isinstance(entity, dict) and nonempty(entity.get("name"))} if isinstance(entities, list) else set()
    if "identifiers" in prov:
        identifiers = prov["identifiers"]
        if not isinstance(identifiers, list):
            rep.error(rid, "provenance.identifiers must be a list")
        else:
            for i, identifier in enumerate(identifiers):
                where = f"provenance.identifiers[{i}]"
                if not isinstance(identifier, dict):
                    rep.error(rid, f"{where} must be an object")
                    continue
                valid = True
                for key, allowed in (("kind", {"institution_code", "customer_number", "bank_account"}),
                                     ("basis", {"official_public", "user_authorized_source"})):
                    if not isinstance(identifier.get(key), str) or identifier[key] not in allowed:
                        rep.error(rid, f"{where}.{key} must be one of {sorted(allowed)}")
                        valid = False
                value, refs = identifier.get("value"), identifier.get("source_ids")
                if not nonempty(value):
                    rep.error(rid, f"{where}.value must be a non-empty string")
                    valid = False
                elif URL_TEXT_RE.search(value) or LITERAL_EMAIL_RE.search(value):
                    rep.error(rid, f"{where}.value must be an identifier, not a URL or e-mail address")
                    valid = False
                for key in ("owner", "bank", "code_system", "usage_scope"):
                    if key in identifier and not nonempty(identifier[key]):
                        rep.error(rid, f"{where}.{key} must be a non-empty string when present")
                        valid = False
                kind = identifier.get("kind")
                required = {"bank_account": ("owner", "bank"),
                            "institution_code": ("owner", "code_system"),
                            "customer_number": ("owner",)}.get(kind, ()) if isinstance(kind, str) else ()
                for key in required:
                    if not nonempty(identifier.get(key)):
                        rep.error(rid, f"{where}.{key} is required for {kind}")
                        valid = False
                for key in ("owner", "bank"):
                    if nonempty(identifier.get(key)) and identifier[key] not in entity_names:
                        rep.error(rid, f"{where}.{key} must exactly match a provenance.entities name")
                        valid = False
                if (not isinstance(refs, list) or not refs or any(not nonempty(ref) for ref in refs)
                        or len(set(refs)) != len(refs) or any(ref not in source_ids for ref in refs)):
                    rep.error(rid, f"{where}.source_ids must uniquely reference existing source IDs")
                    valid = False
                if valid:
                    allowed_identifiers.append(value)
    if not isinstance(entities, list):
        rep.error(rid, "provenance.entities must be a list")
    else:
        seen_entities = set()
        for i, entity in enumerate(entities):
            where = f"provenance.entities[{i}]"
            if not isinstance(entity, dict):
                rep.error(rid, f"{where} must be an object")
                continue
            for key in ("name", "role"):
                if not nonempty(entity.get(key)):
                    rep.error(rid, f"{where}.{key} must be a non-empty string")
            if nonempty(entity.get("name")) and nonempty(entity.get("role")):
                key = (entity["name"], entity["role"])
                if key in seen_entities:
                    rep.error(rid, f"{where} duplicates an entity name/role")
                seen_entities.add(key)
            refs = entity.get("source_ids")
            if not isinstance(refs, list) or not refs or any(not nonempty(ref) for ref in refs):
                rep.error(rid, f"{where}.source_ids must be a non-empty list of source IDs")
            elif len(set(refs)) != len(refs) or any(ref not in source_ids for ref in refs):
                rep.error(rid, f"{where}.source_ids must be unique and reference existing provenance.sources IDs")
    return allowed_identifiers


def currency_observations(text):
    """Recognize explicit currency text, not arbitrary numbers or SWIFT codes.

    NFKC handles fullwidth codes, digits and signs. Unsupported three-letter
    codes count only next to a number; explicit names/signs count by themselves.
    This does not infer a currency from an unlabelled amount or convert values.
    """
    # Resource/query text is not a monetary assertion in the correspondence.
    normalized = unicodedata.normalize("NFKC", URL_TEXT_RE.sub(" ", text))
    observed = set()
    if re.search(r"人民币|人民幣|[¥￥]|(?<![A-Za-z0-9_])(?:CNY|RMB)(?![A-Za-z0-9_])|" + MONEY_NUMBER + r"\s*(?:万|亿)?元", normalized, re.I):
        observed.add("CNY")
    if re.search(r"美元|美金|(?<![A-Za-z0-9_])USD(?![A-Za-z0-9_])|US\s*\$", normalized, re.I) or DOLLAR_AMOUNT_RE.search(normalized):
        observed.add("USD")
    for match in NATURAL_CURRENCY_CODE_RE.finditer(normalized):
        observed.add("USD" if "USD" in match.group(0).upper() else "CNY")
    disallowed = []
    for pattern in (DISALLOWED_MONEY_CODE_RE, DISALLOWED_MONEY_NAME_RE, DISALLOWED_MONEY_SIGN_RE):
        disallowed.extend(match.group(0) for match in pattern.finditer(normalized))
    return normalized, observed, disallowed


def check_cn_context(record, rid, rep, require=False):
    active = require or any(field in record for field in CN_CONTEXT_FIELDS)
    if not active:
        return
    if record.get("business_region") != "CN":
        rep.error(rid, "CN context requires business_region 'CN'")
    scope = record.get("transaction_scope")
    if not isinstance(scope, str) or scope not in {"domestic", "cross_border"}:
        rep.error(rid, "transaction_scope must be domestic or cross_border")
    currencies = record.get("currencies")
    if (not isinstance(currencies, list) or any(not isinstance(value, str) or value not in {"CNY", "USD"} for value in currencies)
            or len(set(currencies)) != len(currencies)):
        rep.error(rid, "currencies must be a unique list containing only CNY and/or USD (or empty)")
        declared = set()
    else:
        declared = set(currencies)
    context = record.get("cross_border_context")
    currency_context = record.get("currency_context")
    for field in ("cross_border_context", "currency_context"):
        if field in record and not isinstance(record[field], str):
            rep.error(rid, f"{field} must be a string when present")
    inp = record.get("input") if isinstance(record.get("input"), dict) else {}
    observed = set()
    disallowed = set()
    for text in strings([inp, record.get("target"), record.get("scenario"), record.get("notes")]):
        _, currencies_found, unsupported = currency_observations(text)
        observed |= currencies_found
        disallowed.update(unsupported)
    if disallowed:
        rep.error(rid, "CN context permits only CNY and USD with a business reason; unsupported currency text: " + ", ".join(sorted(disallowed)))
    if observed - declared:
        rep.error(rid, "observed currency missing from currencies metadata: " + ", ".join(sorted(observed - declared)))
    usd_present = "USD" in declared or "USD" in observed
    if scope == "cross_border" and not nonempty(context):
        rep.error(rid, "cross-border records require non-empty cross_border_context")
    if usd_present:
        if scope == "domestic" and not nonempty(currency_context):
            rep.error(rid, "domestic USD records require non-empty currency_context explaining the foreign-currency business")
        elif not (nonempty(currency_context) or nonempty(context)):
            rep.error(rid, "USD records require non-empty currency_context or cross_border_context")
    if scope == "cross_border" or usd_present:
        if not nonempty(inp.get("business_context")):
            rep.error(rid, "cross-border/USD records require non-empty input.business_context")
    for text in strings(inp):
        normalized = unicodedata.normalize("NFKC", text)
        if NATURAL_CURRENCY_CODE_RE.search(normalized):
            rep.error(rid, "input currency amounts must use natural wording/symbols, not USD/CNY/RMB next to digits")
            break
    if record.get("language") in ("zh", "zh-en") and any(DOLLAR_AMOUNT_RE.search(unicodedata.normalize("NFKC", text)) for text in strings(inp)):
        rep.error(rid, "Chinese input must write dollar amounts with 美元/美金 rather than a dollar sign")


def check_grounding(record, prov, rid, rep, require=False, as_of=None):
    """Validate declared provenance links, not source truth or complete support."""
    kind = prov.get("kind")
    active = require or "grounding" in prov or kind == "source-adapted"
    if not active:
        return
    if require and record.get("schema_version") != "2.0":
        rep.error(rid, "--require-grounding requires schema_version '2.0'")
    if not isinstance(kind, str) or kind not in {"source-adapted", "redacted-source"}:
        rep.error(rid, "grounded records require provenance.kind source-adapted or redacted-source; synthetic is legacy-only")
    sources = prov.get("sources")
    source_roles = {}
    if not isinstance(sources, list) or not sources:
        rep.error(rid, "grounding requires a non-empty provenance.sources list")
    else:
        for i, source in enumerate(sources):
            where = f"provenance.sources[{i}]"
            if not isinstance(source, dict) or not nonempty(source.get("id")):
                rep.error(rid, f"{where} must be an object with a non-empty source id")
                continue
            roles = source.get("roles")
            if (not isinstance(roles, list) or not roles
                    or any(not isinstance(role, str) or role not in SOURCE_ROLES for role in roles)):
                rep.error(rid, f"{where}.roles must be a non-empty list drawn from {sorted(SOURCE_ROLES)}")
                roles = []
            if source["id"] in source_roles:
                rep.error(rid, f"{where}.id is duplicated")
            source_roles[source["id"]] = set(roles)
    grounding = prov.get("grounding")
    if not isinstance(grounding, dict):
        rep.error(rid, "provenance.grounding must be an object for grounded records")
        return
    if not nonempty(grounding.get("theme")):
        rep.error(rid, "provenance.grounding.theme must be a non-empty string")
    if kind == "source-adapted" and not nonempty(grounding.get("adaptation_scope")):
        rep.error(rid, "source-adapted grounding requires non-empty adaptation_scope describing edits and their non-verbatim status")
    context = grounding.get("context")
    for field in ("region", "period", "setting"):
        if not isinstance(context, dict) or not nonempty(context.get(field)):
            rep.error(rid, f"provenance.grounding.context.{field} must be a non-empty string")
    if as_of is not None and isinstance(context, dict) and nonempty(context.get("period")):
        scenario_year = re.search(r"(?<!\d)[0-9]{4}(?!\d)", context["period"])
        if not scenario_year or int(scenario_year.group()) != as_of.year:
            rep.error(rid, f"provenance.grounding.context.period must give the scenario year {as_of.year} first "
                           "under --require-current-year")
    material = grounding.get("source_material")
    material_source_ids = set()
    if not isinstance(material, dict):
        rep.error(rid, "provenance.grounding.source_material must be an object")
    else:
        if not isinstance(material.get("type"), str) or material["type"] not in MATERIAL_TYPES:
            rep.error(rid, f"provenance.grounding.source_material.type must be one of {sorted(MATERIAL_TYPES)}")
        refs = material.get("source_ids")
        if not isinstance(refs, list) or not refs or any(not nonempty(ref) or ref not in source_roles for ref in refs):
            rep.error(rid, "provenance.grounding.source_material.source_ids must reference existing sources")
        else:
            material_source_ids = {ref for ref in refs if "material" in source_roles[ref]}
            if not material_source_ids:
                rep.error(rid, "source_material must reference at least one material-role source; entity/context/policy-only pages do not qualify")
    retrieval = grounding.get("retrieval")
    supplied_only = (isinstance(sources, list) and bool(sources)
                     and all(isinstance(source, dict) and source.get("origin") == "user_supplied" for source in sources))
    if retrieval is None and supplied_only:
        pass  # Nothing was searched; a fabricated query log would be worse than none.
    elif not isinstance(retrieval, dict):
        rep.error(rid, "provenance.grounding.retrieval must be an object")
    else:
        queries = retrieval.get("queries")
        if not isinstance(queries, list) or not queries or any(not nonempty(query) for query in queries):
            rep.error(rid, "provenance.grounding.retrieval.queries must be a non-empty list of non-empty strings")
        searched_at = retrieval.get("searched_at")
        try:
            if not isinstance(searched_at, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", searched_at):
                raise ValueError
            date.fromisoformat(searched_at)
        except ValueError:
            rep.error(rid, "provenance.grounding.retrieval.searched_at must be an ISO calendar date (YYYY-MM-DD)")
    transformations = grounding.get("transformations")
    if (not isinstance(transformations, list) or not transformations
            or any(not isinstance(item, str) or item not in GROUNDING_TRANSFORMATIONS for item in transformations)):
        rep.error(rid, f"provenance.grounding.transformations must be a non-empty list drawn from {sorted(GROUNDING_TRANSFORMATIONS)}")
    elif kind == "redacted-source" and {"faithful_paraphrase", "translation", "scenario_adaptation"}.intersection(transformations):
        rep.error(rid, "redacted-source cannot include paraphrase, translation or scenario adaptation; use provenance.kind source-adapted")
    scenario_adaptation = isinstance(transformations, list) and "scenario_adaptation" in transformations
    fully_adapted = kind == "source-adapted" and scenario_adaptation
    fact_map = grounding.get("fact_map")
    covered = set()
    material_covered = set()
    if not isinstance(fact_map, list):
        rep.error(rid, "provenance.grounding.fact_map must be a list")
    elif not fact_map and not fully_adapted:
        rep.error(rid, "provenance.grounding.fact_map must be a non-empty list outside source-adapted scenarios")
    else:
        for i, fact in enumerate(fact_map):
            where = f"provenance.grounding.fact_map[{i}]"
            if not isinstance(fact, dict):
                rep.error(rid, f"{where} must be an object")
                continue
            valid = True
            for field in ("input_path", "input_quote", "source_id", "locator", "source_claim"):
                if not nonempty(fact.get(field)):
                    rep.error(rid, f"{where}.{field} must be a non-empty string")
                    valid = False
            if nonempty(fact.get("source_id")) and fact["source_id"] not in source_roles:
                rep.error(rid, f"{where}.source_id does not reference an existing source")
                valid = False
            if nonempty(fact.get("input_path")) and nonempty(fact.get("input_quote")):
                try:
                    value = resolve_pointer(record, fact["input_path"])
                    if not isinstance(value, str):
                        raise ValueError("input_path must target a string inside /input")
                    if fact["input_quote"] not in value:
                        raise ValueError("input_quote must be an exact substring of its target")
                except ValueError as exc:
                    rep.error(rid, f"{where}: {exc}")
                    valid = False
            if valid:
                covered.add(fact["input_path"])
                if fact["source_id"] in material_source_ids:
                    material_covered.add(fact["input_path"])
    adaptations = grounding.get("adaptations")
    if "adaptations" in grounding or scenario_adaptation:
        if not isinstance(adaptations, list) or not adaptations:
            rep.error(rid, "grounding.adaptations must be a non-empty list when present or when scenario_adaptation is declared")
        else:
            if not scenario_adaptation:
                rep.error(rid, "non-empty grounding.adaptations require the scenario_adaptation transformation")
            if kind == "redacted-source":
                rep.error(rid, "redacted-source cannot contain adaptations; use provenance.kind source-adapted")
            for i, adaptation in enumerate(adaptations):
                where = f"provenance.grounding.adaptations[{i}]"
                if not isinstance(adaptation, dict):
                    rep.error(rid, f"{where} must be an object")
                    continue
                valid = True
                for field in ("input_path", "input_quote", "change", "reason"):
                    if not nonempty(adaptation.get(field)):
                        rep.error(rid, f"{where}.{field} must be a non-empty string")
                        valid = False
                if "source_claim" in adaptation:
                    rep.error(rid, f"{where} must describe change/reason, not source_claim; source facts belong in fact_map")
                    valid = False
                refs = adaptation.get("basis_source_ids")
                if not isinstance(refs, list) or not refs or any(not nonempty(ref) or ref not in source_roles for ref in refs):
                    rep.error(rid, f"{where}.basis_source_ids must reference existing sources")
                    valid = False
                elif not any(ref in material_source_ids for ref in refs):
                    rep.error(rid, f"{where}.basis_source_ids must include a selected material-role source")
                    valid = False
                if nonempty(adaptation.get("input_path")) and nonempty(adaptation.get("input_quote")):
                    try:
                        value = resolve_pointer(record, adaptation["input_path"])
                        if not isinstance(value, str):
                            raise ValueError("input_path must target a string inside /input")
                        if adaptation["input_quote"] not in value:
                            raise ValueError("input_quote must be an exact substring of its target")
                    except ValueError as exc:
                        rep.error(rid, f"{where}: {exc}")
                        valid = False
                if valid:
                    covered.add(adaptation["input_path"])
                    material_covered.add(adaptation["input_path"])
    body_paths = {"/input/current_email/body"}
    inp = record.get("input")
    if isinstance(inp, dict):
        if isinstance(inp.get("history"), list):
            body_paths.update(f"/input/history/{i}/body" for i in range(len(inp["history"])))
    required_paths = set(body_paths)
    if isinstance(inp, dict) and "business_context" in inp:
        required_paths.add("/input/business_context")
    for path in sorted(required_paths - covered):
        rep.error(rid, f"grounding lacks a valid fact_map or adaptation supporting mapping for {path}")
    for path in sorted((body_paths & covered) - material_covered):
        rep.error(rid, f"grounding requires a body mapping to a material-role source listed in source_material.source_ids for {path}")


def input_token_uses(inp):
    """Return (token kind, declaring key) pairs, e.g. ('SURNAME', 'PERSON_2')."""
    uses = set()
    for text in strings(inp):
        for kind, index in RENDER_TOKEN_RE.findall(text):
            if kind in TOKEN_OWNER:
                uses.add((kind, f"{TOKEN_OWNER[kind]}_{index}"))
    return uses


def parse_stamp(stamp):
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if isinstance(stamp, str) and "T" in stamp else None
    except ValueError:
        return None
    return parsed if parsed is not None and parsed.tzinfo is not None else None


def check_render(record, prov, rid, rep, require=False):
    """Validate declared render relationships; surface names are chosen only by the renderer."""
    render = record.get("render")
    if render is None:
        if require:
            rep.error(rid, "--require-render requires a render object declaring people, organizations and mailboxes")
        return
    if not isinstance(render, dict):
        rep.error(rid, "render must be an object")
        return
    for key in sorted(set(render) - set(RENDER_SECTIONS) - {"style"}):
        rep.error(rid, f"render.{key} is not a defined render section")
    if "style" in render and not isinstance(render["style"], dict):
        rep.error(rid, "render.style must be an object when present")
    sections = {}
    for section, prefix in RENDER_SECTIONS.items():
        value = render.get(section, {})
        if not isinstance(value, dict):
            rep.error(rid, f"render.{section} must be an object keyed by {prefix}_n")
            value = {}
        sections[section] = {}
        for key, item in value.items():
            if not re.fullmatch(prefix + r"_[1-9][0-9]*", key):
                rep.error(rid, f"render.{section} key '{key}' must look like {prefix}_n")
            elif not isinstance(item, dict):
                rep.error(rid, f"render.{section}.{key} must be an object")
            else:
                sections[section][key] = item
    orgs, people, mailboxes = sections["orgs"], sections["people"], sections["mailboxes"]
    sources = prov.get("sources") if isinstance(prov.get("sources"), list) else []
    source_ids = {source.get("id") for source in sources if isinstance(source, dict)}
    entities = prov.get("entities") if isinstance(prov.get("entities"), list) else []
    entity_names = {entity.get("name") for entity in entities if isinstance(entity, dict)}

    def require_sources(where, item):
        refs = item.get("source_ids")
        if not isinstance(refs, list) or not refs or any(not nonempty(ref) or ref not in source_ids for ref in refs):
            rep.error(rid, f"{where}.source_ids must reference existing provenance.sources IDs")

    def optional_strings(where, item, keys):
        for key in keys:
            if key in item and not nonempty(item[key]):
                rep.error(rid, f"{where}.{key} must be a non-empty string when present")

    def check_enum(where, item, key, allowed):
        if key in item and (not isinstance(item[key], str) or item[key] not in allowed):
            rep.error(rid, f"{where}.{key} must be one of {sorted(allowed)}")

    for key, org in orgs.items():
        where = f"render.orgs.{key}"
        kind = org.get("kind")
        if not isinstance(kind, str) or kind not in ORG_KINDS:
            rep.error(rid, f"{where}.kind must be one of {sorted(ORG_KINDS)}")
        elif kind == "fictional":
            for field in ("region", "industry"):
                if not nonempty(org.get(field)):
                    rep.error(rid, f"{where}.{field} is required for a fictional organization")
            check_enum(where, org, "org_type", ORG_TYPES)
            optional_strings(where, org, ("suffix",))
            for field in ("name", "domain", "source_ids"):
                if field in org:
                    rep.error(rid, f"{where}.{field}: fictional organizations get names and domains from the renderer")
        else:
            if not nonempty(org.get("name")) or org["name"] not in entity_names:
                rep.error(rid, f"{where}.name must exactly match a provenance.entities name for a real organization")
            require_sources(where, org)
            if "domain" in org and (not isinstance(org["domain"], str) or not HOSTNAME_RE.fullmatch(org["domain"])):
                rep.error(rid, f"{where}.domain must be a lowercase hostname")
    for key, person in people.items():
        where = f"render.people.{key}"
        if "org" in person and (not isinstance(person["org"], str) or person["org"] not in orgs):
            rep.error(rid, f"{where}.org must reference a render.orgs key")
        check_enum(where, person, "gender", {"m", "f"})
        check_enum(where, person, "device", {"desktop", "mobile"})
        optional_strings(where, person, ("dept", "title"))
        if "name" in person:
            rep.error(rid, f"{where}.name: person names are chosen by the renderer, never stored")
    for key, box in mailboxes.items():
        where = f"render.mailboxes.{key}"
        owner, domain = box.get("owner"), box.get("domain")
        owner = owner if isinstance(owner, str) else None
        if owner not in people and owner not in orgs:
            rep.error(rid, f"{where}.owner must reference a render.people or render.orgs key")
        if not isinstance(domain, str) or domain not in MAILBOX_DOMAINS:
            rep.error(rid, f"{where}.domain must be one of {sorted(MAILBOX_DOMAINS)}")
        if "local" in box and (not isinstance(box["local"], str) or not LOCAL_PART_RE.fullmatch(box["local"])):
            rep.error(rid, f"{where}.local must be a lowercase role-style local part such as 'hr' or 'noreply'")
        if "provider" in box and (domain != "freemail" or not isinstance(box["provider"], str)
                                  or not HOSTNAME_RE.fullmatch(box["provider"])):
            rep.error(rid, f"{where}.provider is a hostname allowed only for freemail mailboxes")
        if "value" in box:
            if not isinstance(box["value"], str) or not HOSTNAME_RE.fullmatch(box["value"]):
                rep.error(rid, f"{where}.value must be a lowercase hostname")
            require_sources(where, box)
        elif domain == "observed":
            rep.error(rid, f"{where}: observed mailboxes require the observed domain as value")
        org_key = owner if owner in orgs else people[owner].get("org") if owner in people else None
        org_key = org_key if isinstance(org_key, str) else None
        if domain in ("org", "lookalike"):
            org = orgs.get(org_key)
            if org is None:
                rep.error(rid, f"{where}: domain '{domain}' needs an owner that belongs to a render.orgs entry")
            elif org.get("kind") == "real" and domain == "org" and not nonempty(org.get("domain")):
                rep.error(rid, f"{where}: a real organization's mailbox needs that organization's sourced domain")
            elif org.get("kind") == "real" and domain == "lookalike" and "value" not in box:
                rep.error(rid, f"{where}: a lookalike of a real organization must be a sourced indicator value, never generated")
    for key, user in sections["users"].items():
        if "owner" in user and (not isinstance(user["owner"], str) or user["owner"] not in people):
            rep.error(rid, f"render.users.{key}.owner must reference a render.people key")
    for key, phone in sections["phones"].items():
        check_enum(f"render.phones.{key}", phone, "kind", PHONE_KINDS)
        if "owner" in phone and (not isinstance(phone["owner"], str) or (phone["owner"] not in people and phone["owner"] not in orgs)):
            rep.error(rid, f"render.phones.{key}.owner must reference a render.people or render.orgs key")
    inp = record.get("input") if isinstance(record.get("input"), dict) else {}
    section_of = {prefix: section for section, prefix in RENDER_SECTIONS.items()}
    for kind, key in sorted(input_token_uses(inp)):
        prefix = key.split("_")[0]
        if prefix in ("USER", "PHONE"):
            continue  # Optional declarations; the renderer has neutral defaults.
        if key not in sections[section_of[prefix]]:
            rep.error(rid, f"input uses [{kind}_{key.split('_')[1]}] but render.{section_of[prefix]} does not declare {key}")
        elif prefix == "ORG" and orgs[key].get("kind") == "real":
            if kind == "LOOKALIKE":
                rep.error(rid, f"[LOOKALIKE_{key.split('_')[1]}] cannot be generated for a real organization; use a sourced mailbox or URL value")
            elif kind == "DOMAIN" and not nonempty(orgs[key].get("domain")):
                rep.error(rid, f"[DOMAIN_{key.split('_')[1]}] needs the real organization's sourced domain")
    if not require:
        return
    history = inp.get("history") if isinstance(inp.get("history"), list) else []
    messages = [(f"input.history[{i}]", message) for i, message in enumerate(history)]
    messages.append(("input.current_email", inp.get("current_email")))
    stamps = []
    for where, message in messages:
        if not isinstance(message, dict):
            continue
        sender = message.get("from")
        if not isinstance(sender, dict) or not isinstance(sender.get("address"), str) or not EMAIL_TOKEN_RE.fullmatch(sender["address"]):
            rep.error(rid, f"{where}.from must be an object with an [EMAIL_n] address under --require-render")
        stamps.append(parse_stamp(message.get("sent_at")))
    current = inp.get("current_email")
    if isinstance(current, dict) and (not isinstance(current.get("to"), list) or not current["to"]):
        rep.error(rid, "input.current_email.to must list at least one recipient under --require-render")
    if all(stamps) and any(later < earlier for earlier, later in zip(stamps, stamps[1:])):
        rep.error(rid, "message sent_at values must run in chronological order with the current email last")


def check_feedback(record, prov, rid, rep):
    """A real detector miss (false positive/negative) recorded outside classifier input."""
    feedback = prov.get("detector_feedback")
    if feedback is None:
        return
    if not isinstance(feedback, dict):
        rep.error(rid, "provenance.detector_feedback must be an object")
        return
    for key in ("detector", "observed_verdict", "review_basis"):
        if not nonempty(feedback.get(key)):
            rep.error(rid, f"provenance.detector_feedback.{key} must be a non-empty string")
    outcome = feedback.get("outcome")
    if not isinstance(outcome, str) or outcome not in FEEDBACK_OUTCOMES:
        rep.error(rid, f"provenance.detector_feedback.outcome must be one of {sorted(FEEDBACK_OUTCOMES)}")
    try:
        date.fromisoformat(feedback.get("observed_at") if isinstance(feedback.get("observed_at"), str) else "")
    except ValueError:
        rep.error(rid, "provenance.detector_feedback.observed_at must be an ISO calendar date (YYYY-MM-DD)")
    if prov.get("kind") != "redacted-source":
        rep.error(rid, "detector_feedback belongs on the real observed email (redacted-source); generated variants share its source_group instead")
    label = (record.get("target") or {}).get("label") if isinstance(record.get("target"), dict) else None
    expected = {"false_positive": "benign", "false_negative": "malicious"}.get(outcome)
    if expected and label != expected and label in ("benign", "malicious"):
        rep.error(rid, f"a {outcome} record must carry the reviewed label '{expected}', not the detector's verdict")
    if not nonempty(record.get("source_group")):
        rep.warn(rid, "detector_feedback record has no source_group; generated variants cannot be grouped with it for splitting")


def check_record(rec, idx, labels, codes, rep, seen, strict=False, require_detailed=False, require_cn_context=False,
                 require_grounding=False, require_raw_urls=False, require_render=False, as_of=None):
    if not isinstance(rec, dict):
        rep.error(f"#{idx}", "record is not a JSON object")
        return None
    rid = rec.get("id")
    if not nonempty(rid):
        rep.error(f"#{idx}", "missing or invalid id")
        rid = f"#{idx}"
    elif rid in seen:
        rep.error(rid, "duplicate id")
    seen.add(rid)
    check_cn_context(rec, rid, rep, require=require_cn_context)
    profile = rec.get("content_profile")
    if "content_profile" in rec and (not isinstance(profile, str) or profile not in {"detailed", "concise"}):
        rep.error(rid, "content_profile must be detailed or concise when present")
    if require_detailed and profile != "detailed":
        rep.error(rid, "--require-detailed requires content_profile 'detailed'")
    if "register" in rec and (not isinstance(rec["register"], str) or rec["register"] not in {"daily_business", "customer_service", "formal_notice"}):
        rep.error(rid, "register must be daily_business, customer_service or formal_notice when present")
    version = rec.get("schema_version")
    v2 = version == "2.0"
    if strict and not v2:
        rep.error(rid, "--strict requires schema_version '2.0'")
    elif version is not None and version not in ("1.0", "2.0"):
        rep.error(rid, "unsupported schema_version (expected '1.0' or '2.0')")
    if v2:
        id_tokens = set(re.split(r"[^A-Za-z0-9]+", rid.lower()))
        label_tokens = {label.lower() for label in labels if len(label) > 1} | {"malicious", "benign", "phishing", "m", "b"}
        if id_tokens & label_tokens:
            rep.error(rid, "v2 id must be opaque and must not encode the label")
        for key in ("scenario_type", "thread_family_id"):
            if not nonempty(rec.get(key)):
                rep.error(rid, f"v2 {key} must be a non-empty string")
        if not isinstance(rec.get("domain"), str) or rec["domain"] not in DOMAINS:
            rep.error(rid, f"v2 domain must be one of {sorted(DOMAINS)}")
    for key in ("pair_id", "scenario_type", "thread_family_id", "source_group", "template_family_id"):
        if key in rec and not nonempty(rec[key]):
            rep.error(rid, f"{key} must be a non-empty string when present")
    if not nonempty(rec.get("scenario")):
        rep.error(rid, "scenario must be a non-empty string")
    prov = rec.get("provenance") if isinstance(rec.get("provenance"), dict) else {}
    kind = prov.get("kind")
    if kind in ("source", "redacted-source"):
        as_of = None  # Imported correspondence keeps its original timeline.
    allowed_kinds = {"synthetic", "redacted-source", "source-adapted"} if v2 else PROV_KINDS
    if not isinstance(kind, str) or kind not in allowed_kinds:
        rep.error(rid, f"provenance.kind must be one of {sorted(allowed_kinds)}")
    allowed_identifiers = check_provenance(prov, rid, rep) if v2 else []
    check_grounding(rec, prov, rid, rep, require=require_grounding, as_of=as_of)
    check_render(rec, prov, rid, rep, require=require_render)
    check_feedback(rec, prov, rid, rep)
    lang = rec.get("language")
    if not isinstance(lang, str) or lang not in LANGS:
        rep.error(rid, f"language must be one of {sorted(LANGS)}")
    difficulty = rec.get("difficulty")
    if v2 or "difficulty" in rec:
        if not isinstance(difficulty, str) or difficulty not in DIFFICULTIES:
            rep.error(rid, f"difficulty must be one of {sorted(DIFFICULTIES)}")
    inp = rec.get("input") if isinstance(rec.get("input"), dict) else {}
    if "business_context" in inp and not isinstance(inp["business_context"], str):
        rep.error(rid, "input.business_context must be a string")
    cur, texts = check_message(inp.get("current_email"), rid, "input.current_email", rep, v2, current=True,
                               require_sent_at=require_render, as_of=as_of)
    hist = inp.get("history", [] if not v2 else None)
    if not isinstance(hist, list):
        rep.error(rid, "input.history must be a list")
        hist = []
    for i, history in enumerate(hist):
        _, history_texts = check_message(history, rid, f"input.history[{i}]", rep, v2,
                                         require_sent_at=require_render, as_of=as_of)
        texts += history_texts
    tgt = rec.get("target") if isinstance(rec.get("target"), dict) else {}
    label = tgt.get("label")
    if not isinstance(label, str) or label not in labels:
        rep.error(rid, f"target.label must be one of {sorted(labels)}")
    evidence = tgt.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        rep.error(rid, "target.evidence must be a non-empty list")
    else:
        for i, item in enumerate(evidence):
            where = f"target.evidence[{i}]"
            if isinstance(item, dict):
                code = item.get("code")
                if not nonempty(code):
                    rep.error(rid, f"{where}.code must be a non-empty string")
                elif v2 and code in FORBIDDEN_V2_CODES:
                    rep.error(rid, f"{where}: header/identity evidence is forbidden in v2; use semantic evidence")
                elif code not in codes:
                    (rep.error if v2 else rep.warn)(rid, f"{where}: unknown evidence code '{code}'")
                if not nonempty(item.get("detail")):
                    (rep.error if v2 or "detail" in item else rep.warn)(rid, f"{where}.detail must be a non-empty string")
                if v2:
                    check_spans(rec, item, rid, where, rep)
            elif v2 or not nonempty(item):
                rep.error(rid, f"{where} must be an evidence object" if v2 else f"{where} must be an object or non-empty string")
    if not nonempty(tgt.get("safe_action")):
        rep.error(rid, "target.safe_action must be a non-empty string")
    if v2 and ("pair_type" in rec or "changed_paths" in rec) and not nonempty(rec.get("pair_id")):
        rep.error(rid, "pair_type/changed_paths require pair_id")
    if v2 and nonempty(rec.get("pair_id")):
        if not isinstance(rec.get("pair_type"), str) or rec["pair_type"] not in {"minimal", "scenario"}:
            rep.error(rid, "paired v2 records require pair_type minimal or scenario")
        if rec.get("pair_type") == "minimal" or "changed_paths" in rec:
            paths = rec.get("changed_paths")
            if not isinstance(paths, list) or not paths or any(not nonempty(path) for path in paths):
                rep.error(rid, "changed_paths must be a non-empty list of JSON Pointers")
            else:
                if len(set(paths)) != len(paths):
                    rep.error(rid, "changed_paths must not repeat paths")
                for path in paths:
                    try:
                        pointer_parts(path)
                    except ValueError as exc:
                        rep.error(rid, f"changed_paths: {exc}")
    cjk, latin = lang_counts(texts)
    if lang == "zh":
        if cjk < 10:
            rep.warn(rid, "tagged zh but subject/body contain almost no Chinese")
        elif latin >= 5 and latin / (latin + cjk / 1.7) > 0.25:
            rep.warn(rid, "tagged zh but English carries a large share; consider zh-en")
    elif lang == "en" and cjk >= 5:
        rep.warn(rid, "tagged en but subject/body contain Chinese; consider zh-en")
    elif lang == "zh-en" and (cjk < 5 or latin < 5):
        rep.warn(rid, "tagged zh-en but one language is nearly absent")
    cur_cjk, cur_latin = lang_counts(texts[1:2])
    if lang == "zh" and cur_cjk < 5 and cur_latin >= 5:
        rep.warn(rid, "tagged zh but the current email is written in English")
    elif lang == "en" and cur_cjk >= 5 and cur_latin < 5:
        rep.warn(rid, "tagged en but the current email is written in Chinese")
    sens = 0
    for text in strings([rec.get("scenario"), rec.get("notes"), inp, tgt]):
        for severity, message in sensitive_findings(text, allowed_identifiers, strict_numbers=v2, allow_raw_urls=v2):
            sens += 1
            if isinstance(kind, str) and kind in {"synthetic", "redacted-source", "source-adapted"}:
                (rep.error if severity == "error" else rep.warn)(rid, f"{kind}: {message}")
    if require_raw_urls and any(URL_TOKEN_RE.search(text) for text in strings(inp)):
        rep.error(rid, "--require-raw-urls rejects [URL_n] placeholders in input; preserve available link text without inventing missing destinations")
    if v2:
        if any(SYNTHETIC_ACCOUNT_RE.search(text) for text in strings([inp, tgt, rec.get("scenario"), rec.get("notes"), prov.get("identifiers")])):
            rep.error(rid, "v2 must not invent or mask bank accounts with [ACCOUNT_n] or SYN-ACCT; use a declared sourced value or omit it")
    body = own_body(text_value(cur.get("body")))
    substantive = substantive_counts(text_value(cur.get("body")))
    metric, minimum, recommended_max = DETAILED_METRICS.get(text_value(lang), ("weighted_units", 350, 800))
    score = substantive[metric]
    if profile == "detailed":
        if score < minimum:
            rep.error(rid, f"detailed current_email.body has {score} {metric}; minimum {minimum} substantive units")
        if score > 2 * recommended_max:
            rep.warn(rid, f"detailed current_email.body has {score} {metric}; exceeds twice recommended maximum {recommended_max}")
        if substantive["duplicate_paragraphs"]:
            rep.warn(rid, f"current_email.body repeats {substantive['duplicate_paragraphs']} nontrivial paragraph(s); duplicates did not count toward length")
    sender_domain, sender_device = "", ""
    render = rec.get("render")
    if isinstance(render, dict) and isinstance(render.get("mailboxes"), dict) and isinstance(cur.get("from"), dict):
        box = render["mailboxes"].get(text_value(cur["from"].get("address")).strip("[]"))
        sender_domain = text_value(box.get("domain")) if isinstance(box, dict) else ""
        people = render.get("people") if isinstance(render.get("people"), dict) else {}
        person = people.get(box.get("owner")) if isinstance(box, dict) and isinstance(box.get("owner"), str) else None
        if sender_domain:
            sender_device = text_value(person.get("device")) or "desktop" if isinstance(person, dict) else "none"
    return {
        "id": rid, "label": text_value(label), "language": text_value(lang), "kind": text_value(kind),
        "difficulty": text_value(difficulty), "scenario_type": text_value(rec.get("scenario_type")),
        "pair_id": text_value(rec.get("pair_id")), "body_len": len(body),
        "has_history": bool(hist),
        "has_redaction": bool(REDACTED_RE.search(json.dumps(inp, ensure_ascii=False)) or ANY_TOKEN_RE.search(json.dumps(inp, ensure_ascii=False))),
        "urgent": bool(URGENCY_RE.search(text_value(cur.get("subject")) + body)),
        "source_sensitive": sens if kind == "source" else 0,
        "content_profile": text_value(profile), "substantive_count": score, "substantive_metric": metric,
        "sender_domain": sender_domain, "sender_device": sender_device,
        "_record": rec, "_input": inp, "_v2": v2,
        "_grounding_active": require_grounding or "grounding" in prov or kind == "source-adapted",
    }


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def escape_pointer(key):
    return str(key).replace("~", "~0").replace("/", "~1")


def leaf_paths(value, path):
    if isinstance(value, dict) and value:
        return set().union(*(leaf_paths(item, path + "/" + escape_pointer(key)) for key, item in value.items()))
    if isinstance(value, list) and value:
        return set().union(*(leaf_paths(item, path + f"/{i}") for i, item in enumerate(value)))
    return {path}


def differing_paths(left, right, path="/input"):
    """Return leaf JSON Pointers; scalar text bodies are single leaves."""
    if isinstance(left, dict) and isinstance(right, dict):
        changed = set()
        for key in left.keys() | right.keys():
            child = path + "/" + escape_pointer(key)
            if key not in left:
                changed |= leaf_paths(right[key], child)
            elif key not in right:
                changed |= leaf_paths(left[key], child)
            else:
                changed |= differing_paths(left[key], right[key], child)
        return changed
    if isinstance(left, list) and isinstance(right, list):
        changed = set()
        for i in range(max(len(left), len(right))):
            child = path + f"/{i}"
            if i >= len(left):
                changed |= leaf_paths(right[i], child)
            elif i >= len(right):
                changed |= leaf_paths(left[i], child)
            else:
                changed |= differing_paths(left[i], right[i], child)
        return changed
    return set() if type(left) is type(right) and left == right else {path}


def entity_set(record):
    prov = record.get("provenance")
    entities = prov.get("entities") if isinstance(prov, dict) else None
    if not isinstance(entities, list):
        return set()
    result = set()
    for entity in entities:
        if isinstance(entity, dict):
            # Source order is immaterial, but attribution differences are not.
            normalized = dict(entity)
            refs = normalized.get("source_ids")
            if isinstance(refs, list):
                normalized["source_ids"] = sorted(refs, key=canonical)
            result.add(canonical(normalized))
    return result


def dataset_checks(rows, labels, balanced, rep):
    if not rows:
        rep.error("dataset", "dataset must contain at least one record")
    by_label = defaultdict(list)
    input_labels = {}
    for row in rows:
        if row["label"] in labels:
            by_label[row["label"]].append(row)
            digest = hashlib.sha256(canonical(row["_input"]).encode("utf-8")).hexdigest()
            if digest in input_labels and input_labels[digest][0] != row["label"]:
                rep.error(row["id"], f"identical input has conflicting labels (also {input_labels[digest][1]})")
            else:
                input_labels[digest] = (row["label"], row["id"])
    pairs = defaultdict(list)
    for row in rows:
        if row["pair_id"]:
            pairs[row["pair_id"]].append(row)
    for pid, members in pairs.items():
        for field in CN_CONTEXT_FIELDS + ("register",):
            if len({canonical(member["_record"].get(field)) for member in members}) > 1:
                rep.error(pid, f"pair members must have the same {field}")
        if len({member["content_profile"] for member in members}) > 1:
            rep.error(pid, "pair members must have the same content_profile")
        if len(members) == 2 and all(member["content_profile"] == "detailed" for member in members):
            counts = [member["substantive_count"] for member in members]
            low, high = min(counts), max(counts)
            if high > low * 1.3:
                ratio = high / low if low else float("inf")
                rep.warn(pid, f"detailed pair substantive length ratio {ratio:.2f} exceeds 1.30 (counts {counts[0]}, {counts[1]})")
        if any(member["_v2"] for member in members):
            if len(members) == 1:
                rep.warn(pid, "singleton pair; allowed for an odd-sized request")
                continue
            if len(members) != 2:
                rep.error(pid, "a complete v2 pair must contain exactly two records")
                continue
            if not all(member["_v2"] for member in members):
                rep.error(pid, "pair mixes v2 and legacy records")
            if len(labels) != 2 or Counter(member["label"] for member in members) != Counter(labels):
                rep.error(pid, "a complete v2 pair must have one record of each of two configured labels")
            left, right = [member["_record"] for member in members]
            for field in ("domain", "scenario_type", "scenario", "thread_family_id", "pair_type"):
                if left.get(field) != right.get(field):
                    rep.error(pid, f"pair members have different {field}")
            li, ri = [member["_input"] for member in members]
            for field in ("history", "business_context"):
                if li.get(field) != ri.get(field):
                    rep.error(pid, f"pair members must have identical input.{field}")
            if entity_set(left) != entity_set(right):
                rep.error(pid, "pair members must have the same provenance.entities set")
            if left.get("pair_type") == "minimal" and right.get("pair_type") == "minimal":
                lp, rp = left.get("changed_paths"), right.get("changed_paths")
                if lp != rp:
                    rep.error(pid, "minimal pair must declare the same changed_paths list")
                if isinstance(lp, list) and all(isinstance(path, str) for path in lp):
                    actual = differing_paths(li, ri)
                    if set(lp) != actual:
                        rep.error(pid, "minimal pair changed_paths do not match actual differing input leaves: " + ", ".join(sorted(actual)))
        else:
            if len({member["label"] for member in members}) < 2:
                rep.warn(pid, "pair does not contain both labels")
            if len({member["scenario_type"] for member in members}) > 1:
                rep.warn(pid, "pair members have different scenario_type")
    total = sum(len(items) for items in by_label.values())
    if balanced and total and len(labels) > 1:
        for label in labels:
            share = len(by_label.get(label, [])) / total
            if abs(share - 1 / len(labels)) > 0.10:
                rep.warn("dataset", f"label '{label}' is {share:.0%} of records (target {1 / len(labels):.0%})")
    present = [label for label in labels if by_label.get(label)]
    if len(present) < 2:
        return "leakage checks skipped (fewer than two labels present)"
    if min(len(by_label[label]) for label in present) < 5:
        return "leakage checks skipped (fewer than 5 records per label)"
    def mean(values):
        return sum(values) / len(values)
    lens = {label: mean([row["body_len"] for row in by_label[label]]) for label in present}
    if min(lens.values()) and max(lens.values()) / min(lens.values()) > 1.5:
        rep.warn("dataset", "body length differs strongly by label: " + ", ".join(f"{key}={value:.0f}" for key, value in lens.items()))
    for key, name, limit in (("has_history", "records with history", 0.3),
                             ("has_redaction", "records with redaction tokens", 0.3),
                             ("urgent", "urgency wording", 0.4)):
        shares = {label: mean([row[key] for row in by_label[label]]) for label in present}
        if max(shares.values()) - min(shares.values()) > limit:
            rep.warn("dataset", f"share of {name} differs by label: " + ", ".join(f"{label}={share:.0%}" for label, share in shares.items()))
    # Rendered sender relationships become visible features; both labels need overlap.
    for field, name in (("sender_domain", "sender mailbox"), ("sender_device", "sender device")):
        senders = {label: [row[field] for row in by_label[label] if row[field]] for label in present}
        if not all(len(values) >= 5 for values in senders.values()):
            continue
        for kind in sorted(set().union(*senders.values())):
            shares = {label: values.count(kind) / len(values) for label, values in senders.items()}
            if max(shares.values()) - min(shares.values()) > 0.4:
                rep.warn("dataset", f"current {name} '{kind}' share differs by label: "
                         + ", ".join(f"{label}={share:.0%}" for label, share in shares.items()))
    return "leakage checks run"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path")
    parser.add_argument("--labels", default="malicious,benign")
    parser.add_argument("--strict", action="store_true", help="require schema_version 2.0 for every record")
    parser.add_argument("--require-detailed", action="store_true", help="require detailed content_profile and substantive current-body minima")
    parser.add_argument("--require-cn-context", action="store_true", help="require mainland-China transaction and currency metadata")
    parser.add_argument("--require-grounding", action="store_true", help="require v2 source-adapted/redacted-source records with material-source mappings; does not verify source truth")
    parser.add_argument("--require-raw-urls", action="store_true", help="reject [URL_n] input placeholders; messages without links remain valid; never fetches URLs")
    parser.add_argument("--require-render", action="store_true", help="require render declarations, sender/recipient mailboxes and sent_at for realistic rendering")
    parser.add_argument("--require-current-year", action="store_true",
                        help="require generated messages dated January 1 through today and a matching scenario year")
    parser.add_argument("--balanced", action="store_true", help="warn if labels deviate >10 points from equal share")
    parser.add_argument("--extra-codes", default="", help="comma-separated evidence codes to accept")
    args = parser.parse_args()
    as_of = date.today() if args.require_current_year else None
    labels = [value.strip() for value in args.labels.split(",") if value.strip()]
    if not labels or len(set(labels)) != len(labels):
        parser.error("--labels must contain at least one label without duplicates")
    codes = KNOWN_CODES | {value.strip() for value in args.extra_codes.split(",") if value.strip()}
    rep = Report()
    records = load(args.path, rep)
    seen = set()
    rows = [row for row in (check_record(rec, i, set(labels), codes, rep, seen, strict=args.strict,
                                      require_detailed=args.require_detailed, require_cn_context=args.require_cn_context,
                                      require_grounding=args.require_grounding, require_raw_urls=args.require_raw_urls,
                                      require_render=args.require_render, as_of=as_of)
                           for i, rec in enumerate(records, 1)) if row]
    leak_note = dataset_checks(rows, labels, args.balanced, rep)
    for line in rep.errors + rep.warnings:
        print(line)
    print(f"\nrecords: {len(rows)}  errors: {len(rep.errors)}  warnings: {len(rep.warnings)}  ({leak_note})")
    for field in ("label", "language", "kind", "difficulty", "scenario_type"):
        counts = Counter(row[field] or "-" for row in rows)
        print(f"{field:>13}: " + ", ".join(f"{key}={value}" for key, value in counts.most_common(15)))
    if any(row["source_sensitive"] for row in rows):
        print("note: source records contain real-looking URLs, numbers or contacts; redact before sharing")
    if args.require_grounding or any(row["_grounding_active"] for row in rows):
        print("note: grounding checks validate declared source links and quoted input spans only; "
              "retrieval authenticity, source claims and complete factual support still require review")
    if args.require_raw_urls:
        print("note: raw-URL mode checks placeholders and heuristic privacy findings only; "
              "URLs were not fetched, verified, classified or checked for exact source preservation")
    for row in rows:
        if row["content_profile"] == "detailed":
            print(f"substantive [{row['id']}]: {row['substantive_count']} {row['substantive_metric']}")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
