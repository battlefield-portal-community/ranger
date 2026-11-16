"""UI components for the feedback cog: the intake modals and their views."""

from .modals import (
    BugReportModal,
    FeatureRequestModal,
    FeedbackModal,
    Submission,
    UpdateFeedbackModal,
    build_modal,
    file_post,
)
from .views import (
    BUG_BUTTON_ID,
    FEATURE_BUTTON_ID,
    MENU_COLOURS,
    DuplicateMatchView,
    FeedbackMenuView,
    menu_colour,
)

__all__ = [
    "BUG_BUTTON_ID",
    "FEATURE_BUTTON_ID",
    "MENU_COLOURS",
    "BugReportModal",
    "DuplicateMatchView",
    "FeatureRequestModal",
    "FeedbackMenuView",
    "FeedbackModal",
    "Submission",
    "UpdateFeedbackModal",
    "build_modal",
    "file_post",
    "menu_colour",
]
