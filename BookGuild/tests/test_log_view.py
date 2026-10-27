from bookguild.events import LogEntry
from bookguild.ui.log_view import LogView, format_entry


def test_filters_by_agent_stage_and_level():
    view = LogView()
    view.set_entries(
        [
            LogEntry("searching", agent="Scout-1", stage="research"),
            LogEntry("timeout", level="warning", agent="Scout-2", stage="research"),
            LogEntry("failed", level="error", agent="Scout-2", stage="research"),
            LogEntry("outline ready", agent="Chair", stage="outline"),
        ]
    )
    assert len(view.visible_entries()) == 4

    view.agent_filter.setCurrentIndex(view.agent_filter.findData("Scout-2"))
    assert [e.message for e in view.visible_entries()] == ["timeout", "failed"]

    view.level_filter.setCurrentText("Errors only")
    assert [e.message for e in view.visible_entries()] == ["failed"]

    view.agent_filter.setCurrentIndex(0)
    view.level_filter.setCurrentText("All levels")
    view.stage_filter.setCurrentIndex(view.stage_filter.findData("outline"))
    assert [e.message for e in view.visible_entries()] == ["outline ready"]


def test_format_escapes_html():
    line = format_entry(LogEntry("<script>", agent="Scout-1", time="2026-10-27T10:11:12"))
    assert "&lt;script&gt;" in line
    assert line.startswith("10:11:12")


def test_format_usd():
    from bookguild.budget import format_usd

    assert format_usd(0) == "$0.00"
    assert format_usd(0.00004) == "$0.00004"
    assert format_usd(1.5) == "$1.50"
