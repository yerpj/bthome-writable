"""The modules published to EspruinoDocs are the ones tested here.

A copy of a module in someone else's tree is a copy that drifts; this project
has paid for that already (`.module-cache`, D-084). So the published form is
generated, and what makes that safe is a single invariant: **the generator
touches comments and nothing else**. Strip the comments from the source and
from the generated file and the two must be the same bytes. Behaviour then
follows, rather than being hoped for.

The size check is the other half, and it is a social limit rather than a
technical one: EspruinoDocs ships a median module of 2 477 bytes and a largest
of 19 027, so a 38 kB file in that directory asks a reviewer to read the wrong
thing.
"""

from __future__ import annotations

import pytest

from tools.build_espruino_bundle import strip_comments
from tools.build_espruino_module import BUDGET, MODULES, OUTPUT_DIR, SOURCE_DIR


@pytest.mark.parametrize("name", MODULES)
def test_the_published_module_exists(name: str) -> None:
    assert (OUTPUT_DIR / name).exists(), (
        f"{name} has not been generated; run `python -m tools.build_espruino_module`"
    )


@pytest.mark.parametrize("name", MODULES)
def test_only_the_comments_differ(name: str) -> None:
    """The whole safety of publishing a generated copy rests here."""
    source = strip_comments((SOURCE_DIR / name).read_text(encoding="utf-8"))
    published = strip_comments((OUTPUT_DIR / name).read_text(encoding="utf-8"))
    assert published == source, (
        f"{name}: the published module's code is not the code that is tested. "
        "Either the generator changed something it should not, or it is stale "
        "-- run `python -m tools.build_espruino_module`."
    )


@pytest.mark.parametrize("name", MODULES)
def test_the_published_module_is_not_the_biggest_thing_in_their_tree(
    name: str,
) -> None:
    size = (OUTPUT_DIR / name).stat().st_size
    assert size <= BUDGET, (
        f"{name} is {size} bytes, over the {BUDGET} this project set itself "
        "against EspruinoDocs' largest module (19 027). Move reasoning to the "
        ".md page rather than raising the budget."
    )


@pytest.mark.parametrize("name", MODULES)
def test_the_published_module_says_where_it_came_from(name: str) -> None:
    """A reader who finds a bug must land in the repository that can fix it,
    and a reader who edits the copy must be told it will be overwritten."""
    text = (OUTPUT_DIR / name).read_text(encoding="utf-8")
    assert "bthome-writable" in text
    assert "Edit it there" in text
    assert "not yet assigned by BTHome" in text, (
        "the provisional object ID has to be stated where the code is read, "
        "not only on the page"
    )
