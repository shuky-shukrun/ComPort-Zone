"""ControlPanel grid: manual tile geometry with spans and drag-to-place.

A custom geometry manager (no QGridLayout): spans and drop previews are
straightforward when tiles are positioned with ``setGeometry`` from the
Qt-free layout math in ``control_panel_models``. The grid mutates the
``ControlPanelConfig`` it was given via ``place_tile``/``set_tile_span`` and
emits ``layoutChanged`` so the host live-saves (FR-9, FR-33..FR-36).
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QPaintEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QWidget

from ..control_panel_models import (
    DEFAULT_GRID_COLUMNS,
    ControlPanelConfig,
    place_tile,
    set_tile_span,
    visible_row_count,
)
from ..themes import THEMES, ThemePalette
from .control_panel_tiles import (
    CONTROL_PANEL_TILE_MIME_TYPE,
    TileFrame,
    create_tile,
    tile_class_for,
)
from .tokens import SPACE_MD

GRID_GUTTER = SPACE_MD
ROW_HEIGHT_MIN = 76
ROW_HEIGHT_MAX = 170


class ControlPanelGridWidget(QWidget):
    """Renders one control_panel config as a grid of tiles."""

    layoutChanged = Signal()
    tileEditRequested = Signal(str)
    tileDuplicateRequested = Signal(str)
    tileRemoveRequested = Signal(str)
    tileEnableToggled = Signal(str, bool)
    tilePollNowRequested = Signal(str)
    tileControlActivated = Signal(str)
    tileChartRequested = Signal(str)
    editModeRequested = Signal()  # a tile long-press asks to enter edit mode

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("controlPanelGrid")
        self.setAcceptDrops(True)
        self._config: ControlPanelConfig | None = None
        self._tiles: dict[str, TileFrame] = {}
        self._edit_mode = False
        self._drop_cell: tuple[int, int] | None = None
        self._drop_span: tuple[int, int] = (1, 1)
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
                tile.removeRequested.connect(self.tileRemoveRequested)
                tile.enableToggled.connect(self.tileEnableToggled)
                tile.pollNowRequested.connect(self.tilePollNowRequested)
                tile.activateRequested.connect(self.tileControlActivated)
                tile.chartRequested.connect(self.tileChartRequested)
                tile.spanRequested.connect(self._handle_span_request)
                tile.editModeRequested.connect(self.editModeRequested)
                tile.cell_metrics_provider = self._cell_stride
                tile.set_edit_mode(self._edit_mode)
                tile.apply_theme_palette(self._theme)
                tile.show()
                self._tiles[entry.id] = tile
            else:
                tile.update_entry(entry)
        self.relayout()

    def tile(self, entry_id: str) -> TileFrame | None:
        return self._tiles.get(entry_id)

    def tiles(self) -> list[TileFrame]:
        return list(self._tiles.values())

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
        entry = self._config.entry_by_id(self._drag_entry_id(event))
        span = (entry.tile.span_w, entry.tile.span_h) if entry else (1, 1)
        position = event.position().toPoint()
        self._drop_cell = self.cell_at(position.x(), position.y(), span[0])
        self._drop_span = span
        self.update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        self._drop_cell = None
        self.update()
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        entry_id = self._drag_entry_id(event)
        cell = self._drop_cell
        self._drop_cell = None
        self.update()
        if not entry_id or cell is None:
            event.ignore()
            return
        self._handle_tile_drop(entry_id, cell[0], cell[1])
        event.acceptProposedAction()

    def _handle_tile_drop(self, entry_id: str, col: int, row: int) -> None:
        if self._config is None:
            return
        if place_tile(self._config.entries, self._config.columns, entry_id, col, row):
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
        if self._drop_cell is None:
            return
        cell_w, row_h, _columns = self._cell_metrics()
        col, row = self._drop_cell
        span_w, span_h = self._drop_span
        rect = QRect(
            round(GRID_GUTTER + col * (cell_w + GRID_GUTTER)),
            GRID_GUTTER + row * (row_h + GRID_GUTTER),
            round(span_w * cell_w + (span_w - 1) * GRID_GUTTER),
            span_h * row_h + (span_h - 1) * GRID_GUTTER,
        )
        painter = QPainter(self)
        pen = QPen(QColor(self._theme.accent))
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)
        painter.end()
