# li-publish

Write LinkedIn posts about your projects in your own voice, and publish them
to your personal profile through LinkedIn's official API. Nothing posts
without your yes.

**Drop notes and images in a folder, run one command, it's posted:**

```
python publish.py
```

## Built on linkedin-agent-skill

Built on [linkedin-agent-skill](https://github.com/Jakeschincariol/linkedin-agent-skill)
by Jake Schincariol (MIT). That pack writes the posts (`/li-post`) and
humanizes them (`/li-human`). **It is not bundled here; install it
separately** (see [Install](#install)).

### What this adds

- **Publishing through the official LinkedIn Posts API.** Text posts and
  posts with up to 20 images (LinkedIn's multi-image limit). Confirmed
  working in Oct 2026 on a self-serve developer app with `w_member_social`:
  text-only, 1 image and 3 images. No partner review needed.
- **OAuth login script** (`auth.py`). One browser login, and the token is
  saved to your local `.env`.
- **Inbox folder workflow.** Put notes or final text plus screenshots in
  `inbox/` and run one command. After posting, everything is archived to
  `posted/<timestamp>/` with the post URL.
- **The `/li-ship` skill.** Run it inside any project: it reads the code,
  gathers context and screenshots, writes the inbox, shows you a dry run,
  and posts on your "go".
- **Humanizer emoji fixes** ([patches/](patches/APPLY.md)). The upstream
  humanizer broke emoji like 👨‍💻 and scored them as AI fingerprints.

## Requirements

- Python 3.10+
- [Claude Code](https://claude.com/claude-code), for drafting and
  `/li-ship`. The `post.md` mode is plain Python and works without it.
- The li-* skills from
  [linkedin-agent-skill](https://github.com/Jakeschincariol/linkedin-agent-skill)
  installed in `~/.claude/skills/` (at least `li-post` and `li-human`).
- A LinkedIn developer app of your own (below).

## LinkedIn app setup (~15 minutes)

Every user needs their own app. LinkedIn issues the Client ID and Secret per
app, and a secret must stay private, so this repo cannot ship one for you.

1. **Create a Company page** if you have none (LinkedIn → For Business →
   Create a Company Page). LinkedIn requires every developer app to be linked
   to one. A placeholder page for yourself is fine.
2. Go to [developer.linkedin.com](https://developer.linkedin.com) →
   **My apps** → **Create app**. Link it to that page and add a logo.
3. **Products** tab → request **Share on LinkedIn** and **Sign In with
   LinkedIn using OpenID Connect**. Both are self-serve and approved
   instantly.
4. **Auth** tab → under *Authorized redirect URLs* add
   `http://localhost:8000/callback`.
5. Copy the **Client ID** and **Primary Client Secret** from the Auth tab
   into your `.env` (next section).

## Install

```
git clone https://github.com/Jakeschincariol/linkedin-agent-skill.git
cp -r linkedin-agent-skill/skills/li-* ~/.claude/skills/

git clone <this repo> li-publish
cd li-publish
git -C ~/.claude/skills/li-human apply "$PWD/patches/li-human-emoji.diff"   # optional, recommended
python install.py
pip install -r publisher/requirements.txt
```

`install.py` sets up your data folder, `LI_HOME` (the `LI_HOME` environment
variable, else `~/.claude/linkedin`). It copies the publisher scripts there,
creates `.env` from `.env.example`, installs `/li-ship` into
`~/.claude/skills/`, and adds an allow rule for `publish.py` to
`~/.claude/settings.json`, after backing that file up. It never overwrites
an existing `.env` or `voice.md`.

Run `python install.py --check` at any point to see what is still missing.

### First login

Fill in `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET` in `LI_HOME/.env`,
then:

```
cd ~/.claude/linkedin
python auth.py
```

Your browser opens LinkedIn's consent screen. Approve it, and the script
saves the access token, its expiry date and your member ID into `.env`.

### Voice profile

Every draft is written from `LI_HOME/voice.md`. Either copy
`voice.example.md` there and edit it, or run `/li-post` in Claude Code with
three of your past posts and ask it to write `voice.md` from them.

## Usage

Run these from `LI_HOME` (or give the full path to `publish.py`).

### Topic mode

```
python publish.py "topic: ... why: ... what: ... for: ... stack: ... github: ..."
```

Drafts with `/li-post`, humanizes, shows the post and asks `Post? [y/N]`.
Text-only. Give real detail; if the idea is too thin, `/li-post` asks a
question instead and nothing is posted.

### Inbox mode

```
python publish.py
```

With no topic, the tool reads `LI_HOME/inbox/`. Put **exactly one** of these
in it:

| file | what happens |
| --- | --- |
| `context.md` | Notes, topic or bullets. Drafted with `/li-post`, then humanized. |
| `post.md` | Your final text. Posted exactly as written: no drafting, no humanizer, only LinkedIn's reserved-character escaping. |

Both or neither: the tool stops and says so.

**Images:** every `.jpg`, `.jpeg` and `.png` in `inbox/`, attached in
filename order, so name them `1-dashboard.png`, `2-logs.png`. Each must be
under 8 MB, 20 at most, and the alt text is the filename. Images upload only
after you say yes. After a successful post, `inbox/` is moved to
`posted/<YYYYMMDD-HHMMSS>/` with a `result.txt` (post URN, URL, final text).
Files are moved, never deleted. If LinkedIn refuses the image upload (403),
the post goes out text-only and the images stay in `inbox/` with
`IMAGES_NOT_POSTED.txt`.

### /li-ship (from inside a project)

```
cd ~/code/my-project
claude
> /li-ship
```

The skill reads the project (README, dependencies, git log), finds or
captures 1 to 3 screenshots, blurs personal data, writes
`inbox/context.md`, runs a dry run and shows you the draft. It locks the
text in as `post.md`, and posts only when you reply "go".

### Flags (both modes)

- `--dry-run`: shows the final text and images, saves the text to
  `drafts/<timestamp>.md`, uploads and posts nothing, and leaves `inbox/`
  as it is.
- `--auto`: posts without the `Post? [y/N]` prompt. Use with care.

Every published post is appended to `LI_HOME/log.md`, which `/li-audit` can
read later, and copied to `LI_HOME/archive/<YYYY-MM-DD>_<slug>/post.md`
(plus the images that were attached). The slug comes from the post's first
line. Other tools, such as ram-engine, read `archive/` as a record of what
was published.

## What is NOT automated, and why

- **Comments, replies, the messaging inbox and analytics.** LinkedIn does not
  offer these to individuals through the API; reading posts and comments
  (`r_member_social`) is restricted to approved partners. Use `/li-reply`,
  `/li-inbox` and `/li-audit` from the skill pack with copy-paste instead.
- **Editing a published post's images.** The API can change a post's text,
  not its media. To fix images, delete the post on LinkedIn and post again.

## Security

- Secrets live only in `LI_HOME/.env`, which is gitignored here and never
  copied into the repo. No script prints the client secret, the access token
  or your member URN, and API error messages are redacted before display.
- The access token expires after about 60 days. `publish.py` warns 7 days
  ahead; rerun `python auth.py` to renew.
- Network traffic goes only to `www.linkedin.com` / `api.linkedin.com`
  (login and posting) and to your local `claude` CLI (drafting). Nothing
  else is contacted.
- The allow rule `install.py` adds lets Claude Code run `publish.py`
  without asking, **including with `--auto`**. `/li-ship` is instructed to
  post only after your "go", but that is an instruction to the model, not a
  hard lock. Remove the rule from `~/.claude/settings.json` if you want a
  permission prompt every time.

## Known limitations / still to verify

- **Video upload:** not supported (images only).
- **Multi-image limit:** LinkedIn documents 2 to 20 images. Tested with up
  to 3; `/li-ship` stops at 3.
- **Rate limits:** not documented for `w_member_social` on personal
  profiles; not tested.
- **Token refresh:** self-serve apps normally get no refresh token, so the
  tool does not try one. When the token expires, log in again.
- **Claude Code auto mode with `--auto`:** not verified how auto mode treats
  an allowed `publish.py --auto` run started by `/li-ship`.
- **Images right after upload:** a `w_member_social` token cannot read
  image processing status, so the post is sent straight after upload. This
  worked in testing.
- **Paths with spaces:** the allow rule and `/li-ship` commands are
  unquoted. Keep `LI_HOME` on a path without spaces.
- **API version:** posts use `LinkedIn-Version: 202608`. LinkedIn retires
  versions after about a year; set `LINKEDIN_API_VERSION` in `.env` to move
  on.

## License and credits

MIT, see [LICENSE](LICENSE).

The post writing, voice profile format, hook formulas and humanizer come
from [linkedin-agent-skill](https://github.com/Jakeschincariol/linkedin-agent-skill)
by Jake Schincariol, MIT licensed. This repo adds the publisher, the inbox
workflow, `/li-ship` and the emoji patch.
