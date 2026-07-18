import pytest

from anki_connect_server.content import clean_field_html


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        (
            '<div>A&nbsp;<span style="color:red">B</span><br>C</div>',
            "A B\nC",
        ),
        ("<pre><code>x &lt; y</code></pre>", "x < y"),
        ("Keep {{c1::this::hint}}", "Keep {{c1::this::hint}}"),
        ('<script type="math/tex">x &lt; y</script>', "x < y"),
        ("before<style>hidden</style><script>bad()</script>after", "beforeafter"),
    ],
)
def test_clean_field_html_preserves_meaning_without_presentation_noise(
    html: str,
    expected: str,
) -> None:
    assert clean_field_html(html) == expected


def test_clean_field_html_describes_media_without_reading_it() -> None:
    existing = {"picture.png", "voice.mp3", "clip.ogg"}

    def media_exists(filename: str) -> bool:
        if "/" in filename or ".." in filename:
            raise ValueError("unsafe")
        return filename in existing

    html = (
        '<img src="picture.png"> [sound:voice.mp3] '
        '<audio><source src="clip.ogg" type="audio/ogg"></audio> '
        '<video src="missing.mp4"></video> '
        '<img src="https://example.com/remote.png"> '
        '<img src="../secret.png"> '
        '<img src="data:image/png;base64,AAAA"> '
        "[anki:tts lang=en_US]spoken words[/anki:tts]"
    )

    assert clean_field_html(html, media_exists=media_exists) == (
        "[image: picture.png] [audio: voice.mp3] [audio: clip.ogg] "
        "[missing video: missing.mp4] "
        "[remote image: https://example.com/remote.png] "
        "[unsupported image: ../secret.png] [unsupported media: data] "
        "[TTS: spoken words]"
    )


def test_empty_presentation_markup_cleans_to_empty_text() -> None:
    assert clean_field_html("<div><span>&nbsp;</span></div>") == ""
