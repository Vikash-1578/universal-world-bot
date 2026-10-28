import tempfile
import time
import unittest
from pathlib import Path

from app.core.config import load_dotenv, load_settings, parse_keys
from app.core.errors import ApprovalRequired, InvalidInput
from app.core.security import Approvals
from app.core.validation import validate
from app.observability.audit import Audit
from app.observability.log import add_secret, redact
from app.storage.db import MIGRATIONS, Database
from app.storage.files import check_upload, safe_join, safe_name
from tests.helpers import TOKEN, make_settings


class ConfigTests(unittest.TestCase):
    def test_dotenv_and_keys(self):
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            (t / ".env").write_text(f'BOT_TOKEN="{TOKEN}"\nOWNER_ID=42  # me\n', encoding="utf-8")
            (t / "keys.txt").write_text("# comment\ngroq:gsk_abc\ngemini: AIza123\nCF_ACCOUNT_ID=abc\nnot a key line\n", encoding="utf-8")
            s = load_settings(t, env=load_dotenv(t / ".env"))
            self.assertEqual((s.bot_token, s.owner_id), (TOKEN, 42))
            self.assertEqual(s.keys_for("groq"), ["gsk_abc"])
            self.assertEqual(s.key("gemini"), "AIza123")
            self.assertEqual(s.key("cf_account_id"), "abc")
            self.assertTrue((t / "data").is_dir())

    def test_parse_keys_skips_bad(self):
        self.assertEqual(parse_keys("::\n=\nhf:x\n"), [("hf", "x")])

    def test_validation(self):
        with tempfile.TemporaryDirectory() as td:
            s = make_settings(Path(td))
            self.assertEqual(validate(s), [])
            s.owner_id = 0
            s.bot_token = "bad"
            whats = " ".join(p.what for p in validate(s))
            self.assertIn("OWNER_ID", whats)
            self.assertIn("format", whats)


class DatabaseTests(unittest.TestCase):
    def test_migrations_fk_and_integrity(self):
        db = Database(":memory:")
        self.assertEqual(db.version, len(MIGRATIONS))
        self.assertTrue(db.integrity_ok())
        with self.assertRaises(Exception):  # foreign keys enforced
            db.insert("scenes", {"project_id": 999, "scene_number": 1})
        self.assertEqual(db.migrate(), len(MIGRATIONS))  # idempotent

    def test_newer_database_refused(self):
        db = Database(":memory:")
        db.execute("PRAGMA user_version = 99")
        with self.assertRaises(RuntimeError):
            db.migrate()

    def test_tx_rollback(self):
        db = Database(":memory:")

        def bad(d):
            d.set_setting("a", 1)
            raise ValueError("x")

        with self.assertRaises(ValueError):
            db.tx(bad)
        self.assertIsNone(db.get_setting("a"))


class FilesTests(unittest.TestCase):
    def test_path_traversal_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertEqual(safe_join(root, "projects", "1"), (root / "projects" / "1").resolve())
            for bad in ("..", "../x", "/etc", "C:\\x", "a/../../b", "x\x00y"):
                with self.assertRaises(InvalidInput, msg=bad):
                    safe_join(root, *bad.split("/"))

    def test_upload_checks(self):
        self.assertEqual(check_upload("image", "../../photo.PNG", 100, b"\x89PNG...."), "photo.PNG")
        with self.assertRaises(InvalidInput):
            check_upload("image", "virus.exe", 100)
        with self.assertRaises(InvalidInput):
            check_upload("image", "big.png", 999 * 1024 * 1024)
        with self.assertRaises(InvalidInput):
            check_upload("image", "fake.png", 100, b"%PDF-1.4")
        self.assertEqual(safe_name("a<b>:c.txt"), "a_b_c.txt")


class SecretTests(unittest.TestCase):
    def test_redaction(self):
        add_secret("supersecretvalue123")
        s = redact(f"token {TOKEN} key gsk_abcdefghijklmnop url ?key=zzz123 and supersecretvalue123 and Bearer abcdefghijklmnop")
        for leaked in (TOKEN, "gsk_abcdefghijklmnop", "zzz123", "supersecretvalue123", "abcdefghijklmnop"):
            self.assertNotIn(leaked, s)


class ApprovalTests(unittest.TestCase):
    def test_one_time_expiring_scoped(self):
        db = Database(":memory:")
        ap = Approvals(db, Audit(db))
        t = ap.request("delete_project", 5, {"x": 1})
        with self.assertRaises(ApprovalRequired):
            ap.consume(t, "delete_project", 6)  # other target
        with self.assertRaises(ApprovalRequired):
            ap.consume(t, "model_install", 5)  # other action
        self.assertEqual(ap.consume(t, "delete_project", 5), {"x": 1})
        with self.assertRaises(ApprovalRequired):
            ap.consume(t, "delete_project", 5)  # used
        t2 = ap.request("cleanup", "all", ttl=-1)
        with self.assertRaises(ApprovalRequired):
            ap.consume(t2, "cleanup", "all")  # expired
        rows = db.all("SELECT action, result FROM audit_events")
        self.assertIn(("delete_project", "approved"), [(r["action"], r["result"]) for r in rows])


if __name__ == "__main__":
    unittest.main()
