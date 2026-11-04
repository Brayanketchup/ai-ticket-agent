"""Offline tests. No network. Run from the repo folder: python -m unittest discover tests"""
import base64
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import install  # noqa: E402
import ticket_fetch as tf  # noqa: E402


def png(w, h, pad=0):
    raw = b"".join(b"\x00" + b"\x00" * (w * 3) for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"") + b"\x00" * pad


class FakeApi(tf.TicketApi):
    """Serves canned responses instead of HTTP."""

    def __init__(self, cfg, responses):
        super().__init__(cfg)
        self.responses = responses
        self.calls = []

    def get(self, url, timeout=30):
        self.calls.append(url)
        return self.responses.get(url, (404, b""))


class FetchHelpers(unittest.TestCase):
    def test_html_to_text_strips_styles_and_keeps_lines(self):
        src = "<html><head><style>p{margin:0}</style></head><body><p>Hello&nbsp;team</p><div>Line two<br>Line three</div><!-- x --><script>alert(1)</script></body></html>"
        self.assertEqual(tf.html_to_text(src), "Hello team\nLine two\nLine three")

    def test_safe_name_blocks_paths(self):
        self.assertEqual(tf.safe_name("../../evil.cgi"), "evil.cgi")
        self.assertEqual(tf.safe_name("/tickets/T1/00_T1_1_email_body.html"), "00_T1_1_email_body.html")
        self.assertEqual(tf.safe_name('a<b>:"c.png'), "a_b___c.png")

    def test_ticket_number_validation(self):
        pattern = tf.DEFAULTS["ticket_pattern"]
        import re
        self.assertTrue(re.match(pattern, "ABC123-45678"))
        self.assertFalse(re.match(pattern, "../etc"))
        self.assertFalse(re.match(pattern, "T1/2"))

    def test_image_size_png(self):
        self.assertEqual(tf.image_size(png(40, 30)), (40, 30))

    def test_extract_images_skips_small_and_duplicates(self):
        big = base64.b64encode(png(10, 10, pad=6000)).decode()
        small = base64.b64encode(png(2, 2)).decode()
        src = (f'<img src="data:image/png;base64,{big}"><img src="data:image/png;base64,{small}">'
               f'<img src="data:image/png;base64,{big}"><img src="https://cdn.example.com/logo.png">')
        with tempfile.TemporaryDirectory() as d:
            saved, remote = tf.extract_images(src, "00_T", Path(d), set())
            self.assertEqual([s[0] for s in saved], ["00_T_img1.png"])
            self.assertEqual(saved[0][2], (10, 10))
            self.assertEqual(remote, ["https://cdn.example.com/logo.png"])


class Config(unittest.TestCase):
    def test_config_file_then_env_override(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "config.json"
            f.write_text(json.dumps({"tickets_dir": "C:/x", "base_url": "https://a/b", "fields": {"author": "Who"}}))
            cfg = tf.load_config(f)
            self.assertEqual(cfg["tickets_dir"], "C:/x")
            self.assertEqual(cfg["fields"]["author"], "Who")
            self.assertEqual(cfg["fields"]["note"], "TicketNote")  # partial override keeps the other defaults
            with mock.patch.dict(os.environ, {"TICKET_AGENT_TICKETS_DIR": "D:/y", "TICKET_AGENT_TOKEN": "t0k"}):
                cfg = tf.load_config(f)
            self.assertEqual(cfg["tickets_dir"], "D:/y")
            self.assertEqual(cfg["token"], "t0k")
            self.assertEqual(cfg["base_url"], "https://a/b")

    def test_defaults_without_config(self):
        cfg = tf.load_config(Path(tempfile.gettempdir()) / "no-such-config.json")
        self.assertEqual(cfg["base_url"], "")
        self.assertTrue(cfg["tickets_dir"].endswith("tickets"))

    def test_missing_base_url_is_a_clear_error(self):
        cfg = tf.load_config(Path(tempfile.gettempdir()) / "no-such-config.json")
        with self.assertRaises(SystemExit) as e:
            tf.TicketApi(cfg)
        self.assertIn("base_url", str(e.exception))

    def test_token_becomes_bearer_header(self):
        cfg = tf.load_config(Path(tempfile.gettempdir()) / "no-such-config.json")
        cfg.update(base_url="https://h/x", token="abc")
        self.assertEqual(tf.TicketApi(cfg).headers["Authorization"], "Bearer abc")


class Fetch(unittest.TestCase):
    def setUp(self):
        self.cfg = tf.load_config(Path(tempfile.gettempdir()) / "no-such-config.json")
        self.cfg["base_url"] = "https://helpdesk.example.com/st"

    def test_end_to_end_with_fake_api(self):
        b = self.cfg["base_url"]
        shot = base64.b64encode(png(20, 20, pad=6000)).decode()
        email = f"<html><body><p>The Save button fails.</p><img src='data:image/png;base64,{shot}'></body></html>"
        detail = {"RESP": "OK", "DATA": [{"ThreadID": 1, "ThreadAction": "Created", "CreatedByName": "Pat",
                                          "CreatedOn": "2026-01-02", "TicketNote": "<b>Help</b>",
                                          "Attachments": [{"url": "/x/T1_1_email_body.html"}, {"url": "log.txt"}]}]}
        responses = {
            f"{b}/detail/T1-0001/": (200, json.dumps(detail).encode()),
            f"{b}/file/T1-0001/T1_1_email_body.html/": (200, email.encode()),
            f"{b}/file/T1-0001/log.txt/": (200, b"error 42"),
            f"{b}/file/T1-0001/T1_1_email_attachments/": (200, b'["report.pdf"]'),
            f"{b}/attachment/T1-0001/T1_1_email_attachments/report.pdf/": (200, b"%PDF-1.4"),
        }
        with tempfile.TemporaryDirectory() as d:
            folder = tf.fetch("T1-0001", d, self.cfg, api=FakeApi(self.cfg, responses))
            md = (folder / "ticket.md").read_text(encoding="utf-8")
            self.assertIn("## Thread 1: Created by Pat on 2026-01-02", md)
            self.assertIn("The Save button fails.", md)
            self.assertIn("images/T1_1_img1.png", md)
            self.assertIn("attachments/report.pdf", md)
            self.assertIn("attachments/log.txt", md)
            self.assertTrue((folder / "attachments" / "report.pdf").exists())

    def test_custom_fields_and_bare_list(self):
        b = self.cfg["base_url"]
        self.cfg["fields"].update(status_key="", data_key="", thread_id="id", author="by", files="files")
        self.cfg["endpoints"]["attachment_list"] = ""
        detail = [{"id": 7, "by": "Sam", "files": ["note.txt"]}]
        responses = {f"{b}/detail/T2-0002/": (200, json.dumps(detail).encode()),
                     f"{b}/file/T2-0002/note.txt/": (200, b"hi")}
        api = FakeApi(self.cfg, responses)
        with tempfile.TemporaryDirectory() as d:
            folder = tf.fetch("T2-0002", d, self.cfg, api=api)
            self.assertIn("Thread 7:  by Sam", (folder / "ticket.md").read_text(encoding="utf-8"))
        self.assertEqual(len(api.calls), 2)

    def test_bad_ticket_number_refused_before_any_request(self):
        api = FakeApi(self.cfg, {})
        with self.assertRaises(SystemExit):
            tf.fetch("../etc", tempfile.gettempdir(), self.cfg, api=api)
        self.assertEqual(api.calls, [])


class Install(unittest.TestCase):
    def test_render_fills_paths_and_marks_install(self):
        template = (REPO / "skill" / "SKILL.md").read_text(encoding="utf-8")
        out = install.render_skill(template, {"tickets_dir": "D:/t", "context_dir": "D:/map"}, "Alex")
        self.assertNotIn("{{", out)
        self.assertIn("D:/t/<TICKET>/ticket.md", out)
        self.assertIn("D:/map", out)
        self.assertIn("Alex", out)
        self.assertTrue(out.startswith("---\nname: ticket-investigate\n"))
        self.assertIn("\n---\n" + install.MARKER + "\n", out)

    def test_install_and_uninstall_into_temp_skills_dir(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(install, "HERE", Path(d)):
            (Path(d) / "skill").mkdir()
            (Path(d) / "skill" / "SKILL.md").write_text((REPO / "skill" / "SKILL.md").read_text(encoding="utf-8"), encoding="utf-8")
            (Path(d) / "ticket_fetch.py").write_text("")
            skills = Path(d) / "skills"
            install.main(["--skills-dir", str(skills), "--tickets-dir", str(Path(d) / "tk"), "--base-url", "https://h/x/"])
            installed = skills / "ticket-investigate" / "SKILL.md"
            self.assertIn(install.MARKER, installed.read_text(encoding="utf-8"))
            cfg = json.loads((Path(d) / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(cfg["base_url"], "https://h/x")
            install.main(["--skills-dir", str(skills), "--uninstall"])
            self.assertFalse(installed.exists())


if __name__ == "__main__":
    unittest.main()
