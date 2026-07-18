"""Shared conversion of Anki field and rendered HTML into concise text."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal, cast
from urllib.parse import unquote, urlsplit

from anki.sound import AVTag

type MediaExpectation = Literal["image", "audio", "video", "auto"]
type MediaReferenceHandler = Callable[[str, MediaExpectation], str]
type AvReferenceHandler = Callable[[AVTag], str]
type MediaExistenceCheck = Callable[[str], bool]

_AV_REFERENCE = re.compile(r"\[anki:play:([qa]):(\d+)]")
_SOUND_REFERENCE = re.compile(r"\[sound:([^]]+)]")
_TTS_REFERENCE = re.compile(r"\[anki:tts(?: [^]]*)?](.*?)\[/anki:tts]", re.DOTALL)
_SPACE = re.compile(r"[ \t\f\v]+")
_NEWLINES = re.compile(r"\n{3,}")
_BLOCK_TAGS = frozenset(
    [
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "dl",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tr",
        "ul",
    ]
)


class _TextRenderer(HTMLParser):
    def __init__(
        self,
        media_reference: MediaReferenceHandler,
        av_reference: AvReferenceHandler | None,
        question_av: Sequence[AVTag],
        answer_av: Sequence[AVTag],
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.media_reference = media_reference
        self.av_reference = av_reference
        self.av = {"q": question_av, "a": answer_av}
        self.parts: list[str] = []
        self.ignored = 0
        self.math_script = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "style":
            self.ignored += 1
            return
        if tag == "script":
            if (attributes.get("type") or "").startswith("math/"):
                self.math_script += 1
            else:
                self.ignored += 1
            return
        if self.ignored:
            return
        if tag == "br" or tag in _BLOCK_TAGS:
            self.parts.append("\n")
        source = attributes.get("src")
        if not source or tag not in ("img", "audio", "video", "source"):
            return
        expected = cast(MediaExpectation, {"img": "image"}.get(tag, tag))
        if tag == "source":
            family = (attributes.get("type") or "").partition("/")[0]
            expected = cast(MediaExpectation, family if family in ("audio", "video") else "auto")
        self.parts.append(self.media_reference(source, expected))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if self.ignored:
            if tag in ("style", "script"):
                self.ignored -= 1
            return
        if tag == "script" and self.math_script:
            self.math_script -= 1
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.ignored:
            return
        if self.math_script:
            data = unescape(data)
        position = 0
        for match in _AV_REFERENCE.finditer(data):
            self._append_raw_references(data[position : match.start()])
            tags = self.av[match.group(1)]
            index = int(match.group(2))
            marker = (
                self.av_reference(tags[index])
                if self.av_reference is not None and index < len(tags)
                else "[unsupported: invalid Anki media reference]"
            )
            self.parts.append(marker)
            position = match.end()
        self._append_raw_references(data[position:])

    def _append_raw_references(self, data: str) -> None:
        position = 0
        for match in _TTS_REFERENCE.finditer(data):
            self._append_sound_references(data[position : match.start()])
            text = _SPACE.sub(" ", match.group(1)).strip()
            self.parts.append(f"[TTS: {text}]" if text else "[TTS]")
            position = match.end()
        self._append_sound_references(data[position:])

    def _append_sound_references(self, data: str) -> None:
        position = 0
        for match in _SOUND_REFERENCE.finditer(data):
            self.parts.append(data[position : match.start()])
            self.parts.append(self.media_reference(match.group(1), "audio"))
            position = match.end()
        self.parts.append(data[position:])

    def text(self) -> str:
        text = (
            "".join(self.parts)
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\N{NO-BREAK SPACE}", " ")
        )
        lines = (_SPACE.sub(" ", line).strip() for line in text.splitlines())
        return _NEWLINES.sub("\n\n", "\n".join(lines)).strip()


def render_anki_text(
    html: str,
    *,
    media_reference: MediaReferenceHandler,
    av_reference: AvReferenceHandler | None = None,
    question_av: Sequence[AVTag] = (),
    answer_av: Sequence[AVTag] = (),
) -> str:
    """Render Anki HTML as readable text using caller-provided media handlers."""
    renderer = _TextRenderer(media_reference, av_reference, question_av, answer_av)
    renderer.feed(html)
    renderer.close()
    return renderer.text()


def clean_field_html(
    html: str,
    *,
    media_exists: MediaExistenceCheck | None = None,
) -> str:
    """Normalize a raw note field without reading or embedding referenced media."""
    return render_anki_text(
        html,
        media_reference=lambda source, expected: _describe_media(source, expected, media_exists),
    )


def _describe_media(
    source: str,
    expected: MediaExpectation,
    media_exists: MediaExistenceCheck | None,
) -> str:
    parsed = urlsplit(source)
    if parsed.scheme in ("http", "https") or parsed.netloc or source.startswith("//"):
        return f"[remote {expected if expected != 'auto' else 'media'}: {source}]"
    if parsed.scheme:
        return f"[unsupported media: {parsed.scheme}]"
    filename = unquote(parsed.path)
    label = expected if expected != "auto" else _media_kind(filename)
    if media_exists is not None:
        try:
            if not media_exists(filename):
                return f"[missing {label}: {filename}]"
        except ValueError:
            return f"[unsupported {label}: {filename}]"
    return f"[{label}: {filename}]"


def _media_kind(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in (".apng", ".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"):
        return "image"
    if suffix in (".aac", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav"):
        return "audio"
    if suffix in (".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"):
        return "video"
    return "media"
