"""Shared test setup: fake Firestore, fake token verification, helpers. No Firebase account or network is needed."""
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
TASK = {"title": "Programming Activity 05", "category": "assignment", "deadline": "2026-11-20", "importance": "high"}
TASK_FIELDS = {"task_id", "subject_id", "title", "deadline", "importance", "category", "progress_pct", "status", "subtasks"}


class ApiTestCase(unittest.TestCase):
    enable_v2 = True

    def setUp(self):
        self.db = FakeFirestore()
        self.app = create_app(db=self.db, token_verifier=fake_verifier, enable_v2=self.enable_v2)
        self.client = self.app.test_client()
        self._real_today = dates.today
        dates.today = lambda: TODAY
        self._default_subjects = {}

    def tearDown(self):
        dates.today = self._real_today

    def call(self, method, path, user="alice", json=None, headers=None, **kwargs):
        sent = dict(headers or {})
        if user:
            sent["Authorization"] = f"Bearer token-{user}"
        return self.client.open(path, method=method, json=json, headers=sent, **kwargs)

    def add_subject(self, user="alice", name="Computer Programming"):
        response = self.call("POST", "/api/subjects", user, json={"subject_name": name})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def default_subject_id(self, user):
        if user not in self._default_subjects:
            self._default_subjects[user] = self.add_subject(user, "Default subject")["subject_id"]
        return self._default_subjects[user]

    def add_task(self, user="alice", **over):
        body = {**TASK, **over}
        if "subject_id" not in body:
            body["subject_id"] = self.default_subject_id(user)
        response = self.call("POST", "/api/tasks", user, json=body)
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def task_doc(self, task_id):
        return self.db.store.get(("tasks", task_id))

    def get_task(self, task_id, user="alice"):
        return next(t for t in self.call("GET", "/api/tasks", user).get_json() if t["task_id"] == task_id)
