from dataclasses import dataclass
from pathlib import Path

import sqlglot
import yaml
from sqlglot import exp


class SQLGuardError(ValueError):
    pass


@dataclass(frozen=True)
class GuardedSQL:
    sql: str
    tables: tuple[str, ...]
    limit_applied: bool


class SQLGuard:
    def __init__(self, schema: dict[str, set[str]], max_rows: int = 500):
        self.schema = schema
        self.max_rows = max_rows

    @classmethod
    def from_meta_config(cls, path: str | Path, max_rows: int = 500):
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        schema = {
            table["name"]: {column["name"] for column in table["columns"]}
            for table in payload["tables"]
        }
        return cls(schema, max_rows)

    def validate(self, sql: str) -> GuardedSQL:
        try:
            expressions = sqlglot.parse(sql, read="mysql")
        except sqlglot.errors.ParseError as error:
            raise SQLGuardError(f"SQL_PARSE_ERROR: {error}") from error
        if len(expressions) != 1:
            raise SQLGuardError("MULTI_STATEMENT_DENIED")
        expression = expressions[0]
        if not isinstance(expression, exp.Query):
            raise SQLGuardError("READ_ONLY_QUERY_REQUIRED")
        denied = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create, exp.Command)
        if any(expression.find(kind) for kind in denied):
            raise SQLGuardError("WRITE_OPERATION_DENIED")

        table_nodes = list(expression.find_all(exp.Table))
        tables = {table.name for table in table_nodes}
        unknown_tables = tables - self.schema.keys()
        if unknown_tables:
            raise SQLGuardError(f"UNKNOWN_TABLE: {','.join(sorted(unknown_tables))}")

        aliases = {table.alias_or_name: table.name for table in table_nodes}
        used_columns = set().union(*(self.schema[table] for table in tables)) if tables else set()
        for column in expression.find_all(exp.Column):
            if column.name == "*":
                continue
            if column.table:
                table_name = aliases.get(column.table, column.table)
                if table_name in self.schema and column.name not in self.schema[table_name]:
                    raise SQLGuardError(f"UNKNOWN_COLUMN: {table_name}.{column.name}")
            elif column.name not in used_columns:
                raise SQLGuardError(f"UNKNOWN_COLUMN: {column.name}")

        limit_applied = expression.args.get("limit") is None
        if limit_applied:
            expression = expression.limit(self.max_rows)
        return GuardedSQL(
            sql=expression.sql(dialect="mysql"),
            tables=tuple(sorted(tables)),
            limit_applied=limit_applied,
        )
