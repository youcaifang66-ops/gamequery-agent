import pytest

from app.agent.correction_policy import BoundedSQLCorrector, CorrectionExhausted


def test_revalidates_each_repair_and_stops_on_success():
    def validator(sql):
        if "fact_payment" not in sql:
            raise ValueError("unknown table")

    corrector = BoundedSQLCorrector(
        validator, lambda sql, error: sql.replace("payment", "fact_payment"), max_repairs=2
    )
    sql, trace = corrector.run("SELECT amount FROM payment")
    assert sql == "SELECT amount FROM fact_payment"
    assert trace.attempts == 1
    assert len(trace.sql_versions) == 2


def test_hard_limit_prevents_infinite_correction_loop():
    corrector = BoundedSQLCorrector(
        lambda sql: (_ for _ in ()).throw(ValueError("still invalid")),
        lambda sql, error: sql,
        max_repairs=2,
    )
    with pytest.raises(CorrectionExhausted, match="after 2 repairs"):
        corrector.run("SELECT broken")
