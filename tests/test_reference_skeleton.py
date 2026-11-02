"""The portable blueprint runs offline and preserves an existing project's files."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


KIT = Path(__file__).resolve().parents[1]
BOOTSTRAP = KIT / "skills" / "qa-project-style" / "scripts" / "bootstrap.py"
RUNTIME_AVAILABLE = all(importlib.util.find_spec(name) is not None
                        for name in ("pytest", "requests", "pydantic", "allure"))


def execute(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.pop("QA_BASE_URL", None)
    env.pop("PYTHONPATH", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([sys.executable, *args], cwd=cwd, env=env, text=True,
                          encoding="utf-8", errors="replace", capture_output=True, timeout=45)


class BootstrapPreservationTests(unittest.TestCase):
    def test_dry_run_creates_nothing(self):
        with tempfile.TemporaryDirectory(prefix="qa-kit-reference-") as temporary:
            target = Path(temporary) / "new-qa"
            result = execute(str(BOOTSTRAP), str(target), "--dry-run")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(target.exists())

    def test_conflict_is_reported_before_any_output_is_written(self):
        with tempfile.TemporaryDirectory(prefix="qa-kit-reference-") as temporary:
            target = Path(temporary)
            existing = target / "configuration.py"
            existing.write_text("TEAM_CONFIGURATION = True\n", encoding="utf-8")
            result = execute(str(BOOTSTRAP), str(target))
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertEqual(existing.read_text(encoding="utf-8"), "TEAM_CONFIGURATION = True\n")
            self.assertEqual({path.name for path in target.iterdir()}, {"configuration.py"})

    def test_linked_target_and_ancestor_are_preserved(self):
        with tempfile.TemporaryDirectory(prefix="qa-kit-reference-") as temporary:
            root = Path(temporary)
            actual = root / "actual"
            actual.mkdir()
            sentinel = actual / "keep.txt"
            sentinel.write_text("existing contents", encoding="utf-8")
            link = root / "linked"
            junction = False
            if os.name == "nt":
                result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(actual)],
                                        capture_output=True, timeout=10)
                junction = result.returncode == 0
            if not junction:
                try:
                    link.symlink_to(actual, target_is_directory=True)
                except OSError:
                    self.skipTest("Neither directory symlinks nor junctions are available")
            try:
                for target in (link, link / "new-qa"):
                    with self.subTest(target=str(target)):
                        result = execute(str(BOOTSTRAP), str(target))
                        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                        self.assertEqual(sentinel.read_text(encoding="utf-8"), "existing contents")
                        self.assertEqual({path.name for path in actual.iterdir()}, {"keep.txt"})
            finally:
                if junction:
                    link.rmdir()
                else:
                    link.unlink()


@unittest.skipUnless(RUNTIME_AVAILABLE, "Use a project venv with the blueprint requirements installed")
class BlueprintRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="qa-kit-reference-")
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name)
        result = execute(str(BOOTSTRAP), str(self.target))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_smoke_passes_with_network_connections_blocked(self):
        code = textwrap.dedent("""
            import socket
            def blocked(*args, **kwargs):
                raise AssertionError('The blueprint smoke must not open a network connection')
            socket.socket.connect = blocked
            socket.create_connection = blocked
            import pytest
            raise SystemExit(pytest.main(['-q']))
        """)
        result = execute("-c", code, cwd=self.target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("2 passed", result.stdout)

    def test_runtime_validates_models_and_preserves_transport_defaults(self):
        code = textwrap.dedent("""
            import json
            from unittest.mock import patch
            import requests
            from pydantic import ValidationError
            from configuration import get_base_url
            from tests.core.http_client import HttpClient
            from tests.models.model import DemoItemResponseSchema
            from tests.helpers.allure_helper.allure_assertion import assert_equals_txt

            try:
                get_base_url()
            except ValueError:
                pass
            else:
                raise AssertionError('A real target must require explicit configuration')

            def response(body):
                result = requests.Response()
                result.status_code = 200
                result._content = json.dumps(body).encode()
                return result

            client = HttpClient('https://example.invalid')
            assert client.session.verify is True
            with patch.object(client.session, 'request', return_value=response([{'id': 'one', 'name': 'A'}])) as send:
                result = client._send_request('GET', '/demo/items', 'list', expected_model=list[DemoItemResponseSchema])
                assert result.model[0].name == 'A'
                assert send.call_args.kwargs['timeout'] == 10

            with patch.object(client.session, 'request', return_value=response({'id': 'one'})):
                try:
                    client._send_request('GET', '/demo/items/one', 'invalid', expected_model=DemoItemResponseSchema)
                except ValidationError:
                    pass
                else:
                    raise AssertionError('A successful HTTP response with a broken schema must fail')

            try:
                assert_equals_txt('CaseSensitive', 'casesensitive')
            except AssertionError:
                pass
            else:
                raise AssertionError('String assertions must preserve case')
            client.close()
        """)
        result = execute("-c", code, cwd=self.target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
