"""General API tests: health, error format, CORS, authentication, and the deterministic AI fallback endpoints.

Run from the backend folder:
    python -m unittest discover -s tests -v     (no extra packages)
    python -m pytest tests -v                   (if pytest is installed)
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from base import TASK, ApiTestCase, create_app, fake_verifier  # noqa: E402

PROTECTED = [
    ("GET", "/api/subjects"), ("POST", "/api/subjects"), ("PATCH", "/api/subjects/abc"), ("DELETE", "/api/subjects/abc"),
    ("GET", "/api/tasks"), ("POST", "/api/tasks"), ("PATCH", "/api/tasks/abc"), ("DELETE", "/api/tasks/abc"),
    ("POST", "/api/tasks/abc/start"), ("POST", "/api/tasks/abc/complete"), ("POST", "/api/tasks/abc/reopen"),
    ("GET", "/api/settings"), ("PUT", "/api/settings"),
    ("GET", "/api/reminders/preferences"), ("PUT", "/api/reminders/preferences"),
    ("GET", "/api/progress"), ("POST", "/api/ai/plan"), ("POST", "/api/ai/chat"),
]


class HealthAndErrorFormatTests(ApiTestCase):
    def test_health_needs_no_token(self):
        response = self.call("GET", "/api/health", user=None)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "success", "message": "TAiM backend is running."})

    def test_unknown_route_and_wrong_method_return_json_detail(self):
        r = self.call("GET", "/api/nope")
        self.assertEqual((r.status_code, r.get_json()["detail"]), (404, "Not found."))
        r = self.call("DELETE", "/api/health")
        self.assertEqual(r.status_code, 405)
        self.assertIsInstance(r.get_json()["detail"], str)

    def test_oversized_body_is_rejected(self):
        r = self.call("POST", "/api/tasks", json={**TASK, "title": "x" * 70000})
        self.assertEqual(r.status_code, 413)
        self.assertIn("detail", r.get_json())


class CorsTests(ApiTestCase):
    def test_preflight_for_allowed_origin_needs_no_token(self):
        r = self.client.options("/api/tasks", headers={
            "Origin": "http://localhost:5500", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type"})
        self.assertIn(r.status_code, (200, 204))
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), "http://localhost:5500")
        self.assertIn("authorization", r.headers.get("Access-Control-Allow-Headers", "").lower())

    def test_preflight_allows_patch_put_delete(self):
        for method in ("PATCH", "PUT", "DELETE"):
            r = self.client.options("/api/tasks/abc", headers={
                "Origin": "http://localhost:5500", "Access-Control-Request-Method": method})
            self.assertIn(method, r.headers.get("Access-Control-Allow-Methods", ""), method)

    def test_other_origins_get_no_cors_header(self):
        r = self.client.options("/api/tasks", headers={
            "Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
        self.assertIsNone(r.headers.get("Access-Control-Allow-Origin"))

    def test_error_responses_still_carry_cors_headers(self):
        r = self.client.get("/api/tasks", headers={"Origin": "http://localhost:5500"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), "http://localhost:5500")


class AuthTests(ApiTestCase):
    def test_every_protected_endpoint_rejects_missing_token(self):
        for method, path in PROTECTED:
            r = self.call(method, path, user=None, json={})
            self.assertEqual(r.status_code, 401, (method, path))
            self.assertIsInstance(r.get_json()["detail"], str)

    def test_malformed_or_invalid_tokens_are_401(self):
        for header in ("Token token-alice", "Bearer", "token-alice", "Bearer bad-token", "Bearer  ", ""):
            r = self.client.get("/api/tasks", headers={"Authorization": header})
            self.assertEqual(r.status_code, 401, header)

    def test_valid_token_works_and_scheme_is_case_insensitive(self):
        r = self.client.get("/api/tasks", headers={"Authorization": "bearer token-alice"})
        self.assertEqual(r.status_code, 200)

    def test_token_without_uid_is_rejected(self):
        app = create_app(db=self.db, token_verifier=lambda token: {"email": "x@example.com"}, enable_v2=True)
        r = app.test_client().get("/api/tasks", headers={"Authorization": "Bearer anything"})
        self.assertEqual(r.status_code, 401)

    def test_missing_firebase_config_is_503_but_missing_token_is_still_401(self):
        app = create_app(token_verifier=fake_verifier, enable_v2=True)  # no db -> FIREBASE_PROJECT_ID is empty in tests
        client = app.test_client()
        self.assertEqual(client.get("/api/tasks").status_code, 401)
        r = client.get("/api/tasks", headers={"Authorization": "Bearer token-alice"})
        self.assertEqual(r.status_code, 503)
        self.assertIn("detail", r.get_json())
        self.assertEqual(client.get("/api/health").status_code, 200)


class AiTests(ApiTestCase):
    PLAN = {"title": "Research Paper", "requirements": "Intro and conclusion", "deadline": "2026-11-26",
            "hoursPerDay": "0.5"}

    def test_plan_is_clearly_labelled_as_fallback_and_has_frontend_shape(self): 
        r = self.call("POST", "/api/ai/plan", json=self.PLAN)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIs(body["mock"], True)
        self.assertIs(body["aiGenerated"], False)
        self.assertEqual(body["source"], "deterministic-fallback")
        self.assertIn("No AI model was used", body["notice"])
        self.assertIn("consent box was not ticked", body["notice"])
        self.assertEqual(len(body["subtasks"]), 5)
        for step in body["subtasks"]:
            self.assertEqual(set(step), {"title", "dueDate", "minutes"})
            self.assertIsInstance(step["minutes"], int)
        due = [s["dueDate"] for s in body["subtasks"]]
        self.assertEqual(due, sorted(due))
        self.assertEqual(due[-1], "2026-11-26")
        self.assertGreaterEqual(due[0], "2026-11-16")

    def test_plan_with_deadline_today_or_past_never_goes_beyond_today(self):
        for deadline in ("2026-11-16", "2026-11-01"):
            body = self.call("POST", "/api/ai/plan", json={**self.PLAN, "deadline": deadline}).get_json()
            self.assertEqual({s["dueDate"] for s in body["subtasks"]}, {"2026-11-16"})

    def test_plan_accepts_number_or_text_hours_and_defaults(self):
        for hours in (1, 2.5, "3", None):
            payload = {k: v for k, v in self.PLAN.items() if k != "hoursPerDay"}
            if hours is not None:
                payload["hoursPerDay"] = hours
            self.assertEqual(self.call("POST", "/api/ai/plan", json=payload).status_code, 200, hours)

    def test_plan_validation(self):
        for field, value in (("title", ""), ("title", 5), ("deadline", "tomorrow"), ("deadline", None),
                             ("hoursPerDay", "lots"), ("hoursPerDay", 0), ("hoursPerDay", 99), ("hoursPerDay", True),
                             ("requirements", 5)):
            r = self.call("POST", "/api/ai/plan", json={**self.PLAN, field: value})
            self.assertEqual(r.status_code, 422, (field, value))
            self.assertIn(field, r.get_json()["errors"])

    def test_chat_priority_question_uses_own_tasks_only(self):
        self.add_task(title="Low one", importance="low")
        urgent = self.add_task(title="Urgent paper", importance="high")
        self.call("PATCH", f"/api/tasks/{urgent['task_id']}", json={"progress_pct": 20})
        self.add_task("bob", title="Bob secret", importance="high")
        body = self.call("POST", "/api/ai/chat", json={"message": "What should I work on first?"}).get_json()
        self.assertIn('"Urgent paper"', body["reply"])
        self.assertIn("20% done", body["reply"])
        self.assertNotIn("Bob", body["reply"])
        self.assertEqual((body["mock"], body["aiGenerated"], body["source"]), (False, False, "rule-based"))
        self.assertIn("AI was not used because consent was not given", body["notice"])
        self.assertIn("rule-based assistant", body["notice"])

    def test_chat_ignores_completed_tasks_when_picking(self):
        done = self.add_task(title="Already done", importance="high")
        self.call("POST", f"/api/tasks/{done['task_id']}/complete")
        self.add_task(title="Still open", importance="low")
        reply = self.call("POST", "/api/ai/chat", json={"message": "what first?"}).get_json()["reply"]
        self.assertIn('"Still open"', reply)
        self.assertNotIn("Already done", reply)

    def test_chat_deadlines_and_other_questions(self):
        self.add_task(title="A", deadline="2026-11-18")
        self.add_task(title="B", deadline="2026-11-17")
        finished = self.add_task(title="Finished", deadline="2026-11-16")
        self.call("POST", f"/api/tasks/{finished['task_id']}/complete")
        reply = self.call("POST", "/api/ai/chat", json={"message": "what is due soon"}).get_json()["reply"]
        self.assertEqual(reply, "Upcoming: B (Nov 17); A (Nov 18).")
        other = self.call("POST", "/api/ai/chat", json={"message": "hello"}).get_json()["reply"]
        self.assertIn("prioritizing tasks and deadlines", other)

    def test_chat_with_no_open_tasks(self):
        self.assertEqual(self.call("POST", "/api/ai/chat", json={"message": "what first?"}).get_json()["reply"],
                         "You have no open tasks.")
        self.assertEqual(self.call("POST", "/api/ai/chat", json={"message": "anything due?"}).get_json()["reply"],
                         "Nothing is due.")

    def test_chat_validation(self):
        for body in ({}, {"message": ""}, {"message": "   "}, {"message": 5}, {"message": "x" * 1001}):
            self.assertEqual(self.call("POST", "/api/ai/chat", json=body).status_code, 422, body)


if __name__ == "__main__":
    unittest.main()
