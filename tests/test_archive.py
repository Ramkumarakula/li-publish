import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "publisher"))

import publish  # noqa: E402


def test_archive_post_copies_text_and_images(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "ARCHIVE_DIR", tmp_path / "archive")
    image = tmp_path / "1-shot.png"
    image.write_bytes(b"fake png")

    first = publish.archive_post("Shipped a thing!\n\nBody text", [image])
    second = publish.archive_post("Shipped a thing!\n\nAgain", [])

    assert first.name.endswith("_shipped-a-thing")
    assert (first / "post.md").read_text(encoding="utf-8") == "Shipped a thing!\n\nBody text\n"
    assert (first / "1-shot.png").read_bytes() == b"fake png"
    assert image.exists()  # copied, not moved: archive_inbox still moves it to posted/
    assert second.name == first.name + "-2"
