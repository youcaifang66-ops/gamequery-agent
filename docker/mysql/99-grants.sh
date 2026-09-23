#!/bin/bash
set -euo pipefail

encode_secret() {
  printf '%s' "$1" | base64 | tr -d '\r\n'
}

meta_password_b64="$(encode_secret "${META_DB_PASSWORD:?META_DB_PASSWORD is required}")"
dw_password_b64="$(encode_secret "${DW_DB_PASSWORD:?DW_DB_PASSWORD is required}")"

mysql --protocol=socket -uroot -p"${MYSQL_ROOT_PASSWORD}" <<SQL
SET @meta_password = CONVERT(FROM_BASE64('${meta_password_b64}') USING utf8mb4);
SET @meta_create = CONCAT(
  "CREATE USER IF NOT EXISTS 'gamequery_meta'@'%' IDENTIFIED BY ",
  QUOTE(@meta_password)
);
PREPARE meta_statement FROM @meta_create;
EXECUTE meta_statement;
DEALLOCATE PREPARE meta_statement;

SET @dw_password = CONVERT(FROM_BASE64('${dw_password_b64}') USING utf8mb4);
SET @dw_create = CONCAT(
  "CREATE USER IF NOT EXISTS 'gamequery_reader'@'%' IDENTIFIED BY ",
  QUOTE(@dw_password)
);
PREPARE dw_statement FROM @dw_create;
EXECUTE dw_statement;
DEALLOCATE PREPARE dw_statement;

GRANT SELECT, INSERT, UPDATE, DELETE ON meta.* TO 'gamequery_meta'@'%';
GRANT SELECT ON dw.* TO 'gamequery_reader'@'%';
FLUSH PRIVILEGES;
SQL
