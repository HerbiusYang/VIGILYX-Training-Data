#!/usr/bin/env python3
"""Regression tests: python3 -m unittest discover -s scripts -p 'test_*.py'."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import validate_records as validator

LABELS = {"malicious", "benign"}


def fixture():
    """Self-contained structural fixture; citations are not claimed as researched."""
    left = {
        "schema_version": "2.0", "id": "r_a38f19d2", "pair_id": "p_c88c34f1",
        "pair_type": "minimal", "changed_paths": ["/input/current_email/body"],
        "thread_family_id": "f_51869d22", "domain": "shopping",
        "scenario_type": "refund", "difficulty": "medium", "language": "en",
        "scenario": "A store processes a previously approved refund.",
        "provenance": {
            "kind": "synthetic",
            "synthetic_scope": "All messages, people and transactions are synthetic test fixtures.",
            "sources": [{"id": "src_refund", "title": "Test refund policy", "publisher": "Test Store",
                         "url": "https://example.com/refunds", "accessed_at": "2026-11-11",
                         "supports": "Refunds return to the original payment method."}],
            "entities": [{"name": "Test Store", "role": "merchant", "source_ids": ["src_refund"]}],
        },
        "input": {
            "business_context": "The customer has already completed the return.",
            "history": [{"from": {"name": "[PERSON_1]", "address": "[EMAIL_1]"},
                         "to": ["[EMAIL_2]"], "sent_at": "2026-11-10T09:00:00+00:00",
                         "subject": "Approved refund", "body": "Your refund was approved and will return to the original payment method.",
                         "attachments": []}],
            "current_email": {"from": {"name": "[PERSON_1]", "address": "[EMAIL_1]"},
                              "to": [{"name": "[PERSON_2]", "address": "[EMAIL_2]"}], "cc": [],
                              "reply_to": None, "sent_at": "2026-11-11T09:00:00+00:00",
                              "subject": "Refund processing", "body": "Please pay a separate processing fee before we release your already approved refund.",
                              "attachments": []},
        },
        "target": {"label": "malicious", "safe_action": "Verify the request through the established support channel.",
                   "evidence": [{"code": "advance_fee_request", "detail": "An additional fee is demanded for an approved refund.",
                                 "spans": [{"path": "/input/current_email/body", "quote": "pay a separate processing fee"}]}]},
    }
    right = copy.deepcopy(left)
    right["id"] = "r_d6eb40e1"
    right["input"]["current_email"]["body"] = "Your already approved refund will return to the original payment method without any processing fee."
    right["target"] = {"label": "benign", "safe_action": "Monitor the original payment method for the approved refund.",
                       "evidence": [{"code": "process_consistent", "detail": "Refund handling agrees with the prior message.",
                                     "spans": [{"path": "/input/current_email/body", "quote": "without any processing fee"},
                                               {"path": "/input/history/0/body", "quote": "original payment method"}]}]}
    return [left, right]


def legacy_fixture():
    rec = fixture()[0]
    for field in ("schema_version", "domain", "pair_id", "pair_type", "changed_paths", "thread_family_id"):
        rec.pop(field)
    rec["provenance"] = {"kind": "synthetic", "file_ref": None, "record_ref": None}
    rec["input"]["current_email"]["from"]["address"] = "sender@merchant.example"
    return rec


def check(records, strict=False, codes=None, require_detailed=False, require_cn_context=False, require_grounding=False, require_raw_urls=False):
    rep, seen, rows = validator.Report(), set(), []
    for i, record in enumerate(records, 1):
        row = validator.check_record(record, i, LABELS, codes or validator.KNOWN_CODES, rep, seen, strict=strict,
                                     require_detailed=require_detailed, require_cn_context=require_cn_context,
                                     require_grounding=require_grounding, require_raw_urls=require_raw_urls)
        if row:
            rows.append(row)
    validator.dataset_checks(rows, LABELS, False, rep)
    return rep


def assign(obj, path, value):
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value


ZH_DETAIL = "\n\n".join([
    "我们已完成本次采购订单与退货入库记录的逐项核对。仓库确认收到的物料数量与此前审批单一致，包装检查和质量复验也已结束，相关记录已提交财务共享中心归档。本次退款的计算口径仍以双方确认的订单明细为准，尚未发生额外服务费或其他扣款事项。",
    "关于此前对账时提到的运输费用，物流团队已核实承运单据，并将属于供应商承担的部分从客户应付金额中移除。更正后的对账单会随本邮件一并发送，请重点核对退款项目名称、对应原订单及费用归属；如果发现差异，请在现有工单中说明，避免另建申请造成重复处理。",
    "退款将退回原交易使用的付款渠道。财务会在本期退款批次提交后更新处理状态，银行或支付机构实际入账时间可能与提交时间不同，因此收到处理通知并不表示资金已经到账。您可以通过原订单详情查看进度，无需先行转账，也无需向经办人员提供验证码或其他认证信息。",
    "为便于后续审计，我们会保留退货签收记录、更正后的对账结果及本次批准意见。若您需要调整收款主体，应先完成正式的主体变更审核，并由财务通过已登记的联系人核实；在审核结束前，本次退款仍遵循原审批内容。请保留这封邮件，并在资金入账后核对金额与项目是否一致。",
])
EN_DETAIL = "\n\n".join([
    "We have completed the reconciliation of the purchase order, the warehouse return record, and the approved refund request. The warehouse confirmed that all returned items were received in the expected quantities and that the inspection was completed without an additional charge. The revised statement therefore uses the same item descriptions and unit prices that were agreed in the existing order. Please review the attached statement against your own records and identify any discrepancy through the existing support case so that our finance team can investigate it before the payment batch is finalized.",
    "The shipping adjustment discussed in the previous correspondence has also been reviewed. The amount allocated to the supplier has been removed from the customer balance, and no processing fee is required to release the approved refund. Our team will return the funds through the original payment method after the batch has been submitted. The posting date may depend on the payment provider, so a processing confirmation should not be treated as confirmation that the credit has already appeared in your account. You can monitor progress through the original order details without opening another request.",
    "For audit purposes, we will retain the warehouse receipt, the revised reconciliation statement, and the approval record with the existing case. If your organization needs to change the receiving entity, that change must complete the established verification process before any payment instruction is revised. Until that review is finished, the approved refund continues to follow the original authorization. Please retain this correspondence and compare the final credit with the approved statement once it arrives. If anything differs, reply through the known case channel and provide the relevant statement line rather than confidential authentication information.",
])


def detailed_record(language, body):
    record = fixture()[0]
    for field in ("pair_id", "pair_type", "changed_paths"):
        record.pop(field)
    record.update(content_profile="detailed", language=language)
    record["input"]["current_email"]["body"] = body
    record["target"]["evidence"][0]["spans"] = [{"path": "/input/current_email/body", "quote": body[:20]}]
    return record


def cn_record(body="更正后的应付金额是32,480元，麻烦按原订单核对一下。", currencies=None, scope="domestic", language="zh"):
    record = detailed_record(language, body)
    record.pop("content_profile")
    record.update(business_region="CN", transaction_scope=scope, currencies=["CNY"] if currencies is None else currencies)
    if scope == "cross_border":
        record["cross_border_context"] = "中国大陆采购方向美国供应商采购服务，合同约定以美元结算。"
        record["input"]["business_context"] = "本例为中国大陆采购方核对美国供应商的服务采购款，合同约定以美元结算。"
    return record


def grounded_fixture(kind="source-adapted"):
    """Fabricated unit-test fixture only; no real retrieval or factual claim."""
    record = fixture()[0]
    for field in ("pair_id", "pair_type", "changed_paths"):
        record.pop(field)
    prov = record["provenance"]
    prov.update(kind=kind)
    prov.pop("synthetic_scope")
    prov["sources"][0]["roles"] = ["material", "policy"]
    paths = ["/input/current_email/body", "/input/history/0/body", "/input/business_context"]
    prov["grounding"] = {
        "theme": "Refund handling in a unit-test email exchange",
        "context": {"region": "CN", "period": "2026-11", "setting": "A fabricated test fixture, not a historical event"},
        "source_material": {"type": "email_thread", "source_ids": ["src_refund"]},
        "retrieval": {"queries": ["unit-test placeholder query, not executed"], "searched_at": "2026-11-11"},
        "transformations": ["anonymization", "excerpt" if kind == "redacted-source" else "faithful_paraphrase"],
        "fact_map": [{"input_path": path, "input_quote": validator.resolve_pointer(record, path),
                      "source_id": "src_refund", "locator": f"test fixture paragraph {i}",
                      "source_claim": "Fixture-only statement: " + validator.resolve_pointer(record, path)}
                     for i, path in enumerate(paths, 1)],
    }
    if kind == "source-adapted":
        prov["grounding"]["adaptation_scope"] = "Unit-test wording adaptation; these are fabricated test messages, not real correspondence."
    return record


def scenario_adapted_fixture():
    """Explicitly recorded plot variation in fabricated test material only."""
    record = grounded_fixture()
    body = "The refund request now asks the customer to pay an additional processing fee before the already approved refund is released."
    record["input"]["current_email"]["body"] = body
    record["target"]["evidence"][0]["spans"] = [{"path": "/input/current_email/body", "quote": "additional processing fee"}]
    grounding = record["provenance"]["grounding"]
    grounding["transformations"].append("scenario_adaptation")
    grounding["adaptation_scope"] = "This unit-test variation adapts the payment request; it is not a real historical email."
    grounding["fact_map"] = [fact for fact in grounding["fact_map"] if fact["input_path"] != "/input/current_email/body"]
    grounding["adaptations"] = [{"input_path": "/input/current_email/body", "input_quote": body,
                                 "basis_source_ids": ["src_refund"], "change": "Reframe the approved refund as a fee request.",
                                 "reason": "Exercise the source-based scenario-adaptation branch in this test."}]
    return record


class ValidationTests(unittest.TestCase):
    def test_documented_material_based_scenario_adaptation_passes(self):
        record = scenario_adapted_fixture()
        self.assertEqual(check([record], require_grounding=True).errors, [])
        history_body = "The warehouse confirmed the returned items and the finance team approved the refund."
        record["input"]["history"][0]["body"] = history_body
        grounding = record["provenance"]["grounding"]
        grounding["fact_map"] = [fact for fact in grounding["fact_map"] if fact["input_path"] != "/input/history/0/body"]
        grounding["adaptations"].append({"input_path": "/input/history/0/body", "input_quote": history_body,
                                        "basis_source_ids": ["src_refund"], "change": "Condense the preceding business events into a test message.",
                                        "reason": "Preserve the original approval as the basis of the adapted sequence."})
        self.assertEqual(check([record], require_grounding=True).errors, [])

    def test_source_adapted_needs_scope_and_scenario_changes_need_records(self):
        record = grounded_fixture()
        record["provenance"]["grounding"].pop("adaptation_scope")
        self.assertTrue(any("adaptation_scope" in error for error in check([record]).errors))
        record = grounded_fixture()
        record["provenance"]["grounding"]["transformations"].append("scenario_adaptation")
        self.assertTrue(any("adaptations must be a non-empty" in error for error in check([record]).errors))
        record = scenario_adapted_fixture()
        record["provenance"]["grounding"].pop("adaptations")
        errors = check([record]).errors
        self.assertTrue(any("/input/current_email/body" in error for error in errors))
        record = scenario_adapted_fixture()
        record["provenance"]["grounding"]["transformations"].remove("scenario_adaptation")
        self.assertTrue(any("require the scenario_adaptation" in error for error in check([record]).errors))

    def test_non_scenario_material_requires_source_facts(self):
        record = grounded_fixture()
        record["provenance"]["grounding"]["fact_map"] = []
        self.assertTrue(any("fact_map must be a non-empty" in error for error in check([record]).errors))

    def test_concise_scenario_accepts_material_based_adaptations_without_named_entities(self):
        record = scenario_adapted_fixture()
        record.update(domain="workplace", content_profile="concise", business_region="CN",
                      transaction_scope="domestic", currencies=[], register="daily_business",
                      scenario_type="mailbox_access", scenario="An employee receives a mailbox access notice.")
        record["input"]["history"] = []
        del record["input"]["business_context"]
        body = "Reply to this email with your mailbox verification code."
        record["input"]["current_email"].update(subject="Mailbox access", body=body)
        record["target"]["evidence"] = [{
            "code": "credential_or_mfa_request",
            "detail": "The sender requests disclosure of a verification code.",
            "spans": [{"path": "/input/current_email/body", "quote": body}],
        }]
        record["provenance"]["entities"] = []
        record["provenance"]["sources"][0].update(title="Test incident description", roles=["material"],
                                                  supports="A sender requested a mailbox verification code.")
        grounding = record["provenance"]["grounding"]
        grounding["theme"] = "Mailbox access verification"
        grounding["source_material"]["type"] = "case_report"
        grounding["adaptation_scope"] = "Fabricated test wording for the reported request."
        grounding["fact_map"] = []
        grounding["adaptations"][0].update(input_quote=body, change="Express the reported request as a short email.",
                                           reason="Retain the request to disclose a verification code.")
        report = check([record], strict=True, require_grounding=True, require_cn_context=True)
        self.assertEqual(report.errors, [])
        grounding["adaptations"][0]["basis_source_ids"] = ["unknown"]
        report = check([record], strict=True, require_grounding=True, require_cn_context=True)
        self.assertTrue(any("/input/current_email/body" in error for error in report.errors))

    def test_adaptations_cannot_present_a_change_as_a_source_claim(self):
        record = scenario_adapted_fixture()
        record["provenance"]["grounding"]["adaptations"][0]["source_claim"] = "An invented change presented as a source fact."
        self.assertTrue(any("not source_claim" in error for error in check([record]).errors))

    def test_redacted_source_rejects_scenario_adaptations(self):
        for declared in (True, False):
            record = scenario_adapted_fixture()
            record["provenance"]["kind"] = "redacted-source"
            record["provenance"]["grounding"]["transformations"] = ["anonymization"] + (["scenario_adaptation"] if declared else [])
            self.assertTrue(any("redacted-source cannot" in error for error in check([record]).errors))

    def test_adaptation_basis_and_spans_are_validated_without_crashes(self):
        cases = [("basis_source_ids", ["missing"]), ("basis_source_ids", [{}]), ("basis_source_ids", []),
                 ("input_path", "/target/safe_action"), ("input_path", "/input/history"), ("input_path", {}),
                 ("input_quote", "A quote absent from the adapted input."), ("change", ""), ("reason", [])]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                record = scenario_adapted_fixture()
                record["provenance"]["grounding"]["adaptations"][0][field] = value
                self.assertTrue(check([record]).errors)
        record = scenario_adapted_fixture()
        context_source = copy.deepcopy(record["provenance"]["sources"][0])
        context_source.update(id="context_only", roles=["context", "entity"])
        record["provenance"]["sources"].append(context_source)
        record["provenance"]["grounding"]["adaptations"][0]["basis_source_ids"] = ["context_only"]
        self.assertTrue(any("selected material-role" in error for error in check([record]).errors))

    def test_grounding_valid_source_adapted_and_redacted_source(self):
        for kind in ("source-adapted", "redacted-source"):
            record = grounded_fixture(kind)
            self.assertEqual(check([record], require_grounding=True).errors, [])
            self.assertEqual(check([record]).errors, [])

    def test_grounding_requirement_preserves_legacy_but_rejects_new_synthesis(self):
        self.assertEqual(check([legacy_fixture()]).errors, [])
        self.assertEqual(check(fixture()).errors, [])
        errors = check([legacy_fixture()], require_grounding=True).errors
        self.assertTrue(any("schema_version" in error for error in errors))
        self.assertTrue(any("synthetic is legacy-only" in error for error in errors))
        record = grounded_fixture()
        record["schema_version"] = "1.0"
        self.assertTrue(any("schema_version" in error for error in check([record], require_grounding=True).errors))
        record = fixture()[0]
        self.assertTrue(any("synthetic is legacy-only" in error for error in check([record], require_grounding=True).errors))

    def test_grounding_is_checked_when_present_or_kind_requires_it(self):
        record = grounded_fixture()
        record["provenance"].pop("grounding")
        self.assertTrue(any("grounding must be an object" in error for error in check([record]).errors))
        record = grounded_fixture("redacted-source")
        record["provenance"]["grounding"] = []
        self.assertTrue(check([record]).errors)

    def test_grounding_requires_material_not_entity_only_page(self):
        record = grounded_fixture()
        record["provenance"]["sources"][0]["roles"] = ["entity", "context", "policy"]
        self.assertTrue(any("material-role" in error for error in check([record]).errors))
        record["provenance"]["sources"][0]["roles"] = ["entity", "material"]
        self.assertEqual(check([record]).errors, [])

    def test_redacted_source_cannot_claim_paraphrasing_or_translation(self):
        for transformation in ("faithful_paraphrase", "translation"):
            record = grounded_fixture("redacted-source")
            record["provenance"]["grounding"]["transformations"].append(transformation)
            self.assertTrue(any("use provenance.kind source-adapted" in error for error in check([record]).errors))
            record["provenance"]["kind"] = "source-adapted"
            record["provenance"]["grounding"]["adaptation_scope"] = "The test text is paraphrased/translated, not a verbatim message."
            self.assertEqual(check([record]).errors, [])
        record = grounded_fixture("redacted-source")
        record["provenance"]["grounding"]["transformations"] = ["excerpt", "anonymization", "format_adaptation"]
        self.assertEqual(check([record]).errors, [])

    def test_each_body_needs_a_mapping_to_selected_material_source(self):
        base = grounded_fixture()
        other = copy.deepcopy(base["provenance"]["sources"][0])
        other.update(id="src_context", roles=["entity", "context"])
        base["provenance"]["sources"].append(other)
        for path in ("/input/current_email/body", "/input/history/0/body"):
            with self.subTest(path=path):
                record = copy.deepcopy(base)
                for fact in record["provenance"]["grounding"]["fact_map"]:
                    if fact["input_path"] == path:
                        fact["source_id"] = "src_context"
                self.assertTrue(any("body mapping to a material-role source" in error and path in error for error in check([record]).errors))
                # Merely marking the other source material is insufficient unless selected.
                record["provenance"]["sources"][1]["roles"] = ["material"]
                self.assertTrue(any("body mapping to a material-role source" in error for error in check([record]).errors))
                record["provenance"]["grounding"]["source_material"]["source_ids"].append("src_context")
                self.assertEqual(check([record]).errors, [])
        for fact in base["provenance"]["grounding"]["fact_map"]:
            if fact["input_path"] == "/input/business_context":
                fact["source_id"] = "src_context"
        self.assertEqual(check([base]).errors, [])

    def test_fact_map_must_cover_each_body_and_business_context(self):
        base = grounded_fixture()
        for missing in ("/input/current_email/body", "/input/history/0/body", "/input/business_context"):
            with self.subTest(missing=missing):
                record = copy.deepcopy(base)
                record["provenance"]["grounding"]["fact_map"] = [item for item in record["provenance"]["grounding"]["fact_map"] if item["input_path"] != missing]
                self.assertTrue(any("lacks a valid" in error and missing in error for error in check([record]).errors))
        record = copy.deepcopy(base)
        record["input"]["history"].append(copy.deepcopy(record["input"]["history"][0]))
        self.assertTrue(any("/input/history/1/body" in error for error in check([record]).errors))

    def test_fact_map_requires_exact_quote_and_existing_source(self):
        for field, value in (("input_path", "/target/safe_action"), ("input_path", "/input/history"),
                             ("input_quote", "This text was never in the email."), ("source_id", "missing"),
                             ("source_claim", ""), ("locator", "")):
            with self.subTest(field=field):
                record = grounded_fixture()
                record["provenance"]["grounding"]["fact_map"][0][field] = value
                errors = check([record]).errors
                self.assertTrue(errors)
                self.assertTrue(any("lacks a valid" in error and "/input/current_email/body" in error for error in errors))

    def test_grounding_nested_structure_errors_never_crash(self):
        cases = [
            (("grounding", "theme"), ""), (("grounding", "context"), []),
            (("grounding", "context", "period"), None), (("grounding", "source_material", "type"), "invented_email"),
            (("grounding", "source_material", "source_ids"), [{}]),
            (("grounding", "source_material", "source_ids"), ["missing"]),
            (("grounding", "retrieval", "queries"), "not a list"),
            (("grounding", "retrieval", "queries"), []),
            (("grounding", "retrieval", "searched_at"), "2026-02-30"),
            (("grounding", "retrieval", "searched_at"), {}),
            (("grounding", "transformations"), ["invent_dialogue"]),
            (("grounding", "transformations"), [{}]),
            (("grounding", "fact_map"), []), (("grounding", "fact_map"), [None]),
            (("sources", 0, "roles"), []), (("sources", 0, "roles"), [{}]),
        ]
        for path, value in cases:
            with self.subTest(path=path, value=value):
                record = grounded_fixture()
                assign(record["provenance"], path, value)
                self.assertTrue(check([record]).errors)

    def test_grounding_cli_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            command = [sys.executable, str(Path(validator.__file__)), str(path), "--require-grounding"]
            path.write_text(json.dumps([grounded_fixture()]), encoding="utf-8")
            good = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
            path.write_text(json.dumps(fixture()), encoding="utf-8")
            bad = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(bad.returncode, 1)
            self.assertNotIn("Traceback", bad.stderr)

    def test_natural_mainland_currency_formats(self):
        for body in ("更正后的应付金额是32,480元，麻烦按原订单核对一下。", "本次退还人民币169.50元，请留意原支付渠道。", "这笔款是￥32,480，请核对。"):
            self.assertEqual(check([cn_record(body)], require_cn_context=True).errors, [])
        for body in ("这笔服务款共2,450美元，请按合同确认一下。", "本次结算2,450美金，原订单金额保持不变。"):
            self.assertEqual(check([cn_record(body, ["USD"], "cross_border")], require_cn_context=True).errors, [])

    def test_currency_codes_next_to_amounts_rejected(self):
        for amount in ("USD 100", "100 USD", "CNY100", "RMB 100", "USD\u00a0100", "１００　ＵＳＤ", "（USD）：100", "100（USD）"):
            record = cn_record("请核对这笔款：" + amount + "。", ["CNY", "USD"], "cross_border")
            self.assertTrue(any("natural wording" in error for error in check([record]).errors), amount)

    def test_dollar_symbol_requires_english_and_usd_context(self):
        for language in ("zh", "zh-en"):
            for amount in ("$100", "US$100", "＄１００"):
                record = cn_record("请核对这笔款" + amount + "。", ["USD"], "cross_border", language)
                self.assertTrue(any("dollar sign" in error for error in check([record]).errors), (language, amount))
        record = cn_record("Please verify the agreed payment of $100.", ["USD"], "cross_border", "en")
        self.assertEqual(check([record]).errors, [])

    def test_nonpermitted_currency_names_codes_and_unicode_signs_rejected(self):
        for amount in ("GBP 100", "100 GBP", "£100", "￡１００", "EUR\u202f100", "€100", "100欧元", "HKD:100", "100港币",
                       "100日元", "JPY 100", "AUD 100", "CAD 100", "SGD 100", "₹100", "₽100", "HK$100"):
            record = cn_record("请核对款项：" + amount + "。", [])
            self.assertTrue(any("unsupported currency" in error for error in check([record]).errors), amount)

    def test_currency_metadata_matches_observed_and_usd_requires_reason(self):
        self.assertTrue(any("missing from currencies" in error for error in check([cn_record(currencies=[])]).errors))
        domestic_usd = cn_record("这笔服务款是100美元，请核对。", ["USD"])
        self.assertTrue(any("currency_context" in error for error in check([domestic_usd]).errors))
        for field in ("cross_border_context",):
            record = cn_record("本次结算100美元。", ["USD"], "cross_border")
            record.pop(field)
            self.assertTrue(any(field in error for error in check([record]).errors))
        record = cn_record("本次结算100美元。", ["USD"], "cross_border")
        record["input"].pop("business_context")
        self.assertTrue(any("input.business_context" in error for error in check([record]).errors))
        for value in (None, ["GBP"], ["CNY", "CNY"], [[]]):
            record = cn_record()
            record["currencies"] = value
            self.assertTrue(check([record]).errors)

    def test_domestic_usd_business_passes_with_explicit_currency_context(self):
        record = cn_record("这笔美元存款已经入账，目前账户余额为2,450美元，麻烦核对一下。", ["USD"])
        record["currency_context"] = "中国大陆企业核对境内银行美元存款余额，本次不涉及跨境付款。"
        record["input"]["business_context"] = "企业已有境内银行美元账户，财务正在核对美元存款入账和账户余额。"
        self.assertEqual(check([record], require_cn_context=True).errors, [])
        missing_reason = copy.deepcopy(record)
        missing_reason.pop("currency_context")
        self.assertTrue(any("currency_context" in error for error in check([missing_reason]).errors))
        missing_reason["cross_border_context"] = "A generic international context does not explain a domestic USD transaction."
        self.assertTrue(any("currency_context" in error for error in check([missing_reason]).errors))
        record["input"].pop("business_context")
        self.assertTrue(any("input.business_context" in error for error in check([record]).errors))

    def test_no_amounts_and_swift_codes_do_not_invent_currency(self):
        record = cn_record("资料已更新，麻烦在原工单里确认一下。SWIFT代码是BARCGB22，内部状态缩写GBP已登记。", [])
        self.assertEqual(check([record]).errors, [])
        self.assertEqual(validator.currency_observations("银行标识为CHASUS33USD")[1:], (set(), []))

    def test_provenance_currency_text_is_not_scanned(self):
        record = cn_record("资料已更新，麻烦在原工单里确认一下。", [])
        record["provenance"]["sources"][0].update(url="https://example.com/GBP100", title="EUR 100 fee table", supports="Historical GBP fees.")
        self.assertEqual(check([record]).errors, [])

    def test_cn_context_is_opt_in_or_explicitly_required(self):
        record = legacy_fixture()
        self.assertEqual(check([record]).errors, [])
        self.assertTrue(check([record], require_cn_context=True).errors)
        record["business_region"] = "CN"
        self.assertTrue(any("transaction_scope" in error for error in check([record]).errors))

    def test_pairs_share_currency_context_and_register(self):
        records = fixture()
        for record in records:
            record.update(business_region="CN", transaction_scope="domestic", currencies=[], register="daily_business")
        self.assertEqual(check(records).errors, [])
        records[1]["currencies"] = ["CNY"]
        self.assertTrue(any("same currencies" in error for error in check(records).errors))
        records[1]["currencies"] = []
        records[1]["currency_context"] = "不同的币种背景"
        self.assertTrue(any("same currency_context" in error for error in check(records).errors))
        records[1].pop("currency_context")
        records[1]["register"] = "formal_notice"
        self.assertTrue(any("same register" in error for error in check(records).errors))
        records[1]["register"] = "anything"
        self.assertTrue(any("register must be" in error for error in check(records).errors))

    def test_detailed_current_body_passes_in_three_languages(self):
        mixed = ZH_DETAIL.split("\n\n")[0] + "\n\n" + EN_DETAIL.split("\n\n")[0] + "\n\n" + ZH_DETAIL.split("\n\n")[1]
        for language, body, metric, minimum in (("zh", ZH_DETAIL, "cjk", 350),
                                                ("en", EN_DETAIL, "english_words", 220),
                                                ("zh-en", mixed, "weighted_units", 350)):
            with self.subTest(language=language):
                self.assertGreaterEqual(validator.substantive_counts(body)[metric], minimum)
                self.assertEqual(check([detailed_record(language, body)], require_detailed=True).errors, [])

    def test_long_history_and_context_do_not_rescue_short_current_body(self):
        record = detailed_record("en", "Please review the agreed statement.")
        record["input"]["history"][0]["body"] = EN_DETAIL
        record["input"]["business_context"] = EN_DETAIL
        record["input"]["current_email"]["subject"] = EN_DETAIL
        self.assertTrue(any("minimum 220" in error for error in check([record]).errors))

    def test_quotation_padding_does_not_count(self):
        markers = ("----- Original Message -----\n", "------------------ 原始邮件 ------------------\n",
                   "From: [EMAIL_1]\nSent: yesterday\n", "On Wednesday, the finance team wrote:\n",
                   "在昨天财务部写道：\n", "> ")
        for marker in markers:
            with self.subTest(marker=marker):
                body = "Please review the agreed statement.\n\n" + marker + EN_DETAIL
                self.assertLess(validator.substantive_counts(body)["english_words"], 20)
                self.assertTrue(check([detailed_record("en", body)]).errors)

    def test_duplicate_paragraphs_do_not_inflate_minimum(self):
        paragraph = EN_DETAIL.split("\n\n")[0]
        body = "\n\n".join([paragraph] * 5)
        counts = validator.substantive_counts(body)
        self.assertEqual(counts["english_words"], validator.substantive_counts(paragraph)["english_words"])
        self.assertEqual(counts["duplicate_paragraphs"], 4)
        report = check([detailed_record("en", body)])
        self.assertTrue(report.errors)
        self.assertTrue(any("duplicates did not count" in warning for warning in report.warnings))

    def test_signature_tokens_links_and_digit_padding_do_not_count(self):
        padding = " ".join(["[ANY_TOKEN_1]", "[REDACTED:PERSON_1]", "https://example.com/many/extra/words", "1,234.50"] * 50)
        body = "Dear team,\n\nPlease review the statement.\n\n" + padding + "\n\nThanks,\n\n" + EN_DETAIL
        self.assertEqual(validator.substantive_counts(body)["english_words"], 4)

    def test_content_profile_is_optional_but_require_detailed_is_explicit(self):
        self.assertEqual(check([legacy_fixture()]).errors, [])
        self.assertTrue(any("--require-detailed" in error for error in check([legacy_fixture()], require_detailed=True).errors))
        record = legacy_fixture()
        record["content_profile"] = "concise"
        self.assertEqual(check([record]).errors, [])
        record["content_profile"] = []
        self.assertTrue(check([record]).errors)

    def test_pair_profile_and_detailed_length_ratio(self):
        records = fixture()
        for record in records:
            record["content_profile"] = "detailed"
            record["input"]["current_email"]["body"] = EN_DETAIL
            record["target"]["evidence"][0]["spans"] = [{"path": "/input/current_email/body", "quote": "We have completed"}]
        records[1]["input"]["current_email"]["body"] += "\n\n" + EN_DETAIL.replace("refund", "credit").replace("payment", "settlement")
        report = check(records)
        self.assertTrue(any("length ratio" in warning for warning in report.warnings))
        records[1]["content_profile"] = "concise"
        self.assertTrue(any("same content_profile" in error for error in check(records).errors))

    def test_huge_detailed_body_warns_without_upper_length_error(self):
        body = "\n\n".join(EN_DETAIL.replace("refund", word) for word in ("refund", "credit", "reimbursement", "repayment"))
        report = check([detailed_record("en", body)])
        self.assertEqual(report.errors, [])
        self.assertTrue(any("twice recommended maximum" in warning for warning in report.warnings))

    def test_v2_valid_pair(self):
        report = check(fixture(), strict=True)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])

    def test_legacy_compatibility_and_strict_gate(self):
        self.assertEqual(check([legacy_fixture()]).errors, [])
        self.assertTrue(any("--strict" in e for e in check([legacy_fixture()], strict=True).errors))

    def test_type_errors_report_without_crashing(self):
        cases = [
            (("input", "current_email", "body"), 123),
            (("input", "current_email", "subject"), 123),
            (("input", "current_email", "from", "address"), 123),
            (("provenance", "kind"), []), (("language",), []), (("difficulty",), {}),
            (("target", "label"), []), (("target", "evidence", 0, "code"), ["invalid"]),
            (("target", "evidence", 0, "detail"), 123), (("pair_id",), []),
            (("scenario_type",), {}), (("input", "history", 0, "subject"), 123),
        ]
        for path, value in cases:
            with self.subTest(path=path):
                record = fixture()[0]
                assign(record, path, value)
                self.assertTrue(check([record]).errors)

    def test_missing_required_scenario_and_empty_dataset(self):
        record = legacy_fixture()
        record.pop("scenario")
        self.assertTrue(any("scenario" in e for e in check([record]).errors))
        self.assertTrue(check([]).errors)

    def test_optional_message_fields_are_validated(self):
        for key, value in (("cc", "not a list"), ("attachments", {}), ("attachments", [{"name": "x.pdf"}]),
                           ("sent_at", "not a date"), ("sent_at", "2026-02-30T12:00+00:00"),
                           ("sent_at", "2026-11-11T12:00"), ("reply_to", 5)):
            with self.subTest(key=key, value=value):
                record = fixture()[0]
                record["input"]["current_email"][key] = value
                self.assertTrue(check([record]).errors)

    def test_v2_provenance_links_and_types(self):
        cases = [
            (("provenance", "sources"), []),
            (("provenance", "sources", 0, "url"), "not a URL"),
            (("provenance", "sources", 0, "accessed_at"), "2026-02-30"),
            (("provenance", "entities", 0, "source_ids"), ["missing"]),
            (("provenance", "entities", 0, "source_ids"), [[]]),
            (("provenance", "kind"), "source"),
        ]
        for path, value in cases:
            with self.subTest(path=path):
                record = fixture()[0]
                assign(record, path, value)
                self.assertTrue(check([record]).errors)

    def test_evidence_quotes_must_resolve_inside_input(self):
        for path, quote in (("/target/safe_action", "Verify"), ("/input/history/9/body", "refund"),
                            ("/input/history/01/body", "refund"), ("/input/history", "refund"),
                            ("/input/current_email/body", "not present"),
                            ("/input/current_email/bo~2dy", "refund")):
            with self.subTest(path=path, quote=quote):
                record = fixture()[0]
                record["target"]["evidence"][0]["spans"] = [{"path": path, "quote": quote}]
                self.assertTrue(check([record]).errors)

    def test_json_pointer_escaping(self):
        record = fixture()[0]
        record["input"]["a/b~c"] = "Supporting text."
        record["target"]["evidence"][0]["spans"] = [{"path": "/input/a~1b~0c", "quote": "Supporting text."}]
        self.assertEqual(check([record]).errors, [])

    def test_header_evidence_forbidden_even_with_extra_codes(self):
        for code in validator.FORBIDDEN_V2_CODES:
            record = fixture()[0]
            record["target"]["evidence"][0]["code"] = code
            self.assertTrue(any("header/identity" in e for e in check([record], codes=validator.KNOWN_CODES | {code}).errors))
        record = legacy_fixture()
        record["target"]["evidence"][0]["code"] = "sender_consistent"
        self.assertEqual(check([record]).errors, [])

    def test_synthetic_scope_required_only_for_v2_synthetic_records(self):
        record = fixture()[0]
        record["provenance"].pop("synthetic_scope")
        self.assertTrue(any("synthetic_scope" in e for e in check([record]).errors))
        record["provenance"]["kind"] = "redacted-source"
        self.assertEqual(check([record]).errors, [])

    def test_v2_literal_addresses_rejected_even_if_reserved(self):
        for literal in ("customer@merchant.example", "张三@例子.公司"):
            record = fixture()[0]
            record["input"]["current_email"]["body"] += " " + literal
            self.assertTrue(any("literal" in e for e in check([record]).errors))
        record = fixture()[0]
        record["input"]["current_email"]["from"]["address"] = "customer@merchant.example"
        self.assertTrue(any("[EMAIL_n]" in e for e in check([record]).errors))

    def test_v2_preserves_raw_urls_and_domains_without_fetching(self):
        for literal in ("https://merchant.example/refund", "www.example.com", "outside-corpus.com",
                        "HTTPS://outside-corpus.com/a?ref=one#two", "outside-corpus.com/path/to/resource",
                        "//outside-corpus.com/resource", "https://例子.公司/账户说明"):
            with self.subTest(literal=literal):
                record = fixture()[0]
                record["input"]["current_email"]["body"] += " " + literal
                before = copy.deepcopy(record)
                self.assertEqual(check([record], require_raw_urls=True).errors, [])
                self.assertEqual(record, before)

    def test_url_private_values_are_scanned_including_percent_encoding(self):
        for value in ("person@merchant.example", "person%40merchant.example", "person%2540merchant.example",
                      "19900000000", "%31%39%39%30%30%30%30%30%30%30%30", "110101199001011234"):
            with self.subTest(value=value):
                record = fixture()[0]
                record["input"]["current_email"]["body"] += " https://example.com/check?value=" + value
                self.assertTrue(check([record]).errors)

    def test_url_authority_separator_is_not_a_mailbox(self):
        record = fixture()[0]
        record["input"]["current_email"]["body"] += " https://example.com:443@outside-corpus.com/path"
        self.assertEqual(check([record]).errors, [])
        record["input"]["current_email"]["body"] += " https://person%40merchant.example@outside-corpus.com/path"
        self.assertTrue(any("literal e-mail" in e for e in check([record]).errors))

    def test_url_tracking_numbers_require_review_not_automatic_redaction(self):
        for value in ("111111111111111111", "123456789012", "4111111111111111"):
            record = fixture()[0]
            record["input"]["current_email"]["body"] += " https://example.com/resource/" + value
            report = check([record])
            self.assertEqual(report.errors, [])
            self.assertTrue(any("digit" in warning for warning in report.warnings))

    def test_raw_url_gate_preserves_legacy_and_does_not_require_links(self):
        record = fixture()[0]
        self.assertEqual(check([record], require_raw_urls=True).errors, [])
        record["input"]["current_email"]["body"] += " [URL_1]"
        self.assertEqual(check([record]).errors, [])
        self.assertTrue(any("--require-raw-urls" in e for e in check([record], require_raw_urls=True).errors))
        record["input"]["current_email"]["body"] = record["input"]["current_email"]["body"].replace(" [URL_1]", "")
        record["input"]["history"][0]["body"] += " [URL_2]"
        self.assertTrue(any("--require-raw-urls" in e for e in check([record], require_raw_urls=True).errors))

    def test_urls_do_not_inflate_language_or_substantive_length(self):
        body = "Please review the attached information."
        for url in ("https://example.com/these/are/not/body/words?note=中文字符",
                    "HTTPS://example.com/these/are/not/body/words", "www.example.com/these/are/not/body/words",
                    "example.com/these/are/not/body/words", "//example.com/these/are/not/body/words"):
            self.assertEqual(validator.substantive_counts(body + " " + url), validator.substantive_counts(body))
            self.assertEqual(validator.lang_counts([body + " " + url]), validator.lang_counts([body]))

    def test_url_resource_names_do_not_create_currency_claims(self):
        _, observed, disallowed = validator.currency_observations("https://example.com/EUR100?label=USD100")
        self.assertEqual(observed, set())
        self.assertEqual(disallowed, [])
        _, observed, disallowed = validator.currency_observations("人民币100元 https://example.com/EUR100")
        self.assertEqual(observed, {"CNY"})
        self.assertEqual(disallowed, [])

    def test_url_privacy_tokens_preserve_following_path_and_query_scope(self):
        body = "Please review the attached information."
        for path in ("/confirm?person=[PERSON_1]&campaign=123456789012345678",
                     "/[PERSON_1]/confirm?campaign=123456789012345678",
                     "/confirm?campaign=123456789012345678&person=[PERSON_1]"):
            with self.subTest(path=path):
                url = "https://example.com" + path
                findings = validator.sensitive_findings(url, strict_numbers=True, allow_raw_urls=True)
                self.assertTrue(findings)
                self.assertTrue(all(severity == "warn" for severity, _ in findings))
                self.assertEqual(validator.substantive_counts(body + " " + url), validator.substantive_counts(body))
                self.assertEqual(validator.lang_counts([body + " " + url]), validator.lang_counts([body]))
                self.assertEqual(validator.URL_TEXT_RE.search("[Review](" + url + ") then continue.").group(0), url)

    def test_private_values_after_url_privacy_tokens_remain_detectable(self):
        for value in ("person@merchant.example", "person%40merchant.example", "19900000000"):
            for path in ("/[PERSON_1]/confirm?value=", "/confirm?person=[PERSON_1]&value="):
                with self.subTest(value=value, path=path):
                    findings = validator.sensitive_findings("https://example.com" + path + value,
                                                           strict_numbers=True, allow_raw_urls=True)
                    self.assertTrue(any(severity == "error" for severity, _ in findings))

    def test_v2_rejects_account_placeholders_and_undeclared_long_numbers(self):
        for value in ("[ACCOUNT_1]", "SYN-ACCT-6230-0042", "4420 1566 4000 5251 9408"):
            record = fixture()[0]
            record["input"]["current_email"]["body"] += " Account: " + value
            self.assertTrue(check([record]).errors, value)

    def test_sourced_account_with_spaces_is_preserved(self):
        record = fixture()[0]
        # This is a declaration-validation fixture, not a source verification test.
        value = "1111 1111 1111 1111 1111"
        record["provenance"]["identifiers"] = [{"kind": "bank_account", "value": value,
                                               "source_ids": ["src_refund"], "basis": "official_public",
                                               "owner": "Test Corporation", "bank": "Test Bank"}]
        record["provenance"]["entities"] += [
            {"name": "Test Corporation", "role": "account owner", "source_ids": ["src_refund"]},
            {"name": "Test Bank", "role": "bank", "source_ids": ["src_refund"]},
        ]
        record["input"]["current_email"]["body"] += " Account: " + value
        self.assertEqual(check([record]).errors, [])

    def test_chinese_adjacent_sensitive_values(self):
        for text in ("手机19900000000", "账号111111111111111111", "域名outside-corpus.com"):
            self.assertTrue(validator.sensitive_findings(text), text)
        self.assertEqual(validator.sensitive_findings("账号SYN-ACCT-6230-0042"), [])

    def test_url_userinfo_does_not_hide_real_host(self):
        self.assertTrue(validator.sensitive_findings("https://example.com:443@outside-corpus.com/path"))
        self.assertEqual(validator.sensitive_findings("https://outside-corpus.com:443@example.com/path"), [])
        self.assertTrue(validator.is_reserved("host.example:443"))
        self.assertFalse(validator.is_reserved("host.example:invalid"))

    def test_pair_rejects_undeclared_differences(self):
        records = fixture()
        records[1]["input"]["current_email"]["subject"] = "Different subject"
        self.assertTrue(any("actual differing" in e for e in check(records).errors))

    def test_pair_requires_shared_context_and_entities(self):
        for path, value in ((("input", "history", 0, "body"), "A changed history."),
                            (("input", "business_context"), "A different context."),
                            (("domain",), "finance"), (("scenario",), "A different scenario."),
                            (("provenance", "entities", 0, "role"), "customer")):
            with self.subTest(path=path):
                records = fixture()
                assign(records[1], path, value)
                self.assertTrue(check(records).errors)

    def test_pairs_cardinality_labels_and_odd_count(self):
        records = fixture()
        third = copy.deepcopy(records[0])
        third["id"] = "r_0e8a02f4"
        self.assertTrue(any("exactly two" in e for e in check(records + [third]).errors))
        records[1]["target"]["label"] = "malicious"
        self.assertTrue(any("one record of each" in e for e in check(records).errors))
        singleton = check(fixture()[:1])
        self.assertEqual(singleton.errors, [])
        self.assertTrue(any("singleton" in w for w in singleton.warnings))

    def test_scenario_pair_allows_multiple_current_message_changes(self):
        records = fixture()
        for record in records:
            record["pair_type"] = "scenario"
            record.pop("changed_paths")
        records[1]["input"]["current_email"]["subject"] = "Refund update"
        self.assertEqual(check(records).errors, [])

    def test_identical_inputs_cannot_have_conflicting_labels_even_in_legacy(self):
        left = legacy_fixture()
        right = copy.deepcopy(left)
        right["id"] = "another-record"
        right["target"]["label"] = "benign"
        self.assertTrue(any("identical input" in e for e in check([left, right]).errors))

    def test_label_bearing_ids_rejected_only_in_v2(self):
        for rid in ("TRAIN-001-M", "rec_benign_001"):
            record = fixture()[0]
            record["id"] = rid
            self.assertTrue(any("opaque" in e for e in check([record]).errors))
        record = legacy_fixture()
        record["id"] = "TRAIN-001-M"
        self.assertEqual(check([record]).errors, [])

    def test_declared_identifiers_exempt_numbers_but_not_urls_or_partial_matches(self):
        record = fixture()[0]
        record["provenance"]["identifiers"] = [{"kind": "bank_account", "value": "111111111111111111",
                                               "source_ids": ["src_refund"], "basis": "user_authorized_source",
                                               "owner": "Test Store", "bank": "Test Bank"}]
        record["provenance"]["entities"].append({"name": "Test Bank", "role": "bank", "source_ids": ["src_refund"]})
        record["input"]["current_email"]["body"] += " Account: 111111111111111111"
        self.assertEqual(check([record]).errors, [])
        record["provenance"]["identifiers"][0]["source_ids"] = ["missing"]
        self.assertTrue(any("18-digit" in e for e in check([record]).errors))
        self.assertTrue(validator.sensitive_findings("账号111111111111111111", ["111111"]))
        self.assertTrue(validator.sensitive_findings("https://outside-corpus.com", ["https://outside-corpus.com"]))

    def test_raw_url_identifier_exemption_is_exact_and_cannot_hide_private_values(self):
        value = "111111111111111111"
        url = "https://example.com/account?code=" + value
        self.assertEqual(validator.sensitive_findings(url, [value], strict_numbers=True, allow_raw_urls=True), [])
        self.assertTrue(validator.sensitive_findings(url, ["111111"], strict_numbers=True, allow_raw_urls=True))
        url = "https://example.com/account?phone=19900000000"
        self.assertTrue(validator.sensitive_findings(url, [url], strict_numbers=True, allow_raw_urls=True))
        record = fixture()[0]
        record["provenance"]["identifiers"] = [{"kind": "customer_number", "value": url,
                                               "source_ids": ["src_refund"], "basis": "official_public",
                                               "owner": "Test Store"}]
        self.assertTrue(any("not a URL" in e for e in check([record]).errors))

    def test_identifier_ownership_fields_and_declared_entities_required(self):
        base = fixture()[0]
        base["provenance"]["identifiers"] = [{"kind": "bank_account", "value": "111111111111111111",
                                             "source_ids": ["src_refund"], "basis": "official_public",
                                             "owner": "Test Store", "bank": "Test Bank"}]
        base["provenance"]["entities"].append({"name": "Test Bank", "role": "bank", "source_ids": ["src_refund"]})
        self.assertEqual(check([base]).errors, [])
        for field in ("owner", "bank"):
            record = copy.deepcopy(base)
            record["provenance"]["identifiers"][0].pop(field)
            self.assertTrue(any(f".{field} is required" in e for e in check([record]).errors))
            record = copy.deepcopy(base)
            record["provenance"]["identifiers"][0][field] = "An undeclared organization"
            self.assertTrue(any("exactly match" in e for e in check([record]).errors))
        for kind, required in (("institution_code", ("owner", "code_system")), ("customer_number", ("owner",))):
            for field in required:
                record = copy.deepcopy(base)
                identifier = record["provenance"]["identifiers"][0]
                identifier.update(kind=kind, code_system="Test Code System")
                identifier.pop(field)
                self.assertTrue(any(f".{field} is required" in e for e in check([record]).errors))

    def test_malformed_identifier_declaration_does_not_crash(self):
        for value in ([[]], None, ["missing"]):
            record = fixture()[0]
            record["provenance"]["identifiers"] = [{"kind": "bank_account", "value": "111111111111111111",
                                                   "source_ids": value, "basis": "user_authorized_source"}]
            self.assertTrue(check([record]).errors)

    def test_json_loader_handles_errors_and_legacy_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            for text in ('[{"id":"a","id":"b"}]', '[NaN]', '', '[broken'):
                path.write_text(text, encoding="utf-8")
                report = validator.Report()
                validator.load(path, report)
                self.assertTrue(report.errors)
            path.write_text(json.dumps(legacy_fixture()) + "\n", encoding="utf-8")
            report = validator.Report()
            self.assertEqual(len(validator.load(path, report)), 1)
            self.assertEqual(report.errors, [])
            report = validator.Report()
            validator.load(Path(directory) / "missing.json", report)
            self.assertTrue(report.errors)

    def test_cli_success_and_failure_exit_statuses(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text(json.dumps(fixture()), encoding="utf-8")
            command = [sys.executable, str(Path(validator.__file__)), str(path), "--strict"]
            good = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
            path.write_text(json.dumps([legacy_fixture()]), encoding="utf-8")
            bad = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(bad.returncode, 1)
            self.assertNotIn("Traceback", bad.stderr)

    def test_cli_raw_urls_flag_rejects_tokens_and_reports_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            records = fixture()
            path.write_text(json.dumps(records), encoding="utf-8")
            command = [sys.executable, str(Path(validator.__file__)), str(path), "--strict", "--require-raw-urls"]
            good = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
            self.assertIn("URLs were not fetched", good.stdout)
            records[0]["input"]["current_email"]["body"] += " [URL_1]"
            path.write_text(json.dumps(records), encoding="utf-8")
            bad = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(bad.returncode, 1)
            self.assertIn("--require-raw-urls rejects", bad.stdout)


if __name__ == "__main__":
    unittest.main()
