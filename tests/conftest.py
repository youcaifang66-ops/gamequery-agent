import os

# 只给自动化测试提供无权限、无真实含义的占位凭据。
# 生产进程仍必须通过环境变量显式提供所有秘密。
os.environ.setdefault("LLM_API_KEY", "test-only-llm-key")
os.environ.setdefault("META_DB_PASSWORD", "test-only-meta-password")
os.environ.setdefault("DW_DB_PASSWORD", "test-only-dw-password")
