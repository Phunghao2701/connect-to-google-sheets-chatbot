import pytest

from sheet_audit_agent.matching import normalize_text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Nguyễn Văn An", "nguyen van an"),
        (" NGUYEN  VAN AN ", "nguyen van an"),
        ("Nguyen-Van-An", "nguyen van an"),
        ("Đặng", "dang"),
        (" . , - _ ", ""),
    ],
)
def test_normalize_text(value: str, expected: str) -> None:
    assert normalize_text(value) == expected

