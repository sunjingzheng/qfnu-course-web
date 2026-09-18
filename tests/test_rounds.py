import pytest

from qfnu_course_web.rounds import RoundOption, RoundSelectionError, parse_rounds, select_round


def test_parse_rounds_keeps_visible_names_and_falls_back_to_ids() -> None:
    html = """
    <a href='/jsxsd/xsxk/xsxk_index?jx0502zbid=round-a'>2026 春季正选</a>
    <button onclick="jrxk('round-b')">2026 春季补选</button>
    <script>jrxk('round-c')</script>
    """

    assert parse_rounds(html) == [
        RoundOption(id="round-a", name="2026 春季正选"),
        RoundOption(id="round-b", name="2026 春季补选"),
        RoundOption(id="round-c", name="round-c"),
    ]


def test_select_round_uses_keyword_priority() -> None:
    rounds = [
        RoundOption(id="1", name="2026 春季正选"),
        RoundOption(id="2", name="2026 春季补选"),
    ]

    assert select_round(rounds, ["补选", "正选"]).id == "2"
    assert select_round([rounds[0]], []).id == "1"
    assert select_round(rounds, []).id == "1"


def test_select_round_rejects_missing_and_ambiguous_matches() -> None:
    rounds = [
        RoundOption(id="1", name="东校区补选"),
        RoundOption(id="2", name="西校区补选"),
    ]

    with pytest.raises(RoundSelectionError, match="多个"):
        select_round(rounds, ["补选"])
    with pytest.raises(RoundSelectionError, match="没有匹配"):
        select_round(rounds, ["正选"])
