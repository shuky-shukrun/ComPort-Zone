from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
)

from ...version_check import VersionCheckResult, build_release_notes_document


class VersionUpdateDialog(QDialog):
    """Update prompt, with the release notes of every version being skipped.

    When more than one release is newer than the running build, the notes of
    all of them are accumulated newest-first into one scrollable viewer, so a
    user several versions behind sees everything they missed rather than only
    the newest release's notes.
    """

    # Bounds for the notes viewer: tall enough that scrolling is worth it, short
    # enough that a long accumulated document still leaves the dialog on screen.
    NOTES_WIDTH = 620
    NOTES_MIN_HEIGHT = 160
    NOTES_MAX_HEIGHT = 420

    def __init__(
        self,
        result: VersionCheckResult,
        check_on_launch: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(
            "New Version Available"
            if result.update_available
            else "ComPort Zone Is Up to Date"
        )
        self.setMinimumWidth(420)

        title_text = (
            f"ComPort Zone {escape(result.latest_version)} is available"
            if result.update_available
            else "ComPort Zone is up to date"
        )
        title = QLabel(title_text, self)
        title.setObjectName("dialogTitle")
        title.setWordWrap(True)

        body = QLabel(self._body_text(result), self)
        body.setWordWrap(True)

        release_url = escape(result.release_url, quote=True)
        link = QLabel(f'<a href="{release_url}">{release_url}</a>', self)
        link.setTextFormat(Qt.TextFormat.RichText)
        link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        link.setOpenExternalLinks(True)
        link.setWordWrap(True)

        self.check_on_launch = QCheckBox("Check for updates when ComPort Zone starts", self)
        self.check_on_launch.setChecked(check_on_launch)

        if result.update_available:
            buttons = QDialogButtonBox(self)
            install_button = buttons.addButton(
                "Download and Install", QDialogButtonBox.ButtonRole.AcceptRole
            )
            buttons.addButton("Later", QDialogButtonBox.ButtonRole.RejectRole)
            install_button.setDefault(True)
        else:
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(body)

        self.release_notes: QTextBrowser | None = self._build_release_notes(result)
        if self.release_notes is not None:
            notes_label = QLabel(
                "What's new in this update:"
                if len(result.releases) == 1
                else f"What's new across the {len(result.releases)} releases you are missing:",
                self,
            )
            notes_label.setWordWrap(True)
            layout.addWidget(notes_label)
            layout.addWidget(self.release_notes, 1)

        layout.addWidget(link)
        layout.addWidget(self.check_on_launch)
        layout.addWidget(buttons)

        if self.release_notes is not None:
            self._size_to_release_notes(self.release_notes)

    @staticmethod
    def _body_text(result: VersionCheckResult) -> str:
        if not result.update_available:
            return (
                "You are using the latest version of ComPort Zone "
                f"({escape(result.current_version)})."
            )
        behind = len(result.releases)
        running = (
            f"You are running version {escape(result.current_version)}"
            f", {behind} releases behind."
            if behind > 1
            else f"You are running version {escape(result.current_version)}."
        )
        return f"{running} Download and run the installer, or open the release page below."

    def _build_release_notes(self, result: VersionCheckResult) -> QTextBrowser | None:
        """Scrollable viewer holding the accumulated notes, or ``None`` if there are none."""
        if not result.releases:
            return None
        document = build_release_notes_document(result.releases)
        if not document.strip():
            return None
        view = QTextBrowser(self)
        view.setObjectName("releaseNotesView")
        view.setOpenExternalLinks(True)
        # Sanitized rich text (see version_check.sanitize_release_notes_html):
        # no images, scripts, or non-http(s) links reach this document.
        # Qt ignores CSS font-size on h1..h6 (it sizes them from the tag), so
        # only non-heading rules belong here — the headings are levelled in
        # build_release_notes_document instead.
        view.document().setDefaultStyleSheet("p.releaseMeta { font-size: 11px; }")
        view.setHtml(document)
        view.moveCursor(view.textCursor().MoveOperation.Start)
        view.setMinimumHeight(self.NOTES_MIN_HEIGHT)
        view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        view.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
        return view

    def _size_to_release_notes(self, view: QTextBrowser) -> None:
        """Open at the height the notes actually need, capped, then stay resizable."""
        # Measure against the styled font, not the pre-polish default one, or a
        # short set of notes reserves far more room than it fills.
        self.ensurePolished()
        view.ensurePolished()
        # Measure on a detached copy: a live QTextEdit document's text width is
        # owned by its viewport, so setting it here would just be overwritten
        # (and read back as the not-yet-laid-out widget's width). The copy is
        # deliberately parentless so Python frees it when this returns.
        probe = view.document().clone()
        probe.setTextWidth(self.NOTES_WIDTH - 60)
        needed = int(probe.size().height()) + 2 * int(probe.documentMargin()) + 8
        preferred = max(self.NOTES_MIN_HEIGHT, min(needed, self.NOTES_MAX_HEIGHT))
        # Raise the minimum so the dialog's size hint accounts for the notes,
        # then relax it so the user can still shrink the dialog afterwards.
        view.setMinimumHeight(preferred)
        self.resize(self.NOTES_WIDTH, self.sizeHint().height())
        view.setMinimumHeight(self.NOTES_MIN_HEIGHT)

    def release_notes_text(self) -> str:
        """Plain text of the accumulated notes (empty when none were shown)."""
        return "" if self.release_notes is None else self.release_notes.toPlainText()

    def check_on_launch_enabled(self) -> bool:
        return self.check_on_launch.isChecked()
