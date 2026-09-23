class SQLPolicyError(ValueError):
    """SQL 策略拒绝；对外只暴露稳定错误码和安全消息。"""

    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        correctable: bool,
    ) -> None:
        self.code = code
        self.safe_message = safe_message
        self.correctable = correctable
        super().__init__(f"{code}: {safe_message}")
