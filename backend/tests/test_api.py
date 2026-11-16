"""API tests. They use a fake Firestore and fake token verification, so no Firebase account or network is needed.

Run from the backend folder:
    python -m unittest tests.test_api -v        (no extra packages)
    python -m pytest tests/test_api.py -v       (if pytest is installed)
"""
import os
import pathlib
import sys
import unittest
from datetime import date

os.environ["FIREBASE_PROJECT_ID"] = ""  # keep the tests away from any real Firebase project (.env is not overridden)
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import dates  # noqa: E402
from app import create_app  # noqa: E402
from fakes import FakeFirestore, fake_verifier  # noqa: E402

TODAY = date(2026, 11, 16)  # a Monday
TASK = {"title": "Programming Activity 05", "course": "Computer Programming", "category": "Assignment",
        "deadline": "2026-11-20", "priority": "High", "progress": 65}
TASK_FIELDS = {"id", "title", "course", "category", "deadline", "priority", "progress"}

PROTECTED = [
    ("GET", "/api/tasks"), ("POST", "/api/tasks"), ("PATCH", "/api/tasks/abc"), ("DELETE", "/api/tasks/abc"),
    ("GET", "/api/settings"), ("PUT", "/api/settings"),
    ("GET", "/api/reminders/preferences"), ("PUT", "/api/reminders/preferences"),
    ("GET", "/api/progress"), ("POST", "/api/ai/plan"), ("POST", "/api/ai/chat"),
]


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.db = FakeFirestore()
        self.app = create_app(db=self.db, token_verifier=fake_verifier)
        self.client = self.app.test_client()
        self._real_today = dates.today
        dates.today = lambda: TODAY

    def tearDown(self):
        dates.today = self._real_today

    def call(self, method, path, user="alice", json=None, headers=None, **kwargs):
        sent = dict(headers or {})
        if user:
            sent["Authorization"] = f"Bearer token-{user}"
        return self.client.open(path, method=method, json=json, headers=sent, **kwargs)

    def add_task(self, user="alice", **over):
        response = self.call("POST", "/api/tasks", user, json={**TASK, **over})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()


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
        app = create_app(db=self.db, token_verifier=lambda token: {"email": "x@example.com"})
        r = app.test_client().get("/api/tasks", headers={"Authorization": "Bearer anything"})
        self.assertEqual(r.status_code, 401)

    def test_client_supplied_user_ids_are_ignored(self):
        self.add_task("bob", title="Bob private task")
        r = self.call("GET", "/api/tasks?uid=bob&userId=bob", user="alice",
                      headers={"X-User-Id": "bob", "X-Uid": "bob"})
        self.assertEqual(r.get_json(), [])
        r = self.call("POST", "/api/tasks", user="alice", json={**TASK, "uid": "bob", "userId": "bob"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(self.call("GET", "/api/tasks", user="bob").get_json()), 1)

    def test_missing_firebase_config_is_503_but_missing_token_is_still_401(self):
        app = create_app(token_verifier=fake_verifier)  # no db -> FIREBASE_PROJECT_ID is empty in tests
        client = app.test_client()
        self.assertEqual(client.get("/api/tasks").status_code, 401)
        r = client.get("/api/tasks", headers={"Authorization": "Bearer token-alice"})
        self.assertEqual(r.status_code, 503)
        self.assertIn("detail", r.get_json())
        self.assertEqual(client.get("/api/health").status_code, 200)


class TaskTests(ApiTestCase):
    def test_create_returns_exact_frontend_shape(self):
        task = self.add_task()
        self.assertEqual(set(task), TASK_FIELDS)
        self.assertTrue(task["id"])
        self.assertEqual({k: v for k, v in task.items() if k != "id"}, TASK)

    def test_create_defaults_for_optional_fields(self):
        r = self.call("POST", "/api/tasks", json={"title": "  Read ch. 3  ", "category": "Project",
                                                   "priority": "Low", "deadline": "2026-12-01"})
        task = r.get_json()
        self.assertEqual((task["title"], task["course"], task["progress"]), ("Read ch. 3", "", 0))

    def test_client_supplied_id_and_internal_fields_are_ignored(self):
        task = self.add_task(id="hacked", completedOn="2020-01-01", createdAt="x", foo="bar")
        self.assertNotEqual(task["id"], "hacked")
        self.assertEqual(set(task), TASK_FIELDS)
        self.assertEqual(self.call("GET", "/api/tasks/hacked", json=None).status_code, 405)

    def test_validation_errors(self):
        bad = {
            "title": ["", "   ", None, 5, "x" * 121],
            "category": ["Homework", "", None, ["Assignment"]],
            "priority": ["Urgent", "high", None],
            "deadline": ["2026-02-30", "11/01/2026", "2026-1-5", "20261101", "", None, 5],
            "progress": [101, -1, "50", True, 50.5, None],
            "course": [5, "x" * 101],
        }
        for field, values in bad.items():
            for value in values:
                r = self.call("POST", "/api/tasks", json={**TASK, field: value})
                self.assertEqual(r.status_code, 422, (field, value))
                body = r.get_json()
                self.assertIsInstance(body["detail"], str)
                self.assertIn(field, body["errors"])

    def test_missing_required_fields(self):
        r = self.call("POST", "/api/tasks", json={})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(set(r.get_json()["errors"]), {"title", "category", "deadline", "priority"})

    def test_body_must_be_a_json_object(self):
        for payload in ("not json", "[1,2]", '"text"', ""):
            r = self.call("POST", "/api/tasks", data=payload, content_type="application/json")
            self.assertEqual(r.status_code, 400, payload)
            self.assertIn("detail", r.get_json())

    def test_list_returns_only_own_tasks_in_creation_order(self):
        first = self.add_task(title="First")
        second = self.add_task(title="Second")
        self.add_task("bob", title="Bob's")
        titles = [t["title"] for t in self.call("GET", "/api/tasks").get_json()]
        self.assertEqual(titles, ["First", "Second"])
        self.assertEqual([t["id"] for t in self.call("GET", "/api/tasks").get_json()], [first["id"], second["id"]])

    def test_patch_updates_only_sent_fields(self):
        task = self.add_task()
        r = self.call("PATCH", f"/api/tasks/{task['id']}", json={"progress": 100, "ignored": 1})
        self.assertEqual(r.status_code, 200)
        updated = r.get_json()
        self.assertEqual(set(updated), TASK_FIELDS)
        self.assertEqual((updated["progress"], updated["title"], updated["priority"]), (100, TASK["title"], "High"))
        self.assertEqual(self.call("GET", "/api/tasks").get_json()[0]["progress"], 100)

    def test_patch_validation_and_empty_body(self):
        task_id = self.add_task()["id"]
        for body in ({}, {"unknown": 1}, {"progress": 150}, {"deadline": "soon"}, {"priority": "x"}):
            r = self.call("PATCH", f"/api/tasks/{task_id}", json=body)
            self.assertEqual(r.status_code, 422, body)
        self.assertEqual(self.call("GET", "/api/tasks").get_json()[0]["progress"], 65)

    def test_patch_and_delete_unknown_id_are_404(self):
        self.assertEqual(self.call("PATCH", "/api/tasks/nope", json={"progress": 5}).status_code, 404)
        self.assertEqual(self.call("DELETE", "/api/tasks/nope").status_code, 404)
        for weird in ("..", ".", "a.b", "a%20b"):
            self.assertEqual(self.call("DELETE", f"/api/tasks/{weird}").status_code, 404, weird)

    def test_students_cannot_change_or_delete_each_others_tasks(self):
        task_id = self.add_task("alice")["id"]
        self.assertEqual(self.call("PATCH", f"/api/tasks/{task_id}", "bob", json={"title": "Pwned"}).status_code, 404)
        self.assertEqual(self.call("DELETE", f"/api/tasks/{task_id}", "bob").status_code, 404)
        task = self.call("GET", "/api/tasks", "alice").get_json()[0]
        self.assertEqual(task["title"], TASK["title"])
        self.assertEqual(self.call("GET", "/api/tasks", "bob").get_json(), [])

    def test_delete_returns_204_and_removes_task(self):
        task_id = self.add_task()["id"]
        r = self.call("DELETE", f"/api/tasks/{task_id}")
        self.assertEqual((r.status_code, r.data), (204, b""))
        self.assertEqual(self.call("GET", "/api/tasks").get_json(), [])
        self.assertEqual(self.call("DELETE", f"/api/tasks/{task_id}").status_code, 404)


class SettingsAndRemindersTests(ApiTestCase):
    def test_settings_defaults_come_from_token_not_request(self):
        r = self.call("GET", "/api/settings", "alice")
        self.assertEqual(r.get_json(), {"name": "Alice", "program": "", "leadDays": 2, "sessionMinutes": 45,
                                        "weeklySummary": True})
        self.assertEqual(self.call("GET", "/api/settings", "bob").get_json()["name"], "Bob")

    def test_settings_put_then_get_and_isolation(self):
        body = {"name": " Ana Reyes ", "program": "BS CS", "leadDays": 5, "sessionMinutes": 60, "weeklySummary": False}
        r = self.call("PUT", "/api/settings", json=body)
        self.assertEqual(r.status_code, 200)
        expected = {**body, "name": "Ana Reyes"}
        self.assertEqual(r.get_json(), expected)
        self.assertEqual(self.call("GET", "/api/settings").get_json(), expected)
        self.assertEqual(self.call("GET", "/api/settings", "bob").get_json()["name"], "Bob")

    def test_settings_partial_update_keeps_other_values(self):
        self.call("PUT", "/api/settings", json={"program": "BS IT", "leadDays": 3})
        r = self.call("PUT", "/api/settings", json={"sessionMinutes": 25}).get_json()
        self.assertEqual((r["program"], r["leadDays"], r["sessionMinutes"]), ("BS IT", 3, 25))

    def test_settings_validation(self):
        bad = [{}, {"name": ""}, {"name": 5}, {"name": "x" * 81}, {"program": 7}, {"leadDays": 4}, {"leadDays": True},
               {"leadDays": "2"}, {"leadDays": 2.0}, {"sessionMinutes": 30}, {"weeklySummary": "yes"},
               {"weeklySummary": 1}]
        for body in bad:
            r = self.call("PUT", "/api/settings", json=body)
            self.assertEqual(r.status_code, 422, body)
            self.assertIsInstance(r.get_json()["detail"], str)

    def test_reminder_defaults_put_get_and_isolation(self):
        self.assertEqual(self.call("GET", "/api/reminders/preferences").get_json(),
                         {"deadline": True, "dailySummary": True, "progressCheckin": False, "quietHours": True})
        full = {"deadline": False, "dailySummary": False, "progressCheckin": True, "quietHours": False}
        self.assertEqual(self.call("PUT", "/api/reminders/preferences", json=full).get_json(), full)
        self.assertEqual(self.call("GET", "/api/reminders/preferences").get_json(), full)
        self.assertTrue(self.call("GET", "/api/reminders/preferences", "bob").get_json()["deadline"])

    def test_reminder_partial_update_and_validation(self):
        r = self.call("PUT", "/api/reminders/preferences", json={"progressCheckin": True}).get_json()
        self.assertEqual((r["progressCheckin"], r["deadline"]), (True, True))
        for body in ({}, {"deadline": "yes"}, {"quietHours": 0}, {"deadline": None}):
            self.assertEqual(self.call("PUT", "/api/reminders/preferences", json=body).status_code, 422, body)


class ProgressTests(ApiTestCase):
    KEYS = {"completionRate", "onTimeRate", "completed", "overdue", "weeklyChange", "weeklyProductivity",
            "weeklyCompletion", "insight", "insightSource"}

    def test_no_tasks_gives_zero_defaults_in_the_expected_shape(self):
        p = self.call("GET", "/api/progress").get_json()
        self.assertEqual(set(p), self.KEYS)
        self.assertEqual((p["completionRate"], p["onTimeRate"], p["completed"], p["overdue"], p["weeklyChange"]),
                         (0, 0, 0, 0, 0))
        self.assertEqual(p["weeklyProductivity"], [0] * 7)
        self.assertEqual(p["weeklyCompletion"], [0] * 4)
        self.assertIsInstance(p["insight"], str)

    def test_statistics_come_from_stored_tasks(self):
        self.add_task(title="Done on time", progress=100, deadline="2026-11-20")   # completed today (Mon)
        self.add_task(title="Overdue", progress=40, deadline="2026-11-10")
        self.add_task(title="Future", progress=0, deadline="2026-11-30")
        self.add_task("bob", title="Not mine", progress=100)
        p = self.call("GET", "/api/progress").get_json()
        self.assertEqual((p["completed"], p["overdue"], p["completionRate"], p["onTimeRate"]), (1, 1, 33, 100))
        self.assertEqual(p["weeklyProductivity"], [1, 0, 0, 0, 0, 0, 0])
        self.assertEqual(p["weeklyCompletion"], [0, 0, 0, 1])
        self.assertEqual(p["weeklyChange"], 0)  # no tasks were completed last week
        self.assertIn("1 overdue", p["insight"])
        self.assertIn("Assignment", p["insight"])

    def test_late_completion_lowers_on_time_rate(self):
        task = self.add_task(progress=0, deadline="2026-11-10")
        self.call("PATCH", f"/api/tasks/{task['id']}", json={"progress": 100})
        p = self.call("GET", "/api/progress").get_json()
        self.assertEqual((p["completed"], p["onTimeRate"], p["overdue"]), (1, 0, 0))

    def test_reopening_a_task_removes_it_from_completed_statistics(self):
        task = self.add_task(progress=100)
        self.call("PATCH", f"/api/tasks/{task['id']}", json={"progress": 80})
        p = self.call("GET", "/api/progress").get_json()
        self.assertEqual((p["completed"], p["weeklyCompletion"]), (0, [0, 0, 0, 0]))

    def test_internal_completion_date_is_not_exposed_on_tasks(self):
        self.add_task(progress=100)
        self.assertEqual(set(self.call("GET", "/api/tasks").get_json()[0]), TASK_FIELDS)


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
        self.add_task(title="Low one", priority="Low", progress=0)
        self.add_task(title="Urgent paper", priority="High", progress=20)
        self.add_task("bob", title="Bob secret", priority="High", progress=0)
        body = self.call("POST", "/api/ai/chat", json={"message": "What should I work on first?"}).get_json()
        self.assertIn('"Urgent paper"', body["reply"])
        self.assertIn("20% done", body["reply"])
        self.assertNotIn("Bob", body["reply"])
        self.assertEqual((body["mock"], body["aiGenerated"], body["source"]),
                         (True, False, "deterministic-fallback"))
        self.assertIn("No AI model was used", body["notice"])

    def test_chat_deadlines_and_other_questions(self):
        self.add_task(title="A", deadline="2026-11-18", progress=0)
        self.add_task(title="B", deadline="2026-11-17", progress=0)
        self.add_task(title="Finished", deadline="2026-11-16", progress=100)
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
