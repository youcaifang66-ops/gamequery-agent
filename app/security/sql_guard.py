from dataclasses import dataclass
from pathlib import Path

import sqlglot
import yaml
from sqlglot import exp
from sqlglot.errors import OptimizeError
from sqlglot.optimizer.qualify import qualify

from app.security.errors import SQLPolicyError

SQLGuardError = SQLPolicyError

DEFAULT_MAX_ROWS = 500
DEFAULT_STATEMENT_TIMEOUT_MS = 5_000

SAFE_ANONYMOUS_FUNCTIONS = {
    "DATE_FORMAT",
    "DATEDIFF",
    "DAY",
    "IF",
    "IFNULL",
    "MONTH",
    "QUARTER",
    "STR_TO_DATE",
    "TIMESTAMPDIFF",
    "YEAR",
}

DENIED_NODE_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Command,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Into,
)


@dataclass(frozen=True)
class GuardedSQL:
    sql: str
    tables: tuple[str, ...]
    max_rows: int
    limit_action: str
    timeout_ms: int

    @property
    def limit_applied(self) -> bool:
        """兼容旧调用方：新增或压低 LIMIT 都表示策略改写过。"""

        return self.limit_action in {"added", "capped"}


class SQLGuard:
    def __init__(
        self,
        schema: dict[str, set[str] | tuple[str, ...] | list[str]],
        max_rows: int = DEFAULT_MAX_ROWS,
        statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    ):
        if max_rows < 1:
            raise ValueError("max_rows must be positive")
        if statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms must be positive")
        self.schema = {
            table: tuple(sorted(columns)) if isinstance(columns, set) else tuple(columns)
            for table, columns in schema.items()
        }
        self.max_rows = max_rows
        self.statement_timeout_ms = statement_timeout_ms

    @classmethod
    def from_meta_config(
        cls,
        path: str | Path,
        max_rows: int = DEFAULT_MAX_ROWS,
        statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    ):
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        schema = {
            table["name"]: tuple(column["name"] for column in table["columns"])
            for table in payload["tables"]
        }
        return cls(schema, max_rows, statement_timeout_ms)

    @staticmethod
    def _deny(code: str, message: str, *, correctable: bool) -> None:
        raise SQLPolicyError(code, message, correctable=correctable)

    def _physical_tables(self, expression: exp.Expression) -> tuple[str, ...]:
        cte_names = {cte.alias_or_name for cte in expression.find_all(exp.CTE)}
        if cte_names & self.schema.keys():
            self._deny(
                "UNSUPPORTED_QUERY_SHAPE",
                "CTE 名称不能覆盖业务表名称。",
                correctable=True,
            )

        physical_tables: set[str] = set()
        for table in expression.find_all(exp.Table):
            if table.db or table.catalog:
                self._deny(
                    "SYSTEM_OBJECT_DENIED",
                    "不允许访问带数据库或目录前缀的对象。",
                    correctable=False,
                )
            if table.name in cte_names:
                continue
            physical_tables.add(table.name)

        unknown_tables = physical_tables - self.schema.keys()
        if unknown_tables:
            names = ",".join(sorted(unknown_tables))
            self._deny(
                "UNKNOWN_TABLE",
                f"未知业务表：{names}",
                correctable=True,
            )
        return tuple(sorted(physical_tables))

    def _qualify_columns(self, expression: exp.Expression) -> exp.Expression:
        typed_schema = {
            table: {column: "UNKNOWN" for column in columns}
            for table, columns in self.schema.items()
        }
        try:
            return qualify(
                expression,
                dialect="mysql",
                schema=typed_schema,
                expand_stars=True,
                validate_qualify_columns=True,
                quote_identifiers=False,
                identify=False,
            )
        except OptimizeError:
            self._deny(
                "UNKNOWN_COLUMN",
                "查询包含未知、冲突或无法确定作用域的字段。",
                correctable=True,
            )

    def _apply_limit(self, expression: exp.Expression) -> tuple[exp.Expression, str]:
        limit = expression.args.get("limit")
        if limit is None:
            return expression.limit(self.max_rows), "added"

        limit_value = limit.expression
        if not isinstance(limit_value, exp.Literal) or limit_value.is_string:
            self._deny(
                "INVALID_LIMIT",
                "LIMIT 必须是 1 到最大返回行数之间的整数。",
                correctable=False,
            )
        try:
            value = int(limit_value.this)
        except (TypeError, ValueError):
            self._deny(
                "INVALID_LIMIT",
                "LIMIT 必须是 1 到最大返回行数之间的整数。",
                correctable=False,
            )
        if value < 1:
            self._deny(
                "INVALID_LIMIT",
                "LIMIT 必须是 1 到最大返回行数之间的整数。",
                correctable=False,
            )
        if value > self.max_rows:
            return expression.limit(self.max_rows), "capped"
        return expression, "kept"

    def _apply_timeout(self, expression: exp.Expression) -> exp.Expression:
        selects = list(expression.find_all(exp.Select))
        if isinstance(expression, exp.Select) and expression not in selects:
            selects.insert(0, expression)
        if not selects:
            self._deny(
                "UNSUPPORTED_QUERY_SHAPE",
                "查询不包含可受控的 SELECT 块。",
                correctable=True,
            )

        for select in selects:
            select.set("hint", None)
        selects[0].set(
            "hint",
            exp.Hint(
                expressions=[
                    exp.Anonymous(
                        this="MAX_EXECUTION_TIME",
                        expressions=[exp.Literal.number(self.statement_timeout_ms)],
                    )
                ]
            ),
        )
        return expression

    def validate(self, sql: str) -> GuardedSQL:
        try:
            expressions = sqlglot.parse(sql, read="mysql")
        except sqlglot.errors.ParseError as error:
            raise SQLPolicyError(
                "SQL_PARSE_ERROR",
                "SQL 无法按 MySQL 方言解析。",
                correctable=True,
            ) from error
        if len(expressions) != 1:
            self._deny(
                "MULTI_STATEMENT_DENIED",
                "只允许单条查询语句。",
                correctable=False,
            )
        expression = expressions[0]
        if not isinstance(expression, exp.Query):
            self._deny(
                "READ_ONLY_QUERY_REQUIRED",
                "只允许只读查询。",
                correctable=False,
            )
        if any(expression.find(kind) for kind in DENIED_NODE_TYPES):
            self._deny(
                "WRITE_OPERATION_DENIED",
                "查询包含写入或管理操作。",
                correctable=False,
            )
        if expression.find(exp.Lock):
            self._deny(
                "LOCKING_QUERY_DENIED",
                "不允许锁定读取。",
                correctable=False,
            )
        for function in expression.find_all(exp.Anonymous):
            if function.name.upper() not in SAFE_ANONYMOUS_FUNCTIONS:
                self._deny(
                    "DANGEROUS_FUNCTION_DENIED",
                    "查询包含未允许的数据库函数。",
                    correctable=False,
                )

        tables = self._physical_tables(expression)
        expression = self._qualify_columns(expression)
        expression, limit_action = self._apply_limit(expression)
        expression = self._apply_timeout(expression)
        return GuardedSQL(
            sql=expression.sql(dialect="mysql"),
            tables=tables,
            max_rows=self.max_rows,
            limit_action=limit_action,
            timeout_ms=self.statement_timeout_ms,
        )
