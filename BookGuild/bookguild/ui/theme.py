"""Colours and labels shared by the widgets. Chosen to read well in light and dark Windows themes."""

from bookguild.events import Status

STATUS_COLORS = {
    Status.IDLE: "#9e9e9e",
    Status.RUNNING: "#1e88e5",
    Status.WAITING: "#ef6c00",
    Status.DONE: "#2e7d32",
    Status.FAILED: "#c62828",
}

STATUS_LABELS = {
    Status.IDLE: "idle",
    Status.RUNNING: "working…",
    Status.WAITING: "waiting for you",
    Status.DONE: "done",
    Status.FAILED: "FAILED",
}

# None means "use the normal text colour".
LEVEL_COLORS = {
    "debug": "#8a8a8a",
    "info": None,
    "success": "#2e7d32",
    "warning": "#ef6c00",
    "error": "#e53935",
}

MUTED = "#8a8a8a"

