import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

GTFS_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "gtfs_min"

GtfsZipFactory = Callable[..., Path]


# Factory fixture: zip the small hand-written feed in tests/fixtures/gtfs_min, like a real agency
# download. Pass overrides to change a file's contents ({"routes.txt": "..."}) or to drop a file
# entirely ({"feed_info.txt": None}). Returns the path of the new zip.
@pytest.fixture
def make_gtfs_zip(tmp_path: Path) -> GtfsZipFactory:
    counter = 0

    # Build one zip from the fixture files plus the given overrides.
    def build(overrides: dict[str, str | None] | None = None) -> Path:
        nonlocal counter
        counter += 1
        files = {path.name: path.read_text() for path in sorted(GTFS_FIXTURE_DIR.glob("*.txt"))}
        files.update(overrides or {})
        zip_path = tmp_path / f"gtfs_{counter}.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for name, content in files.items():
                if content is not None:
                    zf.writestr(name, content)
        return zip_path

    return build


# The unmodified fixture feed as a zip (feed_version "test-v1").
@pytest.fixture
def gtfs_zip(make_gtfs_zip: GtfsZipFactory) -> Path:
    return make_gtfs_zip()
