"""Settings and reminder preferences live in the student document (students/{uid})."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from base import ApiTestCase  # noqa: E402

REMINDER_DEFAULTS = {"deadline": True, "dailySummary": True, "progressCheckin": False, "quietHours": True}


class SettingsTests(ApiTestCase):
    def test_defaults_come_from_the_token_and_reading_writes_nothing(self):
        r = self.call("GET", "/api/settings", "alice")
        self.assertEqual(r.get_json(), {"full_name": "Alice", "leadDays": 2, "sessionMinutes": 45})
        self.assertEqual(self.call("GET", "/api/settings", "bob").get_json()["full_name"], "Bob")
        self.call("GET", "/api/reminders/preferences")
        self.assertEqual(self.db.writes, [])

    def test_removed_fields_are_gone_from_the_response(self):
        body = self.call("GET", "/api/settings").get_json()
        self.assertEqual(set(body), {"full_name", "leadDays", "sessionMinutes"})
        self.assertNotIn("program", body)
        self.assertNotIn("weeklySummary", body)

    def test_put_then_get_is_stored_on_the_student_document(self):
        r = self.call("PUT", "/api/settings", json={"full_name": " Ana Reyes ", "leadDays": 5, "sessionMinutes": 60})
        self.assertEqual(r.status_code, 200)
        expected = {"full_name": "Ana Reyes", "leadDays": 5, "sessionMinutes": 60}
        self.assertEqual(r.get_json(), expected)
        self.assertEqual(self.call("GET", "/api/settings").get_json(), expected)
        doc = self.db.store[("students", "alice")]
        self.assertEqual((doc["student_id"], doc["full_name"], doc["lead_days"], doc["session_minutes"]),
                         ("alice", "Ana Reyes", 5, 60))
        self.assertEqual(doc["email"], "alice@example.com")
        self.assertNotIn("program", doc)
        self.assertNotIn("weeklySummary", doc)
        self.assertNotIn(("users", "alice", "preferences", "settings"), self.db.store)
        self.assertEqual(self.call("GET", "/api/settings", "bob").get_json()["full_name"], "Bob")

    def test_partial_update_keeps_other_values(self):
        self.call("PUT", "/api/settings", json={"full_name": "Ana", "leadDays": 3})
        r = self.call("PUT", "/api/settings", json={"sessionMinutes": 25}).get_json()
        self.assertEqual((r["full_name"], r["leadDays"], r["sessionMinutes"]), ("Ana", 3, 25))

    def test_removed_and_identity_fields_are_ignored(self):
        r = self.call("PUT", "/api/settings", json={"full_name": "Ana", "program": "BS CS", "weeklySummary": False,
                                                    "name": "Old", "student_id": "bob", "email": "evil@example.com"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.get_json()), {"full_name", "leadDays", "sessionMinutes"})
        doc = self.db.store[("students", "alice")]
        self.assertEqual((doc["student_id"], doc["email"], doc["full_name"]), ("alice", "alice@example.com", "Ana"))
        self.assertNotIn("program", doc)
        self.assertNotIn("weeklySummary", doc)
        self.assertNotIn("name", doc)
        # a body with ONLY removed fields changes nothing and is a validation error
        self.assertEqual(self.call("PUT", "/api/settings", json={"program": "x"}).status_code, 422)
        self.assertEqual(self.call("PUT", "/api/settings", json={"weeklySummary": True}).status_code, 422)

    def test_validation(self):
        bad = [{}, {"full_name": ""}, {"full_name": 5}, {"full_name": "x" * 81}, {"leadDays": 4}, {"leadDays": True},
               {"leadDays": "2"}, {"leadDays": 2.0}, {"sessionMinutes": 30}, {"sessionMinutes": None}]
        for body in bad:
            r = self.call("PUT", "/api/settings", json=body)
            self.assertEqual(r.status_code, 422, body)
            self.assertIsInstance(r.get_json()["detail"], str)


class ReminderPreferenceTests(ApiTestCase):
    def test_defaults_put_get_and_isolation(self):
        self.assertEqual(self.call("GET", "/api/reminders/preferences").get_json(), REMINDER_DEFAULTS)
        full = {"deadline": False, "dailySummary": False, "progressCheckin": True, "quietHours": False}
        self.assertEqual(self.call("PUT", "/api/reminders/preferences", json=full).get_json(), full)
        self.assertEqual(self.call("GET", "/api/reminders/preferences").get_json(), full)
        self.assertEqual(self.db.store[("students", "alice")]["reminder_prefs"], full)
        self.assertTrue(self.call("GET", "/api/reminders/preferences", "bob").get_json()["deadline"])

    def test_partial_update_validation_and_unknown_keys(self):
        r = self.call("PUT", "/api/reminders/preferences", json={"progressCheckin": True}).get_json()
        self.assertEqual((r["progressCheckin"], r["deadline"]), (True, True))
        for body in ({}, {"deadline": "yes"}, {"quietHours": 0}, {"deadline": None}, {"unknown": True}):
            self.assertEqual(self.call("PUT", "/api/reminders/preferences", json=body).status_code, 422, body)
        r = self.call("PUT", "/api/reminders/preferences", json={"deadline": False, "junk": 1}).get_json()
        self.assertEqual(set(r), set(REMINDER_DEFAULTS))
        self.assertNotIn("junk", self.db.store[("students", "alice")]["reminder_prefs"])

    def test_settings_and_reminders_do_not_overwrite_each_other(self):
        self.call("PUT", "/api/reminders/preferences", json={"deadline": False})
        self.call("PUT", "/api/settings", json={"leadDays": 7})
        self.assertFalse(self.call("GET", "/api/reminders/preferences").get_json()["deadline"])
        self.call("PUT", "/api/reminders/preferences", json={"quietHours": False})
        self.assertEqual(self.call("GET", "/api/settings").get_json()["leadDays"], 7)


class StudentDocumentCreationTests(ApiTestCase):
    def test_created_lazily_from_the_token_when_data_is_first_written(self):
        self.assertNotIn(("students", "alice"), self.db.store)
        self.add_subject("alice")
        doc = self.db.store[("students", "alice")]
        self.assertEqual((doc["student_id"], doc["full_name"], doc["email"]), ("alice", "Alice", "alice@example.com"))
        self.assertTrue(doc["created_at"])
        self.assertEqual((doc["lead_days"], doc["session_minutes"], doc["reminder_prefs"]), (2, 45, REMINDER_DEFAULTS))
        self.assertNotIn("password_hash", doc)

    def test_existing_student_document_is_not_overwritten_by_later_writes(self):
        self.call("PUT", "/api/settings", json={"full_name": "Ana", "leadDays": 5})
        created = self.db.store[("students", "alice")]["created_at"]
        self.add_task("alice")
        doc = self.db.store[("students", "alice")]
        self.assertEqual((doc["full_name"], doc["lead_days"], doc["created_at"]), ("Ana", 5, created))


if __name__ == "__main__":
    unittest.main()
