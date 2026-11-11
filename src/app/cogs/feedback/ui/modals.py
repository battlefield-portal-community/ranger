"""The intake modals: the bug and feature forms, and the filing itself.

Both forms share :class:`FeedbackModal`, which builds its inputs from
:mod:`..forms` and files the post through :func:`file_post`. The submit order is the
part that has to be right, and is documented on :meth:`FeedbackModal.on_submit`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import discord

from .... import db
from .. import dedupe, forms, tags
from .. import settings as feedback_settings

log = logging.getLogger(__name__)

# Discord's own caps. discord.py validates neither, and Discord answers with a 400
# when the modal opens, so they are asserted where the labels are built.
MAX_LABEL_TEXT = 45
MAX_LABEL_DESCRIPTION = 100

# A file upload component cannot offer more slots than this.
MAX_UPLOAD_FILES = 10


@dataclass
class Submission:
    """A filled-in form, held so a deferred submit (or "File anyway") can finish."""

    kind: str
    forum: discord.ForumChannel
    reporter_id: int
    fields: dict[str, str]
    media: list[discord.Attachment]
    interaction_id: str


async def _reply(
    interaction: discord.Interaction,
    content: str,
    *,
    view: discord.ui.View | None = None,
) -> None:
    """Answer wherever the interaction has room left to answer.

    ``view`` is only passed along when there is one: discord.py's senders take
    ``MISSING`` as "no view", and reject an explicit ``None``.
    """
    kwargs: dict[str, object] = {"ephemeral": True}
    if view is not None:
        kwargs["view"] = view
    if interaction.response.is_done():
        await interaction.followup.send(content, **kwargs)
    else:
        await interaction.response.send_message(content, **kwargs)


def _duplicate_prompt(matches: list[db.FeedbackPost], guild_id: int | None) -> str:
    lines = ["**This may already be filed:**"]
    for post in matches:
        lines.append(
            f"• {post.summary} — "
            f"<https://discord.com/channels/{guild_id}/{post.thread_id}>"
        )
    lines.append("Open one of them, or file this as a new post.")
    return "\n".join(lines)


async def file_post(
    interaction: discord.Interaction,
    submission: Submission,
    *,
    force: bool = False,
) -> None:
    """File a submission in its forum, stopping at the duplicate prompt first."""
    try:
        body = forms.build_body(
            submission.kind, submission.reporter_id, submission.fields
        )
        name = forms.thread_name(submission.fields["summary"])
    except KeyError, ValueError:
        log.exception("The %s form does not fit its message budget", submission.kind)
        await _reply(interaction, "The form is misconfigured; ping a mod.")
        return

    limit = interaction.filesize_limit
    total = sum(attachment.size for attachment in submission.media)
    if total > limit:
        await _reply(
            interaction,
            f"That upload is {total // 2**20} MB in total, over the "
            f"{limit // 2**20} MB I can take. Submit again with fewer files.",
        )
        return

    if not force:
        try:
            matches = await dedupe.search(name, body)
        except Exception:
            # A broken index must not cost a report; file it and log.
            log.exception("The dedupe preflight failed; filing anyway")
            matches = []
        if matches:
            dedupe.remember(submission.reporter_id, submission)
            # ui.views imports the modals, so the prompt is imported here.
            from .views import DuplicateMatchView

            await _reply(
                interaction,
                _duplicate_prompt(matches, interaction.guild_id),
                view=DuplicateMatchView(matches, interaction.guild_id),
            )
            return

    applied = []
    game = tags.game_tag(submission.forum)
    if game is None:
        log.error(
            "Forum %s has no %r tag",
            submission.forum.id,
            feedback_settings.settings().DEFAULT_GAME_TAG,
        )
        await _reply(
            interaction, "That forum is missing the tag I file with; ping a mod."
        )
        return
    applied.append(game)
    if submission.kind == "feature":
        feature = tags.feature_tag(submission.forum)
        if feature is None:
            log.error(
                "Forum %s has no %r tag",
                submission.forum.id,
                feedback_settings.settings().FEATURE_TAG,
            )
            await _reply(
                interaction, "That forum is missing the tag I file with; ping a mod."
            )
            return
        applied.append(feature)

    files = [await attachment.to_file() for attachment in submission.media]
    try:
        result = await submission.forum.create_thread(
            name=name,
            content=body,
            applied_tags=applied,
            # The body names the reporter; it must not ping them.
            allowed_mentions=discord.AllowedMentions.none(),
            files=files or None,
        )
    except discord.Forbidden:
        log.warning("Not allowed to create posts in forum %s", submission.forum.id)
        await _reply(interaction, "I can't post in that forum; ping a mod.")
        return
    except discord.HTTPException:
        log.exception("Filing a %s post failed", submission.kind)
        await _reply(
            interaction, "Something went wrong filing that; try again or ping a mod."
        )
        return

    thread_id = result.thread.id
    filed = await db.create_feedback(
        thread_id=thread_id,
        forum_id=submission.forum.id,
        kind=submission.kind,
        reporter_id=submission.reporter_id,
        summary=name,
        body=body,
        interaction_id=submission.interaction_id,
    )
    if not filed:
        # This submit was already recorded, so the thread it just created is a
        # duplicate and has to go.
        try:
            await result.thread.delete()
        except discord.HTTPException:
            log.exception("Could not delete the duplicate thread %s", thread_id)
        await _reply(interaction, "That report is already filed.")
        return

    await db.log_feedback_event(
        thread_id, "create", submission.reporter_id, submission.kind
    )
    if force:
        await db.log_feedback_event(
            thread_id, "dedupe", submission.reporter_id, "filed anyway"
        )
    await db.index_feedback(thread_id, name, body)

    tag_names = ", ".join(f"`{tag.name}`" for tag in applied)
    await _reply(
        interaction,
        f"Filed: {result.thread.jump_url} · tagged {tag_names}. A mod can retag it.",
    )


class FeedbackModal(discord.ui.Modal):
    """Base for the two intake forms; subclasses set :attr:`kind` and the title."""

    kind: str
    modal_title = "Feedback"

    def __init__(
        self,
        forum: discord.ForumChannel,
        *,
        filesize_mb: int,
        max_files: int,
    ) -> None:
        super().__init__(title=self.modal_title)
        self.forum = forum
        self._inputs: dict[str, discord.ui.TextInput] = {}

        for form_field in forms.fields(self.kind):
            assert len(form_field.label) <= MAX_LABEL_TEXT, form_field.label
            assert len(form_field.hint) <= MAX_LABEL_DESCRIPTION, form_field.hint
            text_input = discord.ui.TextInput(
                style=(
                    discord.TextStyle.paragraph
                    if form_field.paragraph
                    else discord.TextStyle.short
                ),
                required=True,
                max_length=form_field.limit,
            )
            self._inputs[form_field.key] = text_input
            self.add_item(
                discord.ui.Label(
                    text=form_field.label,
                    description=form_field.hint,
                    component=text_input,
                )
            )

        media_hint = f"Optional · max {filesize_mb} MB each · up to {max_files} files"
        assert len(media_hint) <= MAX_LABEL_DESCRIPTION, media_hint
        self.media = discord.ui.FileUpload(
            # `required` defaults to True, so optional media has to say so.
            required=False,
            min_values=0,
            max_values=max_files,
        )
        self.add_item(
            discord.ui.Label(
                text="Screenshots or video",
                description=media_hint,
                component=self.media,
            )
        )

    def _values(self) -> dict[str, str]:
        return {
            key: text_input.value.strip() for key, text_input in self._inputs.items()
        }

    async def on_submit(self, interaction: discord.Interaction) -> None:
        # Reading the uploads and creating the thread outlast the 3 s window.
        await interaction.response.defer(ephemeral=True, thinking=True)
        await file_post(
            interaction,
            Submission(
                kind=self.kind,
                forum=self.forum,
                reporter_id=interaction.user.id,
                fields=self._values(),
                media=list(self.media.values),
                interaction_id=str(interaction.id),
            ),
        )


class BugReportModal(FeedbackModal):
    """The bug form: summary, what happens, steps, optional media."""

    kind = "bug"
    modal_title = "Report a Bug"


class FeatureRequestModal(FeedbackModal):
    """The feature form: summary, want, why, example, optional media."""

    kind = "feature"
    modal_title = "Request a Feature"


def build_modal(
    kind: str, forum: discord.ForumChannel, *, filesize_mb: int
) -> FeedbackModal:
    """Build the form for ``kind`` with the configured upload allowance."""
    max_files = max(
        1, min(feedback_settings.settings().MAX_UPLOAD_FILES, MAX_UPLOAD_FILES)
    )
    modal = {"bug": BugReportModal, "feature": FeatureRequestModal}[kind]
    return modal(forum, filesize_mb=filesize_mb, max_files=max_files)
