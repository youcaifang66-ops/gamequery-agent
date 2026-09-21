from dataclasses import dataclass, field
from typing import Callable


class CorrectionExhausted(RuntimeError):
    pass


@dataclass
class CorrectionTrace:
    attempts: int = 0
    sql_versions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class BoundedSQLCorrector:
    """validate -> repair -> validate，修正次数有硬上限。"""

    def __init__(self, validator: Callable[[str], None], repair: Callable[[str, str], str], max_repairs=2):
        self.validator = validator
        self.repair = repair
        self.max_repairs = max_repairs

    def run(self, sql: str) -> tuple[str, CorrectionTrace]:
        trace = CorrectionTrace(sql_versions=[sql])
        while True:
            try:
                self.validator(sql)
                return sql, trace
            except Exception as error:
                trace.errors.append(str(error))
                if trace.attempts >= self.max_repairs:
                    raise CorrectionExhausted(
                        f"SQL correction exhausted after {trace.attempts} repairs: {error}"
                    ) from error
                sql = self.repair(sql, str(error))
                trace.attempts += 1
                trace.sql_versions.append(sql)
