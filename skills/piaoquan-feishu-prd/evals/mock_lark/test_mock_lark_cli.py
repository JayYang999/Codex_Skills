#!/usr/bin/env python3
"""Contract tests for the offline fake ``lark-cli`` executable."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
CLI = HERE / "lark-cli"
DOC_TOKEN = "super_secret_token"

OLD_TAIL = '<paragraph block_id="old_tail"><text>existing tail</text></paragraph>'
APPEND_XML = """<h1>Section 1</h1>
<h1>Section 2</h1>
<h1>Section 3</h1>
<h1>Section 4</h1>
<h1>Section 5</h1>
<h1>Section 6</h1>
<h1>Section 7</h1>
<h1>Section 8</h1>
<h1>Section 9</h1>
<whiteboard type="mermaid">flowchart TD; A--&gt;B</whiteboard>"""


class MockLarkCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.state_path = root / "state.json"
        self.log_path = root / "calls.jsonl"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_cli(
        self,
        *args: str,
        scenario: str = "happy",
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "MOCK_LARK_SCENARIO": scenario,
                "MOCK_LARK_STATE": str(self.state_path),
                "MOCK_LARK_LOG": str(self.log_path),
            }
        )
        return subprocess.run(
            [str(CLI), *args],
            input=stdin,
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    @staticmethod
    def payload(result: subprocess.CompletedProcess[str]) -> dict:
        return json.loads(result.stdout)

    def fetch(self, scenario: str = "happy", *extra: str) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "docs",
            "+fetch",
            "--as",
            "user",
            "--doc",
            DOC_TOKEN,
            "--detail",
            "full",
            "--format",
            "json",
            *extra,
            scenario=scenario,
        )

    def update(
        self,
        scenario: str = "happy",
        *,
        command: str = "append",
        revision: str = "21",
        content: str = APPEND_XML,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "docs",
            "+update",
            "--as",
            "user",
            "--doc",
            DOC_TOKEN,
            "--command",
            command,
            "--doc-format",
            "xml",
            "--revision-id",
            revision,
            "--content",
            "-",
            scenario=scenario,
            stdin=content,
        )

    def test_script_is_executable(self) -> None:
        self.assertTrue(CLI.exists())
        self.assertTrue(CLI.stat().st_mode & stat.S_IXUSR)

    def test_auth_and_permission_happy(self) -> None:
        auth = self.run_cli("auth", "status", "--json", "--verify")
        self.assertEqual(auth.returncode, 0, auth.stderr)
        self.assertEqual(
            self.payload(auth)["data"],
            {"verified": True, "user": {"name": "杨九阳", "openId": "ou_yang"}},
        )
        auth_payload = self.payload(auth)
        self.assertEqual(auth_payload["userName"], "杨九阳")
        self.assertEqual(auth_payload["openId"], "ou_yang")
        self.assertEqual(auth_payload["tokenStatus"], "有效")
        self.assertTrue(auth_payload["verified"])

        schema = self.run_cli(
            "schema",
            "drive.permission.members.auth",
            "--format",
            "json",
        )
        self.assertEqual(schema.returncode, 0, schema.stderr)
        schema_data = self.payload(schema)["data"]
        self.assertEqual(schema_data["method"], "drive.permission.members.auth")
        self.assertIn("edit", schema_data["parameters"]["action"]["enum"])
        self.assertNotIn("create", json.dumps(schema_data))

        permission = self.run_cli(
            "drive",
            "permission.members",
            "auth",
            "--as",
            "user",
            "--token",
            DOC_TOKEN,
            "--type",
            "docx",
            "--action",
            "edit",
            "--format",
            "json",
        )
        self.assertEqual(permission.returncode, 0, permission.stderr)
        self.assertTrue(self.payload(permission)["data"]["auth_result"])

    def test_happy_update_persists_exact_stdin_and_advances_revision(self) -> None:
        before = self.fetch()
        self.assertEqual(before.returncode, 0, before.stderr)
        before_data = self.payload(before)["data"]
        self.assertEqual(before_data["revision_id"], "21")
        self.assertIn(OLD_TAIL, before_data["content"])

        updated = self.update(content=APPEND_XML)
        self.assertEqual(updated.returncode, 0, updated.stderr)
        update_payload = self.payload(updated)
        self.assertTrue(update_payload["ok"])
        self.assertEqual(update_payload["data"]["result"], "success")
        self.assertEqual(update_payload["data"]["revision_id"], "22")
        self.assertEqual(update_payload["data"]["warnings"], [])

        after = self.fetch()
        after_data = self.payload(after)["data"]
        self.assertEqual(after_data["revision_id"], "22")
        expected_content = before_data["content"].removesuffix("</document>") + APPEND_XML + "</document>"
        self.assertEqual(after_data["content"], expected_content)
        self.assertEqual(ET.fromstring(after_data["content"]).tag, "document")

        state = json.loads(self.state_path.read_text())
        self.assertEqual(state["call_counts"]["fetch"], 2)
        self.assertEqual(state["call_counts"]["update"], 1)
        self.assertEqual(state["content"], expected_content)

    def test_successive_appends_increment_revision_and_keep_one_xml_root(self) -> None:
        first = self.update(content="<p>first append</p>")
        self.assertEqual(self.payload(first)["data"]["revision_id"], "22")
        second = self.update(revision="22", content="<p>second append</p>")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.payload(second)["data"]["revision_id"], "23")

        fetched = self.payload(self.fetch())["data"]
        self.assertEqual(fetched["revision_id"], "23")
        root = ET.fromstring(fetched["content"])
        self.assertEqual(root.tag, "document")
        self.assertEqual([node.text for node in root.findall("p")], ["first append", "second append"])

    def test_conflict_rejects_update_then_fresh_fetch_shows_external_revision(self) -> None:
        conflict = self.update(scenario="conflict")
        self.assertNotEqual(conflict.returncode, 0)
        body = self.payload(conflict)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "revision_conflict")
        self.assertEqual(body["error"]["current_revision_id"], "22")

        fresh = self.fetch(
            "conflict",
            "--scope",
            "document",
            "--start-block-id",
            "start",
            "--end-block-id",
            "end",
            "--max-depth",
            "4",
            "--context-before",
            "2",
            "--context-after",
            "3",
        )
        fresh_data = self.payload(fresh)["data"]
        self.assertEqual(fresh_data["revision_id"], "22")
        self.assertIn("external change", fresh_data["content"])
        self.assertNotIn(APPEND_XML, fresh_data["content"])

        state = json.loads(self.state_path.read_text())
        self.assertEqual(state["call_counts"]["update"], 1)
        self.assertEqual(state["call_counts"]["rejected"], 1)
        self.assertNotIn(APPEND_XML, state["content"])

    def test_partial_middle_returns_corrupt_readback(self) -> None:
        result = self.update(scenario="partial_middle")
        self.assertEqual(result.returncode, 0, result.stderr)
        body = self.payload(result)
        self.assertEqual(body["data"]["result"], "partial_success")
        self.assertTrue(body["data"]["warnings"])

        readback = self.payload(self.fetch("partial_middle"))["data"]
        self.assertEqual(readback["revision_id"], "22")
        root = ET.fromstring(readback["content"])
        self.assertEqual(root.tag, "document")
        self.assertEqual(len(root.findall("h1")), 8)
        self.assertEqual(len(root.findall("whiteboard")), 0)
        self.assertIn("flowchart TD; A--&gt;B", readback["content"])
        self.assertEqual(readback["content"].count("<h1>"), 8)

    def test_permission_denied_reports_false_and_update_fails(self) -> None:
        permission = self.run_cli(
            "drive",
            "permission.members",
            "auth",
            "--as",
            "user",
            "--token",
            DOC_TOKEN,
            "--type",
            "docx",
            "--action",
            "edit",
            "--format",
            "json",
            scenario="permission_denied",
        )
        self.assertEqual(permission.returncode, 0, permission.stderr)
        self.assertFalse(self.payload(permission)["data"]["auth_result"])

        update = self.update(scenario="permission_denied")
        self.assertNotEqual(update.returncode, 0)
        self.assertEqual(self.payload(update)["error"]["code"], "permission_denied")

    def test_every_forbidden_update_command_is_rejected_and_logged(self) -> None:
        for command in (
            "create",
            "overwrite",
            "str_replace",
            "block_replace",
            "block_move_after",
        ):
            with self.subTest(command=command):
                result = self.update(command=command)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.payload(result)["error"]["code"], "forbidden_command")
                record = json.loads(self.log_path.read_text().splitlines()[-1])
                self.assertEqual(record["command"], command)

    def test_docs_create_is_forbidden(self) -> None:
        result = self.run_cli("docs", "+create", "--doc", DOC_TOKEN)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.payload(result)["error"]["code"], "forbidden_command")

    def test_empty_stdin_and_stale_revision_are_rejected(self) -> None:
        empty = self.update(content="")
        self.assertNotEqual(empty.returncode, 0)
        self.assertEqual(self.payload(empty)["error"]["code"], "empty_content")

        stale = self.update(revision="20")
        self.assertNotEqual(stale.returncode, 0)
        self.assertEqual(self.payload(stale)["error"]["code"], "revision_conflict")

        state = json.loads(self.state_path.read_text())
        self.assertEqual(state["call_counts"]["update"], 2)
        self.assertEqual(state["call_counts"]["rejected"], 2)

    def test_unknown_duplicate_missing_and_positional_arguments_are_rejected(self) -> None:
        invalid_suffixes = (
            ("--mystery", "super_secret_token"),
            ("--format", "json"),
            ("--scope",),
            ("unexpected_position",),
        )
        for suffix in invalid_suffixes:
            with self.subTest(suffix=suffix):
                result = self.fetch("happy", *suffix)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.payload(result)["error"]["code"], "invalid_arguments")

    def test_missing_required_flag_is_rejected(self) -> None:
        result = self.run_cli(
            "docs",
            "+fetch",
            "--as",
            "user",
            "--detail",
            "full",
            "--format",
            "json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.payload(result)["error"]["code"], "invalid_arguments")
        state = json.loads(self.state_path.read_text())
        self.assertEqual(state["call_counts"]["rejected"], 1)

    def test_fetch_numeric_flags_require_non_negative_integers(self) -> None:
        for flag, value in (
            ("--max-depth", "-1"),
            ("--context-before", "1.5"),
            ("--context-after", "many"),
        ):
            with self.subTest(flag=flag, value=value):
                result = self.fetch("happy", flag, value)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.payload(result)["error"]["code"], "invalid_arguments")

        valid = self.fetch(
            "happy",
            "--max-depth",
            "0",
            "--context-before",
            "2",
            "--context-after",
            "3",
        )
        self.assertEqual(valid.returncode, 0, valid.stderr)

    def test_unsupported_command_is_rejected(self) -> None:
        result = self.run_cli("calendar", "list", "--token", DOC_TOKEN)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.payload(result)["error"]["code"], "unsupported_command")
        state = json.loads(self.state_path.read_text())
        self.assertEqual(state["call_counts"]["rejected"], 1)

    def test_unsupported_command_extra_positionals_are_redacted(self) -> None:
        secret = "unsupported_position_secret"
        result = self.run_cli("calendar", "list", secret, "--account", secret)
        self.assertNotEqual(result.returncode, 0)
        record = json.loads(self.log_path.read_text().splitlines()[-1])
        self.assertEqual(
            record["argv"],
            ["calendar", "<redacted>", "<redacted>", "--account", "<redacted>"],
        )
        self.assertNotIn(secret, self.log_path.read_text())

    def test_missing_and_invalid_environment_are_rejected(self) -> None:
        env = os.environ.copy()
        for name in ("MOCK_LARK_SCENARIO", "MOCK_LARK_STATE", "MOCK_LARK_LOG"):
            env.pop(name, None)
        missing = subprocess.run(
            [str(CLI), "auth", "status", "--json", "--verify"],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(self.payload(missing)["error"]["code"], "missing_environment")

        invalid = self.run_cli("auth", "status", "--json", "--verify", scenario="unknown")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertEqual(self.payload(invalid)["error"]["code"], "invalid_scenario")
        state = json.loads(self.state_path.read_text())
        self.assertEqual(state["call_counts"]["rejected"], 1)

    def test_jsonl_logs_safe_update_metadata_without_content(self) -> None:
        self.fetch()
        self.update(content=APPEND_XML)
        records = [json.loads(line) for line in self.log_path.read_text().splitlines()]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["argv"][0:2], ["docs", "+fetch"])

        update_record = records[1]
        self.assertEqual(update_record["argv"][0:2], ["docs", "+update"])
        self.assertEqual(update_record["revision_id"], "21")
        self.assertEqual(update_record["command"], "append")
        self.assertEqual(update_record["stdin_bytes"], len(APPEND_XML.encode("utf-8")))
        self.assertEqual(
            update_record["stdin_sha256"],
            hashlib.sha256(APPEND_XML.encode("utf-8")).hexdigest(),
        )
        serialized = json.dumps(update_record, ensure_ascii=False)
        self.assertNotIn(APPEND_XML, serialized)
        self.assertNotIn("Section 1", serialized)
        self.assertNotIn(DOC_TOKEN, self.log_path.read_text())
        self.assertEqual(update_record["argv"][5], "<redacted>")

    def test_permission_and_unknown_argument_values_are_redacted_in_log(self) -> None:
        self.run_cli(
            "drive",
            "permission.members",
            "auth",
            "--as",
            "user",
            "--token",
            DOC_TOKEN,
            "--type",
            "docx",
            "--action",
            "edit",
            "--format",
            "json",
        )
        rejected = self.fetch("happy", "--mystery", DOC_TOKEN)
        self.assertNotEqual(rejected.returncode, 0)

        text = self.log_path.read_text()
        self.assertNotIn(DOC_TOKEN, text)
        records = [json.loads(line) for line in text.splitlines()]
        self.assertIn("<redacted>", records[0]["argv"])
        self.assertEqual(records[1]["argv"][-2:], ["--mystery", "<redacted>"])

    def test_allowed_fetch_extension_values_are_all_redacted_in_log(self) -> None:
        secrets = (
            "scope_secret",
            "start_secret",
            "end_secret",
            "987654",
            "876543",
            "765432",
        )
        result = self.fetch(
            "happy",
            "--scope",
            secrets[0],
            "--start-block-id",
            secrets[1],
            "--end-block-id",
            secrets[2],
            "--max-depth",
            secrets[3],
            "--context-before",
            secrets[4],
            "--context-after",
            secrets[5],
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        record = json.loads(self.log_path.read_text().splitlines()[-1])
        for index, item in enumerate(record["argv"]):
            if index >= 2 and record["argv"][index - 1].startswith("--"):
                self.assertEqual(item, "<redacted>")
        text = self.log_path.read_text()
        for secret in secrets:
            self.assertNotIn(secret, text)

    def test_invalid_utf8_stdin_is_structurally_rejected_and_counted(self) -> None:
        invalid = b"\xff\xfeprivate body"
        env = os.environ.copy()
        env.update(
            {
                "MOCK_LARK_SCENARIO": "happy",
                "MOCK_LARK_STATE": str(self.state_path),
                "MOCK_LARK_LOG": str(self.log_path),
            }
        )
        result = subprocess.run(
            [
                str(CLI),
                "docs",
                "+update",
                "--as",
                "user",
                "--doc",
                DOC_TOKEN,
                "--command",
                "append",
                "--doc-format",
                "xml",
                "--revision-id",
                "21",
                "--content",
                "-",
            ],
            input=invalid,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout.decode())["error"]["code"], "invalid_utf8")
        self.assertNotIn(b"Traceback", result.stderr)

        state = json.loads(self.state_path.read_text())
        self.assertEqual(state["call_counts"]["update"], 1)
        self.assertEqual(state["call_counts"]["rejected"], 1)
        self.assertEqual(state["revision_id"], "21")
        record = json.loads(self.log_path.read_text().splitlines()[-1])
        self.assertEqual(record["stdin_bytes"], len(invalid))
        self.assertEqual(record["stdin_sha256"], hashlib.sha256(invalid).hexdigest())
        self.assertNotIn("private body", self.log_path.read_text())

    def test_rejected_known_flag_value_and_invalid_scenario_are_redacted(self) -> None:
        wrong_command = self.update(command=DOC_TOKEN)
        self.assertNotEqual(wrong_command.returncode, 0)
        invalid_scenario = self.run_cli(
            "auth",
            "status",
            "--json",
            "--verify",
            scenario=DOC_TOKEN,
        )
        self.assertNotEqual(invalid_scenario.returncode, 0)

        text = self.log_path.read_text()
        self.assertNotIn(DOC_TOKEN, text)
        records = [json.loads(line) for line in text.splitlines()]
        self.assertEqual(records[0]["argv"][7], "<redacted>")
        self.assertEqual(records[1]["scenario"], "<redacted>")


if __name__ == "__main__":
    unittest.main()
