#!/usr/bin/env python3
"""SessionStart-хук qa-agent-kit: свежая версия QA-репозитория и комплекта в начале сессии.

Что делает (только безопасное, без слияний и перезаписи ваших изменений):
  1. git fetch в QA-репозитории (не чаще раза в 10 минут) и показывает, где вы стоите.
  2. На основной ветке (master/main): если дерево чистое и есть новые коммиты, подтягивает их
     (git pull --ff-only). Предупреждает, что работать лучше в рабочей ветке (команда /start).
  3. На рабочей ветке: сообщает, насколько она отстаёт от основной; свой upstream подтягивает
     только если дерево чистое и это fast-forward.
  4. Проверяет комплект (путь записан в .qa-kit/kit_path): если у него есть новые коммиты и дерево
     чистое, подтягивает и применяет к проекту (setup_project.py --update --no-exclude).
     Отключить: переменная QA_KIT_NO_AUTOUPDATE=1. Совсем отключить хук: QA_KIT_NO_SYNC=1.

Никогда не создаёт и не переключает ветки, не делает commit и push, не падает при отсутствии сети
(при ошибке просто сообщает об этом). Всегда завершается с кодом 0.

Вывод: JSON для Claude Code (systemMessage показывается вам, additionalContext попадает агенту).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

FETCH_TIMEOUT = 20          # секунд на один git fetch
THROTTLE_SECONDS = 600      # не обращаться к сети чаще, чем раз в 10 минут
TAG = "[qa-agent-kit sync]"


def git(repo: Path, *args: str, timeout: int = 30) -> tuple[int, str]:
    try:
        res = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
        return res.returncode, (res.stdout or "").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 1, ""


def tracked_dirty(repo: Path) -> bool:
    """Есть ли незакоммиченные изменения в отслеживаемых файлах (неотслеживаемые не считаются)."""
    rc, out = git(repo, "status", "--porcelain")
    return rc == 0 and any(line and not line.startswith("??") for line in out.splitlines())


def default_branch(repo: Path) -> str | None:
    rc, out = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if rc == 0 and out.startswith("origin/"):
        return out[len("origin/"):]
    for cand in ("master", "main"):
        rc, _ = git(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{cand}")
        if rc == 0:
            return cand
    return None


def count(repo: Path, rng: str) -> int | None:
    rc, out = git(repo, "rev-list", "--count", rng)
    return int(out) if rc == 0 and out.isdigit() else None


def throttled_fetch(repo: Path, stamp: Path) -> str:
    """Возвращает 'ok', 'skipped' (недавно уже ходили в сеть) или 'failed'."""
    try:
        if stamp.is_file() and time.time() - stamp.stat().st_mtime < THROTTLE_SECONDS:
            return "skipped"
    except OSError:
        pass
    rc, _ = git(repo, "fetch", "--prune", "origin", timeout=FETCH_TIMEOUT)
    if rc != 0:
        return "failed"
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(str(int(time.time())), encoding="utf-8")
    except OSError:
        pass
    return "ok"


def sync_qa_repo(repo: Path, notes: list[str], warns: list[str]) -> None:
    state = repo / ".qa-kit"
    fetch = throttled_fetch(repo, state / "last_sync")
    if fetch == "failed":
        warns.append("Не удалось связаться с удалённым репозиторием (нет сети или доступа): "
                     "статус ниже построен по последним известным данным.")

    base = default_branch(repo)
    rc, branch = git(repo, "branch", "--show-current")
    if rc != 0:
        return
    if not branch:
        warns.append("Репозиторий в состоянии detached HEAD (не на ветке). Для работы создайте ветку: /start <имя>.")
        return
    if base is None:
        notes.append(f"Ветка: {branch}. Основную ветку (origin/master или origin/main) определить не удалось.")
        return

    dirty = tracked_dirty(repo)

    if branch == base:
        behind = count(repo, f"HEAD..origin/{base}") or 0
        if behind > 0:
            if dirty:
                warns.append(f"Вы на основной ветке {base}, и она отстаёт от origin на {behind} коммит(ов), "
                             "но есть незакоммиченные изменения: подтягивать не стал.")
            else:
                rc, out = git(repo, "pull", "--ff-only", "origin", base, timeout=FETCH_TIMEOUT * 2)
                if rc == 0:
                    notes.append(f"Основная ветка {base} обновлена: подтянуто {behind} коммит(ов).")
                else:
                    warns.append(f"Основная ветка {base} отстаёт на {behind} коммит(ов), "
                                 "но подтянуть без слияния не получилось. Сделайте git pull вручную.")
        else:
            notes.append(f"Основная ветка {base} актуальна.")
        warns.append(f"Вы на основной ветке {base}. Работать лучше в рабочей ветке от свежей {base}: "
                     "команда /start <имя>. Тесты в основную ветку агент писать не будет.")
        return

    # рабочая ветка
    behind_base = count(repo, f"{branch}..origin/{base}") or 0
    ahead_base = count(repo, f"origin/{base}..{branch}") or 0
    if behind_base > 0:
        warns.append(f"Ветка {branch} отстаёт от origin/{base} на {behind_base} коммит(ов) "
                     f"(впереди на {ahead_base}). Если нужна свежая основа: git merge origin/{base} "
                     "или git rebase (я сам этого не делаю).")
    else:
        notes.append(f"Ветка {branch} содержит все коммиты origin/{base}.")

    rc, upstream = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if rc == 0 and upstream:
        behind_up = count(repo, f"HEAD..{upstream}") or 0
        if behind_up > 0:
            if dirty:
                warns.append(f"В {upstream} есть {behind_up} новых коммит(ов), но у вас незакоммиченные "
                             "изменения: подтягивать не стал.")
            else:
                rc, _ = git(repo, "pull", "--ff-only", timeout=FETCH_TIMEOUT * 2)
                if rc == 0:
                    notes.append(f"Ветка {branch} обновлена из {upstream}: подтянуто {behind_up} коммит(ов).")
                else:
                    warns.append(f"В {upstream} есть {behind_up} новых коммит(ов), но подтянуть без "
                                 "слияния не получилось (ветки разошлись). Решите вручную.")
    if dirty:
        notes.append("В отслеживаемых файлах есть незакоммиченные изменения.")


def sync_kit(repo: Path, notes: list[str], warns: list[str]) -> None:
    kit_file = repo / ".qa-kit" / "kit_path"
    if not kit_file.is_file():
        return
    try:
        kit = Path(kit_file.read_text(encoding="utf-8").strip())
    except OSError:
        return
    if not (kit / ".git").exists() or not (kit / "setup_project.py").is_file():
        warns.append(f"Комплект не найден по сохранённому пути ({kit}). Запустите setup_project.py заново.")
        return

    fetch = throttled_fetch(kit, repo / ".qa-kit" / "last_kit_sync")
    if fetch == "failed":
        return  # о сети уже сказано выше; про комплект молча
    behind = count(kit, "HEAD..@{u}")
    if not behind:
        return

    manual = (f"git -C \"{kit}\" pull; python \"{kit / 'setup_project.py'}\" \"{repo}\" --update")
    if os.environ.get("QA_KIT_NO_AUTOUPDATE"):
        warns.append(f"У комплекта qa-agent-kit есть {behind} новых коммит(ов). Обновить: {manual}")
        return
    if tracked_dirty(kit):
        warns.append(f"У комплекта qa-agent-kit есть {behind} новых коммит(ов), но в нём есть локальные "
                     f"изменения: сам не обновлял. Обновить вручную: {manual}")
        return
    rc, _ = git(kit, "pull", "--ff-only", timeout=FETCH_TIMEOUT * 2)
    if rc != 0:
        warns.append(f"У комплекта есть {behind} новых коммит(ов), но подтянуть без слияния не получилось. "
                     f"Обновить вручную: {manual}")
        return
    try:
        res = subprocess.run(
            [sys.executable, str(kit / "setup_project.py"), str(repo), "--update", "--no-exclude"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        ok = res.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    if ok:
        warns.append(f"Комплект qa-agent-kit обновлён ({behind} коммит(ов)) и применён к проекту. "
                     "Если новые команды или правила не видны, перезапустите сессию Claude Code.")
    else:
        warns.append("Комплект подтянут, но применить к проекту не получилось. "
                     f"Выполните вручную: python \"{kit / 'setup_project.py'}\" \"{repo}\" --update")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if os.environ.get("QA_KIT_NO_SYNC"):
        return 0
    try:
        sys.stdin.read()  # хук получает JSON на stdin; нам он не нужен
    except Exception:
        pass

    notes: list[str] = []
    warns: list[str] = []
    try:
        rc, top = git(Path.cwd(), "rev-parse", "--show-toplevel")
        if rc != 0 or not top:
            return 0  # не git-репозиторий: молча выходим
        repo = Path(top)
        sync_qa_repo(repo, notes, warns)
        sync_kit(repo, notes, warns)
    except Exception as exc:  # хук не должен ломать запуск сессии
        warns.append(f"Синхронизация прервалась из-за ошибки: {exc}")

    if not notes and not warns:
        return 0

    context = [f"{TAG} Состояние репозитория на старте сессии (собрано автоматически):"]
    context += [f"- {n}" for n in notes] + [f"- ВНИМАНИЕ: {w}" for w in warns]
    if warns:
        context.append("Сообщи пользователю об этих предупреждениях в первой реплике, коротко. "
                       "Если сейчас основная ветка, не пиши файлы тестов, предложи /start <имя>.")
    summary = [f"qa-agent-kit: {n}" for n in notes[:1]] + [f"qa-agent-kit: {w}" for w in warns]
    print(json.dumps({
        "systemMessage": "\n".join(summary),
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n".join(context)},
    }, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        sys.exit(0)
