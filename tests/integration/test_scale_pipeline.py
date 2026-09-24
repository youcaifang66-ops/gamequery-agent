import asyncio
import os

import pytest

from eval.generate_scale_data import generate
from eval.import_scale_data import import_dataset
from eval.run_db_scale_benchmark import run_benchmark
from eval.validate_scale_data import validate_dataset

RUN_SCALE_INTEGRATION = os.getenv("RUN_SCALE_INTEGRATION") == "1"
pytestmark = pytest.mark.skipif(
    not RUN_SCALE_INTEGRATION,
    reason="set RUN_SCALE_INTEGRATION=1 with an isolated MySQL admin account",
)


def test_real_mysql_smoke_pipeline(tmp_path):
    dataset = tmp_path / "scale-smoke"
    generate(dataset, rows=1_000, seed=20260923)
    validation = validate_dataset(dataset, full_scan=True)
    assert validation["status"] == "measured"

    async def scenario():
        settings = {
            "database": "gamequery_scale_ci",
            "username": os.environ["SCALE_DB_USER"],
            "password": os.environ["SCALE_DB_PASSWORD"],
            "host": os.getenv("SCALE_DB_HOST", "127.0.0.1"),
            "port": int(os.getenv("SCALE_DB_PORT", "3306")),
        }
        imported = await import_dataset(
            dataset,
            **settings,
            batch_size=250,
            replace=True,
        )
        assert imported["status"] == "measured"
        assert imported["metrics"]["ground_truth_passed"] is True

        benchmark = await run_benchmark(
            dataset,
            **settings,
            concurrency_levels=(1,),
            iterations=30,
            warmups=1,
        )
        assert benchmark["status"] == "measured"
        for query in benchmark["metrics"]["concurrency_runs"][0]["queries"].values():
            assert query["sample_count"] == 30
            assert query["result_match"] is True

    asyncio.run(scenario())
