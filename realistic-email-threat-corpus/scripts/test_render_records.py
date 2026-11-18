#!/usr/bin/env python3
"""Regression tests: python3 -m unittest discover -s scripts -p 'test_*.py'."""
import copy
import email
import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime
from email import policy
from pathlib import Path

import render_records as renderer

TOKENS = re.compile(r"\[[A-Z][A-Z_]*_[0-9]+\]")


def profiled_record():
    """Fabricated canonical record exercising the render contract; not a researched email."""
    return {
        "schema_version": "2.0", "id": "r_5b20c7", "thread_family_id": "f_31d8e2", "domain": "accounting",
        "scenario_type": "employee_meal_allowance", "difficulty": "medium", "language": "zh",
        "scenario": "Fabricated payroll follow-up used only to test rendering.",
        "render": {
            "orgs": {"ORG_1": {"kind": "fictional", "region": "浙江宁波", "industry": "注塑设备制造", "suffix": "塑料机械有限公司"}},
            "people": {"PERSON_1": {"org": "ORG_1", "dept": "生产计划部", "title": "计划主管", "gender": "m", "device": "mobile"},
                       "PERSON_2": {"org": "ORG_1", "dept": "财务部", "title": "薪资专员", "gender": "f"}},
            "mailboxes": {"EMAIL_1": {"owner": "PERSON_1", "domain": "org"},
                          "EMAIL_2": {"owner": "PERSON_2", "domain": "org"},
                          "EMAIL_3": {"owner": "PERSON_1", "domain": "freemail"},
                          "EMAIL_4": {"owner": "ORG_1", "local": "hr", "domain": "lookalike"}},
            "users": {"USER_1": {"owner": "PERSON_2"}},
        },
        "input": {
            "history": [{"from": {"name": "[PERSON_2]", "address": "[EMAIL_2]"}, "to": ["[EMAIL_1]"],
                         "sent_at": "2026-11-12T09:30:00+08:00", "subject": "10月夜班餐补",
                         "body": "[SURNAME_1]工：\n10月夜班餐补按排班表算好了，明细在附件，麻烦确认人数。\n\n[SIGNATURE_2]",
                         "attachments": [{"name": "餐补明细_[CONTRACT_1].xlsx", "type": "xlsx"}]}],
            "current_email": {"from": {"name": "[PERSON_1]", "address": "[EMAIL_3]"},
                              "to": [{"name": "[PERSON_2]", "address": "[EMAIL_2]"}], "cc": ["[EMAIL_4]"],
                              "sent_at": "2026-11-12T21:05:00+08:00", "subject": "回复：10月夜班餐补",
                              "body": "[GIVEN_2]，那四个人的餐补这个月先别发了，在 https://oa.[DOMAIN_1]/flow/[SLUG_1] 里清零就行。\n\n[SIGNATURE_1]"},
        },
        "target": {"label": "malicious", "safe_action": "Confirm through the known payroll channel.",
                   "evidence": [{"code": "approval_path_bypass", "detail": "Asks payroll to drop an allowance outside the approval path.",
                                 "spans": [{"path": "/input/current_email/body", "quote": "[GIVEN_2]，那四个人的餐补这个月先别发了"},
                                           {"path": "/input/history/0/body", "quote": "按排班表算好了"}]}]},
    }


def render(record, **options):
    return renderer.Renderer(**options).render(record)[0]


class RenderTests(unittest.TestCase):
    def test_undated_threads_follow_the_run_date_across_new_year(self):
        message = {"from": "档案室", "subject": "清单", "body": "清单已收到。"}
        record = {"id": "date-test", "input": {"history": [message] * 5, "current_email": message}}
        for day in (date(2027, 12, 31), date(2028, 1, 1), date(2028, 2, 29)):
            with self.subTest(day=day):
                out = render(record, as_of=day)
                messages = out["input"]["history"] + [out["input"]["current_email"]]
                stamps = [datetime.fromisoformat(m["sent_at"]) for m in messages]
                self.assertTrue(all(s.year == day.year and s.date() <= day for s in stamps))
                self.assertTrue(all(a < b for a, b in zip(stamps, stamps[1:])))
                self.assertEqual(renderer.to_eml(out)["Date"].datetime.date(), stamps[-1].date())
                self.assertIn("sent_at", out["rendering"]["defaults"])

    def test_missing_dates_fit_between_original_timestamps_and_year_boundaries(self):
        engine = renderer.Renderer(as_of=date(2032, 1, 1))
        ctx = renderer.Context(engine, {"id": "partial-dates"})
        messages = [{}, {"sent_at": "2021-01-01T00:01:00+08:00"}, {},
                    {"sent_at": "2021-01-01T00:02:00+08:00"}, {"sent_at": "2021-12-31T23:59:00+08:00"}, {}]
        stamps = engine.timeline(ctx, messages)
        self.assertTrue(all(s.year == 2021 for s in stamps))
        self.assertTrue(all(a < b for a, b in zip(stamps, stamps[1:])))
        for i in (1, 3, 4):
            self.assertEqual(stamps[i], datetime.fromisoformat(messages[i]["sent_at"]))

    def test_filled_date_stays_in_year_across_time_zones(self):
        day = date(2031, 12, 31)
        engine = renderer.Renderer(as_of=day)
        ctx = renderer.Context(engine, {"id": "offset-boundary"})
        stamps = engine.timeline(ctx, [{"sent_at": "2031-12-31T23:55:00+14:00"}, {},
                                      {"sent_at": "2031-12-31T23:58:00-10:00"}])
        self.assertEqual(stamps[1].date(), day)
        self.assertLess(stamps[0], stamps[1])
        self.assertLess(stamps[1], stamps[2])

    def test_all_tokens_render_consistently(self):
        out = render(profiled_record())
        text = json.dumps(out["input"], ensure_ascii=False)
        self.assertIsNone(TOKENS.search(text), TOKENS.findall(text))
        current, history = out["input"]["current_email"], out["input"]["history"][0]
        writer, payroll = current["from"]["name"], current["to"][0]["name"]
        self.assertTrue(history["body"].startswith(writer[0] + "工"))
        self.assertTrue(current["body"].startswith(payroll[1:] + "，") or current["body"].startswith(payroll[2:] + "，"))
        self.assertIn(writer, current["body"])
        self.assertNotIn("[", history["attachments"][0]["name"])

    def test_mailbox_relationships_follow_the_profile(self):
        out = render(profiled_record())
        current, history = out["input"]["current_email"], out["input"]["history"][0]
        org_domain = re.search(r"https://oa\.([^/]+)/flow/", current["body"]).group(1)
        self.assertTrue(history["from"]["address"].endswith("@" + org_domain))
        self.assertTrue(current["to"][0]["address"].endswith("@" + org_domain))
        self.assertIn(current["from"]["address"].split("@")[1], dict(renderer.FREEMAIL))
        hr = current["cc"][0]["address"]
        self.assertTrue(hr.startswith("hr@"))
        self.assertNotEqual(hr.split("@")[1], org_domain)

    def test_rendering_never_depends_on_the_label(self):
        record = profiled_record()
        flipped = copy.deepcopy(record)
        flipped["target"] = {"label": "benign", "safe_action": "None", "evidence": []}
        self.assertEqual(render(record)["input"], render(flipped)["input"])

    def test_seed_family_and_variant_control_personas(self):
        record = profiled_record()
        self.assertEqual(render(record)["input"], render(record)["input"])
        self.assertNotEqual(render(record)["input"], render(record, variant=2)["input"])
        self.assertNotEqual(render(record)["input"], render(record, seed=7)["input"])
        sibling = copy.deepcopy(record)
        sibling["id"] = "r_9e01aa"
        sibling["input"]["current_email"]["body"] = "[GIVEN_2]，餐补按原排班表发放即可。\n\n[SIGNATURE_1]"
        a, b = render(record)["input"], render(sibling)["input"]
        self.assertEqual(a["history"], b["history"])
        self.assertEqual(a["current_email"]["from"], b["current_email"]["from"])
        self.assertEqual(a["current_email"]["to"], b["current_email"]["to"])

    def test_reply_is_quoted_with_client_prefix_and_footer(self):
        out = render(profiled_record())
        current, history = out["input"]["current_email"], out["input"]["history"][0]
        client = out["rendering"]["client"]
        self.assertTrue(current["subject"].startswith(renderer.REPLY_PREFIX[client]))
        self.assertEqual(current["subject"].count("10月夜班餐补"), 1)
        self.assertIn("10月夜班餐补按排班表算好了", current["body"])
        self.assertTrue("发自我的iPhone" in current["body"] or "Outlook for iOS" in current["body"])
        self.assertNotIn("发自我的iPhone", history["body"])
        authored = current["body"].split("\n\n")
        self.assertEqual(authored[1], current["from"]["name"])
        flat = render(profiled_record(), history="array")["input"]["current_email"]["body"]
        self.assertNotIn("按排班表算好了", flat)

    def test_new_subject_is_not_quoted(self):
        record = profiled_record()
        record["input"]["current_email"]["subject"] = "关于夜班餐补的调整"
        body = render(record)["input"]["current_email"]["body"]
        self.assertNotIn("按排班表算好了", body)

    def test_evidence_quotes_stay_exact(self):
        out = render(profiled_record())
        self.assertEqual(out["rendering"]["warnings"], [])
        for span in out["target"]["evidence"][0]["spans"]:
            self.assertIn(span["quote"], renderer.resolve(out, span["path"]))

    def test_heldout_pool_shares_no_given_or_trade_names_with_train(self):
        def names(pool):
            given, orgs = set(), set()
            for i in range(150):
                record = profiled_record()
                record["thread_family_id"] = f"f_{i}"
                ctx = renderer.Context(renderer.Renderer(pool=pool), record)
                given.add(ctx.person("PERSON_1")["given"])
                given.add(ctx.person("PERSON_2")["given"])
                orgs.add(ctx.org("ORG_1")["trade"])
            return given, orgs
        train, heldout = names("train"), names("heldout")
        self.assertFalse(train[0] & heldout[0])
        self.assertFalse(train[1] & heldout[1])

    def test_generated_names_avoid_blocklists(self):
        for i in range(400):
            record = profiled_record()
            record["thread_family_id"] = f"f_{i}"
            ctx = renderer.Context(renderer.Renderer(), record)
            self.assertNotIn(ctx.person("PERSON_1")["name"], renderer.NAME_BLOCKLIST)
            self.assertNotIn(ctx.org("ORG_1")["trade"], renderer.TRADE_BLOCKLIST)

    def test_real_organizations_keep_sourced_domains_and_no_generated_lookalikes(self):
        record = profiled_record()
        record["render"]["orgs"]["ORG_2"] = {"kind": "real", "name": "中国建设银行", "domain": "ccb.com", "source_ids": ["SRC-1"]}
        record["render"]["mailboxes"]["EMAIL_5"] = {"owner": "ORG_2", "local": "service", "domain": "org"}
        record["input"]["current_email"]["body"] += "\n[ORG_2] [EMAIL_5] https://[LOOKALIKE_2]/"
        out = render(record)
        body = out["input"]["current_email"]["body"]
        self.assertIn("中国建设银行 service@ccb.com", body)
        self.assertIn("[LOOKALIKE_2]", body)
        self.assertTrue(any("real organization" in w for w in out["rendering"]["warnings"]))

    def test_legacy_record_uses_flagged_defaults(self):
        record = profiled_record()
        record.pop("render")
        record["input"]["current_email"]["from"] = "生产计划｜[PERSON_1]"
        record["input"]["current_email"].pop("to")
        for message in record["input"]["history"] + [record["input"]["current_email"]]:
            message.pop("sent_at")
        out = render(record)
        current = out["input"]["current_email"]
        self.assertIsNone(TOKENS.search(json.dumps(out["input"], ensure_ascii=False)))
        self.assertRegex(current["from"], r"^生产计划｜\S+ <[^@\s]+@[^>\s]+>$")
        self.assertEqual(len(current["to"]), 1)
        self.assertLess(out["input"]["history"][0]["sent_at"], current["sent_at"])
        for flag in ("no_render_profile", "sent_at", "recipient"):
            self.assertIn(flag, out["rendering"]["defaults"])

    def test_eml_round_trip(self):
        out = render(profiled_record())
        message = email.message_from_bytes(renderer.to_eml(out).as_bytes(), policy=policy.default)
        current = out["input"]["current_email"]
        self.assertEqual(message["From"].addresses[0].addr_spec, current["from"]["address"])
        self.assertEqual(message["Subject"], current["subject"])
        self.assertTrue(message["In-Reply-To"])
        self.assertEqual(message["X-Corpus-Rendered"], "fictional; not real correspondence")
        self.assertIn(current["body"].splitlines()[0], message.get_body(("plain",)).get_content())
        self.assertIn("<blockquote" if "写道" in current["body"] else "border-top", message.get_body(("html",)).get_content())

    def test_cli_writes_json_eml_and_names_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.json"
            path.write_text(json.dumps([profiled_record()], ensure_ascii=False), encoding="utf-8")
            script = str(Path(renderer.__file__))
            result = subprocess.run([sys.executable, script, str(path), "--out", str(Path(directory) / "out.json"),
                                     "--variants", "2", "--names-report", str(Path(directory) / "names.json")],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            rendered = json.loads((Path(directory) / "out.json").read_text(encoding="utf-8"))
            self.assertEqual([r["id"] for r in rendered], ["r_5b20c7.v1", "r_5b20c7.v2"])
            self.assertEqual({r["thread_family_id"] for r in rendered}, {"f_31d8e2"})
            self.assertNotIn("render", rendered[0])
            self.assertTrue(json.loads((Path(directory) / "names.json").read_text(encoding="utf-8"))["people"])
            result = subprocess.run([sys.executable, script, str(path), "--format", "eml", "--out", str(Path(directory) / "eml")],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((Path(directory) / "eml" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest[0]["label"], "malicious")
            self.assertTrue((Path(directory) / "eml" / manifest[0]["file"]).exists())


if __name__ == "__main__":
    unittest.main()
