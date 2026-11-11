"""UI components for the feedback cog: the intake modals and their views."""

from .modals import (
    BugReportModal,
    FeatureRequestModal,
    FeedbackModal,
    Submission,
    build_modal,
    file_post,
)
from .views import (
    BUG_BUTTON_ID,
    FEATURE_BUTTON_ID,
    DuplicateMatchView,
    FeedbackMenuView,
)

__all__ = [
    "BUG_BUTTON_ID",
    "FEATURE_BUTTON_ID",
    "BugReportModal",
    "DuplicateMatchView",
    "FeatureRequestModal",
    "FeedbackMenuView",
    "FeedbackModal",
    "Submission",
    "build_modal",
    "file_post",
]
