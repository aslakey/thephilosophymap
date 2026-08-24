"""Guards for the small-screen layout contract.

The phone layout is split across two files: index.html decides what things look
like at a given size, and main.js decides where the map is drawn and where the
detail panel parks a node. They agree only because they use the same
breakpoints, and nothing but this test enforces that. Drift is silent -- the
page still renders, just with the map laid out for one breakpoint and the
chrome styled for another.

These read the source rather than a browser so they can run in CI without
Chrome. Behaviour itself is verified by hand against real device viewports.
"""

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"


@pytest.fixture(scope="module")
def html():
    return (DOCS / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def main_js():
    return (DOCS / "main.js").read_text(encoding="utf-8")


def js_const(source, name):
    """The string value of a top-level `const NAME = "...";` in main.js."""
    match = re.search(rf'^const {name} = "([^"]+)";', source, re.MULTILINE)
    assert match, f"{name} is not declared as a string constant in main.js"
    return match.group(1)


def media_queries(source):
    """Every media query in the stylesheet, whitespace-normalised."""
    return {" ".join(q.split()) for q in re.findall(r"@media ([^{]+)\{", source)}


class TestBreakpointsAgree:
    """The two files have to draw the line in the same place."""

    def test_compact_chrome_breakpoint_is_shared(self, html, main_js):
        query = js_const(main_js, "SMALL_SCREEN_QUERY")
        assert " ".join(query.split()) in media_queries(html), (
            f"main.js switches to the compact layout at {query!r}, but no @media rule "
            f"in index.html uses that condition. The map would be laid out for a phone "
            f"while the controls are still styled for a desktop, or the reverse."
        )

    def test_detail_panel_breakpoint_is_shared(self, html, main_js):
        query = js_const(main_js, "DETAIL_SHEET_QUERY")
        assert " ".join(query.split()) in media_queries(html), (
            f"main.js parks the selected node for a bottom sheet at {query!r}, but the "
            f"stylesheet does not turn the panel into one at that size. The node would "
            f"be centred under the panel instead of visible above it."
        )

    def test_compact_chrome_covers_short_screens(self, main_js):
        # A phone in landscape is wide but very short; keying only off width
        # would hand it the full-height desktop bar.
        query = js_const(main_js, "SMALL_SCREEN_QUERY")
        assert "max-height" in query, (
            "The compact layout must trigger on short screens too, not just narrow ones."
        )


class TestMapFollowsTheViewport:
    """Rotating a device must re-lay out the map, not crop it."""

    def test_dimensions_are_not_captured_once(self, main_js):
        assert not re.search(r"^const (width|height) = window\.inner", main_js, re.MULTILINE), (
            "width/height are const, so they hold the size the page loaded at. "
            "Rotating a phone would leave the map in a portrait-shaped box."
        )
        assert re.search(r"^let width = window\.innerWidth;", main_js, re.MULTILINE)
        assert re.search(r"^let height = window\.innerHeight;", main_js, re.MULTILINE)

    @pytest.mark.parametrize("event", ["resize", "orientationchange"])
    def test_resize_is_handled(self, main_js, event):
        assert f'window.addEventListener("{event}", handleViewportResize);' in main_js

    def test_resize_reprojects_and_keeps_the_readers_place(self, main_js):
        handler = main_js.split("function handleViewportResize()")[1]
        assert "applyLayoutTargets(currentNodes)" in handler, (
            "A resize must re-project the layout into the new viewport."
        )
        assert "invert" in handler, (
            "A resize must convert the on-screen centre back into source coordinates "
            "and restore it, or a zoomed-in reader is left looking at empty space."
        )


class TestTouchTargets:
    def test_controls_meet_the_44px_minimum_on_touch(self, html):
        coarse = re.search(r"@media \(pointer: coarse\) \{(.+?)\n  \}", html, re.DOTALL)
        assert coarse, "No coarse-pointer block: touch targets keep their mouse sizes."
        assert "min-height: 44px" in coarse.group(1)

    def test_node_hit_target_is_zoom_invariant(self, main_js):
        # The hit circles live inside the zoomed layer, so a fixed radius would
        # shrink them as the reader zooms out -- when taps are least precise.
        assert "NODE_HIT_RADIUS / (currentTransform.k || 1)" in main_js
        assert "updateHitRadius()" in main_js

    def test_search_input_avoids_ios_zoom_on_focus(self, html):
        compact = html.split("@media (max-width: 640px), (max-height: 480px) {")[1]
        search_rule = re.search(r"#search-input \{(.+?)\}", compact, re.DOTALL)
        assert search_rule, "No phone rule for #search-input."
        assert "font-size: 16px" in search_rule.group(1), (
            "iOS Safari zooms the whole page when focusing an input under 16px."
        )


class TestSafeAreas:
    def test_viewport_opts_into_the_safe_area(self, html):
        meta = re.search(r'<meta name="viewport" content="([^"]+)"', html)
        assert meta, "No viewport meta tag."
        assert "viewport-fit=cover" in meta.group(1), (
            "Without viewport-fit=cover the env(safe-area-inset-*) values are all zero."
        )

    def test_chrome_clears_the_notch_and_home_indicator(self, html):
        assert "env(safe-area-inset-top)" in html, "The top bar must clear the notch."
        assert "env(safe-area-inset-bottom)" in html, (
            "The sheet and detail panel must clear the home indicator."
        )
