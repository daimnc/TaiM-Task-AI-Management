"""Phase 4.1 tests: optional Groq/Gemini suggestions for POST /api/ai/plan.

Nothing here uses a real API key, a real model or the real network:
  * the app is built with a FAKE provider (or none);
  * urllib.request.urlopen and the socket-level connect() are blocked in every test, so any real network attempt
    FAILS the test;
  * where real provider classes are tested, only the lowest layer (urllib's HTTPS handler) is replaced by a
    fake transport that returns canned responses. The real opener, redirect handling and error handling still run.

Run from the backend folder:
    python -m unittest tests.test_ai_plan -v
"""
import email.message
import http.client
import io
import json
import pathlib
import socket
import sys
import unittest
import urllib.error
import urllib.parse
import urllib.request
import urllib.response
from datetime import date, timedelta
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from base import TODAY, ApiTestCase  # noqa: E402  (must come first: it keeps real keys out of the tests)

import ai_provider  # noqa: E402
import fallback_ai  # noqa: E402
from ai_provider import GeminiProvider, GroqProvider, ProviderChain, ProviderError, RateLimiter  # noqa: E402
from config import Config, _bounded_float  # noqa: E402

PLAN = {"title": "Research Paper", "requirements": "Intro and conclusion", "deadline": "2026-11-26",
        "hoursPerDay": "0.5", "aiConsent": True}
GOOD = [{"title": "Outline the paper", "minutes": 30}, {"title": "Collect three sources", "minutes": 60},
        {"title": "Write the draft", "minutes": 120}, {"title": "Revise the draft", "minutes": 45},
        {"title": "Proofread and submit", "minutes": 20}]
FAKE_KEY = "SECRET-KEY-123"


class FakeProvider:
    """Stands in for Gemini: records what it was given and returns or raises what the test wants."""

    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def generate_steps(self, title, requirements, deadline, hours_per_day):
        self.calls.append({"title": title, "requirements": requirements, "deadline": deadline, "hours": hours_per_day})
        if self.error is not None:
            raise self.error
        return self.result


class FakeResponse:
    """A 200 response as urllib's HTTPErrorProcessor expects to see it."""
    code, msg = 200, "OK"

    def __init__(self, payload=None, raw=None):
        self._raw = raw if raw is not None else json.dumps(payload).encode("utf-8")

    def info(self):
        return email.message.Message()

    def read(self, size=-1):
        return self._raw if size is None or size < 0 else self._raw[:size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def gemini_payload(steps):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps({"steps": steps})}]}}]}


def groq_payload(steps, reasoning="DO NOT EXPOSE THIS REASONING"):
    return {"choices": [{"message": {"content": json.dumps({"steps": steps}), "reasoning": reasoning}}]}


def http_error(code):
    return urllib.error.HTTPError("https://example.invalid/", code, "error", {}, io.BytesIO(b""))


GEMINI_URL = ai_provider.API_BASE + "gemini-test-model:generateContent"
EVIL_URL = "https://evil.example/steal"


def status_response(code, location=None, url=GEMINI_URL):
    """A non-2xx HTTP response, as the transport layer would hand it to urllib (so urllib decides what to do with it)."""
    headers = email.message.Message()
    if location is not None:
        headers["Location"] = location
    response = urllib.response.addinfourl(io.BytesIO(b""), headers, url, code)
    response.msg = "Test status"
    return response


class FakeTransport:
    """Replaces ONLY urllib's HTTPS handler (the layer that would open a socket). Every request that reaches it is
    recorded in `requests`; `respond()` says what to answer (a response object, or an exception to raise)."""

    def __init__(self, respond=None):
        self.requests = []
        self.respond = respond or (lambda: FakeResponse(gemini_payload(GOOD)))
        self._real_handler = urllib.request.HTTPSHandler

    def https_open(self, request):
        self.requests.append(request)
        outcome = self.respond()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def install(self):
        transport = self

        class FakeHTTPSHandler(self._real_handler):  # a subclass, so build_opener drops its default HTTPSHandler
            def https_open(self, request):
                return transport.https_open(request)

        urllib.request.HTTPSHandler = FakeHTTPSHandler

    def uninstall(self):
        urllib.request.HTTPSHandler = self._real_handler

    def hosts(self):
        return [urllib.parse.urlsplit(r.full_url).hostname for r in self.requests]


def block_real_network(case):
    """Any attempt to open a real connection (through urlopen OR through an opener) fails the test."""
    real_urlopen = urllib.request.urlopen
    real_connect = (http.client.HTTPConnection.connect, http.client.HTTPSConnection.connect)

    def blocked(*args, **kwargs):
        raise AssertionError("A test tried to use the real network.")

    urllib.request.urlopen = blocked
    http.client.HTTPConnection.connect = blocked
    http.client.HTTPSConnection.connect = blocked

    def restore():
        urllib.request.urlopen = real_urlopen
        http.client.HTTPConnection.connect, http.client.HTTPSConnection.connect = real_connect

    case.addCleanup(restore)


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


class AiPlanCase(ApiTestCase):
    """Base for these tests: blocks the real network and gives helpers to plug a provider in."""

    def setUp(self):
        super().setUp()
        block_real_network(self)

    def fake_network(self, respond=None):
        transport = FakeTransport(respond)
        transport.install()
        self.addCleanup(transport.uninstall)
        return transport

    def use(self, provider, limiter=None):
        self.app.extensions["taim_ai"] = provider
        if limiter is not None:
            self.app.extensions["taim_ai_limiter"] = limiter
        return provider

    def plan(self, user="alice", **over):
        body = {**PLAN, **over}
        return self.call("POST", "/api/ai/plan", user, json={k: v for k, v in body.items() if v is not ...})


class IsolationTests(AiPlanCase):
    def test_tests_run_without_any_real_key_or_model(self):
        self.assertEqual(Config.GEMINI_API_KEY, "")
        self.assertEqual(Config.GEMINI_MODEL, "")
        self.assertEqual(Config.GROQ_API_KEY, "")
        self.assertEqual(Config.GROQ_MODEL, "")
        self.assertIsNone(self.app.extensions["taim_ai"])

    def test_the_network_guard_really_blocks(self):
        with self.assertRaises(AssertionError):
            urllib.request.urlopen("https://example.invalid/")

    def test_the_key_is_not_kept_in_app_config(self):
        self.assertNotIn("GEMINI_API_KEY", self.app.config)
        self.assertNotIn("GROQ_API_KEY", self.app.config)

    def test_timeout_setting_is_bounded_and_bad_values_use_the_default(self):
        self.assertEqual(_bounded_float("99", 10.0, 3.0, 12.0), 12.0)
        self.assertEqual(_bounded_float("0", 10.0, 3.0, 12.0), 3.0)
        self.assertEqual(_bounded_float("7.5", 10.0, 3.0, 12.0), 7.5)
        for bad in (None, "", "abc", "nan"):
            self.assertEqual(_bounded_float(bad, 10.0, 3.0, 12.0), 10.0, bad)
        self.assertEqual((Config.AI_RATE_PER_MINUTE, Config.AI_RATE_PER_DAY), (3, 20))


class TemplateUnchangedTests(AiPlanCase):
    def test_refactored_template_matches_the_original_algorithm_exactly(self):
        steps = ["Define scope and outline", "Gather and review sources", "Draft main sections",
                 "Revise and add citations", "Final proofread and submit"]

        def original(deadline, hours, today):  # the pre-refactor build_plan logic, copied verbatim
            days_left = max((date.fromisoformat(deadline) - today).days, 0)
            count, minutes_per_day = len(steps), int(round(hours * 60))
            out, previous = [], 0
            for index, step in enumerate(steps):
                offset = (days_left * (index + 1) + count // 2) // count
                step_days = max(offset - previous, 1)
                previous = offset
                out.append({"title": step, "dueDate": (today + timedelta(days=offset)).isoformat(),
                            "minutes": minutes_per_day * step_days})
            return out

        for delta in list(range(-10, 60)) + [90, 365, 1000]:
            deadline = (TODAY + timedelta(days=delta)).isoformat()
            for hours in (0.25, 0.5, 1.0, 2.0, 2.5, 8.0):
                result = fallback_ai.build_plan("T", deadline, hours, TODAY)
                self.assertEqual(result["subtasks"], original(deadline, hours, TODAY), (delta, hours))
                self.assertEqual(result["notice"], "Rule-based fallback plan: a fixed five-step template spread evenly "
                                                   "before the deadline. No AI model was used.")
                self.assertEqual((result["mock"], result["aiGenerated"], result["source"]),
                                 (True, False, "deterministic-fallback"))

    def test_reason_is_only_appended_to_the_notice(self):
        plain = fallback_ai.build_plan("T", "2026-11-26", 1.0, TODAY)
        with_reason = fallback_ai.build_plan("T", "2026-11-26", 1.0, TODAY, "Extra.")
        self.assertEqual(plain["subtasks"], with_reason["subtasks"])
        self.assertEqual(with_reason["notice"], plain["notice"] + " Extra.")


class ConsentTests(AiPlanCase):
    def test_no_consent_field_means_template_and_provider_is_never_called(self):
        provider = self.use(FakeProvider(GOOD))
        body = self.plan(aiConsent=...).get_json()
        self.assertEqual(provider.calls, [])
        self.assertIs(body["aiGenerated"], False)
        self.assertEqual(body["source"], "deterministic-fallback")
        self.assertIn("consent box was not ticked", body["notice"])
        self.assertIn("No AI model was used", body["notice"])

    def test_consent_false_means_template_and_provider_is_never_called(self):
        provider = self.use(FakeProvider(GOOD))
        body = self.plan(aiConsent=False).get_json()
        self.assertEqual(provider.calls, [])
        self.assertIs(body["aiGenerated"], False)

    def test_consent_must_be_a_real_true_or_false(self):
        provider = self.use(FakeProvider(GOOD))
        for value in ("true", "yes", 1, 0, "false", None, [], {}):
            r = self.plan(aiConsent=value)
            self.assertEqual(r.status_code, 422, repr(value))
            self.assertIn("aiConsent", r.get_json()["errors"])
        self.assertEqual(provider.calls, [])

    def test_consent_without_a_configured_provider_uses_the_template(self):
        body = self.plan().get_json()  # no provider configured
        self.assertIs(body["aiGenerated"], False)
        self.assertIn("not available on this server", body["notice"])
        self.assertEqual(len(body["subtasks"]), 5)

    def test_consent_sends_exactly_the_four_disclosed_fields_to_the_provider(self):
        provider = self.use(FakeProvider(GOOD))
        self.assertEqual(self.plan().status_code, 200)
        self.assertEqual(provider.calls, [{"title": "Research Paper", "requirements": "Intro and conclusion",
                                           "deadline": "2026-11-26", "hours": 0.5}])


class SuccessTests(AiPlanCase):
    def test_ai_response_has_the_template_shape_and_is_labelled_as_ai(self):
        self.use(FakeProvider(GOOD))
        r = self.plan()
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(set(body), {"mock", "aiGenerated", "source", "notice", "subtasks"})
        self.assertEqual((body["mock"], body["aiGenerated"], body["source"]), (False, True, "gemini"))
        self.assertIn("Review each step", body["notice"])
        self.assertEqual([s["title"] for s in body["subtasks"]], [s["title"] for s in GOOD])
        for step in body["subtasks"]:
            self.assertEqual(set(step), {"title", "dueDate", "minutes"})
            self.assertIsInstance(step["minutes"], int)
        due = [s["dueDate"] for s in body["subtasks"]]
        self.assertEqual(due, sorted(due))
        self.assertEqual(due[-1], "2026-11-26")
        self.assertGreaterEqual(due[0], "2026-11-16")

    def test_due_dates_never_go_beyond_today_for_a_past_deadline(self):
        self.use(FakeProvider(GOOD))
        body = self.plan(deadline="2026-11-01").get_json()
        self.assertEqual({s["dueDate"] for s in body["subtasks"]}, {"2026-11-16"})

    def test_model_dates_are_ignored_and_minutes_are_kept(self):
        self.use(FakeProvider([{**s, "dueDate": "1999-01-01"} for s in GOOD]))
        body = self.plan().get_json()
        self.assertNotIn("1999-01-01", [s["dueDate"] for s in body["subtasks"]])
        self.assertEqual([s["minutes"] for s in body["subtasks"]], [s["minutes"] for s in GOOD])

    def test_output_is_sanitized_before_it_is_returned(self):
        messy = [{"title": "1. **Read <b>sources</b>**", "minutes": 30}, {"title": "read sources", "minutes": 40},
                 {"title": "See https://evil.example", "minutes": 10}, {"title": "x" * 200, "minutes": 10},
                 {"title": "Plan\x00the\x07outline", "minutes": 1}, {"title": "Write", "minutes": 99999},
                 {"title": "Edit", "minutes": True}, {"title": "Review", "minutes": 2.5}, "junk"]
        messy += [{"title": f"Extra step {i}", "minutes": 20} for i in range(12)]
        self.use(FakeProvider(messy))
        titles = [s["title"] for s in self.plan().get_json()["subtasks"]]
        self.assertEqual(titles[:3], ["Read sources", "Plan the outline", "Write"])
        self.assertLessEqual(len(titles), 8)
        self.assertEqual(len(titles), len({t.casefold() for t in titles}))
        self.assertFalse(any(("<" in t or ">" in t or "http" in t or "*" in t) for t in titles))

    def test_suggestions_are_saved_only_when_the_student_adds_them(self):
        task = self.add_task()
        self.use(FakeProvider(GOOD))
        writes_before = list(self.db.writes)
        body = self.plan().get_json()
        self.assertEqual(self.db.writes, writes_before)  # generating wrote nothing
        self.assertEqual(self.get_task(task["task_id"])["subtasks"], [])
        items = [{"title": s["title"], "estimated_minutes": s["minutes"]} for s in body["subtasks"][:2]]
        r = self.call("POST", f"/api/tasks/{task['task_id']}/subtasks", json={"subtasks": items})
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertEqual(len(r.get_json()["subtasks"]), 2)  # only after the explicit add

    def test_the_twenty_subtask_limit_is_still_enforced_by_the_existing_endpoint(self):
        task = self.add_task()
        twenty = [{"title": f"Step {i}", "estimated_minutes": 10} for i in range(20)]
        self.assertEqual(self.call("POST", f"/api/tasks/{task['task_id']}/subtasks", json={"subtasks": twenty}).status_code, 201)
        r = self.call("POST", f"/api/tasks/{task['task_id']}/subtasks", json={"subtasks": twenty[:1]})
        self.assertEqual(r.status_code, 422)


    def test_groq_source_is_preserved_in_the_success_response(self):
        provider = FakeProvider(GOOD)
        provider.source = "groq"
        self.use(provider)
        response = self.plan()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["source"], "groq")
        self.assertIn("Groq", response.get_json()["notice"])


class FallbackTests(AiPlanCase):
    def template(self):
        return self.plan(aiConsent=False).get_json()["subtasks"]

    def assert_template(self, response):
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual((body["mock"], body["aiGenerated"], body["source"]), (True, False, "deterministic-fallback"))
        self.assertIn("No AI model was used", body["notice"])
        self.assertEqual(body["subtasks"], self.template())
        return body

    def test_every_provider_failure_returns_the_template_with_http_200(self):
        for reason in ("timeout", "network", "quota", "http_error", "malformed", "invalid_output"):
            self.use(FakeProvider(error=ProviderError(reason)), RateLimiter(100, 100))
            body = self.assert_template(self.plan())
            if reason != "quota":  # "quota" is itself a plain word that the quota notice uses
                self.assertNotIn(reason, body["notice"], reason)  # technical codes are never shown

    def test_quota_has_its_own_plain_notice(self):
        self.use(FakeProvider(error=ProviderError("quota")))
        self.assertIn("quota is used up", self.plan().get_json()["notice"])

    def test_unexpected_errors_are_not_500s_and_do_not_leak_details(self):
        self.use(FakeProvider(error=RuntimeError("secret internal detail")))
        with self.assertLogs(self.app.logger, "WARNING") as logs:
            r = self.plan()
        self.assert_template(r)
        self.assertNotIn("secret internal detail", r.get_data(as_text=True))
        self.assertNotIn("secret internal detail", "\n".join(logs.output))

    def test_bad_model_output_falls_back_to_the_template(self):
        bad_outputs = ["not a list", None, [], {"steps": GOOD}, [{"title": "One", "minutes": 5}] * 5,
                       [{"title": "A", "minutes": 10}, {"title": "B", "minutes": 10}],
                       [{"title": 5, "minutes": 10}] * 6, [{"title": "A", "minutes": "30"}] * 6, ["a", "b", "c"]]
        for output in bad_outputs:
            self.use(FakeProvider(output), RateLimiter(100, 100))
            self.assert_template(self.plan())


class SanitizerTests(unittest.TestCase):
    def steps(self, *titles, minutes=30):
        return [{"title": t, "minutes": minutes} for t in titles]

    def test_titles_are_cleaned(self):
        out = ai_provider.sanitize_steps(self.steps("  - Step 2: Read   the\tbrief  ", "(3) **Draft** `now`",
                                                    "<script>x()</script>Write intro", "Plain title"))
        self.assertEqual([s["title"] for s in out], ["Read the brief", "Draft now", "x()Write intro", "Plain title"])

    def test_bad_steps_are_dropped(self):
        items = self.steps("ok one", "ok two", "ok three", "", "   ", "see www.example.com", "mail me@example.com",
                           "y" * 121)
        items += [{"title": 7, "minutes": 5}, {"minutes": 5}, {"title": "no minutes"}, None, 3, "text",
                  {"title": "bool", "minutes": True}, {"title": "float", "minutes": 5.0},
                  {"title": "neg", "minutes": -5}, {"title": "zero", "minutes": 0}, {"title": "str", "minutes": "9"}]
        self.assertEqual([s["title"] for s in ai_provider.sanitize_steps(items)], ["ok one", "ok two", "ok three"])

    def test_title_of_exactly_120_characters_is_kept(self):
        out = ai_provider.sanitize_steps(self.steps("a" * 120, "b", "c"))
        self.assertEqual(len(out[0]["title"]), 120)

    def test_minutes_are_clamped(self):
        out = ai_provider.sanitize_steps([{"title": "a", "minutes": 1}, {"title": "b", "minutes": 9999},
                                          {"title": "c", "minutes": 90}])
        self.assertEqual([s["minutes"] for s in out], [5, 480, 90])

    def test_duplicates_ignoring_case_are_removed_and_at_most_eight_are_kept(self):
        out = ai_provider.sanitize_steps(self.steps("Same", "SAME", "same", *[f"Step {i}" for i in range(20)]))
        self.assertEqual(len(out), 8)
        self.assertEqual([s["title"] for s in out].count("Same"), 1)

    def test_fewer_than_three_usable_steps_is_invalid(self):
        for items in ([], self.steps("one", "two"), "text", None, {"a": 1}):
            with self.assertRaises(ProviderError) as ctx:
                ai_provider.sanitize_steps(items)
            self.assertEqual(ctx.exception.reason, "invalid_output")

    def test_parse_steps_accepts_plain_wrapped_and_fenced_json(self):
        raw = [{"title": "a", "minutes": 5}]
        self.assertEqual(ai_provider.parse_steps(json.dumps({"steps": raw})), raw)
        self.assertEqual(ai_provider.parse_steps(json.dumps(raw)), raw)
        self.assertEqual(ai_provider.parse_steps("```json\n" + json.dumps({"steps": raw}) + "\n```"), raw)

    def test_parse_steps_rejects_everything_else_as_malformed(self):
        for text in ("not json", "", "{}", '{"steps": "x"}', "123", "null", None, 5):
            with self.assertRaises(ProviderError) as ctx:
                ai_provider.parse_steps(text)
            self.assertEqual(ctx.exception.reason, "malformed", repr(text))


class GeminiProviderTests(unittest.TestCase):
    """The REAL provider class, with urlopen replaced by a fake. No network, no real key."""

    def setUp(self):
        block_real_network(self)
        self.transport = FakeTransport(lambda: self.respond())
        self.transport.install()
        self.addCleanup(self.transport.uninstall)
        self.respond = lambda: FakeResponse(gemini_payload(GOOD))
        self.provider = GeminiProvider(FAKE_KEY, "gemini-test-model", 7.0)

    @property
    def seen(self):
        """[(request, timeout)] for every request that reached the (fake) transport."""
        return [(r, r.timeout) for r in self.transport.requests]

    def call(self):
        return self.provider.generate_steps("Research Paper", "Intro and conclusion", "2026-11-26", 0.5)

    def test_successful_call_returns_the_raw_steps(self):
        self.assertEqual(self.call(), GOOD)

    def test_request_goes_to_google_with_the_key_only_in_a_header(self):
        self.call()
        request, timeout = self.seen[0]
        self.assertEqual(request.full_url, ai_provider.API_BASE + "gemini-test-model:generateContent")
        self.assertTrue(request.full_url.startswith("https://generativelanguage.googleapis.com/"))
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(timeout, 7.0)
        headers = {k.lower(): v for k, v in request.header_items()}
        self.assertEqual(headers["x-goog-api-key"], FAKE_KEY)
        self.assertNotIn(FAKE_KEY, request.full_url)
        self.assertNotIn(FAKE_KEY, request.data.decode("utf-8"))

    def test_only_the_four_disclosed_fields_are_sent(self):
        self.call()
        body = json.loads(self.seen[0][0].data)
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        task = json.loads(body["contents"][0]["parts"][0]["text"])
        self.assertEqual(task, {"task_title": "Research Paper", "requirements": "Intro and conclusion",
                                "deadline": "2026-11-26", "daily_time_hours": 0.5})

    def test_http_errors_map_to_reason_codes(self):
        for code, reason in ((429, "quota"), (403, "http_error"), (400, "http_error"), (401, "http_error"),
                             (500, "http_error"), (503, "http_error")):
            self.respond = lambda code=code: http_error(code)
            with self.assertRaises(ProviderError) as ctx:
                self.call()
            self.assertEqual(ctx.exception.reason, reason, code)

    def test_status_codes_from_the_transport_are_classified_correctly(self):
        """Same mapping, but the status travels through urllib's real response handling (not a pre-built HTTPError)."""
        for code, reason in ((429, "quota"), (403, "http_error"), (400, "http_error"), (401, "http_error"),
                             (500, "http_error"), (503, "http_error")):
            self.respond = lambda code=code: status_response(code)
            with self.assertRaises(ProviderError) as ctx:
                self.call()
            self.assertEqual(ctx.exception.reason, reason, code)
            self.assertNotIn(FAKE_KEY, str(ctx.exception) + repr(ctx.exception))

    def test_only_429_is_quota_and_403_is_not(self):
        self.respond = lambda: status_response(429)
        with self.assertRaises(ProviderError) as ctx:
            self.call()
        self.assertEqual(ctx.exception.reason, "quota")
        self.respond = lambda: status_response(403)
        with self.assertRaises(ProviderError) as ctx:
            self.call()
        self.assertEqual(ctx.exception.reason, "http_error")
        self.assertNotEqual(ai_provider.fallback_notice("http_error"), ai_provider.fallback_notice("quota"))

    def test_the_timeout_is_passed_on_to_the_request(self):
        self.call()
        self.assertEqual(self.seen[0][1], 7.0)
        self.provider = GeminiProvider(FAKE_KEY, "gemini-test-model", 3.5)
        self.call()
        self.assertEqual(self.seen[1][1], 3.5)


    def test_network_problems_map_to_reason_codes(self):
        cases = ((TimeoutError(), "timeout"), (socket.timeout(), "timeout"),
                 (urllib.error.URLError(socket.timeout()), "timeout"), (urllib.error.URLError("dns failed"), "network"),
                 (ConnectionResetError(), "network"), (http.client.IncompleteRead(b""), "network"), (OSError(), "network"))
        for error, reason in cases:
            self.respond = lambda error=error: error
            with self.assertRaises(ProviderError) as ctx:
                self.call()
            self.assertEqual(ctx.exception.reason, reason, repr(error))

    def test_malformed_responses_are_rejected(self):
        bad = (FakeResponse(raw=b"not json"), FakeResponse(raw=b""), FakeResponse({"candidates": []}),
               FakeResponse({}), FakeResponse({"candidates": [{"content": {"parts": []}}]}),
               FakeResponse({"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}),
               FakeResponse({"candidates": [{"content": {"parts": [{"text": '{"steps": 5}'}]}}]}),
               FakeResponse(raw=b"x" * (ai_provider.MAX_RESPONSE_BYTES + 10)))
        for response in bad:
            self.respond = lambda response=response: response
            with self.assertRaises(ProviderError) as ctx:
                self.call()
            self.assertEqual(ctx.exception.reason, "malformed")

    def test_key_never_appears_in_errors_or_repr(self):
        for outcome in (http_error(429), urllib.error.URLError("boom"), TimeoutError("t"), FakeResponse(raw=b"x")):
            self.respond = lambda outcome=outcome: outcome
            with self.assertRaises(ProviderError) as ctx:
                self.call()
            error = ctx.exception
            self.assertNotIn(FAKE_KEY, str(error) + repr(error))
            self.assertIsNone(error.__cause__)
            self.assertTrue(error.__suppress_context__)
        self.assertNotIn(FAKE_KEY, repr(self.provider))
        self.assertNotIn(FAKE_KEY, str(self.provider))

    def test_construction_and_configuration_rules(self):
        for key, model in (("", "m"), (FAKE_KEY, ""), (FAKE_KEY, "../x"), (FAKE_KEY, "a b"), (FAKE_KEY, "m" * 65),
                           (FAKE_KEY, None)):
            with self.assertRaises(ValueError):
                GeminiProvider(key, model, 5)
        make = lambda **kw: ai_provider.provider_from_config(SimpleNamespace(GEMINI_TIMEOUT_SECONDS=5.0, **kw))
        self.assertIsInstance(make(GEMINI_API_KEY="k", GEMINI_MODEL="gemini-x"), GeminiProvider)
        for kw in ({"GEMINI_API_KEY": "", "GEMINI_MODEL": "gemini-x"}, {"GEMINI_API_KEY": "k", "GEMINI_MODEL": ""},
                   {"GEMINI_API_KEY": "  ", "GEMINI_MODEL": "gemini-x"}, {"GEMINI_API_KEY": "k", "GEMINI_MODEL": "../x"},
                   {"GEMINI_API_KEY": None, "GEMINI_MODEL": None}):
            self.assertIsNone(make(**kw), kw)


class GroqProviderTests(unittest.TestCase):
    def setUp(self):
        block_real_network(self)
        self.transport = FakeTransport(lambda: FakeResponse(groq_payload(GOOD)))
        self.transport.install()
        self.addCleanup(self.transport.uninstall)
        self.provider = GroqProvider(FAKE_KEY, "openai/gpt-oss-120b", 7.0)

    def test_request_uses_groq_chat_completions_and_required_user_agent(self):
        self.assertEqual(self.provider.generate_steps("Research Paper", "Intro and conclusion", "2026-11-26", 0.5), GOOD)
        request = self.transport.requests[0]
        headers = {k.lower(): v for k, v in request.header_items()}
        body = json.loads(request.data)
        self.assertEqual(request.full_url, ai_provider.GROQ_API_URL)
        self.assertEqual(headers["authorization"], f"Bearer {FAKE_KEY}")
        self.assertEqual(headers["user-agent"], "TAIM/1.0")
        self.assertEqual(body["model"], "openai/gpt-oss-120b")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertIs(body["include_reasoning"], False)
        self.assertNotIn(FAKE_KEY, request.full_url + request.data.decode())

    def test_only_the_disclosed_task_fields_are_sent(self):
        self.provider.generate_steps("Research Paper", "Intro and conclusion", "2026-11-26", 0.5)
        body = json.loads(self.transport.requests[0].data)
        task = json.loads(body["messages"][1]["content"])
        self.assertEqual(task, {"task_title": "Research Paper", "requirements": "Intro and conclusion",
                                "deadline": "2026-11-26", "daily_time_hours": 0.5})

    def test_reasoning_field_is_not_used_or_exposed(self):
        self.transport.respond = lambda: FakeResponse(groq_payload(GOOD, "PRIVATE-REASONING"))
        self.assertEqual(self.provider.generate_steps("T", "", "2026-11-26", 1), GOOD)
        self.assertNotIn("PRIVATE-REASONING", repr(self.provider))

    def test_http_and_malformed_responses_are_classified_without_secret_leaks(self):
        for outcome, reason in ((http_error(429), "quota"), (http_error(403), "http_error"),
                                (FakeResponse(raw=b"not json"), "malformed"),
                                (FakeResponse({"choices": []}), "malformed")):
            self.transport.respond = lambda outcome=outcome: outcome
            with self.assertRaises(ProviderError) as ctx:
                self.provider.generate_steps("T", "", "2026-11-26", 1)
            self.assertEqual(ctx.exception.reason, reason)
            self.assertNotIn(FAKE_KEY, str(ctx.exception) + repr(ctx.exception))

    def test_redirects_are_refused_for_groq_too(self):
        self.transport.respond = lambda: status_response(302, EVIL_URL, ai_provider.GROQ_API_URL)
        with self.assertRaises(ProviderError):
            self.provider.generate_steps("T", "", "2026-11-26", 1)
        self.assertEqual(len(self.transport.requests), 1)

    def test_timeout_override_is_used(self):
        self.provider.generate_steps("T", "", "2026-11-26", 1, timeout=2.75)
        self.assertEqual(self.transport.requests[0].timeout, 2.75)


class ProviderChainTests(unittest.TestCase):
    class Stub:
        def __init__(self, source, result=None, error=None):
            self.source, self.result, self.error, self.timeouts = source, result, error, []

        def generate_steps(self, *args, timeout=None):
            self.timeouts.append(timeout)
            if self.error:
                raise self.error
            return self.result

    def test_groq_is_primary_and_gemini_is_used_only_after_groq_failure(self):
        groq = self.Stub("groq", error=ProviderError("http_error"))
        gemini = self.Stub("gemini", result=GOOD)
        chain = ProviderChain([groq, gemini], 12.0)
        result = chain.generate_steps("T", "", "2026-11-26", 1)
        self.assertEqual(result.source, "gemini")
        self.assertEqual(result.steps, GOOD)
        self.assertEqual(len(groq.timeouts), 1)
        self.assertEqual(len(gemini.timeouts), 1)
        self.assertLessEqual(gemini.timeouts[0], 12.0)

    def test_response_body_reads_receive_a_decreasing_socket_timeout_budget(self):
        import time as real_time

        class FakeSocket:
            def __init__(self):
                self.timeouts = []

            def settimeout(self, value):
                self.timeouts.append(value)

        class FakeHTTPResponse:
            def __init__(self):
                self.fp = SimpleNamespace(raw=SimpleNamespace(_sock=FakeSocket()))
                self.calls = 0

            def read1(self, size):
                self.calls += 1
                if self.calls == 1:
                    real_time.sleep(0.02)
                    return b"partial"
                raise socket.timeout()

        http_response = FakeHTTPResponse()
        response = SimpleNamespace(fp=http_response)
        with self.assertRaises(socket.timeout):
            ai_provider._read_response_with_deadline(response, 0.5)
        self.assertEqual(http_response.calls, 2)
        self.assertEqual(len(http_response.fp.raw._sock.timeouts), 2)
        self.assertLess(http_response.fp.raw._sock.timeouts[1], http_response.fp.raw._sock.timeouts[0])

    def test_successful_groq_prevents_a_gemini_request(self):
        groq = self.Stub("groq", result=GOOD)
        gemini = self.Stub("gemini", result=GOOD)
        result = ProviderChain([groq, gemini], 12.0).generate_steps("T", "", "2026-11-26", 1)
        self.assertEqual(result.source, "groq")
        self.assertEqual(len(gemini.timeouts), 0)

    def test_invalid_groq_output_fails_over_to_gemini(self):
        groq = self.Stub("groq", result=[{"title": "only one", "minutes": 20}])
        gemini = self.Stub("gemini", result=GOOD)
        result = ProviderChain([groq, gemini], 12.0).generate_steps("T", "", "2026-11-26", 1)
        self.assertEqual(result.source, "gemini")
        self.assertEqual(result.steps, GOOD)

    def test_remaining_shared_timeout_is_passed_to_the_secondary_provider(self):
        now = [100.0]
        original = ai_provider.time.monotonic
        ai_provider.time.monotonic = lambda: now[0]

        class SlowGroq(self.Stub):
            def generate_steps(inner, *args, timeout=None):
                inner.timeouts.append(timeout)
                now[0] += 8.0
                raise ProviderError("timeout")

        try:
            groq = SlowGroq("groq")
            gemini = self.Stub("gemini", result=GOOD)
            result = ProviderChain([groq, gemini], 12.0).generate_steps("T", "", "2026-11-26", 1)
            self.assertEqual(result.source, "gemini")
            self.assertAlmostEqual(groq.timeouts[0], 12.0)
            self.assertAlmostEqual(gemini.timeouts[0], 4.0)
        finally:
            ai_provider.time.monotonic = original

    def test_configuration_orders_groq_before_gemini(self):
        cfg = SimpleNamespace(GROQ_API_KEY="g", GROQ_MODEL="openai/gpt-oss-120b",
                              GEMINI_API_KEY="k", GEMINI_MODEL="gemini-x",
                              AI_TOTAL_TIMEOUT_SECONDS=12.0)
        chain = ai_provider.provider_from_config(cfg)
        self.assertIsInstance(chain, ProviderChain)
        self.assertIsInstance(chain.providers[0], GroqProvider)
        self.assertIsInstance(chain.providers[1], GeminiProvider)
        self.assertEqual(chain.timeout, 12.0)



class RedirectTests(unittest.TestCase):
    """Gemini requests must never follow a redirect: the API key header would be re-sent to the new address.
    Redirect responses come from a fake transport; the real opener and redirect handling decide what happens."""

    def setUp(self):
        block_real_network(self)
        self.next_response = None
        self.transport = FakeTransport(lambda: self.next_response(len(self.transport.requests)))
        self.transport.install()
        self.addCleanup(self.transport.uninstall)
        self.provider = GeminiProvider(FAKE_KEY, "gemini-test-model", 7.0)

    def redirect_to(self, code, location):
        """First request gets the redirect. If anything asks again, the 'other host' would answer with a valid
        plan, so a followed redirect cannot go unnoticed."""
        self.next_response = lambda n: (status_response(code, location) if n == 1
                                        else FakeResponse(gemini_payload(GOOD)))

    def attempt(self):
        with self.assertRaises(ProviderError) as ctx:
            self.provider.generate_steps("Research Paper", "Intro and conclusion", "2026-11-26", 0.5)
        return ctx.exception

    def test_302_redirect_is_refused(self):
        self.redirect_to(302, EVIL_URL)
        error = self.attempt()
        self.assertEqual(error.reason, "http_error")
        self.assertEqual(len(self.transport.requests), 1)

    def test_307_redirect_is_refused(self):
        self.redirect_to(307, EVIL_URL)
        error = self.attempt()
        self.assertEqual(error.reason, "http_error")
        self.assertEqual(len(self.transport.requests), 1)

    def test_every_redirect_status_is_refused(self):
        for code in (301, 302, 303, 307, 308):
            self.transport.requests.clear()
            self.redirect_to(code, EVIL_URL)
            self.assertEqual(self.attempt().reason, "http_error", code)
            self.assertEqual(len(self.transport.requests), 1, code)

    def test_redirect_to_an_unrelated_host_is_refused(self):
        for target in (EVIL_URL, "http://evil.example/plain", "https://generativelanguage.googleapis.com.evil.example/x",
                       "//evil.example/protocol-relative", "/v1beta/other-path-same-host"):
            self.transport.requests.clear()
            self.redirect_to(302, target)
            self.assertEqual(self.attempt().reason, "http_error", target)
            self.assertEqual(len(self.transport.requests), 1, target)

    def test_no_redirected_request_is_issued(self):
        for code in (302, 307):
            self.transport.requests.clear()
            self.redirect_to(code, EVIL_URL)
            self.attempt()
            self.assertEqual([r.full_url for r in self.transport.requests], [GEMINI_URL])
            self.assertEqual(self.transport.hosts(), ["generativelanguage.googleapis.com"])

    def test_the_api_key_is_not_forwarded_to_another_host(self):
        for code in (302, 307):
            self.transport.requests.clear()
            self.redirect_to(code, EVIL_URL)
            self.attempt()
            for request in self.transport.requests:
                self.assertEqual(urllib.parse.urlsplit(request.full_url).hostname, "generativelanguage.googleapis.com")
            sent_elsewhere = [r for r in self.transport.requests
                              if urllib.parse.urlsplit(r.full_url).hostname != "generativelanguage.googleapis.com"]
            self.assertEqual(sent_elsewhere, [])
            self.assertEqual(len(self.transport.requests), 1)

    def test_the_key_and_the_target_never_appear_in_the_error(self):
        self.redirect_to(307, EVIL_URL + "?k=" + FAKE_KEY)
        error = self.attempt()
        text = str(error) + repr(error) + repr(self.provider)
        self.assertNotIn(FAKE_KEY, text)
        self.assertNotIn("evil.example", text)
        self.assertIsNone(error.__cause__)
        self.assertTrue(error.__suppress_context__)

    def test_a_redirect_without_a_location_header_is_also_refused(self):
        self.redirect_to(302, None)
        self.assertEqual(self.attempt().reason, "http_error")
        self.assertEqual(len(self.transport.requests), 1)

    def test_the_gemini_opener_has_no_redirect_following_handler(self):
        opener = ai_provider._build_opener()
        redirect_handlers = [h for h in opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
        self.assertEqual(len(redirect_handlers), 1)
        self.assertIsInstance(redirect_handlers[0], ai_provider._NoRedirectHandler)

    def test_a_normal_success_still_works_through_the_dedicated_opener(self):
        self.next_response = lambda n: FakeResponse(gemini_payload(GOOD))
        self.assertEqual(self.provider.generate_steps("t", "r", "2026-11-26", 0.5), GOOD)
        self.assertEqual(len(self.transport.requests), 1)
        headers = {k.lower(): v for k, v in self.transport.requests[0].header_items()}
        self.assertEqual(headers["x-goog-api-key"], FAKE_KEY)


class RateLimiterTests(unittest.TestCase):
    def test_three_per_minute_then_wait(self):
        clock = Clock()
        limiter = RateLimiter(3, 20, clock)
        for _ in range(3):
            self.assertEqual(limiter.allow("a"), (True, 0))
            clock.now += 5
        allowed, wait = limiter.allow("a")
        self.assertFalse(allowed)
        self.assertTrue(1 <= wait <= 60, wait)
        clock.now += 50  # 65 s after the first request
        self.assertEqual(limiter.allow("a"), (True, 0))

    def test_refused_calls_do_not_use_up_the_allowance(self):
        clock = Clock()
        limiter = RateLimiter(3, 20, clock)
        for _ in range(3):
            limiter.allow("a")
        for _ in range(50):
            self.assertFalse(limiter.allow("a")[0])
        clock.now += 61
        self.assertEqual(limiter.allow("a"), (True, 0))

    def test_students_are_limited_separately(self):
        limiter = RateLimiter(3, 20, Clock())
        for _ in range(3):
            limiter.allow("alice")
        self.assertFalse(limiter.allow("alice")[0])
        self.assertTrue(limiter.allow("bob")[0])

    def test_twenty_per_day(self):
        clock = Clock()
        limiter = RateLimiter(3, 20, clock)
        for _ in range(20):
            self.assertTrue(limiter.allow("a")[0])
            clock.now += 61
        allowed, wait = limiter.allow("a")
        self.assertFalse(allowed)
        self.assertGreater(wait, 60)
        clock.now += 86400
        self.assertTrue(limiter.allow("a")[0])

    def test_memory_stays_bounded(self):
        limiter = RateLimiter(3, 20, Clock())
        limiter.MAX_TRACKED = 5
        for i in range(30):
            limiter.allow(f"user{i}")
        self.assertLessEqual(len(limiter._hits), 5)


class RouteRateLimitTests(AiPlanCase):
    def test_fourth_real_request_in_a_minute_gets_the_template_and_never_reaches_the_provider(self):
        provider = self.use(FakeProvider(GOOD), RateLimiter(3, 20, Clock()))
        for _ in range(3):
            self.assertIs(self.plan().get_json()["aiGenerated"], True)
        r = self.plan()
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIs(body["aiGenerated"], False)
        self.assertEqual(body["source"], "deterministic-fallback")
        self.assertIn("request limit reached", body["notice"])
        self.assertEqual(len(provider.calls), 3)

    def test_template_requests_do_not_count(self):
        provider = self.use(FakeProvider(GOOD), RateLimiter(3, 20, Clock()))
        for _ in range(10):
            self.plan(aiConsent=False)
            self.plan(aiConsent=...)
        for _ in range(3):
            self.assertIs(self.plan().get_json()["aiGenerated"], True)
        self.assertEqual(len(provider.calls), 3)

    def test_failed_requests_count_because_they_reached_for_gemini(self):
        provider = self.use(FakeProvider(error=ProviderError("timeout")), RateLimiter(3, 20, Clock()))
        for _ in range(3):
            self.plan()
        self.assertIn("request limit reached", self.plan().get_json()["notice"])
        self.assertEqual(len(provider.calls), 3)

    def test_each_signed_in_student_has_their_own_limit(self):
        provider = self.use(FakeProvider(GOOD), RateLimiter(3, 20, Clock()))
        for _ in range(4):
            self.plan("alice")
        self.assertIs(self.plan("bob").get_json()["aiGenerated"], True)
        self.assertEqual(len(provider.calls), 4)  # alice 3 + bob 1

    def test_daily_limit_applies_through_the_route(self):
        clock = Clock()
        provider = self.use(FakeProvider(GOOD), RateLimiter(3, 20, clock))
        for _ in range(20):
            self.assertIs(self.plan().get_json()["aiGenerated"], True)
            clock.now += 61
        body = self.plan().get_json()
        self.assertIs(body["aiGenerated"], False)
        self.assertIn("request limit reached", body["notice"])
        self.assertEqual(len(provider.calls), 20)

    def test_the_limit_expires(self):
        clock = Clock()
        self.use(FakeProvider(GOOD), RateLimiter(3, 20, clock))
        for _ in range(4):
            self.plan()
        clock.now += 61
        self.assertIs(self.plan().get_json()["aiGenerated"], True)


class SecurityAndSideEffectTests(AiPlanCase):
    def test_login_is_still_required_and_the_provider_is_not_touched(self):
        provider = self.use(FakeProvider(GOOD))
        self.assertEqual(self.call("POST", "/api/ai/plan", user=None, json=PLAN).status_code, 401)
        self.assertEqual(provider.calls, [])

    def test_plan_still_validates_everything_else(self):
        self.use(FakeProvider(GOOD))
        for field, value in (("title", ""), ("deadline", "tomorrow"), ("hoursPerDay", 99), ("requirements", 5)):
            r = self.plan(**{field: value})
            self.assertEqual(r.status_code, 422, field)
            self.assertIn(field, r.get_json()["errors"])

    def test_nothing_is_written_to_the_database(self):
        self.use(FakeProvider(GOOD))
        for payload in ({}, {"aiConsent": False}, {"deadline": "2026-11-01"}):
            self.assertEqual(self.plan(**payload).status_code, 200)
        self.use(FakeProvider(error=ProviderError("quota")))
        self.assertEqual(self.plan().status_code, 200)
        self.assertEqual(self.db.writes, [])
        self.assertEqual(self.db.store, {})

    def test_request_body_cannot_choose_the_student_or_inject_data(self):
        provider = self.use(FakeProvider(GOOD))
        r = self.plan(student_id="bob", subtasks=[{"title": "x"}], task_id="t1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(provider.calls[0]), {"title", "requirements", "deadline", "hours"})

    def test_real_provider_end_to_end_with_a_fake_network(self):
        self.use(GeminiProvider(FAKE_KEY, "gemini-test-model", 5.0))
        self.fake_network()
        body = self.plan().get_json()
        self.assertEqual((body["aiGenerated"], body["source"]), (True, "gemini"))
        self.assertEqual(len(body["subtasks"]), 5)
        self.assertNotIn(FAKE_KEY, json.dumps(body))

    def test_a_provider_failure_never_leaks_the_key_in_the_response_or_logs(self):
        self.use(GeminiProvider(FAKE_KEY, "gemini-test-model", 5.0))

        self.fake_network(lambda: status_response(429))
        with self.assertLogs(self.app.logger, "WARNING") as logs:
            r = self.plan()
        self.assertEqual(r.status_code, 200)
        self.assertIs(r.get_json()["aiGenerated"], False)
        self.assertNotIn(FAKE_KEY, r.get_data(as_text=True))
        self.assertNotIn(FAKE_KEY, "\n".join(logs.output))
        self.assertNotIn("Research Paper", "\n".join(logs.output))  # task text is never logged


class RouteHttpFailureTests(AiPlanCase):
    """Through the route: the student always gets the template (HTTP 200), with the right plain-language notice."""

    def test_a_redirect_gives_the_generic_notice_and_sends_nothing_elsewhere(self):
        self.use(GeminiProvider(FAKE_KEY, "gemini-test-model", 5.0))
        transport = self.fake_network(lambda: status_response(307, EVIL_URL) if len(transport.requests) == 1
                                      else FakeResponse(gemini_payload(GOOD)))
        with self.assertLogs(self.app.logger, "WARNING") as logs:
            r = self.plan()
        body = r.get_json()
        self.assertEqual(r.status_code, 200)
        self.assertIs(body["aiGenerated"], False)
        self.assertIn(ai_provider.fallback_notice("http_error"), body["notice"])
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(transport.hosts(), ["generativelanguage.googleapis.com"])
        visible = r.get_data(as_text=True) + "\n".join(logs.output)
        self.assertNotIn(FAKE_KEY, visible)
        self.assertNotIn("evil.example", visible)

    def test_429_shows_the_quota_notice_and_403_does_not(self):
        self.use(GeminiProvider(FAKE_KEY, "gemini-test-model", 5.0))
        for code, quota in ((429, True), (403, False)):
            self.fake_network(lambda code=code: status_response(code))
            body = self.plan(user=f"user{code}").get_json()
            self.assertIs(body["aiGenerated"], False)
            self.assertEqual(ai_provider.fallback_notice("quota") in body["notice"], quota, code)
            self.assertEqual(ai_provider.fallback_notice("http_error") in body["notice"], not quota, code)


class GateOffTests(AiPlanCase):
    enable_v2 = False

    def test_ai_plan_works_with_the_v2_gate_off_and_other_routes_stay_503(self):
        self.use(FakeProvider(GOOD))
        self.assertIs(self.plan().get_json()["aiGenerated"], True)
        self.assertEqual(self.call("GET", "/api/tasks").status_code, 503)
        self.assertFalse(self.app.config["ENABLE_V2"])
        self.assertEqual(self.db.writes, [])


if __name__ == "__main__":
    unittest.main()
