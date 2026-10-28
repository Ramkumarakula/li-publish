"""Draft (or take), humanize and publish a LinkedIn post.

    python publish.py "topic" [--auto] [--dry-run]     topic mode
    python publish.py [--auto] [--dry-run]             inbox mode (reads $LI_HOME/inbox/)

Topic mode: drafts with the /li-post skill (claude -p, read-only tools), then
cleans it with the li-human humanizer. Text-only post.

Inbox mode: inbox/ holds exactly one of
    context.md   notes for the post -> drafted with /li-post + humanized
    post.md      final text         -> posted exactly as written (escaping only)
plus any .jpg/.jpeg/.png images, attached in filename order. After a
successful post everything in inbox/ is moved to posted/<timestamp>/.

Both modes show the final text and ask "Post? [y/N]" (--auto skips;
--dry-run saves to drafts/ and stops). post.md mode needs no Claude Code.
"""

import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

from post import (LI_HOME, MAX_IMAGES, ImagePermissionError, PostError, post_text, post_url,
                  token_warning, upload_image, validate)

VOICE_PATH = LI_HOME / "voice.md"
DRAFTS_DIR = LI_HOME / "drafts"
INBOX_DIR = LI_HOME / "inbox"
POSTED_DIR = LI_HOME / "posted"
LOG_PATH = LI_HOME / "log.md"
HUMAN_DIR = Path.home() / ".claude" / "skills" / "li-human"
CLAUDE_TIMEOUT_SECONDS = 600
IMAGE_EXTS = (".jpg", ".jpeg", ".png")
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_NOTE = "IMAGES_NOT_POSTED.txt"

# Appended to the idea so the skill behaves in a non-interactive run.
PROMPT_SUFFIX = f"""

NON-INTERACTIVE RUN (called from a script; nobody can answer questions):
- Read the voice profile at {VOICE_PATH.as_posix()} and hooks.json as the skill says.
- Do not ask questions. If the idea is too thin to write without inventing facts,
  output one line starting with NEEDS_INFO: and your batched question, and stop.
- Do not run /li-human or write any files; the caller humanizes and logs.
- Never invent numbers; use {{{{your number}}}} where one is needed.
- Output the final post exactly as it should be pasted, between a line ===POST===
  and a line ===END===. Hook options and notes may go before ===POST===."""

POST_RE = re.compile(r"^===POST===\s*\n(.*?)\n===END===\s*$", re.S | re.M)


# ---------- drafting and humanizing ----------

def draft_with_claude(idea):
    """Run /li-post in print mode and return (notes, post_text)."""
    claude = shutil.which("claude")
    if not claude:
        sys.exit("The claude CLI is not on PATH. Install Claude Code, or use post.md in the inbox.")
    cmd = [claude, "-p", f"/li-post {idea}{PROMPT_SUFFIX}",
           "--allowedTools", "Read,Glob,Grep",
           "--disallowedTools", "Bash,Write,Edit,WebFetch,WebSearch"]
    print("Drafting with /li-post (this can take a minute)...")
    try:
        res = subprocess.run(cmd, cwd=LI_HOME, stdin=subprocess.DEVNULL, capture_output=True,
                             encoding="utf-8", timeout=CLAUDE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        sys.exit("claude -p timed out.")
    out = res.stdout.strip()
    if res.returncode != 0:
        sys.exit(f"claude -p failed ({res.returncode}): {res.stderr.strip()[:500]}")
    if "NEEDS_INFO:" in out:
        sys.exit("/li-post needs more to go on:\n" + out[out.index("NEEDS_INFO:"):]
                 + "\n\nAdd the answer to your topic or context.md and run again.")
    m = POST_RE.search(out)
    if not m:
        sys.exit("Could not find the post in /li-post's output:\n\n" + out[:2000])
    return out[:m.start()].strip(), m.group(1).strip()


def run_human_script(script, path):
    # -I isolates the interpreter (and ignores PYTHON* env vars), so force UTF-8 with -X utf8.
    res = subprocess.run([sys.executable, "-I", "-X", "utf8", str(HUMAN_DIR / script), str(path), "--json"],
                         capture_output=True, encoding="utf-8")
    try:
        return json.loads(res.stdout)
    except ValueError:
        sys.exit(f"{script} failed (is the li-human skill installed in {HUMAN_DIR}?): {res.stderr.strip()[:500]}")


def humanize(text):
    """Return (clean_text, artefacts_removed, structures_to_rewrite, score, verdict)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "draft.txt"
        path.write_text(text, encoding="utf-8")
        cleaned = run_human_script("humanize.py", path)
        path.write_text(cleaned["text"], encoding="utf-8")
        score = run_human_script("detect.py", path)
    rep = cleaned["report"]
    removed = sum(h["count"] for k in ("invisible", "typographic", "lexical") for h in rep[k])
    return cleaned["text"].strip(), removed, rep["structures"], score["human_score"], score["verdict"]


def draft_and_humanize(idea):
    """Draft with /li-post, humanize, print the report. Returns the final text."""
    notes, draft = draft_with_claude(idea)
    text, removed, structures, score, verdict = humanize(draft)
    if notes:
        print("\n" + notes)
    show(text)
    print(f"humanizer: {removed} artefacts stripped, human score {score} {verdict}")
    for s in structures:
        print(f"  flagged:  {s['name']} - {s['fix']}")
    return text


# ---------- inbox ----------

def read_inbox():
    """Validate inbox/ and return (kind, text, image_paths). kind is 'context' or 'post'."""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    POSTED_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(INBOX_DIR.iterdir(), key=lambda p: p.name)
    names = {p.name for p in files}
    has_context, has_post = "context.md" in names, "post.md" in names
    if has_context == has_post:
        found = "both context.md and post.md" if has_context else "neither context.md nor post.md"
        sys.exit(f"inbox/ must contain exactly one of context.md (notes to draft from) or "
                 f"post.md (final text), but it has {found}.\n  {INBOX_DIR}")
    kind = "context" if has_context else "post"
    text = (INBOX_DIR / f"{kind}.md").read_text(encoding="utf-8").strip()
    if not text:
        sys.exit(f"inbox/{kind}.md is empty.")

    images = [p for p in files if p.suffix.lower() in IMAGE_EXTS]
    for path in images:
        size = path.stat().st_size
        if size >= MAX_IMAGE_BYTES:
            sys.exit(f"{path.name} is {size / 1048576:.1f} MB; images must be under 8 MB.")
    if len(images) > MAX_IMAGES:
        sys.exit(f"inbox/ has {len(images)} images; LinkedIn allows at most {MAX_IMAGES} per post.")
    return kind, text, images


def archive_inbox(urn, url, text, image_note=None):
    """Move everything in inbox/ to posted/<timestamp>/ (or all but images if they were not posted)."""
    base = POSTED_DIR / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest, n = base, 1
    while dest.exists():
        n += 1
        dest = base.with_name(f"{base.name}-{n}")
    dest.mkdir(parents=True)
    for path in INBOX_DIR.iterdir():
        if image_note and path.suffix.lower() in IMAGE_EXTS:
            continue  # left behind on purpose; must be added to the post by hand
        shutil.move(str(path), str(dest / path.name))
    result = f"urn: {urn}\nurl: {url}\n"
    if image_note:
        result += f"images: NOT posted - {image_note}\n"
    (dest / "result.txt").write_text(result + f"\n{text}\n", encoding="utf-8")
    if image_note:
        (INBOX_DIR / IMAGE_NOTE).write_text(
            f"These images were NOT attached to {url}\nReason: {image_note}\n"
            "Add them to the post manually on LinkedIn (edit post > add media), "
            "then move them out of inbox/.\n", encoding="utf-8")
    return dest


# ---------- shared ----------

def show(text):
    print("\n" + "=" * 60 + "\n" + text + "\n" + "=" * 60)
    print(f"length:    {len(text):,} characters")


def show_images(images):
    if images:
        print(f"images:    {len(images)}")
        for p in images:
            print(f"  - {p.name} ({p.stat().st_size / 1024:,.0f} KB)")
    else:
        print("images:    none (text-only post)")


def save_draft(text):
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DRAFTS_DIR / (datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".md")
    path.write_text(text + "\n", encoding="utf-8")
    return path


def log_post(text, url):
    """Append to log.md so /li-audit has a history."""
    first_line = text.splitlines()[0]
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"- {datetime.date.today().isoformat()} | {first_line} | {url}\n")


def upload_all(paths):
    """Upload images. Returns (list of (urn, alt), None) or ([], reason) on a permission error."""
    uploaded = []
    for path in paths:
        print(f"Uploading {path.name}...")
        try:
            uploaded.append((upload_image(path), path.name))
        except ImagePermissionError as e:
            print(f"\n{e}\nPosting text-only; the images stay in inbox/ to add by hand.")
            return [], str(e)
        except requests.RequestException as e:
            sys.exit(f"Network error uploading {path.name} ({type(e).__name__}). Nothing was posted.")
        except PostError as e:
            sys.exit(f"{e}\nNothing was posted.")
    return uploaded, None


def main():
    # Windows consoles default to cp1252, which cannot print emoji. Do this first,
    # so callers never need python -X utf8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):  # not on wrapped streams (some IDEs, tests)
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="Draft, humanize and publish a LinkedIn post.")
    ap.add_argument("topic", nargs="?", help="topic to draft from; omit to use inbox/")
    ap.add_argument("--auto", action="store_true", help="post without asking")
    ap.add_argument("--dry-run", action="store_true", help="save to drafts/ instead of posting")
    args = ap.parse_args()

    inbox = args.topic is None
    images = []
    if inbox:
        kind, content, images = read_inbox()
        print(f"Inbox mode: {kind}.md + {len(images)} image(s)")
    else:
        kind, content = "context", args.topic.strip()
        if not content:
            sys.exit("Topic is empty.")

    if kind == "context":
        if not VOICE_PATH.exists():
            sys.exit(f"No voice profile at {VOICE_PATH}. Copy voice.example.md there and fill it in.")
        idea = content
        if images:
            idea += (f"\n\n({len(images)} image(s) will be attached: "
                     + ", ".join(p.name for p in images) + ". Do not describe them.)")
        text = draft_and_humanize(idea)
    else:
        text = content  # post.md: exactly as written; post.py only escapes reserved characters
        show(text)
    show_images(images)

    try:
        validate(text)
    except PostError as e:
        sys.exit(f"{e} Saved to {save_draft(text)}")

    if args.dry_run:
        print(f"\nDry run: saved to {save_draft(text)}. Nothing was posted or uploaded"
              + (", and inbox/ was not touched." if inbox else "."))
        return
    if kind == "context" and "{{" in text:
        sys.exit(f"\nThe draft still has a {{{{placeholder}}}} to fill in. Not posting.\n"
                 f"Saved to {save_draft(text)}. Add the real number to your notes and rerun.")

    warning = token_warning()
    if warning:
        print("\nWARNING: " + warning)
    if not args.auto and input("\nPost? [y/N] ").strip().lower() != "y":
        print(f"Cancelled. Nothing was posted. Saved to {save_draft(text)}")
        return

    # Upload only after the yes, so a cancel leaves nothing on LinkedIn.
    uploaded, image_note = upload_all(images)
    try:
        urn = post_text(text, uploaded)
    except PostError as e:
        sys.exit(f"{e}\ninbox/ was not touched." if inbox else str(e))

    # Posted. From here on, never retry; just report and file things away.
    url = post_url(urn)
    print(f"Posted: {url}")
    log_post(text, url)
    if inbox:
        try:
            dest = archive_inbox(urn, url, text, image_note)
        except OSError as e:
            sys.exit(f"Posted, but moving inbox/ failed: {e}. Move the files by hand; do NOT rerun.")
        print(f"Archived to {dest}")
        if image_note:
            print(f"Images were NOT attached. They are still in inbox/ with {IMAGE_NOTE}.")


if __name__ == "__main__":
    main()
