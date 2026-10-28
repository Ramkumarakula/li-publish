# li-human emoji patch

Fixes three things in the `li-human` skill from
[linkedin-agent-skill](https://github.com/Jakeschincariol/linkedin-agent-skill)
(diffed against commit `add2c23`, v1.0):

- `humanize.py` deleted the zero-width joiner inside emoji like 👨‍💻 and the
  tag characters inside subdivision flags, breaking them. Whole emoji
  sequences are now protected the same way URLs are; stray invisible
  characters outside emoji are still stripped.
- `detect.py` counted those same characters as an AI fingerprint. Characters
  inside an emoji sequence no longer count.
- `slop.json` flagged 🎯, which the example voice profile uses as a section
  marker. 🚀 🔥 💡 ✨ are still flagged.

Apply it from the root of this repo, after installing the skill pack:

```
git -C ~/.claude/skills/li-human apply "$PWD/patches/li-human-emoji.diff"
```

On Windows PowerShell, use `"$HOME\.claude\skills\li-human"` and
`"$PWD\patches\li-human-emoji.diff"`. `git apply` works there even though
that folder is not a git repo. Reinstalling the skill pack undoes the patch;
apply it again afterwards.
