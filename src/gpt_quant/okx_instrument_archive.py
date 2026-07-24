from __future__ import annotations

from pathlib import Path

from .okx_instruments import OKXSpotInstrumentSnapshot, _write_immutable_file


def write_okx_spot_instrument_observation(
    snapshot: OKXSpotInstrumentSnapshot,
    output_dir: str | Path,
) -> dict[str, Path]:
    """Persist one content-addressed public-instrument forward observation.

    Different request/exchange timestamps produce different metadata hashes and therefore
    coexist immutably. An exact retry resolves to the same files and remains idempotent.
    """

    destination = Path(output_dir)
    if destination.is_symlink():
        raise ValueError("instrument observation output directory cannot be a symbolic link")
    destination.mkdir(parents=True, exist_ok=True)

    observation_id = snapshot.metadata_sha256
    stem = f"okx-{snapshot.instrument_id}-SPOT.instrument.{observation_id}"
    paths = {
        "raw": destination / f"{stem}.raw.json",
        "metadata": destination / f"{stem}.metadata.json",
    }
    raw_existed = paths["raw"].exists()
    _write_immutable_file(paths["raw"], snapshot.raw_response_json)
    try:
        _write_immutable_file(paths["metadata"], snapshot.metadata_bytes())
    except BaseException:
        if not raw_existed:
            paths["raw"].unlink(missing_ok=True)
        raise
    return paths
