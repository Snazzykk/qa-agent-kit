"""Изолированные проверки установки; модели, сеть и рабочие проекты не используются."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SOURCE_KIT = Path(__file__).resolve().parents[1]
WORKFLOWS = {"qa-project-audit", "qa-test-plan", "qa-feature-cases", "qa-test-generation", "qa-test-triage"}


class SetupProjectTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="qa-kit-setup-tests-")
        self.root = Path(self.temporary.name)
        self.kit = self.root / "kit"
        self.repo = self.root / "repository"
        self.repo.mkdir()
        self.kit.mkdir()
        shutil.copy2(SOURCE_KIT / "setup_project.py", self.kit / "setup_project.py")
        for folder in ("templates", "hooks", "commands"):
            shutil.copytree(SOURCE_KIT / folder, self.kit / folder)
        self.make_skill(self.kit / "skills", "api-test-generator", "bundled technical skill")
        self.make_skill(self.kit / "skills", "team-helper", "second technical skill")
        self.make_skill(self.kit / "skills", "qa-project-style", "bundled project style")
        self.git("init", "-q")

    def tearDown(self):
        self.assertTrue(self.root.is_relative_to(Path(tempfile.gettempdir())))
        self.temporary.cleanup()

    @staticmethod
    def make_skill(parent, name, body):
        path = parent / name
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Local test fixture\n---\n\n{body}\n", encoding="utf-8")
        return path

    def git(self, *args, repo=None):
        return subprocess.run(["git", "-C", str(repo or self.repo), *args], capture_output=True, text=True, check=True)

    def install(self, *args, expected=0, repo=None):
        env = os.environ.copy()
        env.pop("QA_KIT_SKILLS", None)
        result = subprocess.run(
            [sys.executable, str(self.kit / "setup_project.py"), str(repo or self.repo), *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    @staticmethod
    def snapshot(root):
        return {p.relative_to(root).as_posix(): p.read_bytes() if p.is_file() else None for p in root.rglob("*")}

    def test_codex_install_uses_discoverable_skills_and_shared_workflows(self):
        self.install("--agent", "codex", "--skills", "api-test-generator")
        skills = self.repo / ".agents" / "skills"
        self.assertEqual({p.name for p in skills.iterdir()}, WORKFLOWS | {"api-test-generator", "qa-project-style"})
        for workflow in WORKFLOWS:
            body = (skills / workflow / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(f"name: {workflow}\n", body)
            self.assertIn("AGENTS.md", body)
            for foreign in ("CLAUDE.md", ".claude/", ".qa-workbench", "$ARGUMENTS", ".mcp.json"):
                self.assertNotIn(foreign, body)
            for stage in ("audit", "plan", "gen", "feature", "triage"):
                self.assertNotIn("/" + stage, body)
        guidance = (self.repo / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("artifacts/qa-profile.json", guidance)
        self.assertIn("$qa-project-style", guidance)
        self.assertNotIn("SessionStart", guidance)
        self.assertFalse((self.repo / ".claude").exists())
        self.assertFalse((self.repo / ".codex").exists())
        self.assertTrue((self.repo / ".qa-kit" / "context").is_dir())

    def test_claude_remains_default_and_preserves_existing_hook_configuration(self):
        settings = self.repo / ".claude" / "settings.local.json"
        settings.parent.mkdir()
        original = {"permissions": {"allow": ["Read"]}, "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo custom"}]}]}}
        settings.write_text(json.dumps(original), encoding="utf-8")
        before = settings.read_bytes()
        self.install("--skills", "api-test-generator")
        self.assertEqual(len(list((self.repo / ".claude" / "commands").glob("*.md"))), 5)
        data = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(data["permissions"], original["permissions"])
        self.assertEqual(data["hooks"]["SessionStart"][0], original["hooks"]["SessionStart"][0])
        self.assertEqual(len(data["hooks"]["SessionStart"]), 2)
        backups = list((self.repo / ".qa-kit" / "backups").glob("*/.claude/settings.local.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)
        self.assertTrue((self.repo / "CLAUDE.md").is_file())
        self.assertFalse((self.repo / "AGENTS.md").exists())

    def test_dry_run_preserves_every_file_and_directory(self):
        agents = self.repo / "AGENTS.md"
        agents.write_text("Project-owned instructions\n", encoding="utf-8")
        before = self.snapshot(self.repo)
        self.install("--agent", "codex", "--dry-run", "--update")
        self.assertEqual(self.snapshot(self.repo), before)

    def test_custom_instructions_and_colliding_workflow_are_untouched(self):
        agents = self.repo / "AGENTS.md"
        agents.write_text("Project-owned instructions\n", encoding="utf-8")
        collision = self.make_skill(self.repo / ".agents" / "skills", "qa-project-audit", "Project-owned workflow")
        custom = self.make_skill(self.repo / ".agents" / "skills", "qa-team-internal", "Independent workflow")
        before = collision.joinpath("SKILL.md").read_bytes()
        self.install("--agent", "codex")
        self.assertEqual(agents.read_text(encoding="utf-8"), "Project-owned instructions\n")
        self.assertEqual((collision / "SKILL.md").read_bytes(), before)
        self.assertTrue((custom / "SKILL.md").is_file())
        for path in ("AGENTS.md", ".agents/skills/qa-project-audit/SKILL.md", ".agents/skills/qa-team-internal/SKILL.md"):
            result = subprocess.run(["git", "-C", str(self.repo), "check-ignore", "-q", path])
            self.assertEqual(result.returncode, 1, f"Чужой путь скрыт exclude: {path}")

    def test_update_backs_up_old_skill_and_preserves_extra_user_files(self):
        self.install("--agent", "codex", "--skills", "api-test-generator")
        skill = self.repo / ".agents" / "skills" / "api-test-generator"
        (skill / "SKILL.md").write_text("Local modifications\n", encoding="utf-8")
        (skill / "my-example.txt").write_text("Keep me\n", encoding="utf-8")
        self.install("--agent", "codex", "--skills", "api-test-generator", "--update")
        self.assertEqual((skill / "SKILL.md").read_bytes(), (self.kit / "skills" / "api-test-generator" / "SKILL.md").read_bytes())
        self.assertEqual((skill / "my-example.txt").read_text(encoding="utf-8"), "Keep me\n")
        old = list((self.repo / ".qa-kit" / "backups").glob("*/.agents/skills/api-test-generator/SKILL.md"))
        self.assertEqual(len(old), 1)
        self.assertEqual(old[0].read_text(encoding="utf-8"), "Local modifications\n")

    def test_update_guidance_preserves_custom_prefix_and_takes_backup(self):
        agents = self.repo / "AGENTS.md"
        agents.write_text("Team instructions\n", encoding="utf-8")
        self.install("--agent", "codex", "--update")
        self.assertTrue(agents.read_text(encoding="utf-8").startswith("Team instructions\n"))
        backups = list((self.repo / ".qa-kit" / "backups").glob("*/AGENTS.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "Team instructions\n")

    def test_external_pack_cannot_replace_bundled_style(self):
        external = self.root / "external"
        self.make_skill(external, "external-helper", "External skill")
        self.make_skill(external, "qa-project-style", "Competing style")
        self.install("--agent", "codex", "--skills-from", str(external), "--skills", "external-helper")
        skills = self.repo / ".agents" / "skills"
        self.assertTrue((skills / "external-helper" / "SKILL.md").is_file())
        self.assertFalse((skills / "api-test-generator").exists())
        self.assertEqual((skills / "qa-project-style" / "SKILL.md").read_bytes(), (self.kit / "skills" / "qa-project-style" / "SKILL.md").read_bytes())

    def test_invalid_selection_fails_without_changes(self):
        before = self.snapshot(self.repo)
        self.install("--agent", "codex", "--skills", "does-not-exist", expected=2)
        self.assertEqual(self.snapshot(self.repo), before)

    def test_codex_exclude_is_specific_and_idempotent(self):
        self.install("--agent", "codex", "--skills", "qa-project-style")
        excluded = self.repo / ".git" / "info" / "exclude"
        before = excluded.read_bytes()
        self.install("--agent", "codex", "--skills", "qa-project-style")
        self.assertEqual(excluded.read_bytes(), before)
        self.assertEqual(self.git("check-ignore", "AGENTS.md").stdout.strip(), "AGENTS.md")
        (self.repo / ".agents" / "unrelated.txt").write_text("team", encoding="utf-8")
        result = subprocess.run(["git", "-C", str(self.repo), "check-ignore", "-q", ".agents/unrelated.txt"])
        self.assertEqual(result.returncode, 1)

    def test_worktree_uses_git_resolved_exclude_and_local_backup(self):
        self.git("-c", "user.name=QA Kit Test", "-c", "user.email=qa-kit@example.invalid", "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "Temporary test root")
        worktree = self.root / "worktree"
        self.git("worktree", "add", "-q", "-b", "qa-test", str(worktree))
        self.install("--agent", "codex", "--skills", "qa-project-style", repo=worktree)
        self.assertEqual(self.git("check-ignore", "AGENTS.md", repo=worktree).stdout.strip(), "AGENTS.md")
        self.assertTrue(any((worktree / ".qa-kit" / "backups").glob("*/git-info-exclude")))

    def symlink(self, target, link):
        try:
            link.symlink_to(target, target_is_directory=target.is_dir())
        except OSError as exc:
            if os.name == "nt" and target.is_dir():
                result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
                if result.returncode == 0:
                    return
            self.skipTest(f"Создание symlink недоступно: {exc}")

    def test_linked_destination_is_refused_without_external_writes(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("Original", encoding="utf-8")
        self.symlink(outside, self.repo / ".agents")
        before = self.snapshot(outside)
        self.install("--agent", "codex", "--update", expected=2)
        self.assertEqual(self.snapshot(outside), before)

    def test_link_inside_existing_skill_is_refused_on_update(self):
        skill = self.make_skill(self.repo / ".agents" / "skills", "api-test-generator", "Local custom skill")
        outside = self.root / "outside"
        outside.mkdir()
        self.symlink(outside, skill / "references")
        before = (skill / "SKILL.md").read_bytes()
        self.install("--agent", "codex", "--skills", "api-test-generator", "--update", expected=2)
        self.assertEqual((skill / "SKILL.md").read_bytes(), before)
        self.assertEqual(list(outside.iterdir()), [])

    def test_linked_source_asset_is_refused(self):
        external = self.root / "external"
        skill = self.make_skill(external, "external-helper", "External skill")
        outside = self.root / "outside"
        outside.mkdir()
        self.symlink(outside, skill / "assets")
        self.install("--agent", "codex", "--skills-from", str(external), "--skills", "external-helper", expected=2)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.repo / ".agents" / "skills" / "external-helper").exists())

    def test_malformed_guidance_markers_preserve_original(self):
        agents = self.repo / "AGENTS.md"
        original = "<!-- qa-agent-kit:end -->\nTeam rules\n<!-- qa-agent-kit:begin -->\n"
        agents.write_text(original, encoding="utf-8")
        self.install("--agent", "codex", "--update", expected=2)
        self.assertEqual(agents.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
