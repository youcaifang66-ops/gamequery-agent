import asyncio

import pytest

from eval.generate_scale_data import generate
from eval.import_scale_data import (
    ScaleImportError,
    import_dataset,
    iter_csv_batches,
    validate_database_target,
)


@pytest.mark.parametrize(
    "database",
    ["dw", "mysql", "meta", "gamequery_scale_bad-name", "other_scale_test"],
)
def test_importer_rejects_default_reserved_and_invalid_database_names(database):
    with pytest.raises(ScaleImportError, match="INVALID_DATABASE_NAME"):
        validate_database_target(database, username="root")


def test_importer_rejects_online_reader_credentials():
    with pytest.raises(ScaleImportError, match="READ_ONLY_CREDENTIALS"):
        validate_database_target(
            "gamequery_scale_smoke",
            username="gamequery_reader",
            reader_username="gamequery_reader",
        )


def test_csv_batches_are_bounded_and_preserve_rows(tmp_path):
    dataset = tmp_path / "dataset"
    generate(dataset, rows=100)

    batches = list(iter_csv_batches(dataset / "fact_player_daily.csv", batch_size=17))

    assert max(map(len, batches)) == 17
    assert sum(map(len, batches)) == 60
    assert len(batches[-1]) <= 17


def test_invalid_dataset_fails_before_database_connection(tmp_path):
    dataset = tmp_path / "dataset"
    generate(dataset, rows=100)
    (dataset / "fact_payment.csv").unlink()
    connected = False

    async def connection_factory(**_kwargs):
        nonlocal connected
        connected = True
        raise AssertionError("must not connect")

    with pytest.raises(ScaleImportError, match="DATASET_INTEGRITY_FAILED"):
        asyncio.run(
            import_dataset(
                dataset,
                database="gamequery_scale_smoke",
                username="root",
                password="top-secret",
                connection_factory=connection_factory,
            )
        )
    assert connected is False
