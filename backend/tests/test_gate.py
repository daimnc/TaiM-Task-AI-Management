"""TAIM_ENABLE_V2: the new data routes must stay disabled (503) unless the gate is explicitly turned on."""
import importlib
import os
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from base import ApiTestCase, create_app, fake_verifier  # noqa: E402

GATED = [
    ("GET", "/api/subjects"), ("POST", "/api/subjects"), ("PATCH", "/api/subjects/abc"), ("DELETE", "/api/subjects/abc"),
    ("GET", "/api/tasks"), ("POST", "/api/tasks"), ("PATCH", "/api/tasks/abc"), ("DELETE", "/api/tasks/abc"),
    ("POST", "/api/tasks/abc/start"), ("POST", "/api/tasks/abc/complete"), ("POST", "/api/tasks/abc/reopen"),
    ("GET", "/api/settings"), ("PUT", "/api/settings"),
    ("GET", "/api/reminders/preferences"), ("PUT", "/api/reminders/preferences"),
    ("GET", "/api/progress"), ("POST", "/api/ai/chat"),
]


class GateDisabledTests(ApiTestCase):
    enable_v2 = False

    def test_every_data_route_is_503_and_writes_nothing(self):
        for method, path in GATED:
            r = self.call(method, path, json={"title": "x", "subject_name": "x"})
            self.assertEqual(r.status_code, 503, (method, path))
            self.assertIn("not enabled", r.get_json()["detail"])
        self.assertEqual(self.db.store, {})
        self.assertEqual(self.db.writes, [])

    def test_auth_still_comes_first(self):
        for method, path in GATED:
            self.assertEqual(self.call(method, path, user=None, json={}).status_code, 401, (method, path))

    def test_health_and_plan_do_not_touch_the_new_layout(self):
        self.assertEqual(self.call("GET", "/api/health", user=None).status_code, 200)
        plan = {"title": "Paper", "deadline": "2026-11-26"}
        self.assertEqual(self.call("POST", "/api/ai/plan", json=plan).status_code, 200)


class GateEnabledTests(ApiTestCase):
    def test_routes_work_when_enabled(self):
        self.assertEqual(self.call("GET", "/api/tasks").status_code, 200)
        self.assertEqual(self.call("GET", "/api/subjects").status_code, 200)


class GateDefaultTests(unittest.TestCase):
    def test_app_follows_the_setting_unless_overridden(self):
        from config import Config
        app = create_app(db=None, token_verifier=fake_verifier)
        self.assertEqual(app.config["ENABLE_V2"], Config.ENABLE_V2)
        self.assertTrue(create_app(db=None, token_verifier=fake_verifier, enable_v2=True).config["ENABLE_V2"])
        self.assertFalse(create_app(db=None, token_verifier=fake_verifier, enable_v2=False).config["ENABLE_V2"])

    def test_setting_is_off_by_default_and_only_true_turns_it_on(self):
        import config
        try:
            with mock.patch("dotenv.load_dotenv"):  # ignore any real backend/.env while checking the parsing
                cases = {None: False, "": False, "false": False, "1": False, "yes": False, "on": False,
                         "true": True, " TRUE ": True}
                for value, expected in cases.items():
                    env = {k: v for k, v in os.environ.items() if k != "TAIM_ENABLE_V2"}
                    if value is not None:
                        env["TAIM_ENABLE_V2"] = value
                    with mock.patch.dict(os.environ, env, clear=True):
                        importlib.reload(config)
                        self.assertIs(config.Config.ENABLE_V2, expected, repr(value))
        finally:
            importlib.reload(config)


if __name__ == "__main__":
    unittest.main()
