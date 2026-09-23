# Contract: SQL Safety and Execution

## SQLGuard Interface

```text
validate(sql: str) -> GuardedSQL
raises SQLPolicyError(code, safe_message, correctable)
```

`GuardedSQL` follows `data-model.md` and is the only SQL type accepted by the execution boundary.

## Validation Order

1. Parse exactly one MySQL statement.
2. Require a read-only query AST.
3. Deny write/DDL/transaction/command nodes anywhere in the AST.
4. Resolve physical tables and deny databases/system objects outside the allow-list.
5. Qualify/validate column scopes against configured schema.
6. Expand projection stars to configured columns; permit aggregate `COUNT(*)`.
7. Reject query shapes whose table/column lineage cannot be proven safe.
8. Keep LIMIT 1–500, add missing LIMIT 500, cap literal LIMIT >500, reject dynamic/negative LIMIT.
9. Apply configured read-only execution timeout to the top-level SELECT.
10. Render MySQL SQL and return GuardedSQL evidence.

## Correctability Matrix

| Code | Correctable | Route |
|---|---:|---|
| SQL_PARSE_ERROR | yes | correct if attempts <2 |
| UNKNOWN_TABLE | yes | correct if attempts <2 |
| UNKNOWN_COLUMN | yes | correct if attempts <2 |
| UNSUPPORTED_QUERY_SHAPE | yes | correct if attempts <2 |
| SQL_EXPLAIN_FAILED | yes | correct if attempts <2 |
| MULTI_STATEMENT_DENIED | no | terminal safety error |
| READ_ONLY_QUERY_REQUIRED | no | terminal safety error |
| WRITE_OPERATION_DENIED | no | terminal safety error |
| SYSTEM_OBJECT_DENIED | no | terminal safety error |
| DANGEROUS_FUNCTION_DENIED | no | terminal safety error |
| LOCKING_QUERY_DENIED | no | terminal safety error |
| INVALID_LIMIT | no | terminal safety error |

External API maps all non-correctable guard codes to `SQL_POLICY_DENIED`; internal trace keeps the specific code.

## Execution Boundary

```text
guard(candidate_sql) -> guarded_sql
explain(guarded_sql.sql, timeout) -> ok | QueryFailure
run(guarded_sql.sql, timeout) -> rows | QueryFailure
```

Invariants:

- `run()` is unreachable unless `explain()` succeeded for the exact same SQL string.
- Any corrected candidate restarts at `guard()`.
- Repository APIs do not accept a second unguarded SQL parameter.
- Result fetching is bounded by GuardedSQL max_rows.
- Timeout/cancellation rolls back the request session before it returns to the pool.

## Database Privilege Contract

- `DW_DB_USER` has `SELECT` on `dw.*` only.
- `META_DB_USER` has the metadata permissions required by the build script and no rights on unrelated databases.
- Application startup fails if required usernames/passwords are absent; no committed default password.
- Integration verification executes one SELECT successfully and proves INSERT/UPDATE/DELETE/CREATE/DROP are denied for `DW_DB_USER`.
