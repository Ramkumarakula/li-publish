"""Install li-publish, or check what is still missing.

    python install.py           install
    python install.py --check   report what is missing; changes nothing

Install:
  1. creates LI_HOME (env var LI_HOME, else ~/.claude/linkedin) with inbox/, drafts/, posted/
  2. copies publisher/*.py and requirements.txt into LI_HOME (never touches .env or voice.md)
  3. creates LI_HOME/.env from .env.example if there is none
  4. copies skills/li-ship into ~/.claude/skills/
  5. adds a Bash allow rule for publish.py to ~/.claude/settings.json (backed up first)

Standard library only, so it runs before `pip install -r requirements.txt`.
Never prints the contents of .env.
"""

import argparse
import datetime
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
LI_HOME = Path(os.environ.get("LI_HOME") or Path.home() / ".claude" / "linkedin").expanduser()
CLAUDE_DIR = Path.home() / ".claude"
SKILLS_DIR = CLAUDE_DIR / "skills"
SETTINGS = CLAUDE_DIR / "settings.json"
ALLOW_RULE = f"Bash(python {(LI_HOME / 'publish.py').as_posix()}*)"

PUBLISHER_FILES = ["auth.py", "post.py", "publish.py", "requirements.txt"]
ENV_KEYS = ["LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET", "LINKEDIN_REDIRECT_URI"]
TOKEN_KEYS = ["LINKEDIN_ACCESS_TOKEN", "LINKEDIN_PERSON_URN", "LINKEDIN_TOKEN_EXPIRES"]
REQUIRED_SKILLS = ["li-post", "li-human", "li-ship"]
SKILL_PACK = "https://github.com/Jakeschincariol/linkedin-agent-skill"


def read_env(path):
    """Parse KEY=VALUE lines. Values are only ever checked for presence, never printed."""
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip("'\"")
    return env


def install():
    for sub in ("", "inbox", "drafts", "posted"):
        (LI_HOME / sub).mkdir(parents=True, exist_ok=True)
    print(f"LI_HOME: {LI_HOME}")

    for name in PUBLISHER_FILES:
        shutil.copy2(REPO / "publisher" / name, LI_HOME / name)
    print(f"  copied {', '.join(PUBLISHER_FILES)}")

    env = LI_HOME / ".env"
    if env.exists():
        print("  .env exists, left as is")
    else:
        shutil.copy2(REPO / ".env.example", env)
        print("  created .env from .env.example - fill in your app's Client ID and Secret")

    dest = SKILLS_DIR / "li-ship"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / "skills" / "li-ship" / "SKILL.md", dest / "SKILL.md")
    print(f"  installed skill li-ship to {dest}")

    add_allow_rule()
    print("\nNext: pip install -r requirements.txt (in LI_HOME), fill in .env, python auth.py.")
    print("Then: python install.py --check")


def add_allow_rule():
    settings = {}
    if SETTINGS.exists():
        try:
            settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except ValueError as e:
            sys.exit(f"{SETTINGS} is not valid JSON ({e}); not touching it. Add this rule by hand:\n  {ALLOW_RULE}")
    allow = settings.setdefault("permissions", {}).setdefault("allow", [])
    if ALLOW_RULE in allow:
        print("  settings.json already allows publish.py")
        return
    if SETTINGS.exists():
        backup = SETTINGS.with_name(f"settings.json.bak-{datetime.datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(SETTINGS, backup)
        print(f"  backed up settings.json to {backup.name}")
    allow.append(ALLOW_RULE)
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"  added allow rule: {ALLOW_RULE}")


def check():
    missing = []

    def report(ok, label, fix=""):
        print(f"  [{'ok' if ok else '--'}] {label}")
        if not ok:
            missing.append(f"{label}: {fix}" if fix else label)

    print(f"LI_HOME: {LI_HOME}")
    report(sys.version_info >= (3, 10), f"Python 3.10+ (have {sys.version.split()[0]})")
    for mod, pkg in (("requests", "requests"), ("dotenv", "python-dotenv")):
        report(importlib.util.find_spec(mod) is not None, f"package {pkg}", "pip install -r requirements.txt")
    report(all((LI_HOME / f).exists() for f in PUBLISHER_FILES), "publisher files in LI_HOME", "python install.py")

    env = read_env(LI_HOME / ".env")
    for key in ENV_KEYS:
        report(bool(env.get(key)), f".env {key}", f"set it in {LI_HOME / '.env'}")
    has_token = all(env.get(k) for k in TOKEN_KEYS)
    report(has_token, "LinkedIn login (token in .env)", "python auth.py")
    if has_token:
        try:
            expires = datetime.date.fromisoformat(env["LINKEDIN_TOKEN_EXPIRES"])
            days = (expires - datetime.date.today()).days
            report(days > 0, f"token valid (expires {expires}, {days} days)", "python auth.py")
        except ValueError:
            report(False, "token expiry date readable", "python auth.py")

    report((LI_HOME / "voice.md").exists(), "voice.md", "copy voice.example.md to LI_HOME/voice.md and fill it in")
    for skill in REQUIRED_SKILLS:
        fix = "python install.py" if skill == "li-ship" else f"install the skill pack: {SKILL_PACK}"
        report((SKILLS_DIR / skill / "SKILL.md").exists(), f"skill {skill}", fix)
    human = SKILLS_DIR / "li-human" / "humanize.py"
    if human.exists():
        patched = "EMOJI_SEQ_RE" in human.read_text(encoding="utf-8")
        report(patched, "li-human emoji patch", "see patches/APPLY.md (optional but recommended)")
    report(shutil.which("claude") is not None, "Claude Code (claude) on PATH",
           "needed for drafting and /li-ship; post.md mode works without it")

    settings = {}
    if SETTINGS.exists():
        try:
            settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except ValueError:
            pass
    report(ALLOW_RULE in settings.get("permissions", {}).get("allow", []),
           "settings.json allow rule for publish.py", "python install.py")

    print(f"\n{len(missing)} thing(s) missing." if missing else "\nAll set.")
    for m in missing:
        print(f"  - {m}")
    return 1 if missing else 0


def main():
    ap = argparse.ArgumentParser(description="Install li-publish or check what is missing.")
    ap.add_argument("--check", action="store_true", help="report what is missing; change nothing")
    args = ap.parse_args()
    if args.check:
        sys.exit(check())
    install()


if __name__ == "__main__":
    main()
