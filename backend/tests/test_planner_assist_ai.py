"""Phase 4.3 API, security, consent, rate-limit and provider tests for POST /api/ai/planner-assist.
The deterministic scheduling rules themselves are tested separately in test_planner_assist.py."""
import hashlib
import json
import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from base import ApiTestCase  # noqa: E402
from test_ai_plan import (EVIL_URL, FAKE_KEY, AiPlanCase, Clock, FakeResponse, FakeTransport,  # noqa: E402
                          block_real_network, status_response)
from test_insights_ai import PHASE41_PROMPT_SHA256, FakeJsonProvider  # noqa: E402

import ai_provider  # noqa: E402
import planner_assist_ai  # noqa: E402
from ai_provider import GeminiProvider, GroqProvider, ProviderChain, ProviderError, RateLimiter  # noqa: E402

SECRET_SUBJECT, SECRET_TASK, BOB_TASK = "Zebra Calculus", "Quokka Report", "Bob Private Essay"
URL = "/api/ai/planner-assist"
RULE_ONLY = {"aiGenerated", "source", "notice", "summary", "tips"}


class PlannerCase(AiPlanCase):
    def setUp(self):
        super().setUp()
        self.subject = self.add_subject("alice", SECRET_SUBJECT)["subject_id"]

    def seed(self):
        for title, due, imp in (("Overdue one", "2026-11-14", "high"), (SECRET_TASK, "2026-11-16", "medium"), ("Soon", "2026-11-18", "low"), ("Later", "2026-12-20", "medium")):
            self.add_task("alice", title=title, deadline=due, importance=imp, subject_id=self.subject)
        self.add_task("bob", title=BOB_TASK)

    def ask(self, user="alice", consent=True, **extra):
        body = {} if consent is ... else {"aiConsent": consent}
        return self.call("POST", URL, user, json={**body, **extra})

    def good(self):
        return {"summary": "Begin with T1 and keep steady, focused work going on S1.",
                "tips": [{"focus": "overdue", "text": "Give T1 your full attention in one calm sitting."},
                         {"focus": "balance", "text": "Keep T2 and T3 ticking over without letting them pile up."}]}

    def use_good(self, **kw):
        return self.use(FakeJsonProvider(json.dumps(self.good()), **kw), None)

    def use_reply(self, reply):
        return self.use(FakeJsonProvider(json.dumps(reply) if not isinstance(reply, str) else reply))

    def plan_part(self, body):
        return {k: v for k, v in body.items() if k not in RULE_ONLY and k not in ("mock",)}


class EndpointTests(PlannerCase):
    def test_needs_a_token(self):
        self.assertEqual(self.call("POST", URL, user=None, json={}).status_code, 401)

    def test_bad_bodies(self):
        self.assertEqual(self.call("POST", URL, json=[1]).status_code, 400)
        cases = {"aiConsent": ["true", 1, "yes", None, []], "hoursPerDay": [0, 0.1, 9, "x", True, None, [], float("inf")],
                 "horizonDays": [0, 15, 1.5, "7", True, None, -1]}
        for field, values in cases.items():
            for bad in values:
                r = self.call("POST", URL, json={field: bad})
                self.assertEqual(r.status_code, 422, (field, bad))
                self.assertIn(field, r.get_json()["errors"])

    def test_bounds_and_defaults(self):
        for body, hours, days in (({}, 2.0, 7), ({"hoursPerDay": 0.25, "horizonDays": 1}, 0.25, 1), ({"hoursPerDay": "1.5", "horizonDays": 14}, 1.5, 14)):
            r = self.call("POST", URL, json=body)
            self.assertEqual(r.status_code, 200, body)
            c = r.get_json()["capacity"]
            self.assertEqual((c["hoursPerDay"], c["horizonDays"], len(r.get_json()["schedule"])), (hours, days, days))

    def test_response_schema_is_identical_for_rule_based_and_ai_and_plan_is_untouched_by_ai(self):
        self.seed()
        rule = self.ask(consent=False)
        self.assertEqual((rule.status_code, rule.headers["Cache-Control"]), (200, "no-store"))
        rule_body = rule.get_json()
        self.use_good()
        ai = self.ask(consent=True)
        self.assertEqual(ai.headers["Cache-Control"], "no-store")
        ai_body = ai.get_json()
        keys = {"mock", "aiGenerated", "source", "notice", "asOf", "summary", "tips", "capacity", "nextTask", "prioritizedTasks", "schedule", "warnings", "limitations"}
        self.assertEqual(set(rule_body), keys); self.assertEqual(set(ai_body), keys)
        self.assertEqual((rule_body["mock"], rule_body["aiGenerated"], rule_body["source"]), (False, False, "rule-based"))
        self.assertEqual((ai_body["mock"], ai_body["aiGenerated"], ai_body["source"]), (False, True, "groq"))
        self.assertEqual(self.plan_part(rule_body), self.plan_part(ai_body))   # schedule, order, numbers, warnings: identical
        self.assertEqual(rule_body["asOf"], "2026-11-16")
        self.assertEqual(rule_body["nextTask"]["title"], rule_body["prioritizedTasks"][0]["title"])

    def test_students_see_only_their_own_data_and_nothing_is_written(self):
        self.seed()
        writes = len(self.db.writes)
        text = json.dumps(self.ask(consent=False).get_json())
        self.assertNotIn(BOB_TASK, text); self.assertIn(SECRET_TASK, text)
        bob = json.dumps(self.ask("bob", consent=False).get_json())
        self.assertIn(BOB_TASK, bob); self.assertNotIn(SECRET_TASK, bob)
        self.assertEqual(len(self.db.writes), writes)

    def test_client_cannot_supply_identity_or_tasks(self):
        self.seed()
        r = self.ask("bob", consent=False, uid="alice", student_id="alice", tasks=[{"title": "Injected"}]).get_json()
        self.assertEqual([t["title"] for t in r["prioritizedTasks"]], [BOB_TASK])

    def test_empty_account(self):
        r = self.ask().get_json()
        self.assertEqual((r["aiGenerated"], r["nextTask"], r["prioritizedTasks"], r["tips"]), (False, None, [], []))
        self.assertIn("no open tasks", r["notice"])


class GateTests(ApiTestCase):
    enable_v2 = False

    def test_503_when_v2_is_off_after_the_token_check(self):
        self.assertEqual(self.call("POST", URL, json={}).status_code, 503)
        self.assertEqual(self.call("POST", URL, user=None, json={}).status_code, 401)


class ConsentAndLimiterTests(PlannerCase):
    def test_no_consent_unconfigured_or_no_tasks_never_reach_a_provider_or_use_quota(self):
        provider = self.use_good()
        lim = self.app.extensions["taim_planner_limiter"]
        self.assertEqual(self.ask(consent=False).get_json()["aiGenerated"], False)      # open tasks absent too
        self.seed()
        for body in ({}, {"aiConsent": False}):
            self.assertFalse(self.call("POST", URL, json=body).get_json()["aiGenerated"])
        self.assertIn("consent box", self.ask(consent=False).get_json()["notice"])
        self.assertEqual((provider.calls, lim._hits), ([], {}))
        self.use(None)
        self.assertIn("not available", self.ask().get_json()["notice"])
        self.assertEqual(lim._hits, {})
        provider = self.use_good()
        self.assertIn("no open tasks", self.ask("carol").get_json()["notice"])
        self.assertEqual((provider.calls, lim._hits), ([], {}))

    def test_completed_only_account_uses_no_quota(self):
        tid = self.add_task("alice", subject_id=self.subject)["task_id"]
        self.call("POST", f"/api/tasks/{tid}/complete")
        provider = self.use_good()
        self.assertIn("no open tasks", self.ask().get_json()["notice"])
        self.assertEqual(provider.calls, [])

    def test_dedicated_limiter_is_separate_from_plan_and_insights(self):
        a = self.app.extensions
        self.assertIsNot(a["taim_planner_limiter"], a["taim_ai_limiter"]); self.assertIsNot(a["taim_planner_limiter"], a["taim_insights_limiter"])
        self.seed(); clock = Clock()
        a["taim_planner_limiter"] = RateLimiter(2, 10, clock=clock)
        provider = self.use_good()
        self.assertTrue(self.ask().get_json()["aiGenerated"]); self.assertTrue(self.ask().get_json()["aiGenerated"])
        limited = self.ask().get_json()
        self.assertFalse(limited["aiGenerated"]); self.assertIn("limit reached", limited["notice"])
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual((a["taim_ai_limiter"]._hits, a["taim_insights_limiter"]._hits), ({}, {}))
        self.assertEqual(self.plan_part(limited), self.plan_part(self.ask(consent=False).get_json()))
        clock.now += 61
        self.assertTrue(self.ask().get_json()["aiGenerated"])

    def test_failover_counts_once(self):
        self.seed()
        limiter = self.app.extensions["taim_planner_limiter"] = RateLimiter(10, 10)
        self.use(ProviderChain([FakeJsonProvider(error=ProviderError("http_error", 400, "bad_request")), FakeJsonProvider(json.dumps(self.good()), source="gemini")], 12.0))
        r = self.ask().get_json()
        self.assertEqual((r["aiGenerated"], r["source"]), (True, "gemini"))
        self.assertEqual(len(limiter._hits["alice"]), 1)


class PrivacyTests(PlannerCase):
    def test_wire_payload_has_no_personal_text_ids_or_calendar_dates(self):
        self.seed()
        provider = self.use_good()
        self.ask()
        self.assertEqual(len(provider.calls), 1)
        wire = provider.calls[0]["system"] + provider.calls[0]["user"]
        for secret in (SECRET_SUBJECT, SECRET_TASK, "Overdue one", "Soon", "Later", BOB_TASK, "alice", "bob", "example.com", "Alice"):
            self.assertNotIn(secret, wire)
        for t in self.ask(consent=False).get_json()["prioritizedTasks"]:
            self.assertNotIn(t["taskId"], wire)
        self.assertIsNone(re.search(r"\d{4}-\d{2}-\d{2}", wire))
        self.assertNotIn("subject_id", wire); self.assertNotIn("deadline", provider.calls[0]["user"].replace("deadlineMinutes", ""))
        data = json.loads(provider.calls[0]["user"])
        self.assertEqual([t["label"] for t in data["tasks"]], ["T1", "T2", "T3", "T4"])
        self.assertEqual({t["subject"] for t in data["tasks"]}, {"S1"})
        self.assertEqual(set(data["tasks"][0]), {"label", "subject", "importance", "status", "daysUntil", "remainingMinutes", "estimateSource", "atRisk", "scheduledToday"})

    def test_only_a_few_tasks_are_labelled_for_large_accounts(self):
        for n in range(12):
            self.add_task("alice", title=f"Task {n}", subject_id=self.subject)
        provider = self.use_good(); self.ask()
        self.assertEqual(len(json.loads(provider.calls[0]["user"])["tasks"]), planner_assist_ai.MAX_LABELLED_TASKS)

    def test_labels_are_shown_as_real_titles_locally_only(self):
        self.seed(); self.use_good()
        r = self.ask().get_json()
        self.assertIn('"Overdue one"', r["summary"] + " ".join(t["text"] for t in r["tips"]))
        self.assertIn(SECRET_SUBJECT, r["summary"])


class ValidatorTests(PlannerCase):
    _seeded = False

    def setUp(self):
        super().setUp()
        self._seeded = False

    def run_reply(self, reply):
        if not self._seeded:
            self.seed(); self._seeded = True
        self.app.extensions["taim_planner_limiter"] = RateLimiter(1000, 1000)
        self.use_reply(reply)
        return self.ask().get_json()

    def assert_falls_back(self, reply):
        r = self.run_reply(reply)
        rule = self.ask(consent=False).get_json()
        self.assertFalse(r["aiGenerated"], reply); self.assertEqual(r["summary"], rule["summary"]); self.assertEqual(r["tips"], rule["tips"])
        self.assertEqual(self.plan_part(r), self.plan_part(rule)); self.assertEqual(r["source"], "rule-based")
        self.assertIn("could not be validated", r["notice"])

    def test_bad_summaries_are_rejected_and_fall_back(self):
        bad = ["Do T1 for 30 minutes.", "You have 3 tasks.", "About 50% done.", "Finish before 2026-11-20.", "Visit https://evil.example now.",
               "Mail me@evil.example please.", "<b>Begin</b> with T9.", "Work on T1 and T12.", "Three tasks need work.", "Fifty percent is fine.",
               "Reschedule T2 to a later week.", "Postpone T2 and skip it.", "Do it tomorrow.", "Work on it on Friday.", "Start with T2 first.",
               "Put T3 ahead of T1.", "Do T2 instead of T1.", "Work harder, you lazy student.", "Extend the deadline for T1.", "Do S1 work in the morning.",
               "Spend two hours on T1.", ""]
        for text in bad:
            self.assert_falls_back({"summary": text, "tips": [{"focus": "next", "text": "Stay steady."}]})
        self.assert_falls_back("not json"); self.assert_falls_back([1]); self.assert_falls_back({"summary": None})

    def test_benign_coaching_language_is_accepted(self):
        rule = None
        for text in (
            "You may want to focus on studying T1 in calm study sessions while keeping S1 moving steadily.",
            "Start with T1 before pressure builds, and take a breather after finishing a step.",
            "Push through T1 calmly and shift focus when ready.",
            "Start with T1 right away, since both T1 and T2 are tight against your schedule and capacity is overloaded.",
            "Start with T1 right away. Both T1 and T2 are tight against your schedule and capacity is overloaded.",
        ):
            r = self.run_reply({"summary": text, "tips": [{"focus": "next", "text": "You may keep T1 moving in study sessions."}]})
            if rule is None:
                rule = self.ask(consent=False).get_json()
            self.assertTrue(r["aiGenerated"], text)
            self.assertEqual(r["source"], "groq")
            self.assertEqual(self.plan_part(r), self.plan_part(rule))

    def test_targeted_schedule_change_month_and_study_log_rejections(self):
        for bad in (
            "Move T2 back.",
            "Shift the deadline.",
            "Drop T2.",
            "Do T3 before T1.",
            "Finish in May.",
            "In March focus on T1.",
            "You studied well.",
            "Study time was long.",
            "There are zero overdue tasks.",
            "Your two tasks are tight.",
        ):
            self.assert_falls_back({"summary": bad, "tips": []})

    def test_bad_tips_are_dropped_and_good_ones_kept(self):
        r = self.run_reply({"summary": "Begin with T1 and stay steady.", "tips": [
            {"focus": "next", "text": "Spend 20 minutes on T1."}, {"focus": "bogus", "text": "Stay calm."}, {"focus": "next", "text": 5},
            {"focus": "balance", "text": "Keep T2 progressing gently."}, {"focus": "balance", "text": "keep t2 progressing gently."}, "x",
            {"focus": "capacity", "text": "Talk to your instructor early."}, {"focus": "capacity", "text": "Ask for help early on."}, {"focus": "next", "text": "One more."}]})
        self.assertTrue(r["aiGenerated"])
        self.assertEqual([t["focus"] for t in r["tips"]], ["balance", "capacity", "capacity"])

    def test_no_valid_tips_keeps_rule_based_tips_with_ai_summary(self):
        r = self.run_reply({"summary": "Begin with T1 and stay steady.", "tips": [{"focus": "next", "text": "Do 5 things."}]})
        self.assertTrue(r["aiGenerated"]); self.assertEqual(r["tips"], self.ask(consent=False).get_json()["tips"])

    def test_reply_cannot_add_fields_or_alter_the_plan(self):
        reply = {**self.good(), "schedule": [], "nextTask": "x", "capacity": {}, "warnings": {}, "prioritizedTasks": []}
        r = self.run_reply(reply)
        self.assertTrue(r["aiGenerated"]); self.assertEqual(self.plan_part(r), self.plan_part(self.ask(consent=False).get_json()))

    def test_markdown_and_whitespace_are_cleaned(self):
        r = self.run_reply({"summary": "**Begin** with   T1,\n stay `steady`.", "tips": []})
        self.assertNotIn("*", r["summary"]); self.assertNotIn("`", r["summary"]); self.assertNotIn("\n", r["summary"])

    def test_json_in_a_code_fence_is_accepted(self):
        self.seed(); self.use_reply("```json\n" + json.dumps(self.good()) + "\n```")
        self.assertTrue(self.ask().get_json()["aiGenerated"])

    def test_start_with_t1_is_the_only_allowed_start_advice(self):
        ok = self.run_reply({"summary": "Start with T1 and breathe.", "tips": []})
        self.assertTrue(ok["aiGenerated"])
        self.assert_falls_back({"summary": "Start with T3 and breathe.", "tips": []})


class ProviderFailureTests(PlannerCase):
    def test_every_provider_failure_falls_back_cleanly(self):
        self.seed(); rule = self.ask(consent=False).get_json()
        for err in (ProviderError("timeout"), ProviderError("network"), ProviderError("quota", 429, "quota"), ProviderError("http_error", 500, "server_error"),
                    ProviderError("malformed"), RuntimeError("boom")):
            self.app.extensions["taim_planner_limiter"] = RateLimiter(10, 10)
            self.use(FakeJsonProvider(error=err))
            r = self.ask()
            self.assertEqual(r.status_code, 200)
            body = r.get_json()
            self.assertFalse(body["aiGenerated"], err); self.assertEqual(self.plan_part(body), self.plan_part(rule)); self.assertTrue(body["notice"])
        self.use(FakeJsonProvider(error=ProviderError("quota", 429, "quota")))
        self.app.extensions["taim_planner_limiter"] = RateLimiter(10, 10)
        self.assertIn("quota", self.ask().get_json()["notice"])

    def test_timeouts_and_both_failing_fall_back_with_safe_logs(self):
        self.seed(); rule = self.ask(consent=False).get_json()
        self.use(ProviderChain([
            FakeJsonProvider(json.dumps({"summary": "You studied well.", "tips": []}), source="groq"),
            FakeJsonProvider(error=ProviderError("timeout"), source="gemini"),
        ], 12.0))
        with self.assertLogs(self.app.logger, "WARNING") as logs:
            r = self.ask()
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertFalse(body["aiGenerated"]); self.assertEqual(body["source"], "rule-based")
        self.assertEqual(self.plan_part(body), self.plan_part(rule))
        joined = "\n".join(logs.output)
        self.assertIn("summary_rejected:text_contains_unsupported_topic", joined)
        self.assertIn("failed (timeout)", joined)
        for secret in (SECRET_SUBJECT, SECRET_TASK, "Overdue one", FAKE_KEY):
            self.assertNotIn(secret, joined)

    def test_provider_without_generate_json_is_treated_as_unconfigured(self):
        self.seed(); self.use(type("P", (), {"source": "groq", "generate_steps": lambda *a: []})())
        self.assertIn("not available", self.ask().get_json()["notice"])


class TransportTests(PlannerCase):
    def test_groq_then_gemini_failover_and_redirect_refusal(self):
        self.seed(); good = json.dumps(self.good()); calls = []
        transport = self.fake_network(lambda: (calls.append(1), FakeResponse({"choices": [{"message": {"content": "bad"}}]}) if len(calls) == 1
                                              else FakeResponse({"candidates": [{"content": {"parts": [{"text": good}]}}]}))[1])
        self.use(ProviderChain([GroqProvider(FAKE_KEY, "openai/gpt-oss-120b", 12.0), GeminiProvider(FAKE_KEY, "gemini-test-model", 12.0)], 12.0))
        r = self.ask().get_json()
        self.assertEqual((r["aiGenerated"], r["source"]), (True, "gemini"))
        self.assertEqual(transport.hosts(), ["api.groq.com", "generativelanguage.googleapis.com"])
        body = b"".join(req.data for req in transport.requests).decode()
        for secret in (SECRET_SUBJECT, SECRET_TASK, "alice"):
            self.assertNotIn(secret, body)
        self.assertNotIn(FAKE_KEY, body)
        self.app.extensions["taim_planner_limiter"] = RateLimiter(10, 10)
        transport.requests.clear(); transport.respond = lambda: status_response(302, EVIL_URL)
        self.use(GeminiProvider(FAKE_KEY, "gemini-test-model", 12.0))
        self.assertFalse(self.ask().get_json()["aiGenerated"]); self.assertEqual(len(transport.requests), 1)

    def test_gemini_38_flash_sends_low_thinking_level_only_for_38_flash(self):
        self.seed(); good = json.dumps(self.good()); rule = self.ask(consent=False).get_json()
        transport = self.fake_network(lambda: FakeResponse({"candidates": [{"content": {"parts": [{"text": good}]}}]}))

        GeminiProvider(FAKE_KEY, "gemini-3.8-flash", 12.0).generate_json("S", "U")
        flash_body = json.loads(transport.requests[0].data)
        self.assertEqual(flash_body["generationConfig"]["thinkingConfig"], {"thinkingLevel": "low"})
        self.assertNotIn("thinkingBudget", flash_body["generationConfig"]["thinkingConfig"])
        self.assertEqual(flash_body["generationConfig"]["maxOutputTokens"], 1500)

        for model in ("gemini-test-model", "gemini-2.0-flash"):
            transport.requests.clear()
            GeminiProvider(FAKE_KEY, model, 12.0).generate_json("S", "U")
            other_body = json.loads(transport.requests[0].data)
            self.assertNotIn("thinkingConfig", other_body["generationConfig"], model)

        transport.requests.clear(); calls = []
        transport.respond = lambda: (
            calls.append(1),
            FakeResponse({"choices": [{"message": {"content": json.dumps({"summary": "You studied well.", "tips": []})}}]})
            if len(calls) == 1
            else FakeResponse({"candidates": [{"content": {"parts": [{"text": good}]}}]}),
        )[1]
        self.use(ProviderChain([GroqProvider(FAKE_KEY, "openai/gpt-oss-120b", 12.0), GeminiProvider(FAKE_KEY, "gemini-3.8-flash", 12.0)], 12.0))
        r = self.ask().get_json()
        self.assertEqual((r["aiGenerated"], r["source"]), (True, "gemini"))
        self.assertEqual(self.plan_part(r), self.plan_part(rule))
        self.assertEqual(transport.hosts(), ["api.groq.com", "generativelanguage.googleapis.com"])

        self.app.extensions["taim_planner_limiter"] = RateLimiter(10, 10)
        transport.requests.clear(); calls.clear()
        transport.respond = lambda: (
            calls.append(1),
            FakeResponse({"choices": [{"message": {"content": json.dumps({"summary": "You studied well.", "tips": []})}}]})
            if len(calls) == 1
            else TimeoutError(),
        )[1]
        timeout_res = self.ask().get_json()
        self.assertEqual((timeout_res["aiGenerated"], timeout_res["source"]), (False, "rule-based"))
        self.assertEqual(self.plan_part(timeout_res), self.plan_part(rule))


class PreviousPhasesUntouchedTests(PlannerCase):
    def test_phase_41_prompt_and_phase_42_endpoint_still_work(self):
        self.assertEqual(hashlib.sha256(ai_provider._SYSTEM_PROMPT.encode()).hexdigest(), PHASE41_PROMPT_SHA256)
        self.seed()
        r = self.call("POST", "/api/ai/insights", json={"aiConsent": False})
        self.assertEqual(r.status_code, 200); self.assertFalse(r.get_json()["aiGenerated"])
        plan = {"title": "Research Paper", "requirements": "", "deadline": "2026-11-26", "hoursPerDay": 1, "aiConsent": True}
        self.use(type("P", (), {"source": "groq", "generate_steps": lambda s, *a: [{"title": f"Step {n}", "minutes": 20} for n in range(4)]})())
        self.assertEqual(self.call("POST", "/api/ai/plan", json=plan).get_json()["source"], "groq")


if __name__ == "__main__":
    unittest.main()