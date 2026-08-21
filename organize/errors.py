class OrganizeError(Exception):
    """사용자에게 그대로 보여줄 수 있는 오류.

    파이썬 예외 문구를 노출하지 않기 위해, 사람이 읽는 문장과
    "무엇을 하면 되는지"를 함께 담는다.
    """

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
