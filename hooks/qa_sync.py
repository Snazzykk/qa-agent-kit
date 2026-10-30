#!/usr/bin/env python3
"""SessionStart-хук qa-agent-kit: подтягивает свежий код QA-репозитория в начале сессии.

Что делает:
  1. git fetch (не чаще раза в 10 минут).
  2. Вы на master/main, правок нет, на сервере есть новое: git pull --ff-only.
  3. Сообщает вам и агенту одну строку статуса и предупреждения (правки мешают, нет сети, ветка отстаёт).

Ветки не создаёт и не переключает, ничего не коммитит и не отправляет (рабочую ветку создаёт /gen).
Отключить: переменная QA_KIT_NO_SYNC=1. Всегда завершается с кодом 0.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

TAG = "[qa-agent-kit sync]"
THROTTLE_SECONDS = 600
TIMEOUT = 20


def git(repo: Path, *args: str, timeout: int = 30) -> tuple[int, str]:
    try:
        res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=timeout)
        return res.returncode, (res.stdout or "").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 1, ""


def count(repo: Path, rng: str) -> int:
    rc, out = git(repo, "rev-list", "--count", rng)
    return int(out) if rc == 0 and out.isdigit() else 0


def base_branch(repo: Path) -> str | None:
    rc, out = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if rc == 0 and out.startswith("origin/"):
        return out[len("origin/"):]
    for cand in ("master", "main"):
        if git(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{cand}")[0] == 0:
            return cand
    return None


def fetch(repo: Path) -> bool:
    """False, если fetch не удался. Недавний успешный fetch повторно не делаем."""
    stamp = repo / ".qa-kit" / "last_sync"
    try:
        if stamp.is_file() and time.time() - stamp.stat().st_mtime < THROTTLE_SECONDS:
            return True
    except OSError:
        pass
    if git(repo, "fetch", "--prune", "origin", timeout=TIMEOUT)[0] != 0:
        return False
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(str(int(time.time())), encoding="utf-8")
    except OSError:
        pass
    return True


def check(repo: Path) -> tuple[str, list[str]]:
    """Возвращает (строка статуса, предупреждения)."""
    warns: list[str] = []
    if not fetch(repo):
        warns.append("не удалось связаться с удалённым репозиторием (нет сети или доступа), "
                     "статус построен по последним известным данным")
    base = base_branch(repo)
    branch = git(repo, "branch", "--show-current")[1]
    if not branch:
        return "репозиторий не на ветке (detached HEAD)", warns
    if base is None:
        return f"ветка {branch}, основную ветку определить не удалось", warns

    rc, status = git(repo, "status", "--porcelain")
    dirty = rc == 0 and any(l and not l.startswith("??") for l in status.splitlines())

    if branch == base:
        behind = count(repo, f"HEAD..origin/{base}")
        line = f"вы на основной ветке {base}; рабочую ветку для тестов создаст /gen"
        if behind == 0:
            return f"{line}; она актуальна", warns
        if dirty:
            warns.append(f"{base} отстаёт от origin на {behind} коммит(ов), но есть ваши правки: не подтягивал")
            return line, warns
        if git(repo, "pull", "--ff-only", "origin", base, timeout=TIMEOUT * 2)[0] == 0:
            return f"{line}; подтянуто {behind} коммит(ов)", warns
        warns.append(f"{base} отстаёт на {behind} коммит(ов), подтянуть без слияния не вышло: сделайте git pull")
        return line, warns

    behind = count(repo, f"{branch}..origin/{base}")
    if behind:
        warns.append(f"ветка {branch} отстаёт от origin/{base} на {behind} коммит(ов) "
                     f"(git merge origin/{base} или rebase делаете вы)")
    return f"ветка {branch}" + (" (есть незакоммиченные правки)" if dirty else ""), warns


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if os.environ.get("QA_KIT_NO_SYNC"):
        return 0
    try:
        sys.stdin.read()
    except Exception:
        pass
    try:
        rc, top = git(Path.cwd(), "rev-parse", "--show-toplevel")
        if rc != 0 or not top:
            return 0
        status, warns = check(Path(top))
    except Exception as exc:  # хук не должен ломать запуск сессии
        status, warns = "", [f"синхронизация прервалась: {exc}"]

    lines = ([f"qa-agent-kit: {status}"] if status else []) + [f"qa-agent-kit: ВНИМАНИЕ: {w}" for w in warns]
    if not lines:
        return 0
    context = f"{TAG} состояние репозитория на старте сессии:\n" + "\n".join(f"- {l}" for l in lines)
    if warns:
        context += "\nСообщи пользователю о предупреждениях в первой реплике, коротко."
    print(json.dumps({"systemMessage": "\n".join(lines),
                      "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}},
                     ensure_ascii=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BaseException:
        sys.exit(0)
