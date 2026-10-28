"""Publish a post to your personal LinkedIn profile via the Posts API.

    from post import post_text, upload_image
    urn = post_text("Hello")          # returns e.g. urn:li:share:123...
    img = upload_image(path)          # urn:li:image:...; then post_text(text, [(img, "alt")])

    python post.py --test             # posts "API test post" after you confirm

Reads LINKEDIN_ACCESS_TOKEN, LINKEDIN_PERSON_URN and LINKEDIN_TOKEN_EXPIRES
from $LI_HOME/.env (written by auth.py). Never retries: one call, one post at
most. Never prints the token or your person URN.
"""

import argparse
import datetime
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# Data folder: .env, voice.md, inbox/, drafts/, posted/, log.md
LI_HOME = Path(os.environ.get("LI_HOME") or Path.home() / ".claude" / "linkedin").expanduser()
ENV_PATH = LI_HOME / ".env"

POSTS_URL = "https://api.linkedin.com/rest/posts"
IMAGES_INIT_URL = "https://api.linkedin.com/rest/images?action=initializeUpload"
API_VERSION_DEFAULT = "202608"  # YYYYMM; override with LINKEDIN_API_VERSION in .env
MAX_CHARS = 3000
MAX_IMAGES = 20  # multiImage allows 2-20 images (MultiImage API docs)
EXPIRY_WARN_DAYS = 7
TEST_TEXT = "API test post"

# Reserved in LinkedIn's "little" text format; each must be backslash-escaped.
# https://learn.microsoft.com/linkedin/marketing/community-management/shares/little-text-format
RESERVED = set("\\|{}@[]()<>#*_~")
HASHTAG_RE = re.compile(r"(?<![\w#])#(\w+)")
# Anything that could identify you or your token in an error message.
SECRET_RE = re.compile(r"urn:li:person:[\w-]+|Bearer\s+\S+|AQ[\w-]{40,}")


class PostError(Exception):
    pass


class ImagePermissionError(PostError):
    """The token may not upload images; posting text-only is still possible."""


def redact(text):
    return SECRET_RE.sub("<redacted>", text)


def escape_little(text):
    """Escape reserved characters, but keep #word hashtags clickable via the hashtag template."""
    out, pos = [], 0
    for m in HASHTAG_RE.finditer(text):
        out.append(_escape_plain(text[pos:m.start()]))
        out.append("{hashtag|\\#|" + _escape_plain(m.group(1)) + "}")
        pos = m.end()
    out.append(_escape_plain(text[pos:]))
    return "".join(out)


def _escape_plain(s):
    return "".join("\\" + c if c in RESERVED else c for c in s)


def _config():
    load_dotenv(ENV_PATH)
    token = os.getenv("LINKEDIN_ACCESS_TOKEN")
    author = os.getenv("LINKEDIN_PERSON_URN")
    if not token or not author:
        raise PostError(f"No LinkedIn login found in {ENV_PATH}. Run: python auth.py")
    return token, author, os.getenv("LINKEDIN_API_VERSION", API_VERSION_DEFAULT)


def token_warning():
    """Return a warning string if the token is expired or expires within EXPIRY_WARN_DAYS, else None."""
    load_dotenv(ENV_PATH)
    raw = os.getenv("LINKEDIN_TOKEN_EXPIRES")
    if not raw:
        return "LINKEDIN_TOKEN_EXPIRES is not set; the token may be stale. Rerun auth.py if posting fails."
    days = (datetime.date.fromisoformat(raw) - datetime.date.today()).days
    if days < 0:
        return f"Your LinkedIn token expired on {raw}. Run: python auth.py"
    if days <= EXPIRY_WARN_DAYS:
        return f"Your LinkedIn token expires in {days} day(s) ({raw}). Rerun auth.py soon."
    return None


def validate(text):
    if not text or not text.strip():
        raise PostError("Post text is empty.")
    if len(text) > MAX_CHARS:
        raise PostError(f"Post is {len(text)} characters; LinkedIn's limit is {MAX_CHARS}.")


def _headers(token, version):
    return {
        "Authorization": f"Bearer {token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": version,
        "Content-Type": "application/json",
    }


def _error_message(resp):
    try:
        msg = resp.json().get("message", "")
    except ValueError:
        msg = resp.text[:300]
    return redact(str(msg))


def upload_image(path):
    """Upload one image file. Returns its urn:li:image URN.

    Raises ImagePermissionError on 403 (caller may fall back to text-only),
    PostError on anything else. Uploading never creates a post on its own.
    """
    path = Path(path)
    token, author, version = _config()
    init = requests.post(IMAGES_INIT_URL, json={"initializeUploadRequest": {"owner": author}},
                         headers=_headers(token, version), timeout=30)
    if init.status_code == 401:
        raise PostError("LinkedIn rejected the token (401). Run: python auth.py")
    if init.status_code == 403:
        raise ImagePermissionError(f"Image upload not permitted (403): {_error_message(init)}")
    if init.status_code != 200:
        raise PostError(f"Image upload init failed ({init.status_code}): {_error_message(init)}")
    value = init.json()["value"]

    put = requests.put(value["uploadUrl"], data=path.read_bytes(), timeout=120, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"})
    if put.status_code == 403:
        raise ImagePermissionError(f"Image upload not permitted (403) for {path.name}")
    if not 200 <= put.status_code < 300:
        raise PostError(f"Uploading {path.name} failed ({put.status_code})")
    return value["image"]


def post_text(text, images=None):
    """Publish text as a public post. Returns the post URN. Raises PostError on failure.

    images: optional list of (image_urn, alt_text). One -> content.media,
    2-20 -> content.multiImage.
    """
    validate(text)
    images = images or []
    if len(images) > MAX_IMAGES:
        raise PostError(f"{len(images)} images; LinkedIn allows at most {MAX_IMAGES} per post.")
    token, author, version = _config()
    body = {
        "author": author,
        "commentary": escape_little(text),
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if len(images) == 1:
        body["content"] = {"media": {"id": images[0][0], "altText": images[0][1]}}
    elif images:
        body["content"] = {"multiImage": {"images": [{"id": u, "altText": a} for u, a in images]}}
    try:
        resp = requests.post(POSTS_URL, json=body, headers=_headers(token, version), timeout=30)
    except requests.RequestException as e:
        # The request may have reached LinkedIn; do not blindly resend.
        raise PostError(f"Network error ({type(e).__name__}). Check your profile before trying again; "
                        "the post may have gone through.")

    if resp.status_code == 401:
        raise PostError("LinkedIn rejected the token (401). Run: python auth.py")
    if not 200 <= resp.status_code < 300:
        raise PostError(f"Post failed ({resp.status_code}): {_error_message(resp)}")

    urn = resp.headers.get("x-restli-id")
    if not urn:
        raise PostError("Post was accepted but LinkedIn returned no post id. Check your profile.")
    return urn


def post_url(urn):
    return f"https://www.linkedin.com/feed/update/{urn}"


def main():
    parser = argparse.ArgumentParser(description="Post to LinkedIn via the official API.")
    parser.add_argument("--test", action="store_true", help=f'post the single line "{TEST_TEXT}"')
    args = parser.parse_args()
    if not args.test:
        parser.error("use --test here, or publish.py for real posts")

    warning = token_warning()
    if warning:
        print("WARNING: " + warning)
    print("About to post publicly to your LinkedIn profile:\n\n" + TEST_TEXT + "\n")
    if input("Post? [y/N] ").strip().lower() != "y":
        print("Cancelled. Nothing was posted.")
        return
    try:
        urn = post_text(TEST_TEXT)
    except PostError as e:
        sys.exit(str(e))
    print(f"Posted: {post_url(urn)}")


if __name__ == "__main__":
    main()
