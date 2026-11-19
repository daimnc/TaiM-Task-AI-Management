"""Phase 4.2: AI Insights tests (Option 1: Deterministic Core + Optional AI Enhancement)."""
import copy
import hashlib
import io
import json
import pathlib
import sys
import unittest
import urllib.error

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from base import TODAY, ApiTestCase  # noqa: E402
from test_ai_plan import (EVIL_URL, FAKE_KEY, AiPlanCase, Clock, FakeResponse, FakeTransport,  # noqa: E402
                          block_real_network, status_response)

import ai_provider  # noqa: E402
import insights  # noqa: E402
import insights_ai  # noqa: E402
import store  # noqa: E402
from ai_provider import GeminiProvider, GroqProvider, ProviderChain, ProviderError, RateLimiter  # noqa: E402
from config import Config  # noqa: E402
from insights import flatten_facts  # noqa: E402

SECRET_SUBJECT, SECRET_TASK = "Zebra Calculus", "Quokka Report"
PHASE41_PROMPT_SHA256 = "3794e8ff7a0bd1c198792e4eb95dee9b504679a745fb379b0f93a47fe94d266e"


class FakeJsonProvider:
    def __init__(self, reply=None, error=None, source="groq", timeout=12.0):
        self.reply, self.error, self.source, self.timeout, self.calls = reply, error, source, timeout, []

    def generate_json(self, system_prompt, user_text, timeout=None, max_tokens=2048):
        self.calls.append({"system": system_prompt, "user": user_text, "timeout": timeout})
        if self.error is not None:
            raise self.error
        return self.reply(self) if callable(self.reply) else self.reply


class InsightsCase(AiPlanCase):
    def setUp(self):
        super().setUp()
        self.subject = self.add_subject("alice", SECRET_SUBJECT)["subject_id"]

    def seed(self, user="alice"):
        for title, due in (("Overdue one", "2026-11-14"), (SECRET_TASK, "2026-11-16"), ("Soon", "2026-11-18"),
                           ("Later", "2026-12-20")):
            self.add_task(user, title=title, deadline=due, subject_id=self.subject)
        for n in range(5):
            tid = self.add_task(user, title=f"Done {n}", deadline="2026-11-25", subject_id=self.subject)["task_id"]
            self.call("POST", f"/api/tasks/{tid}/complete", user)

    def facts(self, user="alice"):
        return insights.build_facts(store.list_task_docs(self.db, user), store.list_subjects(self.db, user), TODAY)

    def ask(self, user="alice", consent=True, **extra):
        body = {} if consent is ... else {"aiConsent": consent}
        return self.call("POST", "/api/ai/insights", user, json={**body, **extra})

    def good(self):
        return {
            "summary": "You have open work concentrated in S1 with overdue tasks that need immediate attention.",
            "suggestions": [
                {"area": "deadlines", "text": "Start with T1 first to clear your overdue work."},
                {"area": "workload", "text": "Break one upcoming task in S1 into small steps."},
            ],
        }

    def use_good(self, **kw):
        return self.use(FakeJsonProvider(json.dumps(self.good()), **kw))


class EndpointAndSchemaTests(InsightsCase):
    def test_needs_a_token(self):
        self.assertEqual(self.call("POST", "/api/ai/insights", user=None, json={}).status_code, 401)

    def test_bad_bodies(self):
        self.assertEqual(self.call("POST", "/api/ai/insights", json=[1]).status_code, 400)
        for bad in ("true", 1, "yes", None, [], {}):
            r = self.ask(consent=bad)
            self.assertEqual(r.status_code, 422, bad)
            self.assertIn("aiConsent", r.get_json()["errors"])

    def test_response_schema_is_consistent_between_rule_based_and_ai(self):
        self.seed()
        rule = self.ask(consent=False)
        self.assertEqual(rule.status_code, 200)
        self.assertEqual(rule.headers["Cache-Control"], "no-store")
        rule_body = rule.get_json()
        self.use_good()
        ai_body = self.ask(consent=True).get_json()
        expected_keys = {"mock", "aiGenerated", "source", "notice", "summary", "insights", "suggestions", "facts", "limitations"}
        self.assertEqual(set(rule_body), expected_keys)
        self.assertEqual(set(ai_body), expected_keys)
        self.assertEqual((rule_body["mock"], rule_body["aiGenerated"], rule_body["source"]), (False, False, "rule-based"))
        self.assertEqual((ai_body["mock"], ai_body["aiGenerated"], ai_body["source"]), (False, True, "groq"))
        expected_insights = insights.rule_based_insights(self.facts())["insights"]
        self.assertEqual([i["area"] for i in rule_body["insights"]], list(insights.AREAS))
        self.assertEqual(rule_body["insights"], expected_insights)
        self.assertEqual(ai_body["insights"], expected_insights)
        for body in (rule_body, ai_body):
            self.assertTrue(body["suggestions"])
            for sug in body["suggestions"]:
                self.assertEqual(set(sug), {"area", "text"})
                self.assertIn(sug["area"], insights.AREAS)
                self.assertIsInstance(sug["text"], str)
        self.assertEqual(rule_body["facts"], ai_body["facts"])
        self.assertEqual(rule_body["limitations"], ai_body["limitations"])

    def test_facts_match_engine_without_internal_ids(self):
        self.seed()
        shown = self.ask(consent=False).get_json()["facts"]
        self.assertEqual(flatten_facts(shown), flatten_facts(self.facts()))
        self.assertTrue(all("subjectId" not in row for row in shown["workload"]["subjects"]))
        self.assertNotIn("notes", shown["dataQuality"])

    def test_empty_account_and_progress_unchanged_and_no_writes(self):
        r = self.ask(consent=True).get_json()
        self.assertFalse(r["aiGenerated"])
        self.assertEqual([i["area"] for i in r["insights"]], list(insights.AREAS))
        self.assertEqual(r["suggestions"], [])
        self.seed()
        before = self.call("GET", "/api/progress").get_json()
        self.use_good()
        snapshot = copy.deepcopy(self.db.store)
        self.ask()
        self.ask(consent=False)
        self.assertEqual(self.db.store, snapshot)
        self.assertEqual(self.call("GET", "/api/progress").get_json(), before)


class GateTests(ApiTestCase):
    enable_v2 = False

    def test_gate_off_is_503_and_provider_never_called(self):
        provider = FakeJsonProvider("{}")
        self.app.extensions["taim_ai"] = provider
        self.assertEqual(self.call("POST", "/api/ai/insights", json={"aiConsent": True}).status_code, 503)
        self.assertEqual((provider.calls, self.db.store), ([], {}))


class ConsentAndRateLimitTests(InsightsCase):
    def test_no_consent_and_unconfigured_return_full_deterministic_core(self):
        self.seed()
        r_unconf = self.ask().get_json()
        self.assertFalse(r_unconf["aiGenerated"])
        self.assertEqual([i["area"] for i in r_unconf["insights"]], list(insights.AREAS))
        provider = self.use_good()
        for consent in (False, ...):
            r = self.ask(consent=consent).get_json()
            self.assertFalse(r["aiGenerated"])
            self.assertIn("consent box was not ticked", r["notice"])
            self.assertEqual([i["area"] for i in r["insights"]], list(insights.AREAS))
            self.assertTrue(r["suggestions"])
        self.assertEqual(provider.calls, [])

    def test_non_json_provider_and_no_tasks_use_zero_allowance(self):
        self.seed()
        limiter = RateLimiter(2, 10)
        self.use(type("OnlyPlans", (), {"generate_steps": lambda *a: []})())
        self.app.extensions["taim_insights_limiter"] = limiter
        self.assertIn("not available", self.ask().get_json()["notice"])
        self.assertEqual(limiter._hits, {})

    def test_no_tasks_does_not_call_provider(self):
        provider = self.use(FakeJsonProvider("{}"))
        r = self.ask().get_json()
        self.assertIn("no tasks to analyse", r["notice"])
        self.assertEqual((provider.calls, self.app.extensions["taim_insights_limiter"]._hits), ([], {}))

    def test_rate_limits_and_per_student_isolation(self):
        self.assertEqual((Config.INSIGHTS_RATE_PER_MINUTE, Config.INSIGHTS_RATE_PER_DAY), (2, 10))
        self.assertIsNot(self.app.extensions["taim_insights_limiter"], self.app.extensions["taim_ai_limiter"])
        self.seed()
        bob_sub = self.add_subject("bob", "Other")["subject_id"]
        self.add_task("bob", title="Bob task", subject_id=bob_sub)
        provider = self.use_good()
        clock = Clock()
        self.app.extensions["taim_insights_limiter"] = RateLimiter(2, 10, clock=clock)
        self.assertTrue(self.ask("alice").get_json()["aiGenerated"])
        self.assertTrue(self.ask("alice").get_json()["aiGenerated"])
        third = self.ask("alice").get_json()
        self.assertFalse(third["aiGenerated"])
        self.assertIn("request limit reached", third["notice"])
        self.assertEqual([i["area"] for i in third["insights"]], list(insights.AREAS))
        self.assertTrue(self.ask("bob").get_json()["aiGenerated"])
        self.assertEqual(len(provider.calls), 3)


class SuccessAndFallbackTests(InsightsCase):
    def test_labels_substituted_and_incomplete_suggestions_handled(self):
        self.seed()
        self.use_good()
        r = self.ask().get_json()
        self.assertEqual((r["aiGenerated"], r["source"], r["mock"]), (True, "groq", False))
        texts = " ".join([r["summary"]] + [s["text"] for s in r["suggestions"]])
        self.assertIn(SECRET_SUBJECT, texts)
        self.assertIn('"Overdue one"', texts)
        self.assertNotRegex(texts, r"\b[ST]\d\b")

        self.app.extensions["taim_insights_limiter"] = RateLimiter(10, 10)
        self.use(FakeJsonProvider(json.dumps({
            "summary": "Prioritize S1 tasks first.",
            "suggestions": [{"area": "bogus", "text": "x"}, {"area": "deadlines", "text": "5 overdue"},
                            {"area": "workload", "text": "S9 bad"}],
        })))
        r2 = self.ask().get_json()
        self.assertTrue(r2["aiGenerated"])
        self.assertEqual([i["area"] for i in r2["insights"]], list(insights.AREAS))
        self.assertEqual(r2["suggestions"], insights.rule_based_insights(self.facts())["suggestions"])

    def test_gemini_fenced_and_failover_and_every_error_fallback(self):
        self.seed()
        self.use(FakeJsonProvider("```json\n" + json.dumps(self.good()) + "\n```", source="gemini"))
        r = self.ask().get_json()
        self.assertEqual((r["aiGenerated"], r["source"]), (True, "gemini"))

        self.app.extensions["taim_insights_limiter"] = RateLimiter(10, 10)
        self.use(ProviderChain([FakeJsonProvider(error=ProviderError("http_error", 400, "bad_request")),
                                FakeJsonProvider(json.dumps(self.good()), source="gemini")], 12.0))
        self.assertEqual(self.ask().get_json()["source"], "gemini")

        for outcome in (ProviderError("timeout"), ProviderError("network"), ProviderError("quota"),
                        ProviderError("malformed"), ProviderError("invalid_output"), RuntimeError(f"secret {FAKE_KEY}")):
            self.app.extensions["taim_insights_limiter"] = RateLimiter(10, 10)
            self.use(FakeJsonProvider(error=outcome))
            resp = self.ask()
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertEqual((body["aiGenerated"], body["source"]), (False, "rule-based"))
            self.assertEqual([i["area"] for i in body["insights"]], list(insights.AREAS))
            self.assertNotIn(FAKE_KEY, json.dumps(body))


class PrivacyAndValidatorTests(InsightsCase):
    def test_privacy_and_isolation(self):
        self.seed()
        bob_sub = self.add_subject("bob", "Bobs Private")["subject_id"]
        self.add_task("bob", title="Bobs Task", subject_id=bob_sub)
        provider = self.use_good()
        self.ask("alice")
        wire = provider.calls[0]["system"] + provider.calls[0]["user"]
        for secret in (SECRET_SUBJECT, SECRET_TASK, "Overdue one", "Bobs", "alice", "@", self.subject):
            self.assertNotIn(secret, wire)
        self.assertNotRegex(wire, r"\d{4}-\d{2}-\d{2}")
        self.assertEqual(json.loads(provider.calls[0]["user"])["numeric_facts"]["completion.totalTasks"], 9)

    def test_validator_blocks_numbers_and_unsupported_topics_but_allows_qualitative_english(self):
        self.seed()
        f = self.facts()
        for bad in ("4 tasks open.", "100% in S1.", "Two tasks overdue.", "50 percent done.",
                    "Study in the evening.", "About two hours.", "Reopened tasks.", "S9 task.", "https://evil.example"):
            with self.assertRaises(ProviderError):
                insights_ai.validate_ai_output(json.dumps({"summary": bad, "suggestions": []}), f)
        out = insights_ai.validate_ai_output(json.dumps({
            "summary": "<b>Focus</b> on T1 first while keeping one S1 task moving.",
            "suggestions": [{"area": "deadlines", "text": "Do T1 first."}, {"area": "workload", "text": "do t1 first."}],
        }), f)
        self.assertEqual(out["summary"], "Focus on T1 first while keeping one S1 task moving.")
        self.assertEqual(len(out["suggestions"]), 1)


class GroqJsonAndEndToEndTests(InsightsCase):
    def test_groq_reasoning_parameter_gating_and_safe_400_code(self):
        transport = self.fake_network(lambda: FakeResponse({"choices": [{"message": {"content": '{"ok":2}', "reasoning": "HIDDEN"}}]}))
        for model in ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "meta-models/muse-spark-open"):
            transport.requests.clear()
            GroqProvider(FAKE_KEY, model, 7.0).generate_json("S", "U")
            body = json.loads(transport.requests[0].data)
            self.assertIs(body["include_reasoning"], False)
            self.assertEqual(body["reasoning_effort"], "low")
            self.assertGreaterEqual(body["max_completion_tokens"], 2048)

        for model in ("openai/gpt-oss-safeguard-20b", "minimaxai/minimax-m2.7"):
            transport.requests.clear()
            GroqProvider(FAKE_KEY, model, 7.0).generate_json("S", "U")
            body = json.loads(transport.requests[0].data)
            self.assertIs(body["include_reasoning"], False)
            self.assertNotIn("reasoning_effort", body)

        for model in ("llama-3.3-70b-versatile", "meta-llama/llama-4-scout-17b-16e-instruct", "qwen/qwen3-vl-32b-instruct"):
            transport.requests.clear()
            GroqProvider(FAKE_KEY, model, 7.0).generate_json("S", "U")
            body = json.loads(transport.requests[0].data)
            self.assertNotIn("include_reasoning", body)
            self.assertNotIn("reasoning_effort", body)

        err_body = json.dumps({"error": {"message": f"secret {FAKE_KEY}", "code": "json_validate_failed"}}).encode()
        transport.respond = lambda: urllib.error.HTTPError(ai_provider.GROQ_API_URL, 400, "Bad", {}, io.BytesIO(err_body))
        with self.assertRaises(ProviderError) as ctx:
            GroqProvider(FAKE_KEY, "openai/gpt-oss-120b", 7.0).generate_json("S", "U")
        self.assertEqual((ctx.exception.status_code, ctx.exception.category, ctx.exception.provider_code),
                         (400, "bad_request", "json_validate_failed"))
        self.assertNotIn(FAKE_KEY, str(ctx.exception) + repr(vars(ctx.exception)))

    def test_end_to_end_failover_redirects_and_phase41_untouched(self):
        self.seed()
        good = json.dumps(self.good())
        calls = []
        transport = self.fake_network(lambda: (calls.append(1), FakeResponse({"choices": [{"message": {"content": "bad"}}]}) if len(calls) == 1 else FakeResponse({"candidates": [{"content": {"parts": [{"text": good}]}}]}))[1])
        self.use(ProviderChain([GroqProvider(FAKE_KEY, "openai/gpt-oss-120b", 12.0), GeminiProvider(FAKE_KEY, "gemini-test-model", 12.0)], 12.0))
        r = self.ask().get_json()
        self.assertEqual((r["aiGenerated"], r["source"]), (True, "gemini"))
        self.assertEqual(transport.hosts(), ["api.groq.com", "generativelanguage.googleapis.com"])

        self.app.extensions["taim_insights_limiter"] = RateLimiter(10, 10)
        transport.requests.clear()
        transport.respond = lambda: status_response(302, EVIL_URL)
        self.use(GeminiProvider(FAKE_KEY, "gemini-test-model", 12.0))
        self.assertFalse(self.ask().get_json()["aiGenerated"])
        self.assertEqual(len(transport.requests), 1)

        self.assertEqual(hashlib.sha256(ai_provider._SYSTEM_PROMPT.encode()).hexdigest(), PHASE41_PROMPT_SHA256)
        plan = {"title": "Research Paper", "requirements": "", "deadline": "2026-11-26", "hoursPerDay": 1, "aiConsent": True}
        self.use(type("P", (), {"source": "groq", "generate_steps": lambda s, *a: [{"title": f"Step {n}", "minutes": 20} for n in range(4)]})())
        self.assertEqual(self.call("POST", "/api/ai/plan", json=plan).get_json()["source"], "groq")


if __name__ == "__main__":
    unittest.main()
