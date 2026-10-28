---
name: li-ship
description: "Publish a LinkedIn post about the current project: gather context, capture screenshots, draft, post via the li-publish inbox publisher"
---

# li-ship

Turns the project in the current working directory into a LinkedIn post and publishes it through the li-publish inbox publisher. Nothing is posted until the user says "go".

## Paths

`LI_HOME` is the `LI_HOME` environment variable if set, else `~/.claude/linkedin`. Resolve it once, at the start, with forward slashes:

```
python -c "import os, pathlib; print(pathlib.Path(os.environ.get('LI_HOME') or pathlib.Path.home() / '.claude' / 'linkedin').expanduser().as_posix())"
```

Use that exact printed path wherever `<LI_HOME>` appears below.

- Publisher: `<LI_HOME>/publish.py` (put there by `install.py`)
- Inbox: `<LI_HOME>/inbox/` (exactly one of `context.md` or `post.md`, plus up to 3 `.png`/`.jpg` images, attached in filename order)
- Drafts: `<LI_HOME>/drafts/`, posted history: `<LI_HOME>/posted/`, post log: `<LI_HOME>/log.md`

## 0. Check the inbox first

List the inbox, `posted/` and the last lines of `log.md`. If the inbox already holds files from another post, or `log.md` shows this project was posted recently, stop and ask before going on: rerunning would post twice or attach the wrong images.

## 1. Understand the project

Read the README, the dependency files (package.json, pyproject.toml, requirements.txt, go.mod, Cargo.toml, ...), `git log --oneline`, the folder layout and the main entry points. Never read `.env` or any file holding secrets or keys.

## 2. GitHub link

Run `git remote get-url origin`. Use the URL only if the repo is public: `gh repo view --json visibility` says PUBLIC, or (no gh) an unauthenticated `curl -s -o /dev/null -w "%{http_code}"` on the repo URL returns 200. Otherwise write `github: none` and say nothing about GitHub in the post. No remote also means `github: none`.

## 3. Images (1 to 3, in this order of preference)

Save to the inbox as `1-<name>.png`, `2-<name>.png`, `3-<name>.png` in the order they should appear.

a. **Existing images in the repo**: screenshots, demo GIF frames or architecture diagrams in `docs/`, `screenshots/`, `assets/` or referenced by the README. Logos and icons do not count.
b. **Web UI**: start it the way the README says (if it is already running, check it serves the current code; otherwise start a second instance on a free port). Open it with Playwright, headless, viewport 1280x800, and screenshot the 1 or 2 most representative pages. Install Playwright with `pip install playwright` and `python -m playwright install chromium` if it is missing (or use the project's own Playwright if it has one). Stop every server you started afterwards.
c. **Media output** (video, images): one good frame or sample with ffmpeg, e.g. `ffmpeg -ss 2 -i <video> -frames:v 1 -vf scale=1280:-2 <name>.png`. Look at it before keeping it; pick another time if it is blank or a fade.
d. **CLI only**: run its main command on sample input and render the terminal output to an image with a small Python script using Pillow: dark background, monospace font, at most 40 lines.

Before saving any image, open it and check for real people's or clients' names, phone numbers, emails, addresses, tokens or keys. Blur or crop them (Playwright: set `filter: blur(6px)` on matching elements before the screenshot; afterwards: blur the region with Pillow or sharp), then open it again to confirm. If no image can be made, continue text-only and say why.

## 4. context.md

Write `<LI_HOME>/inbox/context.md` with these lines:

```
topic: <what it is, one line>
why: <the problem that made the user build it; if the repo does not make it clear, ask the user one question>
what: <2-4 main features>
for: <who would use it>
value: <what it saves or improves>
stack: <main languages, frameworks, services from the dependency files>
github: <url or none>
```

Only features that exist in the code and work (not the README's wishlist). Only numbers that appear in the repo or that the user gave. Never invent a metric. If something is built but switched off (dry run, behind a flag), say so.

## 5. Dry run

Run, through the Bash tool, in exactly this form (the allow rule `install.py` adds is a prefix match on it):

```
python <LI_HOME>/publish.py --dry-run
```

Show the user the full draft, the humanizer score and verdict, and the image list. Point out any claim in the draft that the code does not support.

The publisher writes a new draft on every run from `context.md`, so the text shown here would not be the text posted. After showing it, lock it in: copy the draft it saved (`drafts/<timestamp>.md`, named in its last line) to `inbox/post.md` and move `context.md` to `drafts/<timestamp>-context.md`. A `post.md` is posted exactly as written.

## 6. Wait for "go"

- On **"go"**: run `python <LI_HOME>/publish.py --auto` (Bash tool) and give the post URL it prints. Confirm the inbox is empty and `posted/<timestamp>/` has the files. If the image upload returns 403, say which images are still in the inbox (it leaves `IMAGES_NOT_POSTED.txt` beside them).
- On **anything else**: apply the user's edits. Changes to the wording go into `inbox/post.md` directly, word for word as asked; changes to the content (features, angle, facts) go into `context.md`, which is put back in the inbox in place of `post.md`, and step 5 runs again. Then wait for "go" again.

Never run `--auto` without a "go" for the exact text shown last.
