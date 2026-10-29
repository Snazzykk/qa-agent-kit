#!/usr/bin/env python3
"""Подключает qa-agent-kit к QA-репозиторию. Только стандартная библиотека Python 3.10+.

Что делает:
  1. Кладёт команды комплекта в <qa_repo>/.claude/commands/.
  2. Кладёт скиллы в <qa_repo>/.claude/skills/ (источник: --skills-from, см. README).
  3. Добавляет правила в CLAUDE.md (внутри маркеров; ваш текст не трогает).
  4. Создаёт project.yml и features/_brief-template.md, если их нет (существующие не перезаписывает).
  5. Добавляет служебные пути в .git/info/exclude, чтобы они не попали в коммиты.

Чего не делает: не запускает Claude, не клонирует репо разработки (это делает /audit), не трогает
.mcp.json и ~/.claude/, не делает commit.

Примеры:
  python setup_project.py C:\\work\\my-qa-tests
  python setup_project.py . --dry-run
  python setup_project.py . --skills-from C:\\Users\\me\\qa-skills --update
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
BEGIN = "<!-- qa-agent-kit:begin -->"
END = "<!-- qa-agent-kit:end -->"
IGNORE_NAMES = {"__pycache__", ".DS_Store"}
EXCLUDE_ENTRIES = [
    ".claude/",
    "CLAUDE.md",
    "project.yml",
    "artifacts/",
    "features/",
    ".qa-kit/",
    "docs/test-plan.md",
    "docs/gap-report.md",
    "docs/automation-plan.md",
]


class Report:
    """Собирает строки итога, чтобы показать их одним списком в конце."""

    def __init__(self) -> None:
        self.done: list[str] = []
        self.skipped: list[str] = []
        self.warnings: list[str] = []

    def add(self, line: str) -> None:
        self.done.append(line)

    def skip(self, line: str) -> None:
        self.skipped.append(line)

    def warn(self, line: str) -> None:
        self.warnings.append(line)


def say(text: str = "") -> None:
    print(text)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess | None:
    """Запускает git в репозитории; None, если git не установлен."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def is_git_repo(repo: Path) -> bool:
    res = git(repo, "rev-parse", "--git-dir")
    return res is not None and res.returncode == 0


def is_tracked(repo: Path, rel: str) -> bool:
    res = git(repo, "ls-files", "--error-unmatch", rel)
    return res is not None and res.returncode == 0


def find_skills_source(explicit: str | None) -> Path | None:
    """Где лежат скиллы: --skills-from, переменная QA_KIT_SKILLS, <kit>/skills, ~/qa-skills."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env = os.environ.get("QA_KIT_SKILLS")
    if env:
        candidates.append(Path(env).expanduser())
    candidates += [KIT / "skills", Path.home() / "qa-skills"]
    for cand in candidates:
        if cand.is_dir() and any((d / "SKILL.md").is_file() for d in cand.iterdir() if d.is_dir()):
            return cand
    return None


def same_content(a: Path, b: Path) -> bool:
    if a.is_file() and b.is_file():
        return a.read_bytes() == b.read_bytes()
    if a.is_dir() and b.is_dir():
        names_a = sorted(p.relative_to(a).as_posix() for p in a.rglob("*") if p.is_file() and not _ignored(p, a))
        names_b = sorted(p.relative_to(b).as_posix() for p in b.rglob("*") if p.is_file() and not _ignored(p, b))
        if names_a != names_b:
            return False
        return all((a / n).read_bytes() == (b / n).read_bytes() for n in names_a)
    return False


def _ignored(path: Path, root: Path) -> bool:
    return any(part in IGNORE_NAMES for part in path.relative_to(root).parts)


def copy_item(src: Path, dst: Path, update: bool, dry: bool, rep: Report, label: str) -> None:
    """Копирует файл или папку. Существующее и отличающееся трогает только с --update."""
    if dst.exists():
        if same_content(src, dst):
            rep.skip(f"{label}: уже актуально")
            return
        if not update:
            rep.skip(f"{label}: отличается от комплекта, не тронуто (--update, чтобы обновить)")
            return
    action = "обновлено" if dst.exists() else "добавлено"
    if not dry:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*IGNORE_NAMES))
        else:
            shutil.copy2(src, dst)
    rep.add(f"{label}: {action}")


def install_commands(repo: Path, update: bool, dry: bool, rep: Report) -> None:
    src_dir = KIT / "commands"
    for src in sorted(src_dir.glob("*.md")):
        copy_item(src, repo / ".claude" / "commands" / src.name, update, dry, rep, f"команда /{src.stem}")


def install_skills(repo: Path, skills_src: Path | None, update: bool, dry: bool, rep: Report) -> None:
    if skills_src is None:
        rep.warn(
            "Скиллы не найдены (см. README, раздел «Скиллы»). Команды без них будут работать хуже. "
            "Укажите --skills-from <папка> или переменную QA_KIT_SKILLS."
        )
        return
    count = 0
    for src in sorted(p for p in skills_src.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()):
        copy_item(src, repo / ".claude" / "skills" / src.name, update, dry, rep, f"скилл {src.name}")
        count += 1
    rep.add(f"скиллы взяты из: {skills_src} ({count} шт.)")


def install_claude_md(repo: Path, update: bool, dry: bool, rep: Report) -> None:
    tpl = (KIT / "templates" / "CLAUDE.md.tpl").read_text(encoding="utf-8").strip()
    block = f"{BEGIN}\n{tpl}\n{END}\n"
    target = repo / "CLAUDE.md"

    if not target.exists():
        if not dry:
            target.write_text(block, encoding="utf-8")
        rep.add("CLAUDE.md: создан с правилами комплекта")
        return

    text = target.read_text(encoding="utf-8")
    if BEGIN in text and END in text:
        head, rest = text.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
        new_text = head + block.rstrip("\n") + tail
        if new_text == text:
            rep.skip("CLAUDE.md: блок комплекта уже актуален")
            return
        if not update:
            rep.skip("CLAUDE.md: блок комплекта устарел, не тронут (--update, чтобы обновить)")
            return
        if not dry:
            target.write_text(new_text, encoding="utf-8")
        rep.add("CLAUDE.md: блок комплекта обновлён (остальной текст не тронут)")
        return

    # В файле есть чужой текст, нашего блока нет: допишем в конец.
    if is_tracked(repo, "CLAUDE.md") and not update:
        rep.warn(
            "CLAUDE.md уже есть в git. Дописывание правил создаст изменение в отслеживаемом файле. "
            "Не сделано. Запустите с --update, если это нужно, либо добавьте блок вручную."
        )
        return
    if not dry:
        target.write_text(text.rstrip("\n") + "\n\n" + block, encoding="utf-8")
    rep.add("CLAUDE.md: правила комплекта дописаны в конец (ваш текст сохранён)")


def install_templates(repo: Path, dry: bool, rep: Report) -> None:
    items = [
        (KIT / "templates" / "project.yml", repo / "project.yml", "project.yml"),
        (KIT / "templates" / "feature-brief.md", repo / "features" / "_brief-template.md",
         "features/_brief-template.md"),
    ]
    for src, dst, label in items:
        if dst.exists():
            rep.skip(f"{label}: уже есть, не перезаписан")
            continue
        if not dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        rep.add(f"{label}: создан (заполните)")


def ensure_context_dir(repo: Path, dry: bool, rep: Report) -> None:
    """Папка для файлов с контекстом (ТЗ, спецификации, HAR); исключена из git через .qa-kit/."""
    ctx = repo / ".qa-kit" / "context"
    if ctx.is_dir():
        rep.skip(".qa-kit/context/: уже есть")
        return
    if not dry:
        ctx.mkdir(parents=True, exist_ok=True)
    rep.add(".qa-kit/context/: создана (сюда кладите ТЗ, спецификации, коллекции, HAR; в git не попадёт)")


HOOK_MARK = "qa_sync.py"


def install_hook(repo: Path, update: bool, dry: bool, rep: Report) -> None:
    """Хук SessionStart: при старте сессии подтягивает свежую версию репозитория и комплекта."""
    copy_item(KIT / "hooks" / "qa_sync.py", repo / ".claude" / "hooks" / "qa_sync.py",
              update, dry, rep, "хук qa_sync.py")

    # Путь к комплекту: хук по нему проверяет, не вышла ли новая версия комплекта.
    kit_file = repo / ".qa-kit" / "kit_path"
    if not kit_file.exists() or kit_file.read_text(encoding="utf-8").strip() != str(KIT):
        if not dry:
            kit_file.parent.mkdir(parents=True, exist_ok=True)
            kit_file.write_text(str(KIT), encoding="utf-8")
        rep.add(".qa-kit/kit_path: записан путь к комплекту (для автообновления комплекта)")

    settings = repo / ".claude" / "settings.local.json"
    data: dict = {}
    if settings.exists():
        try:
            loaded = json.loads(settings.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            rep.warn(".claude/settings.local.json содержит некорректный JSON: хук SessionStart не подключён. "
                     "Исправьте файл и запустите скрипт снова.")
            return
        if not isinstance(loaded, dict) or not isinstance(loaded.get("hooks", {}), dict):
            rep.warn(".claude/settings.local.json имеет неожиданную структуру: хук SessionStart не подключён.")
            return
        data = loaded

    session_start = data.setdefault("hooks", {}).setdefault("SessionStart", [])
    for entry in session_start:
        for hook in entry.get("hooks", []) if isinstance(entry, dict) else []:
            if HOOK_MARK in str(hook.get("command", "")):
                rep.skip("settings.local.json: хук SessionStart уже подключён")
                return
    if settings.exists() and is_tracked(repo, ".claude/settings.local.json") and not update:
        rep.warn(".claude/settings.local.json уже в git: подключение хука изменило бы отслеживаемый файл. "
                 "Не сделано. Запустите с --update или добавьте хук вручную (см. docs/GUIDE.md).")
        return

    py = "python" if shutil.which("python") else ("python3" if shutil.which("python3") else "python")
    session_start.append({"hooks": [{
        "type": "command",
        "command": f"{py} .claude/hooks/qa_sync.py",
        "timeout": 60,
        "statusMessage": "qa-agent-kit: проверка свежести репозитория...",
    }]})
    if not dry:
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rep.add("settings.local.json: подключён хук SessionStart (автообновление при старте сессии)")


def update_exclude(repo: Path, dry: bool, rep: Report) -> None:
    if not is_git_repo(repo):
        rep.warn("Это не git-репозиторий (или git не найден): .git/info/exclude не обновлён.")
        return
    res = git(repo, "rev-parse", "--git-path", "info/exclude")
    if res is None or res.returncode != 0 or not res.stdout.strip():
        rep.warn("Не удалось определить .git/info/exclude, служебные пути в exclude не добавлены.")
        return
    path = Path(res.stdout.strip())
    if not path.is_absolute():
        path = repo / path
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    missing = [e for e in EXCLUDE_ENTRIES if e not in existing]
    if not missing:
        rep.skip(".git/info/exclude: уже содержит нужные пути")
        return
    if not dry:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            if existing and existing[-1] != "":
                fh.write("\n")
            fh.write("# qa-agent-kit (служебное, локально)\n")
            fh.write("\n".join(missing) + "\n")
    rep.add(f".git/info/exclude: добавлено {len(missing)} путей (в коммиты не попадут)")
    tracked = [e.rstrip("/") for e in EXCLUDE_ENTRIES if is_tracked(repo, e.rstrip("/"))]
    if tracked:
        rep.warn(
            "Эти пути уже отслеживаются git, exclude на них не действует: " + ", ".join(tracked) + ". "
            "Если это пак, который не должен лежать в репозитории, уберите его из индекса вручную "
            "(git rm -r --cached <путь>), я этого не делаю."
        )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="Подключить qa-agent-kit к QA-репозиторию.")
    ap.add_argument("qa_repo", help="путь к QA-репозиторию (корень), куда подключаем комплект")
    ap.add_argument("--skills-from", help="папка со скиллами (по умолчанию: $QA_KIT_SKILLS, <kit>/skills, ~/qa-skills)")
    ap.add_argument("--update", action="store_true", help="обновить уже установленные команды, скиллы и блок CLAUDE.md")
    ap.add_argument("--no-hook", action="store_true", help="не подключать автообновление при старте сессии (хук)")
    ap.add_argument("--no-exclude", action="store_true", help="не трогать .git/info/exclude")
    ap.add_argument("--dry-run", action="store_true", help="только показать, что будет сделано, ничего не менять")
    args = ap.parse_args()

    repo = Path(args.qa_repo).expanduser().resolve()
    if not repo.is_dir():
        say(f"Ошибка: папка не найдена: {repo}")
        return 2
    if repo == KIT:
        say("Ошибка: нельзя подключать комплект к самому себе. Укажите путь к QA-репозиторию.")
        return 2

    rep = Report()
    skills_src = find_skills_source(args.skills_from)

    say(f"QA-репозиторий: {repo}")
    say(f"Режим: {'ПРОБНЫЙ (ничего не меняется)' if args.dry_run else 'установка'}")
    say()

    install_commands(repo, args.update, args.dry_run, rep)
    install_skills(repo, skills_src, args.update, args.dry_run, rep)
    install_claude_md(repo, args.update, args.dry_run, rep)
    install_templates(repo, args.dry_run, rep)
    ensure_context_dir(repo, args.dry_run, rep)
    if not args.no_hook:
        install_hook(repo, args.update, args.dry_run, rep)
    if not args.no_exclude:
        update_exclude(repo, args.dry_run, rep)

    if rep.done:
        say("Сделано:")
        for line in rep.done:
            say(f"  + {line}")
    if rep.skipped:
        say("Пропущено:")
        for line in rep.skipped:
            say(f"  - {line}")
    if rep.warnings:
        say("Обратите внимание:")
        for line in rep.warnings:
            say(f"  ! {line}")

    say()
    say("Дальше:")
    say("  1. Заполните project.yml (минимум: dev_repo ИЛИ источник в sources/requirements).")
    say("  2. Если нужны Confluence/Jira, добавьте MCP в .mcp.json вручную (см. README).")
    say("  3. Откройте claude в этом репозитории и напишите /audit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
