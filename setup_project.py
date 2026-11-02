#!/usr/bin/env python3
"""Подключает qa-agent-kit к QA-репозиторию. Только стандартная библиотека Python 3.10+.

Что делает:
  1. Для Claude ставит commands/skills в .claude/; --agent codex ставит skills в .agents/skills/.
  2. Копирует выбранные технические скиллы и личный образец qa-project-style.
  3. Добавляет правила в CLAUDE.md или AGENTS.md (внутри маркеров, с сохранением вашего текста).
  4. Создаёт project.yml и features/_brief-template.md, если их нет (существующие не перезаписывает).
  5. Добавляет служебные пути в .git/info/exclude, чтобы они не попали в коммиты.

Чего не делает: не запускает агента, не клонирует репо разработки, не меняет MCP, глобальные
настройки или авторизацию. Обновлённые файлы сохраняются в .qa-kit/backups/.

Примеры:
  python setup_project.py C:\\work\\my-qa-tests
  python setup_project.py . --dry-run
  python setup_project.py . --agent codex --skills qa-project-style,source-aware-test-gen
  python setup_project.py . --skills-from C:\\Users\\me\\qa-skills --update
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

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
    "docs/automation-plan.md",
]
WORKFLOWS = {
    "audit": ("qa-project-audit", "Разведка QA-репозитория и источников продукта без генерации тестов."),
    "plan": ("qa-test-plan", "Подготовка плана автоматизации по контексту QA-проекта."),
    "feature": ("qa-feature-cases", "Разбор новой фичи и подготовка кейсов на утверждение."),
    "gen": ("qa-test-generation", "Генерация автотестов по утверждённому плану или кейсам фичи."),
    "triage": ("qa-test-triage", "Разбор падений, нестабильных тестов и влияния изменений в QA-проекте."),
}
STYLE_SKILL = "qa-project-style"


class InstallError(Exception):
    """Установка остановлена до записи по небезопасному пути."""


class Report:
    """Собирает строки итога, чтобы показать их одним списком в конце."""

    def __init__(self, repo: Path | None = None) -> None:
        self.done: list[str] = []
        self.skipped: list[str] = []
        self.warnings: list[str] = []
        self.repo = repo
        self.backup_root: Path | None = None

    def add(self, line: str) -> None:
        self.done.append(line)

    def skip(self, line: str) -> None:
        self.skipped.append(line)

    def warn(self, line: str) -> None:
        self.warnings.append(line)


def say(text: str = "") -> None:
    print(text)


def _is_link(path: Path) -> bool:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return True
    if os.name == "nt" and path.exists():
        return bool(getattr(path.lstat(), "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    return False


def _check_path(path: Path) -> None:
    """Не разрешаем links/junctions в самом пути или существующих родителях."""
    for item in reversed((path, *path.parents)):
        if _is_link(item):
            raise InstallError(f"Путь содержит symlink/junction, не изменён: {item}")


def _check_tree(path: Path) -> None:
    _check_path(path)
    if not path.exists():
        return
    if not path.is_dir():
        if not path.is_file():
            raise InstallError(f"Ожидался обычный файл или папка: {path}")
        return
    for folder, directories, files in os.walk(path, followlinks=False):
        directories[:] = [name for name in directories if name not in IGNORE_NAMES]
        for name in (*directories, *files):
            if name in IGNORE_NAMES:
                continue
            child = Path(folder) / name
            if _is_link(child):
                raise InstallError(f"Папка содержит symlink/junction, не изменена: {child}")


def _guard_target(target: Path, rep: Report) -> None:
    if rep.repo is not None and not target.is_relative_to(rep.repo):
        raise InstallError(f"Путь записи выходит из QA-репозитория: {target}")
    _check_path(target)


def _backup(target: Path, dry: bool, rep: Report, *, external_label: str | None = None) -> None:
    if dry or not target.exists():
        return
    _check_tree(target)
    if rep.repo is None:
        raise InstallError("Для резервной копии требуется корень QA-репозитория")
    if rep.backup_root is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
        rep.backup_root = rep.repo / ".qa-kit" / "backups" / stamp
    relative = Path(external_label) if external_label else target.relative_to(rep.repo)
    destination = rep.backup_root / relative
    _guard_target(destination, rep)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if target.is_dir():
        shutil.copytree(target, destination, ignore=shutil.ignore_patterns(*IGNORE_NAMES))
    else:
        shutil.copy2(target, destination)


def write_item(target: Path, content: str, update: bool, dry: bool, rep: Report, label: str) -> bool:
    _guard_target(target, rep)
    if target.exists():
        if not target.is_file():
            raise InstallError(f"Ожидался обычный файл: {target}")
        if target.read_text(encoding="utf-8") == content:
            rep.skip(f"{label}: уже актуально")
            return True
        if not update:
            rep.skip(f"{label}: отличается от комплекта, не тронуто (--update, чтобы обновить)")
            return False
        _backup(target, dry, rep)
    if not dry:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    rep.add(f"{label}: записан")
    return True


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
        # Дополнительные пользовательские файлы сохраняются при обновлении.
        return all((b / n).is_file() and (a / n).read_bytes() == (b / n).read_bytes() for n in names_a)
    return False


def _ignored(path: Path, root: Path) -> bool:
    return any(part in IGNORE_NAMES for part in path.relative_to(root).parts)


def copy_item(src: Path, dst: Path, update: bool, dry: bool, rep: Report, label: str) -> bool:
    """Копирует файл или папку. Существующее и отличающееся трогает только с --update."""
    _check_tree(src)
    _guard_target(dst, rep)
    _check_tree(dst)
    if dst.exists():
        if same_content(src, dst):
            rep.skip(f"{label}: уже актуально")
            return True
        if not update:
            rep.skip(f"{label}: отличается от комплекта, не тронуто (--update, чтобы обновить)")
            return False
        if src.is_dir() != dst.is_dir():
            raise InstallError(f"Тип существующего пути отличается, не изменён: {dst}")
        _backup(dst, dry, rep)
    action = "обновлено" if dst.exists() else "добавлено"
    if not dry:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*IGNORE_NAMES))
        else:
            shutil.copy2(src, dst)
    rep.add(f"{label}: {action}")
    return True


def install_commands(repo: Path, update: bool, dry: bool, rep: Report) -> None:
    src_dir = KIT / "commands"
    for src in sorted(src_dir.glob("*.md")):
        copy_item(src, repo / ".claude" / "commands" / src.name, update, dry, rep, f"команда /{src.stem}")


def codex_text(text: str) -> str:
    """Адаптирует общие инструкции, сохраняя один источник workflow-текстов."""
    text = text.replace("CLAUDE.md", "AGENTS.md")
    text = text.replace(".claude/commands", ".agents/skills").replace(".claude/skills", ".agents/skills")
    text = text.replace("проверь по `.mcp.json`", "проверь доступные MCP-инструменты сессии")
    text = text.replace("`.mcp.json`", "настройки MCP Codex").replace(".mcp.json", "настройки MCP Codex")
    text = text.replace("$ARGUMENTS", "уточнения из текущего запроса пользователя")
    text = text.replace("Claude Code", "Codex")
    for stage, (name, _) in WORKFLOWS.items():
        text = re.sub(rf"(?<![\w:/])/{stage}\b", lambda match, value=name: "$" + value, text)
    return text


def install_codex_workflows(repo: Path, update: bool, dry: bool, rep: Report) -> list[str]:
    installed = []
    for stage, (name, description) in WORKFLOWS.items():
        source = KIT / "commands" / f"{stage}.md"
        _check_tree(source)
        body = re.sub(r"\A---\r?\n[\s\S]*?\r?\n---\r?\n", "", source.read_text(encoding="utf-8"))
        text = (f"---\nname: {name}\ndescription: {json.dumps(description, ensure_ascii=False)}\n---\n\n"
                "Прочитай `AGENTS.md` этого QA-репозитория. Аргументы этапа бери из текущего запроса.\n\n"
                + codex_text(body).strip() + "\n")
        target = repo / ".agents" / "skills" / name / "SKILL.md"
        if write_item(target, text, update, dry, rep, f"workflow ${name}"):
            installed.append(name)
    return installed


def skill_sources(skills_src: Path | None, selected: set[str] | None) -> dict[str, Path]:
    sources = {}
    if skills_src is not None:
        _check_path(skills_src)
        sources = {p.name: p for p in skills_src.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()}
    style = KIT / "skills" / STYLE_SKILL
    if not (style / "SKILL.md").is_file():
        raise InstallError(f"В комплекте отсутствует обязательный скилл {STYLE_SKILL}")
    sources[STYLE_SKILL] = style
    if selected is not None:
        missing = selected - sources.keys()
        if missing:
            raise InstallError("Скиллы не найдены: " + ", ".join(sorted(missing)))
        sources = {name: path for name, path in sources.items() if name in selected or name == STYLE_SKILL}
    collisions = set(sources) & {name for name, _ in WORKFLOWS.values()}
    if collisions:
        raise InstallError("Имена скиллов зарезервированы для этапов комплекта: " + ", ".join(sorted(collisions)))
    return sources


def install_skills(repo: Path, skills_src: Path | None, update: bool, dry: bool, rep: Report,
                   agent: str = "claude", selected: set[str] | None = None) -> list[str]:
    if skills_src is None:
        rep.warn(
            "Скиллы не найдены (см. README, раздел «Скиллы»). Команды без них будут работать хуже. "
            "Укажите --skills-from <папка> или переменную QA_KIT_SKILLS."
        )
    installed = []
    folder = ".agents" if agent == "codex" else ".claude"
    for name, source in sorted(skill_sources(skills_src, selected).items()):
        if copy_item(source, repo / folder / "skills" / name, update, dry, rep, f"скилл {name}"):
            installed.append(name)
    rep.add(f"технические скиллы: {len(installed)} шт.; личный образец берётся из комплекта")
    return installed


def install_claude_md(repo: Path, update: bool, dry: bool, rep: Report, agent: str = "claude") -> bool:
    tpl = (KIT / "templates" / "CLAUDE.md.tpl").read_text(encoding="utf-8").strip()
    if agent == "codex":
        tpl = re.sub(r"^## Ветки и свежесть репозитория\n[\s\S]*?(?=^## |\Z)", "", tpl, flags=re.MULTILINE)
        tpl = codex_text(tpl)
        tpl += ("\n\n## Работа в Codex\n\n"
                "В начале новой сессии прочитай `project.yml` и существующий `artifacts/qa-profile.json`; "
                "для продолжения фичи — её brief и cases. Перед генерацией открой ближайшие образцы "
                "тестов и их фикстуры, клиентов и assertions. Для выбора образцов, проверки стиля и "
                "каркаса проекта без тестов используй `$qa-project-style`. "
                "Общие сведения о стиле дополняй в `style_profile` того же QA-профиля.\n\n"
                "Этапы доступны как `$qa-project-audit`, `$qa-test-plan`, `$qa-feature-cases`, "
                "`$qa-test-generation`, `$qa-test-triage`. Это skills, а не нативные slash-команды Codex. "
                "Проверь текущий `git status` и изменения в релевантных исходниках перед продолжением.\n")
    block = f"{BEGIN}\n{tpl}\n{END}\n"
    target = repo / ("AGENTS.md" if agent == "codex" else "CLAUDE.md")
    label = target.name
    _guard_target(target, rep)

    if not target.exists():
        if not dry:
            target.write_text(block, encoding="utf-8")
        rep.add(f"{label}: создан с правилами комплекта")
        return True

    text = target.read_text(encoding="utf-8")
    if (text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1
            or (BEGIN in text and text.index(BEGIN) > text.index(END))):
        raise InstallError(f"Некорректные маркеры комплекта в {label}: файл не изменён")
    if BEGIN in text and END in text:
        head, rest = text.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
        new_text = head + block.rstrip("\n") + tail
        if new_text == text:
            rep.skip(f"{label}: блок комплекта уже актуален")
            return True
        if not update:
            rep.skip(f"{label}: блок комплекта устарел, не тронут (--update, чтобы обновить)")
            return False
        _backup(target, dry, rep)
        if not dry:
            target.write_text(new_text, encoding="utf-8")
        rep.add(f"{label}: блок комплекта обновлён (остальной текст не тронут)")
        return True

    # В файле есть чужой текст, нашего блока нет: допишем в конец.
    if (agent == "codex" or is_tracked(repo, label)) and not update:
        rep.warn(
            f"{label} уже существует. Правила проекта сохранены без изменений. "
            "Не сделано. Запустите с --update, если это нужно, либо добавьте блок вручную."
        )
        return False
    _backup(target, dry, rep)
    if not dry:
        target.write_text(text.rstrip("\n") + "\n\n" + block, encoding="utf-8")
    rep.add(f"{label}: правила комплекта дописаны в конец (ваш текст сохранён)")
    return True


def install_templates(repo: Path, dry: bool, rep: Report) -> None:
    items = [
        (KIT / "templates" / "project.yml", repo / "project.yml", "project.yml"),
        (KIT / "templates" / "feature-brief.md", repo / "features" / "_brief-template.md",
         "features/_brief-template.md"),
    ]
    for src, dst, label in items:
        _guard_target(dst, rep)
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
    _guard_target(ctx, rep)
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

    settings = repo / ".claude" / "settings.local.json"
    _guard_target(settings, rep)
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
    if not isinstance(session_start, list):
        rep.warn("SessionStart должен быть списком: существующие настройки сохранены без изменений.")
        return
    for entry in session_start:
        hooks = entry.get("hooks", []) if isinstance(entry, dict) else []
        for hook in hooks if isinstance(hooks, list) else []:
            if not isinstance(hook, dict):
                continue
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
        _backup(settings, dry, rep)
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rep.add("settings.local.json: подключён хук SessionStart (fetch и подтягивание при старте сессии)")


def update_exclude(repo: Path, dry: bool, rep: Report, agent: str = "claude",
                   installed_skills: list[str] | None = None, guidance_installed: bool = True) -> None:
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
    _check_path(path.absolute())
    entries = EXCLUDE_ENTRIES
    if agent == "codex":
        entries = [entry for entry in EXCLUDE_ENTRIES if entry not in {".claude/", "CLAUDE.md"}]
        if guidance_installed:
            entries = ["AGENTS.md", *entries]
        entries += [f".agents/skills/{name}/" for name in sorted(set(installed_skills or []))]
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    missing = [e for e in entries if e not in existing]
    tracked = [e.rstrip("/") for e in entries if is_tracked(repo, e.rstrip("/"))]
    if tracked:
        rep.warn("Эти пути уже отслеживаются git, exclude на них не действует: " + ", ".join(tracked))
    if not missing:
        rep.skip(".git/info/exclude: уже содержит нужные пути")
        return
    if not dry:
        _backup(path, dry, rep, external_label="git-info-exclude")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            if existing and existing[-1] != "":
                fh.write("\n")
            fh.write("# qa-agent-kit (служебное, локально)\n")
            fh.write("\n".join(missing) + "\n")
    rep.add(f".git/info/exclude: добавлено {len(missing)} путей (в коммиты не попадут)")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="Подключить qa-agent-kit к QA-репозиторию.")
    ap.add_argument("qa_repo", help="путь к QA-репозиторию (корень), куда подключаем комплект")
    ap.add_argument("--agent", choices=("claude", "codex"), default="claude", help="клиент агента (по умолчанию claude)")
    ap.add_argument("--skills-from", help="папка со скиллами (по умолчанию: $QA_KIT_SKILLS, <kit>/skills, ~/qa-skills)")
    ap.add_argument("--skills", help="установить только эти технические скиллы, через запятую; qa-project-style ставится всегда")
    ap.add_argument("--update", action="store_true", help="обновить установленные файлы с резервной копией в .qa-kit/backups/")
    ap.add_argument("--no-hook", action="store_true", help="не подключать хук (fetch и подтягивание при старте сессии)")
    ap.add_argument("--no-exclude", action="store_true", help="не трогать .git/info/exclude")
    ap.add_argument("--dry-run", action="store_true", help="только показать, что будет сделано, ничего не менять")
    args = ap.parse_args()

    repo = Path(os.path.abspath(Path(args.qa_repo).expanduser()))
    try:
        _check_path(repo)
    except InstallError as exc:
        say(f"Ошибка: {exc}")
        return 2
    if not repo.is_dir():
        say(f"Ошибка: папка не найдена: {repo}")
        return 2
    if repo == KIT:
        say("Ошибка: нельзя подключать комплект к самому себе. Укажите путь к QA-репозиторию.")
        return 2

    rep = Report(repo)
    skills_src = find_skills_source(args.skills_from)
    if args.skills_from and not Path(args.skills_from).expanduser().is_dir():
        say(f"Ошибка: папка со скиллами не найдена: {args.skills_from}")
        return 2
    selected = None
    if args.skills is not None:
        selected = {name.strip() for name in args.skills.split(",") if name.strip()}
        if not selected:
            say("Ошибка: --skills требует хотя бы одно имя; только личный образец: --skills qa-project-style")
            return 2
    try:
        skill_sources(skills_src, selected)
    except InstallError as exc:
        say(f"Ошибка: {exc}")
        return 2

    say(f"QA-репозиторий: {repo}")
    say(f"Режим: {'ПРОБНЫЙ (ничего не меняется)' if args.dry_run else 'установка'}")
    say()

    try:
        workflows = []
        if args.agent == "codex":
            workflows = install_codex_workflows(repo, args.update, args.dry_run, rep)
        else:
            install_commands(repo, args.update, args.dry_run, rep)
        installed = install_skills(repo, skills_src, args.update, args.dry_run, rep, args.agent, selected)
        guidance = install_claude_md(repo, args.update, args.dry_run, rep, args.agent)
        install_templates(repo, args.dry_run, rep)
        ensure_context_dir(repo, args.dry_run, rep)
        if args.agent == "claude" and not args.no_hook:
            install_hook(repo, args.update, args.dry_run, rep)
        if not args.no_exclude:
            update_exclude(repo, args.dry_run, rep, args.agent, workflows + installed, guidance)
    except (InstallError, OSError) as exc:
        say(f"Ошибка установки: {exc}")
        return 2

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
    if rep.backup_root is not None:
        say(f"Резервные копии изменённых файлов: {rep.backup_root}")

    say()
    say("Дальше:")
    say("  1. Заполните project.yml (блоки 1-4; минимум: имя и один источник в блоке 2).")
    if args.agent == "codex":
        say("  2. Подключите нужные MCP-серверы в настройках Codex, если источники требуют их.")
        say("  3. Откройте Codex в этом репозитории и вызовите $qa-project-audit")
    else:
        say("  2. Если нужны Confluence/Jira, добавьте MCP в .mcp.json вручную (см. README).")
        say("  3. Откройте claude в этом репозитории и напишите /audit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
