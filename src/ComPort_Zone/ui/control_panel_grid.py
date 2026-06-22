"""ControlPanel grid: manual tile geometry with spans and drag-to-place.

A custom geometry manager (no QGridLayout): spans and drop previews are
straightforward when tiles are positioned with ``setGeometry`` from the
Qt-free layout math in ``control_panel_models``. The grid mutates the
``ControlPanelConfig`` it was given via ``place_tile``/``set_tile_span`` and
emits ``layoutChanged`` so the host live-saves (FR-9, FR-33..FR-36).
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeyEvent,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from ..control_panel_models import (
    DEFAULT_GRID_COLUMNS,
    ControlPanelConfig,
    move_tiles,
    place_tile,
    set_tile_span,
    visible_row_count,
)
from ..themes import THEMES, ThemePalette
from .control_panel_tiles import (
    CONTROL_PANEL_TILE_MIME_TYPE,
    TileFrame,
    clipboard_has_tile,
    clipboard_tile_count,
    create_tile,
    tile_class_for,
)
from .tokens import SPACE_MD

GRID_GUTTER = SPACE_MD
ROW_HEIGHT_MIN = 68
ROW_HEIGHT_MAX = 160


class ControlPanelGridWidget(QWidget):
    """Renders one control_panel config as a grid of tiles."""

    layoutChanged = Signal()
    tileEditRequested = Signal(str)
    tileDuplicateRequested = Signal(str)
    tileCopyRequested = Signal(str)
    tileCutRequested = Signal(str)
    pasteRequested = Signal()
    addEntryRequested = Signal()
    tileRemoveRequested = Signal(str)
    tileEnableToggled = Signal(str, bool)
    tilePollNowRequested = Signal(str)
    tileControlActivated = Signal(str)
    tileChartRequested = Signal(str)
    editModeRequested = Signal()  # a tile long-press asks to enter edit mode
    # Keyboard shortcuts on the focused grid act on the whole selection.
    copySelectionRequested = Signal()
    cutSelectionRequested = Signal()
    deleteSelectionRequested = Signal()
    duplicateSelectionRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("controlPanelGrid")
        self.setAcceptDrops(True)
        # Focusable so keyboard shortcuts (copy/cut/paste/delete/select-all)
        # only fire while the user is working with tiles — not when a tile's
        # spinbox/input has focus (there Ctrl+C still copies text).
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._config: ControlPanelConfig | None = None
        self._tiles: dict[str, TileFrame] = {}
        self._selected_ids: set[str] = set()
        self._edit_mode = False
        self._drop_cell: tuple[int, int] | None = None
        # Drop-preview rects (col, row, span_w, span_h) — one per tile so a
        # multi-selection drag previews the whole moving group.
        self._drop_rects: list[tuple[int, int, int, int]] = []
        # Marquee (rubber-band) box-select state.
        self._band_origin: QPoint | None = None
        self._band_rect: QRect | None = None
        self._band_additive = False
        self._theme: ThemePalette = THEMES["ComPort Zone Dark"]

    # -------------------------------------------------------------- config

    @property
    def config(self) -> ControlPanelConfig | None:
        return self._config

    def set_config(self, config: ControlPanelConfig) -> None:
        """Adopt a config: create/update/remove tiles by entry id, then
        lay everything out."""
        self._config = config
        wanted = {entry.id: entry for entry in config.entries}
        for entry_id in list(self._tiles):
            entry = wanted.get(entry_id)
            tile = self._tiles[entry_id]
            recreate = entry is not None and type(tile) is not tile_class_for(entry)
            if entry is None or recreate:
                self._tiles.pop(entry_id).deleteLater()
        for entry in config.entries:
            tile = self._tiles.get(entry.id)
            if tile is None:
                tile = create_tile(entry, self)
                tile.editRequested.connect(self.tileEditRequested)
                tile.duplicateRequested.connect(self.tileDuplicateRequested)
                tile.copyRequested.connect(self.tileCopyRequested)
                tile.cutRequested.connect(self.tileCutRequested)
                tile.pasteRequested.connect(self.pasteRequested)
                tile.removeRequested.connect(self.tileRemoveRequested)
                tile.enableToggled.connect(self.tileEnableToggled)
                tile.pollNowRequested.connect(self.tilePollNowRequested)
                tile.activateRequested.connect(self.tileControlActivated)
                tile.chartRequested.connect(self.tileChartRequested)
                tile.spanRequested.connect(self._handle_span_request)
                tile.editModeRequested.connect(self.editModeRequested)
                tile.selectionToggled.connect(self._toggle_selection)
                tile.cell_metrics_provider = self._cell_stride
                tile.selected_count_provider = lambda: len(self._selected_ids)
                tile.set_edit_mode(self._edit_mode)
                tile.apply_theme_palette(self._theme)
                tile.show()
                self._tiles[entry.id] = tile
            else:
                tile.update_entry(entry)
        # Drop selection of any entry that no longer exists, then mirror
        # the (possibly pruned) selection onto the live tiles.
        self._selected_ids &= set(self._tiles)
        for entry_id, tile in self._tiles.items():
            tile.set_selected(entry_id in self._selected_ids)
        self.relayout()

    def tile(self, entry_id: str) -> TileFrame | None:
        return self._tiles.get(entry_id)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        # Right-click on empty grid space (tiles handle their own menu):
        # add a new entry, or paste a copied tile.
        if self._config is None:
            return
        menu = QMenu(self)
        add_action = menu.addAction("Add Entry…")
        add_action.triggered.connect(lambda: self.addEntryRequested.emit())
        paste_count = clipboard_tile_count()
        paste_action = menu.addAction(
            f"Paste {paste_count} Tiles" if paste_count > 1 else "Paste Tile"
        )
        paste_action.setEnabled(clipboard_has_tile())
        paste_action.triggered.connect(lambda: self.pasteRequested.emit())
        menu.exec(event.globalPos())
        menu.deleteLater()

    def tiles(self) -> list[TileFrame]:
        return list(self._tiles.values())

    # -------------------------------------------------------- selection

    def selected_ids(self) -> set[str]:
        """Entry ids currently selected (ctrl-click) for multi-tile copy."""
        return set(self._selected_ids)

    def _toggle_selection(self, entry_id: str) -> None:
        self.setFocus()  # own keyboard focus while the user selects tiles
        if entry_id in self._selected_ids:
            self._selected_ids.discard(entry_id)
        else:
            self._selected_ids.add(entry_id)
        tile = self._tiles.get(entry_id)
        if tile is not None:
            tile.set_selected(entry_id in self._selected_ids)

    def select_all(self) -> None:
        self.set_selection(set(self._tiles))

    def set_selection(self, ids: set[str]) -> None:
        """Replace the selection with ``ids`` (intersected with live tiles)."""
        self._selected_ids = set(ids) & set(self._tiles)
        for entry_id, tile in self._tiles.items():
            tile.set_selected(entry_id in self._selected_ids)

    def clear_selection(self) -> None:
        if not self._selected_ids:
            return
        self._selected_ids.clear()
        for tile in self._tiles.values():
            tile.set_selected(False)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # Press on empty grid space (tiles handle their own clicks) begins a
        # marquee. A no-drag click clears the selection on release; a drag
        # box-selects. Ctrl makes the marquee additive.
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self._band_origin = event.position().toPoint()
            self._band_rect = None
            self._band_additive = bool(
                event.modifiers() & Qt.KeyboardModifier.ControlModifier
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._band_origin is not None and (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            self._band_rect = QRect(
                self._band_origin, event.position().toPoint()
            ).normalized()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._band_origin is not None:
            origin = self._band_origin
            rect = self._band_rect
            self._band_origin = None
            self._band_rect = None
            self.update()
            dragged = (
                event.position().toPoint() - origin
            ).manhattanLength() >= QApplication.startDragDistance()
            if dragged and rect is not None:
                hit = {
                    entry_id
                    for entry_id, tile in self._tiles.items()
                    if tile.geometry().intersects(rect)
                }
                self.set_selection((self._selected_ids | hit) if self._band_additive else hit)
            elif not self._band_additive:
                self.clear_selection()  # a plain click clears
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        # Only fires when the grid itself has focus (see setFocusPolicy), so
        # these never hijack copy/paste from a focused spinbox or search box.
        key = event.key()
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        has_selection = bool(self._selected_ids)
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and has_selection:
            self.deleteSelectionRequested.emit()
        elif ctrl and key == Qt.Key.Key_A:
            self.select_all()
        elif ctrl and key == Qt.Key.Key_C and has_selection:
            self.copySelectionRequested.emit()
        elif ctrl and key == Qt.Key.Key_X and has_selection:
            self.cutSelectionRequested.emit()
        elif ctrl and key == Qt.Key.Key_V:
            self.pasteRequested.emit()
        elif ctrl and key == Qt.Key.Key_D and has_selection:
            self.duplicateSelectionRequested.emit()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def apply_theme_palette(self, theme: ThemePalette) -> None:
        self._theme = theme
        for tile in self._tiles.values():
            tile.apply_theme_palette(theme)

    # ------------------------------------------------------------ edit mode

    def set_edit_mode(self, enabled: bool) -> None:
        self._edit_mode = enabled
        for tile in self._tiles.values():
            tile.set_edit_mode(enabled)
        self.update()

    @property
    def edit_mode(self) -> bool:
        return self._edit_mode

    # -------------------------------------------------------------- layout

    def _cell_metrics(self) -> tuple[float, float, int]:
        """(cell width, row height, columns) for the current width."""
        columns = self._config.columns if self._config else DEFAULT_GRID_COLUMNS
        available = max(0, self.width() - GRID_GUTTER * (columns + 1))
        cell_w = available / columns if columns else 0
        row_h = int(max(ROW_HEIGHT_MIN, min(ROW_HEIGHT_MAX, cell_w * 0.6)))
        return cell_w, row_h, columns

    def _cell_stride(self) -> tuple[float, float, int]:
        """Per-cell stride (cell size + gutter) + column count, handed to
        tiles so a corner-drag in pixels maps to whole-cell spans."""
        cell_w, row_h, columns = self._cell_metrics()
        return cell_w + GRID_GUTTER, row_h + GRID_GUTTER, columns

    def relayout(self) -> None:
        """Position every tile from its TilePlacement (manual geometry)."""
        if self._config is None:
            return
        cell_w, row_h, _columns = self._cell_metrics()
        for entry in self._config.entries:
            tile = self._tiles.get(entry.id)
            if tile is None:
                continue
            placement = entry.tile
            x = round(GRID_GUTTER + placement.col * (cell_w + GRID_GUTTER))
            y = GRID_GUTTER + placement.row * (row_h + GRID_GUTTER)
            width = round(placement.span_w * cell_w + (placement.span_w - 1) * GRID_GUTTER)
            height = placement.span_h * row_h + (placement.span_h - 1) * GRID_GUTTER
            tile.setGeometry(x, y, width, height)
            tile.apply_cell_width(cell_w)
        self.setMinimumHeight(self._content_height())
        self.updateGeometry()

    def _content_height(self) -> int:
        if self._config is None:
            return GRID_GUTTER * 2
        _cell_w, row_h, _columns = self._cell_metrics()
        rows = visible_row_count(self._config)
        return GRID_GUTTER + rows * (row_h + GRID_GUTTER)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        self.relayout()

    def cell_at(self, x: int, y: int, span_w: int = 1) -> tuple[int, int]:
        """Grid cell under a widget-local point, clamped so a tile of
        ``span_w`` still fits the row."""
        cell_w, row_h, columns = self._cell_metrics()
        col = int((x - GRID_GUTTER) // (cell_w + GRID_GUTTER)) if cell_w else 0
        row = int((y - GRID_GUTTER) // (row_h + GRID_GUTTER))
        col = max(0, min(col, columns - max(1, span_w)))
        row = max(0, row)
        return col, row

    # ----------------------------------------------------------- drag/drop

    def _drag_entry_id(self, event) -> str:
        data = event.mimeData().data(CONTROL_PANEL_TILE_MIME_TYPE)
        return bytes(data).decode("utf-8") if data else ""

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._edit_mode and event.mimeData().hasFormat(CONTROL_PANEL_TILE_MIME_TYPE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if not self._edit_mode or self._config is None:
            event.ignore()
            return
        position = event.position().toPoint()
        preview = self._compute_drop(self._drag_entry_id(event), position.x(), position.y())
        if preview is None:
            event.ignore()
            return
        self._drop_cell, self._drop_rects = preview
        self.update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        self._drop_cell = None
        self._drop_rects = []
        self.update()
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        entry_id = self._drag_entry_id(event)
        cell = self._drop_cell
        self._drop_cell = None
        self._drop_rects = []
        self.update()
        if not entry_id or cell is None:
            event.ignore()
            return
        self._handle_tile_drop(entry_id, cell[0], cell[1])
        event.acceptProposedAction()

    def _compute_drop(
        self, anchor_id: str, x: int, y: int
    ) -> tuple[tuple[int, int], list[tuple[int, int, int, int]]] | None:
        """Resolve a drag into the anchor's target cell + preview rects.

        A single tile previews one rect at its clamped target. A drag of a
        tile that is part of a multi-selection moves the whole group by one
        clamped delta (mirrors ``move_tiles``), previewing every member."""
        if self._config is None:
            return None
        anchor = self._config.entry_by_id(anchor_id)
        if anchor is None:
            return None
        col, row = self.cell_at(x, y, anchor.tile.span_w)
        if anchor_id in self._selected_ids and len(self._selected_ids) > 1:
            group = [e for e in self._config.entries if e.id in self._selected_ids]
            columns = self._config.columns
            dcol = col - anchor.tile.col
            drow = row - anchor.tile.row
            min_col = min(e.tile.col for e in group)
            min_row = min(e.tile.row for e in group)
            max_right = max(e.tile.col + e.tile.span_w for e in group)
            dcol = max(-min_col, min(dcol, columns - max_right))
            drow = max(-min_row, drow)
            rects = [
                (e.tile.col + dcol, e.tile.row + drow, e.tile.span_w, e.tile.span_h)
                for e in group
            ]
            return (anchor.tile.col + dcol, anchor.tile.row + drow), rects
        return (col, row), [(col, row, anchor.tile.span_w, anchor.tile.span_h)]

    def _handle_tile_drop(self, entry_id: str, col: int, row: int) -> None:
        if self._config is None:
            return
        if entry_id in self._selected_ids and len(self._selected_ids) > 1:
            anchor = self._config.entry_by_id(entry_id)
            if anchor is None:
                return
            moved = move_tiles(
                self._config.entries,
                self._config.columns,
                set(self._selected_ids),
                col - anchor.tile.col,
                row - anchor.tile.row,
            )
        else:
            moved = place_tile(self._config.entries, self._config.columns, entry_id, col, row)
        if moved:
            self.relayout()
            self.layoutChanged.emit()

    def _handle_span_request(self, entry_id: str, span_w: int, span_h: int) -> None:
        if self._config is None:
            return
        if set_tile_span(self._config.entries, self._config.columns, entry_id, span_w, span_h):
            entry = self._config.entry_by_id(entry_id)
            tile = self._tiles.get(entry_id)
            if entry is not None and tile is not None:
                tile.update_entry(entry)
            self.relayout()
            self.layoutChanged.emit()

    # ---------------------------------------------------------------- paint

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._band_rect is not None:
            painter = QPainter(self)
            accent = QColor(self._theme.accent)
            fill = QColor(accent)
            fill.setAlpha(40)
            painter.setBrush(fill)
            painter.setPen(QPen(accent, 1))
            painter.drawRect(self._band_rect)
            painter.end()
        if not self._drop_rects:
            return
        cell_w, row_h, _columns = self._cell_metrics()
        painter = QPainter(self)
        pen = QPen(QColor(self._theme.accent))
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        for col, row, span_w, span_h in self._drop_rects:
            rect = QRect(
                round(GRID_GUTTER + col * (cell_w + GRID_GUTTER)),
                GRID_GUTTER + row * (row_h + GRID_GUTTER),
                round(span_w * cell_w + (span_w - 1) * GRID_GUTTER),
                span_h * row_h + (span_h - 1) * GRID_GUTTER,
            )
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)
        painter.end()
