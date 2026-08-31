"""
Class Widgets 2.0 - 今日课程显示插件 (独立全屏窗口版)
显示当日所有课程缩写，并高亮当前课程，使用mask仅显示UI区域
"""

import os
import sys
import json
import time
import sqlite3
import ctypes
import darkdetect
from loguru import logger
from PySide6.QtCore import QObject, QUrl, Slot, Property, Signal, QTimer, QEvent, QPointF, QSize
from PySide6.QtGui import (QGuiApplication, QScreen, QRegion, QCursor,
                           QPainter, QPainterPath, QPen, QColor, QImage,
                           QPolygonF)
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickImageProvider
from ClassWidgets.SDK import CW2Plugin
from PySide6.QtCore import Qt

# 深浅色主题跟随主程序 RinUI ThemeManager（Light/Dark/Auto），无 RinUI 时回退 darkdetect。
try:
    from RinUI.core.theme import ThemeManager as RinThemeManager
    _HAS_RIN_THEME = True
except Exception:
    RinThemeManager = None
    _HAS_RIN_THEME = False

plugin_logger = logger.bind(plugin="lessons-displayer")

DEFAULT_UI_WIDTH = 100
UI_HEIGHT = 54

# 插件设置默认值：配置文件有对应项则用之，否则回落默认；"恢复默认设置"= 删除配置文件。
DEFAULT_SETTINGS = {
    "animation_performance": True, # 动画性能优化（高级设置，默认启用）
    "widgets_layer": "follow",   # 小组件图层：跟随软件设置(follow)/始终置顶(top)/始终置底(bottom)
    "countdown_style": "default", # 倒计时样式：默认字号(default)/大字号(large)
    "auto_close_after_class": True, # 下课后自动关闭特殊模式
    "auto_close_delay": 3,       # 下课后自动关闭的延迟时间数值
    "auto_close_unit": "min",    # 延迟时间单位：min(分)/sec(秒)
    "device_type": "interactive_panel", # 设备类型：交互智能平板(interactive_panel)/投影设备或其他(projector)
}

SETTINGS_CONFIG_FILENAME = "settings.json"


def _time_to_minutes(time_str: str) -> int:
    """将 "HH:MM" 格式的时间转换为分钟数"""
    h, m = map(int, time_str.split(':'))
    return h * 60 + m


# 笔触逻辑颜色 → 实际显示色（light=浅色模式/白板、dark=深色模式/熄屏）。
# 存储用逻辑名（如 "mono"/"red"），显示时按当前模式取对应 hex；
# 切换模式时已画笔触的显示色随之切换（重放时按最新模式解析）。
_PEN_COLOR_MAP = {
    "mono":   {"light": "#000000", "dark": "#FFFFFF"},   # 黑/白（白板黑、熄屏白）
    "red":    {"light": "#C62828", "dark": "#EF5350"},
    "blue":   {"light": "#1565C0", "dark": "#42A5F5"},
    "green":  {"light": "#2E7D32", "dark": "#66BB6A"},
    "orange": {"light": "#EF6C00", "dark": "#FFA726"},
    "yellow": {"light": "#F9A825", "dark": "#FFEE58"},
    "cyan":   {"light": "#00838F", "dark": "#4DD0E1"},
    "purple": {"light": "#6A1B9A", "dark": "#AB47BC"},
}


def _pen_display_color(logical, light):
    """笔触逻辑颜色名 → 当前模式显示 hex；未知（如旧数据的 hex）原样返回。"""
    entry = _PEN_COLOR_MAP.get(logical)
    if not entry:
        return logical
    return entry["light" if light else "dark"]


def _stroke_path(points, width):
    """把笔划点列（逻辑坐标）平滑成 Catmull-Rom → 三次贝塞尔 QPainterPath。

    相邻两点之间用一段三次贝塞尔曲线，其两个控制点由前后相邻点决定
    （Catmull-Rom 张力 1/6），曲线精确穿过每个输入点，绘制再快、采样点
    再稀疏也不会出现折线。首/末段以端点自身做镜像补点，避免端部切线突变。
    单点或全部重合（零长度）的退化路径回退为圆点（笔=圆点、橡皮=点擦圆），
    否则 Qt 不渲染零长度线段的 round cap，点擦/单击会失效。
    """
    path = QPainterPath()
    if not points:
        return path
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    if len(points) == 1 or (max(xs) - min(xs) < 0.01 and max(ys) - min(ys) < 0.01):
        x, y = points[0]
        r = max(0.5, width / 2.0)
        path.addEllipse(QPointF(x, y), r, r)
        return path

    def _pt(i):
        return QPointF(points[i][0], points[i][1])

    n = len(points)
    path.moveTo(points[0][0], points[0][1])
    for i in range(n - 1):
        p0 = _pt(max(0, i - 1))
        p1 = _pt(i)
        p2 = _pt(i + 1)
        p3 = _pt(min(n - 1, i + 2))
        c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6.0,
                     p1.y() + (p2.y() - p0.y()) / 6.0)
        c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6.0,
                     p2.y() - (p3.y() - p1.y()) / 6.0)
        path.cubicTo(c1, c2, p2)
    return path


def _draw_stroke(painter, stroke, light=True):
    """在给定 QPainter 上绘制一笔（pen 用颜色描边 / eraser 用 Clear 擦除）。

    注意：QPainter 的合成模式会跨调用持续，重放时橡皮（Clear）后的笔画必须
    显式回到 SourceOver，否则后续笔画会被错误地"擦除"。
    单点/重合点（点状笔迹）用 fillPath 填充闭合圆，避免被 pen 描边再放大
    一倍（addEllipse 半径=width/2 + width 描边 → 外径=width，直径=2*width）。
    pen 颜色为逻辑名（"mono"/"red"...），按 light（是否浅色模式）解析为显示 hex。
    """
    if not stroke or not stroke.get("points"):
        return
    points = stroke["points"]
    width = stroke.get("width", 4.0)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    is_dot = len(points) == 1 or (max(xs) - min(xs) < 0.01 and max(ys) - min(ys) < 0.01)
    path = _stroke_path(points, width)
    if stroke["op"] == "eraser":
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        if is_dot:
            painter.fillPath(path, QColor(Qt.transparent))
        else:
            # 显式 NoBrush：防止被上一笔的 setBrush 残留填充（封闭路径会被填充）
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(Qt.transparent), width,
                                Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(path)
    else:
        color = _pen_display_color(stroke.get("color", "mono"), light)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        if is_dot:
            painter.fillPath(path, QColor(color))
        else:
            # 显式 NoBrush：防止被上一笔的 setBrush 残留填充（封闭路径会被填充）
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(color), width,
                                Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(path)


# 选择工具的统一选中蓝（描边/填充/矩形边框/虚线共用，深浅色一致）
SELECTION_BLUE = "#1E88E5"


def _draw_selection_outline(painter, stroke, light=True):
    """在被选中笔划下方画 2px 蓝色描边（先画宽 width+4 的蓝色，再画原笔划覆盖 → 边缘留 2px 蓝）。

    仅对 pen 笔划生效（橡皮是不可见的透明擦除区，不参与选择）。点状笔划先填
    半径+2 的蓝色圆，再被原笔划覆盖 → 外围 2px 蓝圈。
    """
    if not stroke or stroke.get("op") != "pen" or not stroke.get("points"):
        return
    points = stroke["points"]
    width = stroke.get("width", 4.0)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    is_dot = len(points) == 1 or (max(xs) - min(xs) < 0.01 and max(ys) - min(ys) < 0.01)
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
    if is_dot:
        x, y = points[0]
        r = max(0.5, width / 2.0) + 2.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(SELECTION_BLUE))
        painter.drawEllipse(QPointF(x, y), r, r)
        # 关键：重置 brush，否则残留蓝色会让后续 drawPath 填充封闭路径
        painter.setBrush(Qt.NoBrush)
    else:
        path = _stroke_path(points, width)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(SELECTION_BLUE), width + 4.0,
                            Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(path)


class StrokeStore:
    """特殊模式笔迹/橡皮数据的 SQLite 增量存储（支持撤销回滚的会话链）。

    每个"画布会话"对应一个 data/canvas_<时间戳>.db 文件；每一步操作增量落盘：
    - strokes 表：一笔一行的增量保存（pen/eraser），每笔 commit。
    - ops 表：操作日志（add/clear/modify），记录每次增量操作，供撤销参考。
    - meta 表：屏幕分辨率（像素宽高）/DPR/模式/创建时间，以及清屏链信息：
      `prev_file`（本会话由哪个文件清屏而来）、`created_by`（"initial"/"clear"）。
    清屏时保留旧文件、新建空白会话文件并记录 prev_file；撤销清屏时切回 prev_file、
    删除空白文件，之后的笔迹写回旧文件。启动时 open_latest() 恢复最近一次会话。
    """

    def __init__(self, data_dir):
        self._data_dir = data_dir
        self._conn = None
        self._db_path = None

    def _ensure_dir(self):
        try:
            os.makedirs(self._data_dir, exist_ok=True)
        except Exception as e:
            plugin_logger.debug(f"创建数据目录失败: {e}")

    @property
    def db_path(self):
        return self._db_path

    @property
    def has_session(self):
        return self._conn is not None

    @property
    def data_dir(self):
        """数据目录路径（供多页注册表 pages.json 使用）。"""
        return self._data_dir

    def current_file(self):
        """当前会话文件名（basename）；无会话返回 None。"""
        return os.path.basename(self._db_path) if self._db_path else None

    def _ensure_tables(self):
        """确保三张表存在（兼容旧文件：只有 meta/strokes，无 ops）。"""
        try:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS strokes("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " op TEXT NOT NULL,"
                " color TEXT,"
                " width REAL,"
                " points TEXT NOT NULL,"
                " created_at TEXT)")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS ops("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " type TEXT NOT NULL,"
                " data TEXT NOT NULL,"
                " created_at TEXT)")
            self._conn.commit()
        except Exception as e:
            plugin_logger.debug(f"建表失败: {e}")

    def _write_meta(self, key, value):
        try:
            self._conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                               (key, str(value)))
            self._conn.commit()
        except Exception as e:
            plugin_logger.debug(f"写 meta 失败: {e}")

    def _meta_value(self, key, default=""):
        if self._conn is None:
            return default
        try:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return row[0] if row else default
        except Exception:
            return default

    def open_session(self, name):
        """打开指定会话文件（basename）作为当前会话；不存在返回 False。"""
        self.close()
        if not name:
            return False
        path = os.path.join(self._data_dir, name)
        if not os.path.exists(path):
            return False
        try:
            self._db_path = path
            self._conn = sqlite3.connect(path)
            self._ensure_tables()
            return True
        except Exception as e:
            plugin_logger.debug(f"打开会话文件失败: {e}")
            self._conn = None
            self._db_path = None
            return False

    def open_latest(self):
        """恢复最近一次会话文件（跨进程重启后保留上次白板内容与清屏链）。"""
        try:
            names = [n for n in os.listdir(self._data_dir)
                     if n.startswith("canvas_") and n.endswith(".db")]
        except Exception:
            names = []
        if not names:
            return False
        try:
            names.sort(key=lambda n: os.path.getmtime(os.path.join(self._data_dir, n)))
        except Exception:
            pass
        return self.open_session(names[-1])

    def new_session(self, screen_w, screen_h, dpr, mode,
                    prev_file=None, created_by="initial"):
        """结束当前会话（若有），新建空白会话文件并建表 + 写元数据。

        prev_file=旧会话文件名、created_by="clear" 时，本文件记录"由清屏生成、
        清屏前数据在 prev_file"——撤销清屏时据此切回旧文件（之后笔迹写回旧文件）。
        """
        self.close()
        self._ensure_dir()
        path = os.path.join(self._data_dir, f"canvas_{int(time.time() * 1000)}.db")
        self._db_path = path
        self._conn = sqlite3.connect(path)
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        self._ensure_tables()
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        self._conn.executemany("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", [
            ("screen_width", str(int(screen_w or 0))),
            ("screen_height", str(int(screen_h or 0))),
            ("device_pixel_ratio", str(float(dpr or 1.0))),
            ("mode", str(mode or "")),
            ("created_at", now),
            ("prev_file", str(prev_file or "")),
            ("created_by", str(created_by or "initial")),
        ])
        self._conn.commit()
        plugin_logger.info(f"新建笔迹会话文件: {path} (created_by={created_by}, prev={prev_file})")
        return path

    def add_stroke(self, op, color, width, points):
        """增量保存一笔（pen/eraser）；每笔即 commit，返回新行 id。"""
        if self._conn is None:
            return None
        try:
            cur = self._conn.execute(
                "INSERT INTO strokes(op,color,width,points,created_at) VALUES(?,?,?,?,?)",
                (op, color or "", float(width or 0.0),
                 json.dumps([[float(x), float(y)] for x, y in points]),
                 time.strftime("%Y-%m-%d %H:%M:%S")))
            self._conn.commit()
            return int(cur.lastrowid)
        except Exception as e:
            plugin_logger.debug(f"保存笔迹失败: {e}")
            return None

    def delete_stroke(self, stroke_id):
        """删除一笔（撤销"新增"时回滚）。"""
        if self._conn is None:
            return
        try:
            self._conn.execute("DELETE FROM strokes WHERE id=?", (int(stroke_id),))
            self._conn.commit()
        except Exception as e:
            plugin_logger.debug(f"删除笔迹失败: {e}")

    def update_stroke(self, stroke_id, op, color, width, points):
        """整行更新一笔（撤销/重做"修改"时回滚）。"""
        if self._conn is None:
            return
        try:
            self._conn.execute(
                "UPDATE strokes SET op=?,color=?,width=?,points=? WHERE id=?",
                (op, color or "", float(width or 0.0),
                 json.dumps([[float(x), float(y)] for x, y in points]),
                 int(stroke_id)))
            self._conn.commit()
        except Exception as e:
            plugin_logger.debug(f"更新笔迹失败: {e}")

    def log_op(self, op_type, data):
        """把一次增量操作追加进当前会话的 ops 表（撤销日志，跨重启保留记录）。"""
        if self._conn is None:
            return
        try:
            self._conn.execute(
                "INSERT INTO ops(type,data,created_at) VALUES(?,?,?)",
                (op_type, json.dumps(data, ensure_ascii=False),
                 time.strftime("%Y-%m-%d %H:%M:%S")))
            self._conn.commit()
        except Exception as e:
            plugin_logger.debug(f"写操作日志失败: {e}")

    def load_all(self):
        """按绘制顺序读取全部笔迹（pen 与 eraser 交错，重放即还原画面），含 id。"""
        if self._conn is None:
            return []
        try:
            rows = self._conn.execute(
                "SELECT id,op,color,width,points FROM strokes ORDER BY id").fetchall()
            out = []
            for sid, op, color, width, points in rows:
                try:
                    pts = json.loads(points)
                except Exception:
                    continue
                out.append({"id": int(sid), "op": op, "color": color,
                            "width": float(width),
                            "points": [[float(x), float(y)] for x, y in pts]})
            return out
        except Exception as e:
            plugin_logger.debug(f"读取笔迹失败: {e}")
            return []

    def remove_file(self, name):
        """删除一个会话文件（含 -shm/-wal 侧文件）；用于撤销清屏时清理空白文件。"""
        if not name:
            return
        for suffix in ("", "-shm", "-wal"):
            try:
                p = os.path.join(self._data_dir, name + suffix)
                if os.path.exists(p):
                    os.remove(p)
            except Exception as e:
                plugin_logger.debug(f"删除会话文件失败: {name}{suffix}: {e}")

    def close(self):
        if self._conn is not None:
            try:
                self._conn.commit()
                self._conn.close()
            except Exception:
                pass
            self._conn = None


class WhiteboardBackend(QObject):
    """特殊模式笔迹数据 + 离屏烘焙（QQuickImageProvider 消费），渲染逻辑纯 Python。

    QML 通过 Image（image://whiteboard/canvas）显示烘焙 QImage；每一次笔划变化
    （begin/move/end/clear）递增 imageVersion 触发 QML 刷新。笔迹向量存于
    _strokes，每笔完成经 StrokeStore 增量落盘；擦除全屏调用 clearAll() 新建会话。

    选择工具：_selection 记录选中笔划 id；圈选/单击实时计算；选中笔划渲染 1px
    蓝色描边（烘进 QImage）；确认后暴露 selectionRect/hasSelection 给 QML 画矩形
    + 四角把手 + 浮动工具栏。缩放/平移/换色/换粗细修改向量并增量落盘。

    撤销：_undo_stack 为增量操作栈（add/clear/modify），undo() 逐项回滚——
    add→删除该笔、clear→切回清屏前文件并删空白文件（之后笔迹写回旧文件）、
    modify→恢复旧数据。每次操作经 StrokeStore.log_op 追加进 ops 表。
    """

    imageVersionChanged = Signal()
    selectionChanged = Signal()      # 选择状态/矩形/共同样式变化
    canUndoChanged = Signal()        # 撤销栈变化
    pageChanged = Signal()           # 页数/当前页变化（翻页/加页/撤销清屏等）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._strokes = []       # 全部向量笔迹（含橡皮），含 id
        self._image = QImage()   # 烘焙画布（逻辑像素尺寸）
        self._active = None      # 进行中笔迹 {op,color,width,points}
        self._last_pt = None
        self._base = None        # 进行中笔划的基础图快照（仅含已完成笔划）
        self._store = None
        self._screen = (0, 0, 1.0, "")   # (宽, 高, dpr, mode) 逻辑像素
        self._canvas_size = (1, 1)
        self._image_version = 0
        self._light = True
        # 选择状态
        self._selection = []       # 选中笔划 id 列表
        self._sel_active = False   # 是否已确认（松开鼠标后）
        self._sel_rect = None      # [x, y, w, h]
        self._sel_poly = None      # 圈选中的多边形点 [[x,y], ...]
        self._sel_color = ""       # 选中笔划共同逻辑色（不同=空串）
        self._sel_width = 0        # 共同粗细（不同=0）
        # 拖拽组合修改快照（一次拖拽合并为一次撤销）
        self._modify_snapshot = None
        # 撤销栈（增量操作日志：add/clear/modify/delete）
        self._undo_stack = []
        # 多页结构：每页独立会话文件/笔迹/撤销栈（page=dict: file/strokes/undo）
        self._pages = []
        self._page_index = 0

    # ---------- Python 侧接线 ----------
    def set_store(self, store):
        self._store = store

    def set_screen_info(self, w, h, dpr, mode):
        self._screen = (w, h, dpr or 1.0, mode)
        self._light = (mode == "whiteboard")   # 白板=浅色

    def set_canvas_size(self, w, h):
        """设置画布逻辑尺寸（屏幕宽高），由 Plugin 接线时传入。"""
        self._canvas_size = (max(1, int(w)), max(1, int(h)))

    def load_strokes(self, strokes):
        """载入既有笔迹并整幅重放渲染（进入特殊模式时恢复上次内容）。

        多页结构：优先按 data/pages.json 注册表恢复各页（每页独立会话文件/笔迹），
        否则默认单页（映射当前会话文件）。注册表缺失/损坏时退化为单页。
        """
        self._strokes = list(strokes or [])
        self._pages = []
        self._page_index = 0
        reg = self._load_page_registry()
        if reg and reg.get("pages"):
            for f in reg["pages"]:
                st = []
                if self._store and f and self._store.open_session(f):
                    st = self._store.load_all()
                self._pages.append({"file": f, "strokes": st, "undo": []})
            self._page_index = max(0, min(int(reg.get("current", 0) or 0),
                                          len(self._pages) - 1))
            cur = self._pages[self._page_index]["file"]
            if self._store:
                if not (cur and self._store.open_session(cur)):
                    # 当前页文件缺失（异常）→ 重建空白会话
                    w, h, dpr, mode = self._screen
                    self._store.new_session(w, h, dpr, mode)
                    self._pages[self._page_index]["file"] = self._store.current_file()
                    self._save_page_registry()
            self._strokes = self._pages[self._page_index]["strokes"]
            self._undo_stack = self._pages[self._page_index]["undo"]
        else:
            self._pages = [{"file": self._store.current_file() if self._store else None,
                            "strokes": self._strokes, "undo": self._undo_stack}]
            self._page_index = 0
        self._ensure_image()
        self._render_all()
        self._bump()

    def image(self):
        """当前烘焙图像（供 ImageProvider 返回）。"""
        return self._image

    # ---------- 内部 ----------
    def _bump(self):
        self._image_version += 1
        self.imageVersionChanged.emit()

    def _ensure_image(self):
        """确保烘焙画布尺寸正确；不符（含初始）则重建并从向量笔迹重放。"""
        w, h = self._canvas_size
        if self._image.isNull() or self._image.width() != w or self._image.height() != h:
            self._image = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
            self._image.fill(Qt.transparent)
            if self._strokes:
                p = QPainter(self._image)
                p.setRenderHint(QPainter.Antialiasing)
                for s in self._strokes:
                    _draw_stroke(p, s, self._light)
                p.end()

    def _redraw_active(self):
        """把进行中的整笔（含全部采样点）用平滑贝塞尔路径重绘。

        每次 move 都以基础图快照（仅含已完成笔划）为底重画当前整笔，因此
        实时显示与最终落盘/重放完全一致，绘制再快也圆滑无折线；橡皮（Clear
        合成）也天然正确——每次都从基础图重新推算出擦除区域。
        """
        if not self._active or self._base is None:
            return
        self._image = self._base.copy()
        p = QPainter(self._image)
        p.setRenderHint(QPainter.Antialiasing)
        _draw_stroke(p, self._active, self._light)
        p.end()

    def _render_all(self):
        self._ensure_image()
        self._image.fill(Qt.transparent)
        p = QPainter(self._image)
        p.setRenderHint(QPainter.Antialiasing)
        sel = set(self._selection or [])
        for s in self._strokes:
            if s.get("id") in sel and s.get("op") == "pen":
                _draw_selection_outline(p, s, self._light)
            _draw_stroke(p, s, self._light)
        p.end()

    # ---------- QML 槽 ----------
    @Slot(str)
    def setMode(self, mode):
        """模式切换（whiteboard↔blackboard）时更新浅/深色并重放所有笔触，
        使已画笔触的显示色随之切换（黑/白互变、彩色深浅互变）。
        """
        light = (mode == "whiteboard")
        if light != self._light:
            self._light = light
            self._render_all()
            self._bump()

    # ---------- QML 槽 ----------
    @Slot(int, str, float, float, float)
    def beginStroke(self, op, color, width, x, y):
        """开始一笔：op 0=pen 1=eraser；width 为笔划粗细/橡皮直径。

        笔的起点不画独立圆（避免每笔起点出现一个大圆点）；橡皮按下即擦（点擦圆）。
        """
        self._active = {"op": "pen" if op == 0 else "eraser",
                        "color": color or "", "width": float(width),
                        "points": [[float(x), float(y)]]}
        self._last_pt = (float(x), float(y))
        self._ensure_image()
        self._base = self._image.copy()   # 快照：仅含已完成笔划
        if self._active["op"] == "eraser":
            self._redraw_active()
            self._bump()

    @Slot(float, float)
    def moveStroke(self, x, y):
        if not self._active:
            return
        cur = (float(x), float(y))
        if abs(cur[0] - self._last_pt[0]) < 0.5 and abs(cur[1] - self._last_pt[1]) < 0.5:
            return
        self._active["points"].append([cur[0], cur[1]])
        self._last_pt = cur
        self._redraw_active()
        self._bump()

    @Slot()
    def endStroke(self):
        """结束一笔：加入向量并增量落盘（图像已实时烘焙），压入撤销栈。"""
        if not self._active:
            return
        if self._active["points"]:
            if self._active["op"] == "pen" and len(self._active["points"]) == 1:
                # 笔单击（按下即松、未拖动）→ 补一个起点小点，保证有点痕
                self._redraw_active()
                self._bump()
            if self._store:
                a = self._active
                sid = self._store.add_stroke(a["op"], a.get("color"),
                                             a.get("width", 0.0), a["points"])
                if sid is not None:
                    a["id"] = int(sid)
                    self._push_undo({"type": "add", "id": int(sid)})
            self._strokes.append(self._active)
        self._active = None
        self._last_pt = None
        self._base = None

    @Slot()
    def clearAll(self):
        """擦除全屏：清空画布并新建空白会话（旧数据文件保留）。

        新文件 meta 记录 prev_file（清屏前文件）与 created_by="clear"；撤销清屏
        时据此切回旧文件、删除空白文件，之后的笔迹写回旧文件。
        """
        prev = self._store.current_file() if self._store else None
        self._strokes = []
        self._active = None
        self._last_pt = None
        self._base = None
        self._selection = []
        self._sel_rect = None
        self._sel_active = False
        self._ensure_image()
        self._image.fill(Qt.transparent)
        if self._store:
            w, h, dpr, mode = self._screen
            self._store.new_session(w, h, dpr, mode, prev_file=prev, created_by="clear")
            created = self._store.current_file()
            self._push_undo({"type": "clear", "prev_file": prev, "created_file": created})
            # 当前页映射到新的空白会话文件（翻页/重启后仍指向正确文件）
            self._sync_current_page_file()
        self._bump()
        self.selectionChanged.emit()

    @Slot()
    def cancelStroke(self):
        """取消进行中的一笔（如切出画布），不落盘。"""
        self._active = None
        self._last_pt = None
        self._base = None

    @Property(int, notify=imageVersionChanged)
    def imageVersion(self):
        return self._image_version

    # ---------- 笔划几何辅助 ----------
    def _stroke_dense_points(self, stroke, steps=8):
        """把笔划的 Catmull-Rom→三次贝塞尔路径离散化为密集点列（包含/命中判定用）。

        与渲染用的 _stroke_path 同一构造，保证判定与所见一致；点状/重合退化返回单点。
        """
        points = stroke.get("points") or []
        if not points:
            return []
        if len(points) == 1:
            return [[points[0][0], points[0][1]]]
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        if max(xs) - min(xs) < 0.01 and max(ys) - min(ys) < 0.01:
            return [[points[0][0], points[0][1]]]

        def _pt(i):
            return QPointF(points[i][0], points[i][1])

        n = len(points)
        out = [[points[0][0], points[0][1]]]
        for i in range(n - 1):
            p0 = _pt(max(0, i - 1))
            p1 = _pt(i)
            p2 = _pt(i + 1)
            p3 = _pt(min(n - 1, i + 2))
            c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6.0,
                         p1.y() + (p2.y() - p0.y()) / 6.0)
            c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6.0,
                         p2.y() - (p3.y() - p1.y()) / 6.0)
            for k in range(1, steps + 1):
                t = k / steps
                mt = 1.0 - t
                x = mt ** 3 * p1.x() + 3 * mt * mt * t * c1.x() \
                    + 3 * mt * t * t * c2.x() + t ** 3 * p2.x()
                y = mt ** 3 * p1.y() + 3 * mt * mt * t * c1.y() \
                    + 3 * mt * t * t * c2.y() + t ** 3 * p2.y()
                out.append([x, y])
        return out

    def _stroke_bbox(self, stroke, pad=0.0):
        """笔划点包围盒 [x, y, w, h]（可选外扩 pad=宽度/2 以包含笔划厚度）。"""
        pts = stroke.get("points") or []
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return [min(xs) - pad, min(ys) - pad,
                max(xs) - min(xs) + pad * 2, max(ys) - min(ys) + pad * 2]

    # ---------- 选择：内部 ----------
    def _select_ids(self, ids):
        """设置选中笔划 id 集合并重绘（圈选过程中实时调用）。"""
        self._selection = list(ids)
        self._update_selection_style()
        self._render_all()
        self._bump()
        self.selectionChanged.emit()

    def _update_selection_style(self):
        """计算选中笔划的共同逻辑色与粗细（不同则空/0，供浮动菜单高亮）。"""
        colors = set()
        widths = set()
        for s in self._strokes:
            if s.get("id") in self._selection:
                colors.add((s.get("color") or "") or "mono")
                widths.add(float(s.get("width", 4.0)))
        self._sel_color = colors.pop() if len(colors) == 1 else ""
        self._sel_width = int(round(widths.pop())) if len(widths) == 1 else 0

    def _compute_selection_rect(self):
        """按选中笔划（含厚度）计算包围矩形，确认选择状态。"""
        if not self._selection:
            self._sel_rect = None
            self._sel_active = False
            return
        xs = []
        ys = []
        for s in self._strokes:
            if s.get("id") not in self._selection:
                continue
            bb = self._stroke_bbox(s, float(s.get("width", 4.0)) / 2.0)
            if bb:
                xs.extend([bb[0], bb[0] + bb[2]])
                ys.extend([bb[1], bb[1] + bb[3]])
        if not xs:
            self._sel_rect = None
            self._sel_active = False
            return
        minx, miny = min(xs), min(ys)
        maxx, maxy = max(xs), max(ys)
        self._sel_rect = [minx, miny, maxx - minx, maxy - miny]
        self._sel_active = True

    def _select_inside_polygon(self):
        """圈选：把被闭合多边形完全包裹（所有离散点在内）的 pen 笔划选为候选。"""
        poly_pts = self._sel_poly or []
        if len(poly_pts) < 3:
            self._select_ids([])
            return
        poly = QPolygonF([QPointF(p[0], p[1]) for p in poly_pts])
        pb = poly.boundingRect()
        sel = []
        for s in self._strokes:
            if s.get("op") != "pen":
                continue
            bb = self._stroke_bbox(s)
            if bb is None:
                continue
            # 快速剔除：笔划包围盒须整体落在多边形包围盒内（否则不可能完全包裹）
            if (bb[0] < pb.left() - 0.01 or bb[1] < pb.top() - 0.01
                    or bb[0] + bb[2] > pb.right() + 0.01
                    or bb[1] + bb[3] > pb.bottom() + 0.01):
                continue
            dense = self._stroke_dense_points(s)
            ok = True
            for p in dense:
                if not poly.containsPoint(QPointF(p[0], p[1]), Qt.OddEvenFill):
                    ok = False
                    break
            if ok:
                sel.append(s.get("id"))
        self._select_ids(sel)

    def _hit_stroke(self, x, y):
        """返回点击点命中的最近 pen 笔划 id（距离中心线 <= 半宽+3px），否则 None。"""
        best = None
        best_d2 = float('inf')
        for s in self._strokes:
            if s.get("op") != "pen":
                continue
            tol = max(float(s.get("width", 4.0)) / 2.0, 3.0) + 3.0
            dense = self._stroke_dense_points(s)
            for p in dense:
                d2 = (p[0] - x) ** 2 + (p[1] - y) ** 2
                if d2 <= tol * tol and d2 < best_d2:
                    best_d2 = d2
                    best = s.get("id")
        return best

    @staticmethod
    def _point_in_rect(x, y, r):
        return bool(r) and r[0] <= x <= r[0] + r[2] and r[1] <= y <= r[1] + r[3]

    # ---------- 选择：QML 槽 ----------
    @Slot('QVariantList')
    def beginSelection(self, points):
        """开始圈选：清除旧的已确认矩形/工具栏状态，记录多边形并实时计算被包裹笔划。"""
        self._sel_active = False
        self._sel_rect = None
        self._sel_poly = [[float(p[0]), float(p[1])] for p in (points or [])]
        self._select_inside_polygon()

    @Slot('QVariantList')
    def updateSelection(self, points):
        """圈选过程中多边形变化：重算被包裹笔划。"""
        self._sel_poly = [[float(p[0]), float(p[1])] for p in (points or [])]
        self._select_inside_polygon()

    @Slot()
    def endSelection(self):
        """松开鼠标：结束圈选，固定选中集合并计算边界矩形（QML 据此画矩形+把手+工具栏）。"""
        self._sel_poly = None
        self._compute_selection_rect()
        self._update_selection_style()
        self._render_all()
        self._bump()
        self.selectionChanged.emit()

    @Slot()
    def cancelSelection(self):
        """取消圈选（鼠标取消事件）：不确认选择，清空。"""
        self._sel_poly = None
        self._selection = []
        self._sel_rect = None
        self._sel_active = False
        self._sel_color = ""
        self._sel_width = 0
        self._render_all()
        self._bump()
        self.selectionChanged.emit()

    @Slot(float, float)
    def clickSelect(self, x, y):
        """单击选择：命中某笔划则单选该笔划；未命中：点在已选矩形内则保留，否则取消。"""
        x, y = float(x), float(y)
        hit = self._hit_stroke(x, y)
        if hit is not None:
            self._selection = [hit]
            self._sel_poly = None
            self._compute_selection_rect()
            self._update_selection_style()
            self._render_all()
            self._bump()
            self.selectionChanged.emit()
        elif self._sel_active and self._point_in_rect(x, y, self._sel_rect):
            pass  # 在选中矩形内点空白 → 保持选择
        else:
            self.clearSelection()

    @Slot()
    def clearSelection(self):
        """清除选择：去掉蓝色描边/矩形/浮动工具栏。"""
        self._sel_poly = None
        self._selection = []
        self._sel_rect = None
        self._sel_active = False
        self._sel_color = ""
        self._sel_width = 0
        self._render_all()
        self._bump()
        self.selectionChanged.emit()

    @Slot(float, float, float, float)
    def applyTransform(self, x1, y1, w1, h1):
        """把选中笔划映射到目标矩形 (x1,y1,w1,h1)（平移或等比缩放）。

        以"当前选择矩形 _sel_rect"为基准逐事件映射（而非按下时的快照）：连续拖拽
        产生的多次事件不会累积误差，笔迹与矩形严格同步跟随鼠标；撤销由
        beginModify/endModify 把一次拖拽合并为一次操作。
        """
        r = self._sel_rect
        if not r or not self._selection:
            return
        x0, y0, w0, h0 = r
        if w0 <= 0 or h0 <= 0:
            return
        for s in self._strokes:
            if s.get("id") not in self._selection or s.get("op") != "pen":
                continue
            new_pts = []
            for px, py in s.get("points", []):
                new_pts.append([x1 + (px - x0) * (w1 / w0),
                                y1 + (py - y0) * (h1 / h0)])
            s["points"] = new_pts
            if self._store:
                self._store.update_stroke(s["id"], s.get("op"), s.get("color", ""),
                                          s.get("width", 4.0), s["points"])
        # 选择矩形直接采用目标矩形（角点/边框精确跟随鼠标，笔迹严格在其中）
        self._sel_rect = [x1, y1, w1, h1]
        self._sel_active = True
        self._update_selection_style()
        self._render_all()
        self._bump()
        self.selectionChanged.emit()

    @Slot()
    def beginModify(self):
        """开始一次组合修改（拖拽平移/缩放）：记录选中笔划的旧快照。"""
        self._modify_snapshot = []
        for s in self._strokes:
            if s.get("id") in self._selection:
                self._modify_snapshot.append({
                    "id": s["id"],
                    "old": {"op": s.get("op"), "color": s.get("color", ""),
                            "width": s.get("width", 4.0),
                            "points": [list(p) for p in s.get("points", [])]}})

    @Slot()
    def endModify(self):
        """结束组合修改：数据有变化则压入一次 modify 撤销操作；无变化（纯点击）忽略。"""
        if not self._modify_snapshot:
            return
        changes = []
        for item in self._modify_snapshot:
            sid = item["id"]
            old = item["old"]
            for s in self._strokes:
                if s.get("id") == sid:
                    new = {"op": s.get("op"), "color": s.get("color", ""),
                           "width": s.get("width", 4.0),
                           "points": [list(p) for p in s.get("points", [])]}
                    if new != old:
                        changes.append({"id": sid, "old": old})
                    break
        self._modify_snapshot = None
        if changes:
            self._push_undo({"type": "modify", "changes": changes})

    @Slot(int)
    def setSelectionWidth(self, w):
        """给选中笔划统一换粗细。"""
        w = float(int(w))
        if w <= 0 or not self._selection:
            return
        changes = []
        for s in self._strokes:
            if s.get("id") not in self._selection or s.get("op") != "pen":
                continue
            old = {"op": s.get("op"), "color": s.get("color", ""),
                   "width": s.get("width", 4.0),
                   "points": [list(p) for p in s.get("points", [])]}
            s["width"] = w
            changes.append({"id": s.get("id"), "old": old})
            if self._store:
                self._store.update_stroke(s["id"], s.get("op"), s.get("color", ""),
                                          w, s["points"])
        if changes:
            self._push_undo({"type": "modify", "changes": changes})
        self._update_selection_style()
        self._render_all()
        self._bump()
        self.selectionChanged.emit()

    @Slot(str)
    def setSelectionColor(self, color):
        """给选中笔划统一换颜色（逻辑名，显示 hex 随模式映射）。"""
        if not self._selection:
            return
        color = color or ""
        changes = []
        for s in self._strokes:
            if s.get("id") not in self._selection or s.get("op") != "pen":
                continue
            old = {"op": s.get("op"), "color": s.get("color", ""),
                   "width": s.get("width", 4.0),
                   "points": [list(p) for p in s.get("points", [])]}
            s["color"] = color
            changes.append({"id": s.get("id"), "old": old})
            if self._store:
                self._store.update_stroke(s["id"], s.get("op"), color,
                                          s.get("width", 4.0), s["points"])
        if changes:
            self._push_undo({"type": "modify", "changes": changes})
        self._update_selection_style()
        self._render_all()
        self._bump()
        self.selectionChanged.emit()

    # ---------- 多页：注册表 ----------
    def _load_page_registry(self):
        """读取 data/pages.json 页注册表（页顺序 + 当前页索引）；无/损坏返回 None。"""
        if not self._store:
            return None
        try:
            p = os.path.join(self._store.data_dir, "pages.json")
            if not os.path.exists(p):
                return None
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _save_page_registry(self):
        """把当前页顺序/当前页索引写回 pages.json（翻页/加页/清屏改文件映射时调用）。"""
        if not self._store:
            return
        try:
            p = os.path.join(self._store.data_dir, "pages.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"pages": [pg.get("file") for pg in self._pages],
                           "current": self._page_index}, f, ensure_ascii=False)
        except Exception as e:
            plugin_logger.debug(f"保存页注册表失败: {e}")

    def _sync_current_page_file(self):
        """当前页的会话文件记录与 store 当前文件同步（清屏/撤销清屏改文件后调用）。"""
        if self._store and 0 <= self._page_index < len(self._pages):
            self._pages[self._page_index]["file"] = self._store.current_file()
            self._save_page_registry()

    # ---------- 多页：QML 槽 ----------
    @Slot()
    def prevPage(self):
        """上一页。"""
        self._switch_to_page(self._page_index - 1)

    @Slot()
    def nextPage(self):
        """下一页（末页的"加页"走 addPage）。"""
        self._switch_to_page(self._page_index + 1)

    @Slot()
    def addPage(self):
        """新增一页（最多 10 页）：保存当前页内存状态，新建空白会话文件作为新页并切换过去。"""
        if len(self._pages) >= 10:
            return
        self.cancelStroke()
        self._pages[self._page_index]["file"] = self._store.current_file() if self._store else None
        self._pages[self._page_index]["strokes"] = self._strokes
        self._pages[self._page_index]["undo"] = self._undo_stack
        if self._store:
            w, h, dpr, mode = self._screen
            self._store.new_session(w, h, dpr, mode)
            new_file = self._store.current_file()
        else:
            new_file = None
        self._strokes = []
        self._undo_stack = []
        self._pages.append({"file": new_file, "strokes": self._strokes,
                            "undo": self._undo_stack})
        self._page_index = len(self._pages) - 1
        self._sel_poly = None
        self._selection = []
        self._sel_rect = None
        self._sel_active = False
        self._sel_color = ""
        self._sel_width = 0
        self._ensure_image()
        self._image.fill(Qt.transparent)
        self._save_page_registry()
        self._render_all()
        self._bump()
        self.selectionChanged.emit()
        self.canUndoChanged.emit()
        self.pageChanged.emit()

    def _switch_to_page(self, index):
        """切到指定页（0-based）：保存当前页内存状态，打开目标页会话文件并载入其笔迹/撤销栈。"""
        n = len(self._pages)
        if index < 0 or index >= n or index == self._page_index:
            return
        self.cancelStroke()
        self._pages[self._page_index]["file"] = self._store.current_file() if self._store else None
        self._pages[self._page_index]["strokes"] = self._strokes
        self._pages[self._page_index]["undo"] = self._undo_stack
        self._page_index = index
        page = self._pages[index]
        if self._store:
            if page["file"]:
                if not self._store.open_session(page["file"]):
                    w, h, dpr, mode = self._screen
                    self._store.new_session(w, h, dpr, mode)
                    page["file"] = self._store.current_file()
            else:
                w, h, dpr, mode = self._screen
                self._store.new_session(w, h, dpr, mode)
                page["file"] = self._store.current_file()
        self._strokes = page["strokes"]
        self._undo_stack = page["undo"]
        # 切页后旧选择/圈选失效 → 清除
        self._sel_poly = None
        self._selection = []
        self._sel_rect = None
        self._sel_active = False
        self._sel_color = ""
        self._sel_width = 0
        self._save_page_registry()
        self._render_all()
        self._bump()
        self.selectionChanged.emit()
        self.canUndoChanged.emit()
        self.pageChanged.emit()

    # ---------- 选择：删除选中 ----------
    @Slot()
    def deleteSelection(self):
        """删除选中笔划（浮动工具栏"删除"按钮）：内存/存储同步删除，记录一次可撤销操作。"""
        if not self._selection:
            return
        ids = set(self._selection)
        removed = [s for s in self._strokes if s.get("id") in ids]
        if not removed:
            return
        self._strokes = [s for s in self._strokes if s.get("id") not in ids]
        if self._store:
            for s in removed:
                self._store.delete_stroke(s["id"])
        self._push_undo({"type": "delete", "strokes": [
            {"id": int(s.get("id", 0)), "op": s.get("op", "pen"),
             "color": s.get("color", ""), "width": float(s.get("width", 4.0)),
             "points": [list(p) for p in (s.get("points") or [])]}
            for s in removed]})
        self._sel_poly = None
        self._selection = []
        self._sel_rect = None
        self._sel_active = False
        self._sel_color = ""
        self._sel_width = 0
        self._render_all()
        self._bump()
        self.selectionChanged.emit()

    # ---------- 撤销 ----------
    def _push_undo(self, op):
        """压入撤销栈并追加进当前会话 ops 表（增量操作日志）。"""
        self._undo_stack.append(op)
        self.canUndoChanged.emit()
        if self._store:
            self._store.log_op(op.get("type", ""), op)

    @Slot()
    def undo(self):
        """撤销上一步操作（新增笔划/清屏/移动/缩放/换色/换粗细均可撤销）。"""
        if not self._undo_stack:
            return
        op = self._undo_stack.pop()
        try:
            t = op.get("type")
            if t == "add":
                sid = op.get("id")
                self._strokes = [s for s in self._strokes if s.get("id") != sid]
                if self._store:
                    self._store.delete_stroke(sid)
            elif t == "clear":
                prev = op.get("prev_file")
                created = op.get("created_file")
                if self._store and prev:
                    # 切回清屏前的文件，加载其笔迹；空白文件的内容已全部撤销 → 删除
                    self._store.open_session(prev)
                    self._strokes = self._store.load_all()
                    if created:
                        self._store.remove_file(created)
                    # 当前页重新映射到旧文件（之后笔迹写回旧文件）
                    self._sync_current_page_file()
                else:
                    self._strokes = []
            elif t == "delete":
                # 撤销删除：把被删笔划重新落盘（新 id），按原 id 排序放回原位保持绘制顺序
                for st in op.get("strokes", []):
                    sid = None
                    if self._store:
                        sid = self._store.add_stroke(st.get("op", "pen"),
                                                     st.get("color", ""),
                                                     st.get("width", 4.0),
                                                     st.get("points") or [])
                    self._strokes.append({
                        "_orig_id": int(st.get("id", 0)),
                        "id": int(sid) if sid is not None else int(st.get("id", 0)),
                        "op": st.get("op", "pen"),
                        "color": st.get("color", ""),
                        "width": float(st.get("width", 4.0)),
                        "points": [list(p) for p in (st.get("points") or [])]})
                self._strokes.sort(key=lambda s: s.get("_orig_id", s.get("id", 0)))
            elif t == "modify":
                for ch in op.get("changes", []):
                    sid = ch.get("id")
                    old = ch.get("old") or {}
                    for s in self._strokes:
                        if s.get("id") == sid:
                            s["op"] = old.get("op", s.get("op", "pen"))
                            s["color"] = old.get("color", "")
                            s["width"] = float(old.get("width", 4.0))
                            s["points"] = [list(p) for p in old.get("points", [])]
                            if self._store:
                                self._store.update_stroke(
                                    sid, s["op"], s["color"], s["width"], s["points"])
                            break
        except Exception as e:
            plugin_logger.debug(f"撤销失败: {e}")
        # 撤销后旧选择可能引用已删/已改的笔划 → 清除选择
        self._sel_poly = None
        self._selection = []
        self._sel_rect = None
        self._sel_active = False
        self._sel_color = ""
        self._sel_width = 0
        self._render_all()
        self._bump()
        self.selectionChanged.emit()
        self.canUndoChanged.emit()

    # ---------- 选择/撤销属性 ----------
    @Property(bool, notify=selectionChanged)
    def hasSelection(self):
        return bool(self._sel_active and self._selection)

    @Property('QVariantList', notify=selectionChanged)
    def selectionRect(self):
        return list(self._sel_rect) if self._sel_rect else []

    @Property(str, notify=selectionChanged)
    def selectionColor(self):
        return self._sel_color

    @Property(int, notify=selectionChanged)
    def selectionWidth(self):
        return self._sel_width

    @Property(bool, notify=canUndoChanged)
    def canUndo(self):
        return bool(self._undo_stack)

    # ---------- 多页属性 ----------
    @Property(int, notify=pageChanged)
    def pageCount(self):
        return len(self._pages)

    @Property(int, notify=pageChanged)
    def currentPage(self):
        return self._page_index

    @Property(bool, notify=pageChanged)
    def canGoPrev(self):
        return self._page_index > 0

    @Property(bool, notify=pageChanged)
    def canGoNext(self):
        return self._page_index < len(self._pages) - 1

    @Property(bool, notify=pageChanged)
    def canAddPage(self):
        return len(self._pages) < 10


class WhiteboardImageProvider(QQuickImageProvider):
    """把 WhiteboardBackend 的烘焙 QImage 提供给 QML Image（image://whiteboard/...）。"""

    def __init__(self, backend):
        super().__init__(QQuickImageProvider.Image)
        self._backend = backend

    def requestImage(self, id, size, requestedSize):
        return self._backend.image()


class LessonsBackend(QObject):
    lessonsUpdated = Signal()
    themeChanged = Signal(bool)
    positionChanged = Signal()
    widthChanged = Signal()
    opacityChanged = Signal()
    scrollRequested = Signal(int)
    modeChanged = Signal()
    fontChanged = Signal()  
    bgOpacityChanged = Signal()
    scaleFactorChanged = Signal()
    switchingChanged = Signal()
    popupOpenChanged = Signal()
    layerChanged = Signal()
    countdownStyleChanged = Signal()
    remainingTextChanged = Signal()
    widgetRadiusChanged = Signal()
    # 绘图工具状态（特殊模式工具栏）：activeTool 0=选择 1=笔 2=橡皮；笔粗细/颜色
    activeToolChanged = Signal()
    penWidthChanged = Signal()
    penColorChanged = Signal()

    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin
        self._popup_open = False
        self._lessons = []
        self._display_items = []
        self._current_lesson_id = ""
        self._next_lesson_id = ""
        self._current_state = 0
        self._is_dark = False
        self._ui_x = 0
        self._ui_y = 0
        self._ui_width = DEFAULT_UI_WIDTH
        self._opacity = 0
        self._mode = "normal"
        self._current_icon = "ic_fluent_question_20_regular"
        self._current_remaining_text = ""
        self._font_family = ""
        self._font_weight = 400

        # 自动关闭特殊模式相关
        self._auto_close_timer = QTimer()
        self._auto_close_timer.timeout.connect(self._on_auto_close_timeout)
        self._auto_close_timer.setSingleShot(True)
        self._in_auto_close_status = False

        # 特殊模式窗口切换标记（切换期间禁用按钮，防止误操作）
        self._switching = False

        # 移除窗口 mask 的引用计数（右键菜单/文本提示可同时占用，归零才恢复）
        self._mask_hide_refs = 0

        # 小组件图层状态（由插件设置 + 主程序 widgets_layer 配置计算）
        self._layer_topmost = False
        self._layer_bottommost = False

        # 倒计时样式（特殊模式设置：默认字号/大字号）
        self._countdown_style = "default"
        self._update_countdown_style()

        # 动画性能优化：纯平移动画期间临时禁用 mask（动画结束恢复）
        self._anim_optimize_active = False
        self._anim_optimize_timer = QTimer()
        self._anim_optimize_timer.setSingleShot(True)
        self._anim_optimize_timer.timeout.connect(self._on_anim_optimize_timeout)

        self._update_font()

        self._bg_opacity = 1.0
        self._update_bg_opacity
        
        self._scale_factor = 1.0
        self._update_scale_factor()

        # 外围圆角半径（跟随主程序 widget_corner_radius 配置换算）
        self._widget_radius = 27.0
        self._update_widget_radius()

        # 绘图工具状态（特殊模式工具栏）：0=选择 1=笔 2=橡皮
        self._active_tool = 0
        # 笔工具：粗细(2/4/6px)与颜色（hex）；颜色空串=自动跟随模式（浅色黑/深色白）
        self._pen_width = 4
        self._pen_color = ""

    @Slot(int)
    def setActiveTool(self, tool):
        """设置当前绘图工具：0=选择 1=笔 2=橡皮"""
        tool = int(tool)
        if tool != self._active_tool:
            self._active_tool = tool
            self.activeToolChanged.emit()

    @Slot(int)
    def setPenWidth(self, width):
        """设置笔划粗细：2/4/6 px"""
        width = int(width)
        if width != self._pen_width:
            self._pen_width = width
            self.penWidthChanged.emit()

    @Slot(str)
    def setPenColor(self, color):
        """设置笔迹逻辑颜色名（mono/red/blue/green/orange/yellow/cyan/purple）；空串=自动（mono）"""
        if color != self._pen_color:
            self._pen_color = color or ""
            self.penColorChanged.emit()

    @Property(int, notify=activeToolChanged)
    def activeTool(self):
        return self._active_tool

    @Property(int, notify=penWidthChanged)
    def penWidth(self):
        return self._pen_width

    @Property(str, notify=penColorChanged)
    def penColor(self):
        """当前笔迹逻辑颜色名；未手动选择时默认 mono（黑/白，随模式自动切换显示色）。

        存储/绘制都按逻辑名（如 "mono"/"red"），实际显示 hex 由当前模式映射
        （白板浅色=深色/黑，熄屏深色=浅色/白），切换模式时已画笔触显示色随之切换。
        """
        return self._pen_color or "mono"


    def set_ui_opacity(self, opacity):
        if opacity != self._opacity:
            self._opacity = opacity
            self.opacityChanged.emit()

    def _update_bg_opacity(self):
        try:
            configs = self.plugin._configs
            if configs:
                self._bg_opacity = getattr(configs.preferences, 'opacity', 1.0)
            else:
                self._bg_opacity = 1.0
        except Exception:
            self._bg_opacity = 1.0
        self.bgOpacityChanged.emit()

    def _update_scale_factor(self):
        try:
            configs = self.plugin._configs
            if configs:
                self._scale_factor = getattr(configs.preferences, 'scale_factor', 1.0)
            else:
                self._scale_factor = 1.0
        except Exception:
            self._scale_factor = 1.0
        self.scaleFactorChanged.emit()

    def _update_widget_radius(self):
        """跟随主程序 widget_corner_radius 换算外围圆角：min(27, r*27/16)（>16→27，0~16 等比缩放；读不到→27）。"""
        try:
            configs = self.plugin._configs
            if configs:
                r = getattr(configs.preferences, 'widget_corner_radius', None)
                if r is not None:
                    self._widget_radius = min(27.0, float(r) * 27.0 / 16.0)
                else:
                    self._widget_radius = 27.0
            else:
                self._widget_radius = 27.0
        except Exception:
            self._widget_radius = 27.0
        self.widgetRadiusChanged.emit()

    def _update_font(self):
        """从配置更新字体和字重"""
        try:
            configs = self.plugin._configs
            if configs:
                prefs = configs.preferences
                self._font_family = getattr(prefs, 'font', 'Microsoft YaHei')
                self._font_weight = getattr(prefs, 'font_weight', 600)
            else:
                self._font_family = "Microsoft YaHei"
                self._font_weight = 600
        except Exception as e:
            plugin_logger.debug(f"读取字体配置失败: {e}，使用默认值")
            self._font_family = "Microsoft YaHei"
            self._font_weight = 600
        self.fontChanged.emit()

    def _get_entry_full_name(self, entry):
        """获取条目的全称"""
        entry_type = entry.get("type", "")
        if entry_type == "class":
            subject_id = entry.get("subjectId")
            if subject_id and subject_id in self.plugin._subjects_name_map:
                return self.plugin._subjects_name_map[subject_id]
            return "课程"
        elif entry_type == "activity":
            title = entry.get("title", "")
            if title:
                return title
            return "活动"
        elif entry_type == "break":
            return "课间"
        elif entry_type == "preparation":
            return "预备"
        else:
            return "未知"

    def update_lessons(self):
        entries = self.plugin.api.runtime.current_day_entries
        if not entries:
            self._lessons = []
            self._display_items = [{
                "type": "placeholder",
                "icon": "ic_fluent_text_bullet_list_dismiss_20_regular",
                "text": "今天还没有课程 ~"
            }]
            self._current_lesson_id = ""
            self._next_lesson_id = ""
            self.lessonsUpdated.emit()
            plugin_logger.info("没有课程需要显示，添加占位提示")
            return

        self.plugin._update_subjects_map()

        all_entries = entries
        n = len(all_entries)

        def should_show(entry):
            e_type = entry.get("type", "")
            if e_type == "break":
                return False
            if e_type == "activity" and entry.get("title") in ["大课间", "升旗", "晚读/晚练", "备考", "进考场"]:
                return False
            return True

        show_flags = [should_show(e) for e in all_entries]

        display_items = []
        lessons = []
        filtered_ids = set()

        last_displayed_end = None

        for i, entry in enumerate(all_entries):
            if not show_flags[i]:
                continue

            entry_id = entry.get("id", "")
            entry_type = entry.get("type", "")
            title = entry.get("title", "")
            abbr = self.plugin._get_entry_abbr(entry)
            full_name = self._get_entry_full_name(entry)
            is_class = (entry_type == "class")

            if last_displayed_end is not None:
                current_start = _time_to_minutes(entry.get("startTime"))
                gap = current_start - last_displayed_end
                if gap >= 15:
                    display_items.append({"type": "separator"})

            lesson_item = {
                "type": "lesson",
                "id": entry_id,
                "abbr": abbr,
                "fullName": full_name,
                "isClass": is_class
            }
            display_items.append(lesson_item)
            lessons.append(lesson_item)
            filtered_ids.add(entry_id)

            last_displayed_end = _time_to_minutes(entry.get("endTime"))

        if not display_items:
            display_items.append({
                "type": "placeholder",
                "icon": "ic_fluent_text_bullet_list_dismiss_20_regular",
                "text": "今天还没有课程 ~"
            })

        self._display_items = display_items
        self._lessons = lessons

        current = self.plugin.api.runtime.current_entry
        if current and current.get("type") == "class":
            self._current_lesson_id = current.get("id", "")
        else:
            self._current_lesson_id = ""

        next_lesson_id = ""
        next_entries = self.plugin.api.runtime.next_entries
        if next_entries:
            for ne in next_entries:
                if ne.get("id") in filtered_ids and ne.get("type") == "class":
                    next_lesson_id = ne.get("id", "")
                    break
        self._next_lesson_id = next_lesson_id

        self._current_state = 1 if self.plugin.api.runtime.current_status == "class" else 0
        self.lessonsUpdated.emit()

        self._update_current_icon_and_remaining()
        self._check_auto_close()

    def _get_auto_close_delay_ms(self):
        """读取"下课后自动关闭"延迟时间并转换为毫秒（数值 × 单位）。"""
        try:
            delay = self.plugin.settings_backend.getInt("auto_close_delay")
        except Exception:
            delay = 3
        if delay < 0:
            delay = 0
        try:
            unit = self.plugin.settings_backend.getString("auto_close_unit")
        except Exception:
            unit = "min"
        if unit == "sec":
            return delay * 1000
        return delay * 60 * 1000  # 默认分

    def _check_auto_close(self):
        """检查是否满足自动关闭特殊模式的条件（受"下课后自动关闭"设置控制）。"""
        try:
            enabled = self.plugin.settings_backend.getBool("auto_close_after_class")
        except Exception:
            enabled = True
        if not enabled:
            # 开关关闭：不自动关闭
            self._in_auto_close_status = False
            self._auto_close_timer.stop()
            return
        current_status = self.plugin.api.runtime.current_status
        is_auto_close_status = current_status in ("break", "activity", "free")
        if is_auto_close_status:
            if not self._in_auto_close_status:
                self._in_auto_close_status = True
                self._auto_close_timer.start(self._get_auto_close_delay_ms())
        else:
            if self._in_auto_close_status:
                self._in_auto_close_status = False
                self._auto_close_timer.stop()

    def _on_auto_close_timeout(self):
        """自动关闭超时处理"""
        try:
            enabled = self.plugin.settings_backend.getBool("auto_close_after_class")
        except Exception:
            enabled = True
        if self._mode != "normal" and enabled:
            self.exitSpecialMode()
            delay_ms = self._get_auto_close_delay_ms()
            plugin_logger.info(f"自动关闭特殊模式：课间/活动持续 {delay_ms // 1000} 秒")

    def _set_remaining_text(self, text):
        """设置剩余时间文本；变化时发 remainingTextChanged（供 QML 更新），
        避免依赖 lessonsUpdated（其在文本更新前发出，导致设置变化时字号与文本不同步）。"""
        if text != self._current_remaining_text:
            self._current_remaining_text = text
            self.remainingTextChanged.emit()

    def _update_current_icon_and_remaining(self):
        """更新当前活动的图标和剩余时间文本"""
        current_entry = self.plugin.api.runtime.current_entry

        if current_entry:
            subject_id = current_entry.get("subjectId")
            if subject_id:
                try:
                    schedule = self.plugin.api._app.schedule_manager.schedule
                    if schedule and hasattr(schedule, 'subjects'):
                        for subj in schedule.subjects:
                            if subj.id == subject_id and subj.icon:
                                self._current_icon = subj.icon
                                break
                        else:
                            e_type = current_entry.get("type", "")
                            if e_type == "class":
                                self._current_icon = "ic_fluent_class_20_regular"
                            elif e_type == "break":
                                self._current_icon = "ic_fluent_shifts_activity_20_filled"
                            elif e_type == "activity":
                                self._current_icon = "ic_fluent_alert_20_regular"
                            elif e_type == "preparation":
                                self._current_icon = "ic_fluent_hourglass_half_20_regular"
                            else:
                                self._current_icon = "ic_fluent_question_20_regular"
                except Exception as e:
                    plugin_logger.debug(f"获取科目图标失败: {e}")
                    self._current_icon = "ic_fluent_question_20_regular"
            else:
                e_type = current_entry.get("type", "")
                if e_type == "class":
                    self._current_icon = "ic_fluent_class_20_regular"
                elif e_type == "break":
                    self._current_icon = "ic_fluent_shifts_activity_20_filled"
                elif e_type == "activity":
                    self._current_icon = "ic_fluent_alert_20_regular"
                elif e_type == "preparation":
                    self._current_icon = "ic_fluent_hourglass_half_20_regular"
                else:
                    self._current_icon = "ic_fluent_question_20_regular"
        else:
            self._current_icon = "ic_fluent_accessibility_20_regular"

        remaining = self.plugin.api.runtime.remaining_time
        if not remaining:
            self._set_remaining_text("")
            return

        minutes = remaining.get("minute", 0)
        seconds = remaining.get("second", 0)
        total_seconds = minutes * 60 + seconds

        # 倒计时样式：大字号用英文缩写（x min/x sec/x min 后/x sec 后）
        if self._countdown_style == "large":
            if total_seconds < 60:
                secs = max(1, total_seconds)
                if self._current_state == 1:
                    self._set_remaining_text(f"{secs} sec")
                else:
                    self._set_remaining_text(f"{secs} sec 后")
            else:
                mins = round(total_seconds / 60)
                if self._current_state == 1:
                    self._set_remaining_text(f"{mins} min")
                else:
                    self._set_remaining_text(f"{mins} min 后")
            return

        if total_seconds < 60:
            secs = max(1, total_seconds)
            if self._current_state == 1:
                self._set_remaining_text(f"剩 {secs} 秒")
            else:
                self._set_remaining_text(f"{secs} 秒后上课")
        else:
            mins = round(total_seconds / 60)
            if self._current_state == 1:
                self._set_remaining_text(f"剩 {mins} 分钟")
            else:
                self._set_remaining_text(f"{mins} 分钟后上课")

    def set_dark_theme(self, is_dark):
        if self._is_dark != is_dark:
            self._is_dark = is_dark
            self.themeChanged.emit(is_dark)

    def set_ui_width(self, width):
        if width != self._ui_width and width > 0:
            self._ui_width = width
            self.widthChanged.emit()
            self.update_position()

    def update_position(self, trigger_anim_optimize=False):
        """根据配置计算并更新 UI 位置。

        trigger_anim_optimize=True 表示本次是纯平移（位置/隐藏变化、宽度不变），
        动画性能优化启用时在平移动画期间临时禁用 mask（动画结束恢复）；
        宽度变化（set_ui_width）与初始定位不触发（mask 正常更新）。
        """
        try:
            configs = self.plugin._configs
            prefs = configs.preferences
            interactions = configs.interactions
            anchor = prefs.widgets_anchor
            offset_x = prefs.widgets_offset_x
            offset_y = prefs.widgets_offset_y
            hide = interactions.hide.state

            old_x, old_y = self._ui_x, self._ui_y

            scale_factor = prefs.scale_factor if hasattr(prefs, 'scale_factor') else 1.0
            mini_mode = prefs.mini_mode if hasattr(prefs, 'mini_mode') else False
            base_height = 56 if mini_mode else 100
            widgets_height = base_height * scale_factor

            screen = QGuiApplication.primaryScreen().availableGeometry()
            screen_width = screen.width()
            screen_height = screen.height()
            ui_width = self._ui_width

            parts = anchor.split("_")
            if len(parts) != 2:
                x = (screen_width - ui_width) // 2
                y = 132
            else:
                vert, horz = parts[0].lower(), parts[1].lower()

                if vert == "top":
                    if hide and horz == "center":
                        y = -UI_HEIGHT + 24
                    else:
                        y = 8 + widgets_height + offset_y
                elif vert == "bottom":
                    if hide and horz == "center":
                        y = screen_height - 24
                    else:
                        y = screen_height - UI_HEIGHT - offset_y - widgets_height + 40
                else:
                    y = 132

                if horz == "left":
                    if hide:
                        x = -ui_width + 24
                    else:
                        x = offset_x
                elif horz == "right":
                    if hide:
                        x = screen_width - 24
                    else:
                        x = screen_width - ui_width - offset_x
                elif horz == "center":
                    x = (screen_width - ui_width) // 2 + offset_x
                else:
                    x = (screen_width - ui_width) // 2

            self._ui_x = int(x)
            self._ui_y = int(y)

            # 动画性能优化：纯平移开始时临时禁用 mask（须在 positionChanged.emit() 前，否则其触发的 _update_mask 会做 mask 计算）
            if trigger_anim_optimize and (self._ui_x != old_x or self._ui_y != old_y):
                self._maybe_begin_translate_anim()

            self.positionChanged.emit()

            new_opacity = 0 if hide else 1
            self.set_ui_opacity(new_opacity)

        except Exception as e:
            plugin_logger.error(f"计算位置失败: {e}")
            screen = QGuiApplication.primaryScreen().availableGeometry()
            self._ui_x = (screen.width() - self._ui_width) // 2
            self._ui_y = 132
            self.positionChanged.emit()
            self.set_ui_opacity(1)

    def request_scroll_to_current(self):
        target_id = self._current_lesson_id or self._next_lesson_id
        if not target_id:
            return
        for i, lesson in enumerate(self._lessons):
            if lesson["id"] == target_id:
                for idx, item in enumerate(self._display_items):
                    if item.get("type") == "lesson" and item.get("id") == target_id:
                        self.scrollRequested.emit(idx)
                        break
                break

    def _set_mode(self, mode):
        if self._mode != mode:
            self._mode = mode
            self.modeChanged.emit()
            # 未手动选色时笔色跟随模式（白板黑/熄屏白），通知 QML 刷新菜单
            if not self._pen_color:
                self.penColorChanged.emit()

    @Slot()
    def enterWhiteboard(self):
        self._set_mode("whiteboard")

    @Slot()
    def enterBlackboard(self):
        self._set_mode("blackboard")

    @Slot()
    def exitSpecialMode(self):
        self._set_mode("normal")

    @Slot()
    def hideWidgetMask(self):
        """请求移除窗口 mask（引用计数：右键菜单 / 按钮文本提示可同时占用）。

        仅正常模式有意义（特殊模式窗口为纯色全屏，无 mask），非正常模式直接忽略，
        避免特殊窗口的 tooltip/菜单累计引用计数后随窗口销毁而泄漏。
        """
        if self.mode != "normal":
            return
        try:
            self._mask_hide_refs += 1
            if self.plugin.window:
                self.plugin._mask_enabled = False
                self.plugin.window.setMask(QRegion())
        except Exception as e:
            plugin_logger.debug(f"移除 mask 失败: {e}")

    @Slot()
    def showWidgetMask(self):
        """释放 mask 占用；引用计数归零且处于正常模式时恢复窗口 mask。"""
        if self.mode != "normal":
            return
        try:
            self._mask_hide_refs = max(0, self._mask_hide_refs - 1)
            if self.plugin.window and self._mask_hide_refs == 0:
                self.plugin._mask_enabled = True
                self.plugin._update_mask()
        except Exception as e:
            plugin_logger.debug(f"恢复 mask 失败: {e}")

    def _maybe_begin_translate_anim(self):
        """动画性能优化：纯平移动画开始 → 临时禁用 mask。

        仅当"动画性能优化"设置启用（默认启用）且处于正常模式时生效。
        禁用期间复用 _mask_hide_refs 引用计数（+1），确保与右键菜单/文本提示
        等 mask 占用叠加时互不干扰、归零才恢复。
        """
        try:
            enabled = self.plugin.settings_backend.getBool("animation_performance")
        except Exception:
            enabled = True
        if not enabled:
            return
        if self.mode != "normal":
            return
        if self._anim_optimize_active:
            return
        self._anim_optimize_active = True
        self._mask_hide_refs += 1
        try:
            if self.plugin.window:
                self.plugin._mask_enabled = False
                self.plugin.window.setMask(QRegion())
        except Exception as e:
            plugin_logger.debug(f"禁用 mask（动画优化）失败: {e}")
        # 兜底：QML 动画结束信号丢失时强制恢复，防止 mask 永久性失效
        self._anim_optimize_timer.start(700)

    @Slot()
    def endTranslateAnim(self):
        """动画性能优化：纯平移动画结束 → 恢复 mask（引用计数归零时）。"""
        if not self._anim_optimize_active:
            return
        self._anim_optimize_active = False
        self._anim_optimize_timer.stop()
        try:
            self._mask_hide_refs = max(0, self._mask_hide_refs - 1)
            if self.plugin.window and self._mask_hide_refs == 0:
                self.plugin._mask_enabled = True
                self.plugin._update_mask()
        except Exception as e:
            plugin_logger.debug(f"恢复 mask（动画优化）失败: {e}")

    def _on_anim_optimize_timeout(self):
        """兜底：动画结束信号未触发时强制结束动画优化并恢复 mask。"""
        if not self._anim_optimize_active:
            return
        self._anim_optimize_active = False
        try:
            self._mask_hide_refs = max(0, self._mask_hide_refs - 1)
            if self.plugin.window and self._mask_hide_refs == 0:
                self.plugin._mask_enabled = True
                self.plugin._update_mask()
        except Exception as e:
            plugin_logger.debug(f"兜底恢复 mask 失败: {e}")

    @Slot()
    def holdTopmost(self):
        """弹出浮层（右键菜单 / 设置页）时强制插件所有窗口置顶（引用计数，可叠加）。

        模仿特殊模式：置顶走 SetWindowPos(HWND_TOPMOST) + raise_ + requestActivate
        + _make_foreground_window（设系统前台）。同时把 popupOpen 置 True，让主窗口
        QML flags 绑定在浮层打开时也带上 WindowStaysOnTopHint（与特殊模式一致）。
        """
        try:
            self.plugin._topmost_refs += 1
            self._set_popup_open(True)
            self.plugin._apply_topmost_all(True)
        except Exception as e:
            plugin_logger.debug(f"置顶失败: {e}")

    @Slot()
    def releaseTopmost(self):
        """浮层关闭后释放置顶占用；引用计数归零且处于正常模式时移除置顶。
        特殊模式窗口本就需保持置顶，不在此处移除。"""
        try:
            self.plugin._topmost_refs = max(0, self.plugin._topmost_refs - 1)
            if self.plugin._topmost_refs == 0:
                self._set_popup_open(False)
                self.plugin._apply_topmost_all(False)
        except Exception as e:
            plugin_logger.debug(f"恢复窗口层级失败: {e}")

    def _set_popup_open(self, value):
        """同步 popupOpen（浮层是否打开），供 QML flags 绑定判断是否置顶"""
        value = bool(value)
        if value != self._popup_open:
            self._popup_open = value
            self.popupOpenChanged.emit()

    @Property(bool, notify=popupOpenChanged)
    def popupOpen(self):
        return self._popup_open

    @Slot(result=bool)
    def isUiAboveTaskbar(self):
        """检测当前 UI 是否位于任务栏上层（供 QML 监测/调试用）"""
        try:
            return self.plugin._is_above_taskbar()
        except Exception:
            return True

    def _get_main_widgets_layer(self):
        """读取主程序 widgets_layer 配置：top/bottom/normal（跟随软件设置用）"""
        try:
            return self.plugin._configs.preferences.widgets_layer
        except Exception:
            return "top"

    def _update_layer_state(self):
        """根据插件 widgets_layer 设置 + 主程序 widgets_layer 配置计算置顶/置底状态。

        follow 时跟随主程序（top→置顶、bottom→置底、normal→普通），结果经
        layerTopmost/layerBottommost 暴露给 QML flags 绑定。
        """
        try:
            strategy = self.plugin.settings_backend.getString("widgets_layer")
        except Exception:
            strategy = "follow"
        if strategy not in ("follow", "top", "bottom"):
            strategy = "follow"

        topmost = False
        bottommost = False
        if strategy == "top":
            topmost = True
        elif strategy == "bottom":
            bottommost = True
        else:  # follow：跟随主程序配置
            main_layer = self._get_main_widgets_layer()
            if main_layer == "top":
                topmost = True
            elif main_layer == "bottom":
                bottommost = True
            # normal → 两者都 False（普通层级）

        if topmost != self._layer_topmost or bottommost != self._layer_bottommost:
            self._layer_topmost = topmost
            self._layer_bottommost = bottommost
            self.layerChanged.emit()

    @Property(bool, notify=layerChanged)
    def layerTopmost(self):
        """QML flags 绑定：正常模式下是否置顶"""
        return self._layer_topmost

    @Property(bool, notify=layerChanged)
    def layerBottommost(self):
        """QML flags 绑定：正常模式下是否置底"""
        return self._layer_bottommost

    def _update_countdown_style(self):
        """从插件设置读取倒计时样式（default/large），变化时 emit 信号供 QML 更新字号。"""
        try:
            style = self.plugin.settings_backend.getString("countdown_style")
        except Exception:
            style = "default"
        if style not in ("default", "large"):
            style = "default"
        if style != self._countdown_style:
            self._countdown_style = style
            self.countdownStyleChanged.emit()

    @Property(str, notify=countdownStyleChanged)
    def countdownStyle(self):
        """倒计时样式：default（默认字号）/ large（大字号）"""
        return self._countdown_style

    @Property(str, notify=modeChanged)
    def mode(self):
        return self._mode

    @Property(int, notify=positionChanged)
    def uiX(self):
        return self._ui_x

    @Property(int, notify=positionChanged)
    def uiY(self):
        return self._ui_y

    @Property(int, notify=widthChanged)
    def uiWidth(self):
        return self._ui_width

    @Property(float, notify=opacityChanged)
    def uiOpacity(self):
        return self._opacity

    @Property(list, notify=lessonsUpdated)
    def displayItems(self):
        return self._display_items

    @Property(str, notify=lessonsUpdated)
    def currentLessonId(self):
        return self._current_lesson_id

    @Property(str, notify=lessonsUpdated)
    def nextLessonId(self):
        return self._next_lesson_id

    @Property(int, notify=lessonsUpdated)
    def currentState(self):
        return self._current_state

    @Property(bool, notify=themeChanged)
    def isDarkTheme(self):
        return self._is_dark

    @Property(str, notify=lessonsUpdated)
    def currentIcon(self):
        return self._current_icon

    @Property(str, notify=remainingTextChanged)
    def currentRemainingText(self):
        return self._current_remaining_text

    @Property(str, notify=fontChanged)
    def fontFamily(self):
        return self._font_family

    @Property(int, notify=fontChanged)
    def fontWeight(self):
        return self._font_weight
    
    @Property(float, notify=bgOpacityChanged)
    def bgOpacity(self):
        return self._bg_opacity

    @Property(float, notify=scaleFactorChanged)
    def scaleFactor(self):
        return self._scale_factor

    @Property(float, notify=widgetRadiusChanged)
    def widgetRadius(self):
        """外围胶囊圆角半径（已按主程序 widget_corner_radius 换算，未乘缩放因子）"""
        return self._widget_radius

    def set_switching(self, value):
        """设置窗口切换标记（切换期间禁用按钮，防止误操作）"""
        if value != self._switching:
            self._switching = bool(value)
            self.switchingChanged.emit()

    @Property(bool, notify=switchingChanged)
    def switching(self):
        return self._switching


class SettingsBackend(QObject):
    """插件设置后端：设置项默认值写死在源码，配置文件按需生成。

    - 配置文件路径：<plugin PATH>/settings.json，初始（打包时）不包含。
    - 一经用户配置（setBool），即生成/更新配置文件。
    - 读取规则：配置文件有该键 → 用配置值；没有 → 用 DEFAULT_SETTINGS 默认值。
    - "恢复默认设置"（resetDefaults）= 删除配置文件，全部回落到默认值。
    """

    settingsChanged = Signal()

    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin
        self._config_path = os.path.join(plugin.PATH, SETTINGS_CONFIG_FILENAME)
        self._config = self._load_config()
        # 插件元数据（"关于"页展示用，从 cwplugin.json 读取，与发版流程同步）
        self._plugin_meta = self._load_plugin_meta()

    def _load_plugin_meta(self):
        """读取 cwplugin.json 获取插件元数据；缺失/损坏时返回空 dict（"关于"页用兜底值）"""
        try:
            meta_path = os.path.join(self.plugin.PATH, "cwplugin.json")
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            plugin_logger.debug(f"读取插件元数据失败: {e}")
        return {}

    @Property(str, constant=True)
    def pluginName(self):
        return self._plugin_meta.get("name", "Lessons Displayer")

    @Property(str, constant=True)
    def pluginVersion(self):
        return self._plugin_meta.get("version", "0.0.0")

    @Property(str, constant=True)
    def pluginAuthor(self):
        return self._plugin_meta.get("author", "")

    @Property(str, constant=True)
    def pluginUrl(self):
        return self._plugin_meta.get("url", "")

    @Property(str, constant=True)
    def pluginDescription(self):
        return self._plugin_meta.get("description", "")

    def _load_config(self):
        """读取配置文件；不存在/损坏时返回空 dict（全部用默认值）"""
        try:
            if os.path.exists(self._config_path):
                with open(self._config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            plugin_logger.debug(f"读取设置失败（使用默认值）: {e}")
        return {}

    def _save_config(self):
        """写入配置文件（首次调用即生成配置文件）"""
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
            plugin_logger.debug(f"设置已保存: {self._config_path}")
        except Exception as e:
            plugin_logger.debug(f"保存设置失败: {e}")

    @Slot(str, result=bool)
    def getBool(self, key):
        """读取设置：配置文件有该键用配置值，否则用源码默认值"""
        return self._config.get(key, DEFAULT_SETTINGS.get(key, False))

    @Slot(str, bool)
    def setBool(self, key, value):
        """写入设置项（自动保存，首次写入生成配置文件）"""
        value = bool(value)
        if self._config.get(key) == value:
            return
        self._config[key] = value
        self._save_config()
        self.settingsChanged.emit()

    @Slot(str, result=str)
    def getString(self, key):
        """读取字符串设置：配置文件有该键用配置值，否则用源码默认值"""
        return self._config.get(key, DEFAULT_SETTINGS.get(key, ""))

    @Slot(str, str)
    def setString(self, key, value):
        """写入字符串设置项（自动保存，首次写入生成配置文件）"""
        value = str(value)
        if self._config.get(key) == value:
            return
        self._config[key] = value
        self._save_config()
        self.settingsChanged.emit()

    @Slot(str, result=int)
    def getInt(self, key):
        """读取整数设置：配置文件有该键用配置值，否则用源码默认值"""
        try:
            return int(self._config.get(key, DEFAULT_SETTINGS.get(key, 0)))
        except Exception:
            return int(DEFAULT_SETTINGS.get(key, 0))

    @Slot(str, int)
    def setInt(self, key, value):
        """写入整数设置项（自动保存，首次写入生成配置文件）"""
        value = int(value)
        if self._config.get(key) == value:
            return
        self._config[key] = value
        self._save_config()
        self.settingsChanged.emit()

    @Slot()
    def resetDefaults(self):
        """恢复默认设置：删除配置文件，全部回落到源码默认值"""
        try:
            if os.path.exists(self._config_path):
                os.remove(self._config_path)
                plugin_logger.info(f"已删除配置文件（恢复默认设置）: {self._config_path}")
        except Exception as e:
            plugin_logger.debug(f"删除配置文件失败: {e}")
        self._config = {}
        self.settingsChanged.emit()

    @Property(bool, notify=settingsChanged)
    def hasConfig(self):
        """是否已生成配置文件（用于界面提示当前是否使用默认值）"""
        return os.path.exists(self._config_path)


class Plugin(CW2Plugin):
    def __init__(self, api):
        super().__init__(api)
        self._subjects_map = {}
        self._subjects_name_map = {}
        self.backend = None
        self.is_dark_theme = False
        self.engine = None
        self.window = None
        self.ui_item = None
        self.ui_loader = None
        self._ui_ready_checked = False
        self._layer_timer = None
        self._width_timer = None
        self._scroll_timer = None
        self._theme_timer = None
        self._configs = None
        self._mask_enabled = True
        self.settings_backend = None
        # 日志文件 handler id（on_unload 时移除，否则 Windows 下删除插件目录会因文件占用失败）
        self._log_handler_id = None
        # 弹出浮层（右键菜单/设置页）置顶引用计数：>0 时所有插件窗口持续置顶
        self._topmost_refs = 0

        # 启动淡入：等待宽度变化或超时（见 _on_ui_ready）
        self._ui_fade_timeout_timer = None
        self._ui_fade_in_started = False
        self._initial_ui_width = 0

        # 特殊模式专用全屏窗口（进入特殊模式时创建，保证完全置顶）
        self.special_engine = None
        self.special_window = None

        # 笔迹数据存储（SQLite，data/ 目录；擦除全屏时新建会话文件）
        self._stroke_store = None
        # 笔迹数据后端（特殊窗口引擎专用；随窗口销毁）
        self._wb_backend = None

        # 贴边隐藏：主程序小组件隐藏时是否已真正隐藏插件主窗口（避免特殊模式
        # 与初始显示逻辑把它误当作"未显示"）；_hide_window_timer 用于延迟隐藏
        # （等胶囊滑出屏幕后再隐藏，避免恢复时的陈旧帧闪现）
        self._edge_hidden = False
        self._hide_window_timer = None

        self._cursor_timer = QTimer()
        self._cursor_timer.timeout.connect(self._check_mouse_idle)
        self._last_mouse_pos = None
        self._idle_seconds = 0
        self._cursor_hidden = False

        plugin_logger.info("今日课程插件初始化完成")

    def _setup_logging(self):
        try:
            log_dir = os.path.join(self.PATH, "log")
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, "lessons-displayer.log")
            # 保存 handler id，供 on_unload 时释放日志文件句柄
            self._log_handler_id = logger.add(
                log_file,
                rotation="1 MB",
                retention="7 days",
                encoding="utf-8",
                format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
                level="DEBUG",
                filter=lambda record: record["extra"].get("plugin") == "lessons-displayer"
            )
            plugin_logger.debug(f"日志文件已创建: {log_file}")
        except Exception as e:
            self._log_handler_id = None
            plugin_logger.error(f"设置插件日志失败: {e}")

    def _remove_logging(self):
        """移除插件日志处理器，释放 log/ 句柄（否则 Windows 上删除插件目录会因文件占用失败）。"""
        try:
            if getattr(self, "_log_handler_id", None) is not None:
                logger.remove(self._log_handler_id)
                self._log_handler_id = None
                plugin_logger.debug("已移除插件日志处理器")
        except Exception as e:
            plugin_logger.debug(f"移除插件日志处理器失败: {e}")

    def _ensure_engine_import_paths(self, engine):
        """确保 QML 引擎能解析 `import RinUI`（新版主程序不再为插件引擎注入该路径，否则根对象为空）。

        把 RinUI 包所在目录（site-packages，含 qmldir）加入引擎导入路径；重复添加无副作用。
        """
        candidates = []
        try:
            from RinUI.core.config import RINUI_PATH
            candidates.append(str(RINUI_PATH))
        except Exception:
            try:
                import RinUI as _rinui_mod
                # RinUI/__init__.py 的父目录的父目录 = site-packages
                candidates.append(os.path.dirname(os.path.dirname(_rinui_mod.__file__)))
            except Exception as e:
                plugin_logger.debug(f"获取 RinUI 导入路径失败: {e}")
                return False
        try:
            existing = set(engine.importPathList())
            added = False
            for p in candidates:
                if p and p not in existing:
                    engine.addImportPath(p)
                    added = True
                    plugin_logger.debug(f"已为引擎添加 RinUI 导入路径: {p}")
            return added
        except Exception as e:
            plugin_logger.debug(f"设置引擎导入路径失败: {e}")
            return False

    def on_load(self):
        # 兼容新版主程序：调用基类 on_load（设 pid、注册后端桥、发 initialized；旧版空实现无副作用）
        super().on_load()
        self._setup_logging()
        plugin_logger.info("今日课程插件加载成功")

        self.api.runtime.updated.connect(self.on_runtime_updated)
        self.api.theme.changed.connect(self.on_theme_changed)
        plugin_logger.debug("已连接 theme.changed 信号")

        self._update_subjects_map()

        # 深浅色主题：优先跟随主程序配置（RinUI ThemeManager），回退系统主题
        self._init_theme()
        if _HAS_RIN_THEME:
            try:
                # 主程序设置切换深浅色主题时同步（Light/Dark/Auto）
                RinThemeManager().themeChanged.connect(self._on_rin_theme_changed)
                plugin_logger.debug("已连接 RinUI 主题变化信号")
            except Exception as e:
                plugin_logger.debug(f"连接 RinUI 主题信号失败: {e}")

        self._configs = self.api._app.configs
        self._configs.configChanged.connect(self._on_config_changed)
        plugin_logger.debug("已连接 configChanged 信号")

        self.backend = LessonsBackend(self)
        self.backend.update_lessons()
        self.backend.set_dark_theme(self.is_dark_theme)
        self.backend.update_position()
        # 首次显示前重置 opacity 为 0，避免 uiLoader 加载后内容直接可见
        self.backend.set_ui_opacity(0)
        self.backend.modeChanged.connect(self._on_mode_changed)
        plugin_logger.debug("已连接 modeChanged 信号")

        # 图层状态变化时立即应用（置顶/置底/普通互斥），置顶稳定后无需每秒刷新
        self.backend.layerChanged.connect(self._on_layer_changed)
        plugin_logger.debug("已连接 layerChanged 信号")

        self.backend.positionChanged.connect(self._update_mask)
        self.backend.widthChanged.connect(self._update_mask)

        # 设置后端：默认值写死在源码，配置按需生成 settings.json
        self.settings_backend = SettingsBackend(self)
        # 插件设置变化（如小组件图层）时刷新图层状态并驱动 QML flags 绑定
        self.settings_backend.settingsChanged.connect(self._on_plugin_settings_changed)
        if self.backend:
            self.backend._update_layer_state()
            # settings_backend 就绪后重新加载倒计时样式（__init__ 时其为 None，会回落默认）
            self.backend._update_countdown_style()
        plugin_logger.debug("已连接 settingsChanged 信号")

        self.engine = QQmlApplicationEngine()
        # 兼容新版主程序：确保 import RinUI 可解析（否则 QML 加载失败，无根对象）
        self._ensure_engine_import_paths(self.engine)
        self.engine.rootContext().setContextProperty("lessonsBackend", self.backend)
        self.engine.rootContext().setContextProperty("settingsBackend", self.settings_backend)

        qml_path = os.path.join(self.PATH, "qml", "FullScreenWindow.qml")
        plugin_logger.debug(f"加载 QML 文件: {qml_path}")
        qml_url = QUrl.fromLocalFile(qml_path)
        self.engine.load(qml_url)

        if self.engine.rootObjects():
            self.window = self.engine.rootObjects()[0]
            screen = QGuiApplication.primaryScreen().availableGeometry()
            self.window.setProperty("screenWidth", screen.width())
            self.window.setProperty("screenHeight", screen.height())

            self.window.setFlag(Qt.FramelessWindowHint, True)
            self.window.setColor(Qt.transparent)

            # 事件过滤器：特殊模式下鼠标按下/移动时恢复隐藏的光标
            self.window.installEventFilter(self)

            self.window.uiReady.connect(self._on_ui_ready)
            plugin_logger.debug("已连接 uiReady 信号")

            # 特殊模式启动动画播放完成后，显示已准备好的专用窗口
            try:
                self.window.specialAnimationFinished.connect(self._on_special_animation_finished)
                plugin_logger.debug("已连接 specialAnimationFinished 信号")
            except Exception as e:
                plugin_logger.debug(f"连接 specialAnimationFinished 失败: {e}")

            QTimer.singleShot(5000, self._check_ui_ready_timeout)

            plugin_logger.info("全屏窗口已创建（隐藏状态）")
        else:
            plugin_logger.error("无法创建全屏窗口")

        self._start_theme_polling()
        self._start_layer_sync()
        self._start_scroll_timer()

    def _on_config_changed(self):
        plugin_logger.debug("配置变化，更新位置、背景不透明度和字体")
        # 先同步贴边隐藏的窗口显隐再更新位置（否则位置动画在隐藏期间被浪费，恢复时闪现目标位置）
        self._sync_hide_visibility()
        if self.backend:
            # 纯平移（位置/隐藏变化，宽度不变）：动画性能优化启用时动画期间临时禁用 mask
            self.backend.update_position(trigger_anim_optimize=True)
            self.backend._update_font()
            self.backend._update_bg_opacity()
            self.backend._update_scale_factor()
            # 主程序"小组件圆角半径"配置变化时刷新外围圆角
            self.backend._update_widget_radius()
            # 主程序 widgets_layer 配置变化（跟随软件设置）时刷新图层状态
            self.backend._update_layer_state()

    def _sync_hide_visibility(self):
        """贴边隐藏时真正隐藏插件主窗口，解除时恢复显示（新版主程序仅 opacity=0 仍驻留屏幕）。

        仅在正常模式处理，用 _edge_hidden 区分"因贴边隐藏"与"尚未显示/特殊模式隐藏"。
        """
        if not self.window or not self.backend or not self._configs:
            return
        if self.backend.mode != "normal":
            return
        try:
            hide = self._configs.interactions.hide.state
        except Exception as e:
            plugin_logger.debug(f"读取隐藏状态失败: {e}")
            return
        try:
            if hide:
                if self.window.isVisible() and not self._edge_hidden:
                    self._edge_hidden = True
                    # 延迟隐藏：等胶囊滑出屏幕后再隐藏，避免恢复时闪现陈旧帧
                    try:
                        if self._hide_window_timer:
                            self._hide_window_timer.stop()
                        self._hide_window_timer = QTimer()
                        self._hide_window_timer.setSingleShot(True)
                        self._hide_window_timer.timeout.connect(self._do_edge_hide)
                        self._hide_window_timer.start(500)
                    except Exception:
                        self._do_edge_hide()
            else:
                # 解除隐藏：取消待执行的延迟隐藏
                if self._hide_window_timer:
                    try:
                        self._hide_window_timer.stop()
                    except Exception:
                        pass
                if self._edge_hidden and not self.window.isVisible():
                    self._edge_hidden = False
                    self.window.show()
                    # 恢复后确保 mask 应用到正常位置（动画优化可能已禁用 mask）
                    self._enable_mask_and_update()
                    plugin_logger.debug("贴边隐藏解除：已恢复插件主窗口")
        except Exception as e:
            plugin_logger.debug(f"同步贴边隐藏窗口失败: {e}")

    def _do_edge_hide(self):
        """延迟隐藏到期：胶囊已滑出屏幕后真正隐藏插件主窗口。"""
        try:
            if self.window and self._edge_hidden and self.window.isVisible():
                self.window.hide()
                plugin_logger.debug("贴边隐藏：已隐藏插件主窗口（胶囊滑出后）")
        except Exception as e:
            plugin_logger.debug(f"延迟隐藏窗口失败: {e}")

    def _check_mask_health(self):
        """mask 自愈：正常模式、无占用、可见时若 mask 被意外禁用/清空则重新应用。"""
        try:
            if not self.window or not self.backend:
                return
            if self.backend.mode != "normal":
                return
            if not self.window.isVisible():
                return
            if self.backend._mask_hide_refs > 0:
                return
            if self.backend._anim_optimize_active:
                return
            # 引用计数归零且无动画优化时 mask 本应处于启用状态。
            if not self._mask_enabled:
                self._mask_enabled = True
                self._update_mask()
                plugin_logger.debug("mask 自愈：恢复被意外禁用的 mask")
            else:
                # 实际 mask 为空（可能被重置）→ 重新应用，防止窗口失去裁剪
                cur = self.window.mask()
                if cur is not None and cur.isEmpty():
                    self._update_mask()
                    plugin_logger.debug("mask 自愈：重新应用被清空的 mask")
        except Exception as e:
            plugin_logger.debug(f"mask 自愈检查失败: {e}")

    def _on_plugin_settings_changed(self):
        """插件设置变化（小组件图层/倒计时样式/自动关闭等）：刷新图层状态，驱动 QML flags 绑定重新求值"""
        if self.backend:
            self.backend._update_layer_state()
            # 倒计时样式变化：更新样式属性（QML 字号）并重新生成倒计时文本
            self.backend._update_countdown_style()
            self.backend._update_current_icon_and_remaining()
            # 自动关闭设置变化：重新检查（开关/延迟时间/单位变化立即生效）
            self.backend._check_auto_close()

    def _start_layer_sync(self):
        self._layer_timer = QTimer()
        self._layer_timer.timeout.connect(self._sync_window_layer)
        self._layer_timer.start(1000)
        plugin_logger.debug("已启动窗口层级同步定时器")

    def _sync_window_layer(self):
        if not self.window or not self.backend:
            return
        # 有弹出浮层（右键菜单/设置页）打开：跳过层级同步（避免 lower 掉已置顶的窗口）
        if self._topmost_refs > 0:
            return
        if self.backend.mode != "normal":
            # 特殊模式下持续强制置顶，防止窗口层级被重置导致任务栏露出
            self._force_topmost()
            return
        try:
            # 每次同步重算图层状态（layerChanged 驱动置顶应用）；置顶稳定后无需每秒刷新，非置顶仍每秒应用作兜底
            self.backend._update_layer_state()
            if not self.backend.layerTopmost:
                self._apply_layer_flags()
        except Exception as e:
            plugin_logger.debug(f"同步窗口层级失败: {e}")
        # mask 自愈：周期检查并修复偶发的 mask 失效/错位
        self._check_mask_health()

    def _apply_layer_flags(self):
        """按图层策略设置 Qt flags + Win32 层级（置顶/置底/普通互斥）。

        与 _apply_topmost_all 同一套置顶方式（默认置顶用 SWP_NOACTIVATE 不抢焦点），
        Python 统一互斥控制，避免 QML flags 与 setFlag 冲突残留。
        """
        if not self.window or not self.backend:
            return
        try:
            topmost = self.backend.layerTopmost
            bottommost = self.backend.layerBottommost

            # Qt flags：互斥设置 top/bottom hint
            flags = self.window.flags()
            new_flags = flags & ~(Qt.WindowStaysOnTopHint | Qt.WindowStaysOnBottomHint)
            if topmost:
                new_flags |= Qt.WindowStaysOnTopHint
            elif bottommost:
                new_flags |= Qt.WindowStaysOnBottomHint
            if new_flags != flags:
                self.window.setFlags(new_flags)

            if sys.platform != 'win32':
                return
            hwnd = int(self.window.winId())
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            if topmost:
                ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0,
                                                  SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                self.window.raise_()
            else:
                ctypes.windll.user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0,
                                                  SWP_NOMOVE | SWP_NOSIZE)
                if bottommost:
                    self.window.lower()
        except Exception as e:
            plugin_logger.debug(f"应用图层失败: {e}")

    def _on_layer_changed(self):
        """图层状态变化时立即应用图层；置顶稳定后无需每秒刷新。仅正常模式且无浮层占用时应用。"""
        if not self.window or not self.backend:
            return
        if self.backend.mode != "normal":
            return
        if self._topmost_refs > 0:
            return
        self._apply_layer_flags()

    def _start_theme_polling(self):
        self._theme_timer = QTimer()
        self._theme_timer.timeout.connect(self._check_system_theme)
        self._theme_timer.start(1000)
        plugin_logger.debug("已启动主题轮询定时器")

    def _init_theme(self):
        """初始化深浅色：优先跟随主程序配置（RinUI ThemeManager），回退系统主题。"""
        if _HAS_RIN_THEME:
            try:
                rin_theme = RinThemeManager().get_theme()  # "Light"/"Dark"（Auto 时已解析）
                self.is_dark_theme = (rin_theme == "Dark")
                plugin_logger.debug(f"跟随主程序主题: {rin_theme}, 深色模式: {self.is_dark_theme}")
                return
            except Exception as e:
                plugin_logger.debug(f"读取主程序主题失败，回退系统主题，错误: {e}")
        try:
            sys_theme = darkdetect.theme()
            self.is_dark_theme = (sys_theme == "Dark")
            plugin_logger.debug(f"通过 darkdetect 获取初始主题: {sys_theme}, 深色模式: {self.is_dark_theme}")
        except Exception as e:
            self.is_dark_theme = False
            plugin_logger.debug(f"无法获取系统主题，使用默认浅色，错误: {e}")

    def _on_rin_theme_changed(self, actual_theme):
        """主程序深浅色主题变化（RinUI ThemeManager 信号，参数为实际主题 Light/Dark）"""
        is_dark = (actual_theme == "Dark")
        if is_dark != self.is_dark_theme:
            plugin_logger.debug(f"主程序主题变化: {actual_theme}, 深色模式: {is_dark}")
            self.is_dark_theme = is_dark
            if self.backend:
                self.backend.set_dark_theme(is_dark)

    def _check_system_theme(self):
        if _HAS_RIN_THEME:
            # 已跟随主程序主题（RinUI Auto 模式自行监听系统主题），无需再轮询
            return
        try:
            sys_theme = darkdetect.theme()
            is_dark = (sys_theme == "Dark")
            if is_dark != self.is_dark_theme:
                plugin_logger.debug(f"系统主题变化: {sys_theme}, 深色模式: {is_dark}")
                self.is_dark_theme = is_dark
                if self.backend:
                    self.backend.set_dark_theme(is_dark)
        except Exception as e:
            pass

    def _start_width_polling(self):
        self._width_timer = QTimer()
        self._width_timer.timeout.connect(self._update_widgets_width)
        self._width_timer.start(500)
        plugin_logger.debug("已启动小组件宽度轮询定时器")

    def _update_widgets_width(self):
        if not self.ui_item:
            return
        try:
            root_window = self.api._app.widgets_window.root_window
            if not root_window:
                return
            loader = root_window.findChild(QObject, "widgetsLoader")
            if not loader:
                return

            children = loader.childItems()
            if not children:
                return

            valid_children = []
            for child in children:
                obj_name = child.objectName()
                width = child.width()
                if obj_name != "addWidgetsContainer" and width > 0:
                    valid_children.append(child)

            if not valid_children:
                return

            last_child = valid_children[-1]
            total_width = int(last_child.x() + last_child.width())

            if total_width > 0 and self.backend:
                if total_width != self.backend._ui_width:
                    self.backend.set_ui_width(total_width)
        except Exception as e:
            plugin_logger.debug(f"计算小组件宽度失败: {e}")

    def _start_scroll_timer(self):
        self._scroll_timer = QTimer()
        self._scroll_timer.timeout.connect(self._request_scroll)
        self._scroll_timer.start(1000)
        plugin_logger.debug("已启动滚动请求定时器")

    def _request_scroll(self):
        if self.backend:
            self.backend.request_scroll_to_current()

    def _check_ui_ready_timeout(self):
        if not hasattr(self, 'ui_item') or not self.ui_item:
            plugin_logger.error("uiReady 信号未在 5 秒内触发，Loader 可能加载失败")
            if self.window:
                plugin_logger.debug(f"窗口对象有效，flags: {self.window.flags()}")
                children = self.window.children()
                plugin_logger.debug(f"窗口共有 {len(children)} 个子对象")
                for i, child in enumerate(children):
                    obj_name = child.objectName()
                    class_name = child.metaObject().className()
                    plugin_logger.debug(f"  [{i}] {class_name}: {obj_name}")

                loader = self.window.findChild(QObject, "uiLoader")
                if loader:
                    status = loader.property("status")
                    error_str = loader.property("errorString")
                    plugin_logger.error(f"Loader status: {status} (0=Null,1=Ready,2=Loading,3=Error), error: {error_str}")
                else:
                    plugin_logger.error("无法找到 uiLoader")
            else:
                plugin_logger.error("窗口对象无效")

    def _on_ui_ready(self):
        plugin_logger.debug("_on_ui_ready 被调用")
        try:
            loader = self.window.findChild(QObject, "uiLoader")
            if not loader:
                plugin_logger.error("无法找到 uiLoader")
                return

            self.ui_loader = loader
            self.ui_item = loader.property("item")
            if not self.ui_item:
                plugin_logger.error("UI 项未加载")
                return

            x = self.ui_item.x()
            y = self.ui_item.y()
            w = self.ui_item.width()
            h = self.ui_item.height()
            plugin_logger.debug(f"UI 项初始位置: ({x}, {y}, {w}, {h})")

            self.ui_loader.xChanged.connect(self._update_mask)
            self.ui_loader.yChanged.connect(self._update_mask)
            self.ui_loader.widthChanged.connect(self._update_mask)
            self.ui_loader.heightChanged.connect(self._update_mask)

            self._update_mask()

            hide = self._configs.interactions.hide.state
            self.backend.set_ui_opacity(0)

            # 启动淡入：宽度一旦变化或 2 秒内无变化即启动（与宽度过渡动画同步）
            self._ui_fade_in_started = False
            self._initial_ui_width = int(self.backend.uiWidth)
            plugin_logger.debug(f"初始 UI 宽度: {self._initial_ui_width}")

            def do_fade_in():
                """宽度已变化或超时：启动淡入（与宽度过渡动画同步进行）"""
                if self._ui_fade_in_started:
                    return
                self._ui_fade_in_started = True
                if self._ui_fade_timeout_timer:
                    self._ui_fade_timeout_timer.stop()
                target = 0 if hide else 1
                plugin_logger.info("开始淡入（宽度过渡同步进行）")
                QTimer.singleShot(0, lambda: self.backend.set_ui_opacity(target))

            # 兜底：2 秒内宽度无变化则淡入
            self._ui_fade_timeout_timer = QTimer()
            self._ui_fade_timeout_timer.setSingleShot(True)
            self._ui_fade_timeout_timer.timeout.connect(do_fade_in)
            self._ui_fade_timeout_timer.start(2000)

            # 宽度首次变化即淡入（仅触发一次）
            def on_width_first_changed():
                if int(self.backend.uiWidth) != self._initial_ui_width:
                    try:
                        self.backend.widthChanged.disconnect(on_width_first_changed)
                    except Exception:
                        pass
                    do_fade_in()

            self.backend.widthChanged.connect(on_width_first_changed)

            # 显示窗口（opacity 保持 0，内容待淡入）
            self.window.show()
            plugin_logger.info("窗口已显示，等待宽度变化后淡入")

            # 启动时若主程序已处于贴边隐藏状态，则直接隐藏插件主窗口
            self._edge_hidden = False
            self._sync_hide_visibility()

            self._sync_window_layer()
            # 窗口就绪后显式应用一次图层（置顶/置底/普通）：_sync_window_layer
            # 在置顶状态时不再每秒应用，须在此确保初始置顶生效
            self._apply_layer_flags()
            self._start_width_polling()

            plugin_logger.info("UI 已加载，mask 更新连接已建立")
        except Exception as e:
            plugin_logger.error(f"处理 UI 就绪失败: {e}")

    def _update_mask(self):
        if not self.window:
            return
        if self.backend and self.backend.mode != "normal":
            self.window.setMask(QRegion())
            return
        if not self._mask_enabled:
            return
        try:
            if self.ui_loader:
                x = int(self.ui_loader.property("x"))
                y = int(self.ui_loader.property("y"))
                w = int(self.ui_loader.property("width"))
                h = int(self.ui_loader.property("height"))
            elif self.backend:
                x = int(self.backend.uiX)
                y = int(self.backend.uiY)
                w = int(self.backend.uiWidth)
                h = UI_HEIGHT
            else:
                return
            region = QRegion(x, y, w, h)
            self.window.setMask(region)
        except Exception as e:
            plugin_logger.error(f"更新 mask 失败: {e}")

    def _check_mouse_idle(self):
        """检查鼠标是否空闲，用于特殊模式下自动隐藏光标"""
        if not self._active_window() or self.backend.mode == "normal":
            return
        pos = QCursor.pos()
        if self._last_mouse_pos == pos:
            self._idle_seconds += 0.5
            if self._idle_seconds >= 4.0 and not self._cursor_hidden:
                # 作用于当前实际显示的窗口（特殊模式下为专用全屏窗口）
                self._active_window().setCursor(Qt.BlankCursor)
                self._cursor_hidden = True
        else:
            self._last_mouse_pos = pos
            self._idle_seconds = 0
            if self._cursor_hidden:
                # 恢复光标同样作用于当前实际显示的窗口（否则专用窗口仍保持 BlankCursor）
                self._active_window().setCursor(Qt.ArrowCursor)
                self._cursor_hidden = False

    def eventFilter(self, obj, event):
        """特殊模式下鼠标按下/移动时恢复隐藏的光标（兜底"点击不改变位置"不触发移动检测的情况）。"""
        if self._cursor_hidden:
            try:
                etype = event.type()
                if etype == QEvent.MouseButtonPress or etype == QEvent.MouseMove:
                    win = self._active_window()
                    if win:
                        win.setCursor(Qt.ArrowCursor)
                    self._cursor_hidden = False
                    self._last_mouse_pos = QCursor.pos()
                    self._idle_seconds = 0
            except Exception:
                pass
        # QObject.eventFilter 默认返回 False（不拦截事件，继续向目标分发）
        return False

    def _enable_mask_and_update(self):
        """延迟后恢复 mask 更新（仅在引用计数归零且正常模式时，避免裁掉仍打开的浮层）。"""
        if not self.backend:
            return
        if self.backend.mode != "normal":
            return
        if self.backend._mask_hide_refs > 0:
            return
        if self.backend._anim_optimize_active:
            return
        self._mask_enabled = True
        self._update_mask()

    def _make_foreground_window(self, hwnd):
        """将窗口设为系统前台窗口（绕过 Windows 前台锁定）

        任务栏由系统按"前台窗口"管理：只有前台窗口是全屏置顶窗口时，
        任务栏才会保持在窗口下方。若其它窗口（如资源管理器）是前台，
        任务栏会浮在置顶窗口之上。这里用 AttachThreadInput 技巧绕过
        前台锁定，确保可靠地置为前台。
        """
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            if user32.GetForegroundWindow() == hwnd:
                return
            current_tid = kernel32.GetCurrentThreadId()
            fg_hwnd = user32.GetForegroundWindow()
            fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)
            attached = False
            if fg_tid and fg_tid != current_tid:
                if user32.AttachThreadInput(current_tid, fg_tid, True):
                    attached = True
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            if attached:
                user32.AttachThreadInput(current_tid, fg_tid, False)
        except Exception as e:
            plugin_logger.debug(f"设置前台窗口失败: {e}")

    def _active_window(self):
        """特殊模式下若专用窗口已显示则使用它，否则使用主窗口。

        强制置顶/设前台/光标操作等应作用于当前实际显示在屏幕上的窗口。
        """
        if (self.backend and self.backend.mode != "normal"
                and self.special_window and self.special_window.isVisible()):
            return self.special_window
        return self.window

    def _is_above_taskbar(self, hwnd=None):
        """检测窗口是否位于任务栏上层（覆盖任务栏）

        任务栏由系统按"前台窗口"动态管理（静态 z 序不可靠）：只有前台
        窗口为全屏置顶窗口时任务栏才会保持在窗口下方。因此判定条件：
        1) 窗口是系统前台窗口（GetForegroundWindow）
        2) 窗口是置顶窗口（WS_EX_TOPMOST）
        3) 窗口矩形覆盖到屏幕底部（任务栏区域）
        三者同时满足才认为 UI 位于任务栏上层、任务栏被其覆盖。
        """
        if sys.platform != 'win32':
            return True
        try:
            user32 = ctypes.windll.user32
            if hwnd is None:
                win = self._active_window()
                if not win:
                    return False
                hwnd = int(win.winId())

            # 1) 必须是系统前台窗口，否则系统会让任务栏浮在其上
            if user32.GetForegroundWindow() != hwnd:
                return False

            # 2) 必须是置顶窗口
            GWL_EXSTYLE = -20
            WS_EX_TOPMOST = 0x00000008
            if not (user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST):
                return False

            # 3) 必须覆盖到屏幕底部（任务栏所在区域）
            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
            r = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            screen = QGuiApplication.primaryScreen()
            if screen:
                geo = screen.geometry()
                if r.bottom < geo.y() + geo.height():
                    return False

            return True
        except Exception as e:
            plugin_logger.debug(f"检测任务栏层级失败: {e}")
            return True

    def _force_topmost(self):
        """重新强制窗口置顶并置为前台（Windows），确保全屏时覆盖任务栏。

        特殊模式下只操作专用窗口（special_window），绝不对主窗口 raise/设前台，
        否则主窗口（同为 topmost 且后 raise）会盖住专用窗口导致工具栏"消失再显示"。
        """
        if not self.window or not self.backend:
            return
        if self.backend.mode == "normal":
            return
        if sys.platform != 'win32':
            return
        # 特殊模式：始终针对专用窗口（即使 isVisible 短暂为 False 也不回退到主窗口）
        if self.special_window:
            win = self.special_window
        else:
            win = self.window
        if not win:
            return
        try:
            # 先确保 Qt 层窗口标志一致（防止此前被意外清除导致置顶失效/露出标题栏）
            if not (win.flags() & Qt.WindowStaysOnTopHint):
                win.setFlag(Qt.WindowStaysOnTopHint, True)
            if not (win.flags() & Qt.FramelessWindowHint):
                win.setFlag(Qt.FramelessWindowHint, True)
            hwnd = int(win.winId())
            HWND_TOPMOST = -1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                              SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            win.raise_()
            # 关键：保持前台，否则任务栏会浮在窗口之上
            self._make_foreground_window(hwnd)
        except Exception as e:
            plugin_logger.debug(f"强制置顶失败: {e}")

    def _apply_topmost_all(self, topmost):
        """对主窗口与专用窗口应用/移除置顶（Windows API 直接改标志，不重建窗口）。

        置顶需同时设为系统前台（否则其它前台窗口可压住）；移除仅限正常模式。
        """
        if sys.platform != 'win32':
            return
        wins = []
        if self.window:
            wins.append(self.window)
        if self.special_window and self.special_window.isVisible():
            wins.append(self.special_window)
        if not wins:
            return
        for win in wins:
            try:
                if topmost:
                    if not (win.flags() & Qt.WindowStaysOnTopHint):
                        win.setFlag(Qt.WindowStaysOnTopHint, True)
                    hwnd = int(win.winId())
                    HWND_TOPMOST = -1
                    SWP_NOMOVE = 0x0002
                    SWP_NOSIZE = 0x0001
                    # 模仿特殊模式 _on_mode_changed：不用 SWP_NOACTIVATE（需激活窗口）
                    ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                                      SWP_NOMOVE | SWP_NOSIZE)
                    win.raise_()
                    win.requestActivate()
                    # 关键：模仿特殊模式，设为系统前台窗口（重新取 winId，绕过前台锁定）
                    self._make_foreground_window(int(win.winId()))
                else:
                    # 仅正常模式移除；特殊模式下需保持置顶
                    if self.backend and self.backend.mode != "normal":
                        continue
                    # 图层策略为"始终置顶"（layerTopmost）时保持置顶，
                    # 浮层关闭后不得移除（QML flags 绑定与 _sync_window_layer 兜底都依赖它）
                    if self.backend and self.backend.layerTopmost:
                        continue
                    if win.flags() & Qt.WindowStaysOnTopHint:
                        win.setFlag(Qt.WindowStaysOnTopHint, False)
                    hwnd = int(win.winId())
                    HWND_NOTOPMOST = -2
                    SWP_NOMOVE = 0x0002
                    SWP_NOSIZE = 0x0001
                    ctypes.windll.user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                                                      SWP_NOMOVE | SWP_NOSIZE)
            except Exception as e:
                plugin_logger.debug(f"应用置顶失败: {e}")

    def _ensure_stroke_store(self):
        """确保笔迹 SQLite 存储就绪：优先恢复最近一次会话文件（跨进程保留白板内容
        与清屏链 prev_file），无历史文件才新建初始会话。"""
        if self._stroke_store is None:
            self._stroke_store = StrokeStore(os.path.join(self.PATH, "data"))
        if not self._stroke_store.has_session:
            if self._stroke_store.open_latest():
                plugin_logger.info("已恢复最近笔迹会话: "
                                   + str(self._stroke_store.current_file()))
                return
            screen = QGuiApplication.primaryScreen()
            geo = screen.geometry() if screen else None
            dpr = float(screen.devicePixelRatio()) if screen else 1.0
            self._stroke_store.new_session((geo.width() if geo else 0),
                                           (geo.height() if geo else 0),
                                           dpr, self.backend.mode if self.backend else "")

    def _prepare_special_window(self):
        """按钮按下时即开始创建专用全屏窗口（隐藏，暂不显示）。

        立即创建隐藏的专用窗口并加载内容（利用主窗口播放启动动画的时间作为
        加载时间）；待动画播放完成后由 _on_special_animation_finished 直接显示
        （无渐变动画）。专用窗口以全新状态全屏置顶，保证特殊模式完全置顶
        （避免复用主窗口时任务栏浮在其上）。
        """
        if not self.backend or self.backend.mode == "normal":
            return
        if self.special_window or self.special_engine:
            return
        # 每次进入特殊模式重置为"选择"工具：工具栏 UI 默认选中"选择"，若沿用上次
        # 留下的笔/橡皮后端状态，会出现"UI 显示选择但实际是笔/橡皮"的不一致
        try:
            self.backend.setActiveTool(0)
        except Exception:
            pass
        try:
            self.backend.set_switching(True)
            engine = QQmlApplicationEngine()
            engine.rootContext().setContextProperty("lessonsBackend", self.backend)
            # 抑制新窗口首次加载的展开动画（只对特殊窗口引擎生效），避免与主窗口动画重复
            engine.rootContext().setContextProperty("suppressExpandAnim", True)
            if self.settings_backend:
                engine.rootContext().setContextProperty("settingsBackend", self.settings_backend)
            # 笔迹数据后端：须在 QML 加载前注册 context property 与 image provider，
            # 并把上次会话笔迹载入（QML Image 通过 image://whiteboard/... 显示烘焙 QImage）
            try:
                self._ensure_stroke_store()
                screen = QGuiApplication.primaryScreen()
                geo = screen.geometry() if screen else None
                dpr = float(screen.devicePixelRatio()) if screen else 1.0
                sw = geo.width() if geo else 0
                sh = geo.height() if geo else 0
                wb = WhiteboardBackend()
                wb.set_store(self._stroke_store)
                wb.set_canvas_size(sw, sh)
                wb.set_screen_info(sw, sh, dpr, self.backend.mode)
                wb.load_strokes(self._stroke_store.load_all())
                engine.rootContext().setContextProperty("whiteboardBackend", wb)
                engine.addImageProvider("whiteboard", WhiteboardImageProvider(wb))
                self._wb_backend = wb
            except Exception as e:
                plugin_logger.error(f"接线笔迹后端失败: {e}")
            # 复制主引擎的导入路径（保证 RinUI 等可用）
            try:
                for p in self.engine.importPathList():
                    engine.addImportPath(p)
            except Exception:
                pass
            # 兜底：兼容新版主程序（主引擎可能未注入 RinUI 路径）
            self._ensure_engine_import_paths(engine)
            qml_path = os.path.join(self.PATH, "qml", "SpecialModeWindow.qml")
            engine.load(QUrl.fromLocalFile(qml_path))
            if not engine.rootObjects():
                plugin_logger.error("创建特殊模式窗口失败：无根对象")
                engine.deleteLater()
                self.backend.set_switching(False)
                return
            win = engine.rootObjects()[0]
            self.special_engine = engine
            self.special_window = win
            # 创建即强制无边框工具窗口（QML flags 在某些环境可能未即时生效，这里兜底）
            try:
                win.setFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
            except Exception:
                pass
            # 事件过滤器：特殊模式下鼠标按下/移动时恢复隐藏的光标
            win.installEventFilter(self)
            # 保持隐藏，等待主窗口动画完成信号后直接显示
            plugin_logger.info("特殊模式专用窗口已创建（隐藏，等待主窗口动画完成）")
            # 兜底：即使动画完成信号未触发，也确保专用窗口显示并恢复按钮
            QTimer.singleShot(1500, self._on_special_animation_finished)
            QTimer.singleShot(3000, lambda: self.backend.set_switching(False))
        except Exception as e:
            plugin_logger.error(f"创建特殊模式窗口异常: {e}")
            self._destroy_special_window()
            self.backend.set_switching(False)

    def _on_special_animation_finished(self):
        """主窗口动画完成：直接显示专用窗口（主窗口保留在其下方可见，退出时即时显露胶囊）。"""
        if not self.backend:
            return
        if self.backend.mode == "normal":
            self._destroy_special_window()
            return
        if not self.special_window:
            self.backend.set_switching(False)
            return
        try:
            # 强制无边框工具窗口并铺满屏幕（不依赖 setWindowState(FullScreen)——
            # Tool 窗口在 Windows 上 FullScreen 状态不可靠，可能露出系统标题栏/最小化关闭按钮）
            self.special_window.setFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
            screen = QGuiApplication.primaryScreen()
            if screen:
                self.special_window.setGeometry(screen.geometry())
            self.special_window.show()
            self.special_window.raise_()
            self._force_topmost()
            # 主窗口保持可见在其下方（已渲染就绪），不隐藏
            self.backend.set_switching(False)
            plugin_logger.info("特殊模式专用窗口已显示（主窗口保留在其下方，可即时退出）")
        except Exception as e:
            plugin_logger.error(f"显示特殊模式窗口失败: {e}")
            self.backend.set_switching(False)

    def _destroy_special_window(self):
        """销毁特殊模式专用窗口"""
        if getattr(self, "_wb_backend", None):
            try:
                self._wb_backend.deleteLater()
            except Exception:
                pass
            self._wb_backend = None
        if self.special_window:
            try:
                self.special_window.close()
                self.special_window.deleteLater()
            except Exception:
                pass
            self.special_window = None
        if self.special_engine:
            try:
                self.special_engine.deleteLater()
            except Exception:
                pass
            self.special_engine = None
        if self.backend:
            self.backend.set_switching(False)

    def _on_mode_changed(self):
        """特殊模式切换（混合方案）：进入创建专用全屏窗口保证完全置顶；退出仅销毁专用窗口即时显露胶囊。"""
        mode = self.backend.mode
        if mode == "normal":
            # 退出特殊模式：清零 mask 引用计数（专用窗口销毁时 tooltip/菜单可能未配对释放，会污染 _mask_hide_refs），立即销毁专用窗口并恢复
            if self.backend:
                self.backend._mask_hide_refs = 0
                self.backend._anim_optimize_active = False
                self.backend._anim_optimize_timer.stop()
            self._destroy_special_window()
            self.window.setMask(QRegion())
            self._mask_enabled = False
            # 统一应用图层策略（flags + SetWindowPos），避免手动 setFlag 残留
            if self.backend:
                self.backend._update_layer_state()
            self._apply_layer_flags()
            if self._cursor_hidden:
                self._active_window().setCursor(Qt.ArrowCursor)
                self._cursor_hidden = False
            self._cursor_timer.stop()
            # 恢复胶囊 mask：等 400ms 平移动画结束后（450ms）再恢复，避免动画中间帧错误裁切
            QTimer.singleShot(450, self._enable_mask_and_update)
            # 退出特殊模式后若主程序仍处于贴边隐藏，则保持插件主窗口隐藏
            self._edge_hidden = False
            self._sync_hide_visibility()
        else:
            # 特殊模式（进入或白板↔熄屏切换）：先清零 mask 引用计数
            if self.backend:
                self.backend._mask_hide_refs = 0
                self.backend._anim_optimize_active = False
                self.backend._anim_optimize_timer.stop()
            # 模式间切换（白板↔熄屏）：专用窗口已存在并显示，若再对主窗口 raise/置顶/设前台
            # 会盖住专用窗口（同为 topmost、主窗口后 raise 在上）导致工具栏"先消失再显示"。
            # 直接返回，样式由 QML modeChanged 驱动直接更新；仅首次进入特殊模式才做窗口操作。
            if self.special_window or self.special_engine:
                # 防御：确保专用窗口保持在 Z 序最上（只顶专用窗口，不碰主窗口），
                # 防止任何路径把主窗口 raise 到其上方遮挡工具栏。
                if self.special_window and sys.platform == 'win32':
                    try:
                        hwnd = int(self.special_window.winId())
                        HWND_TOPMOST = -1
                        SWP_NOMOVE = 0x0002
                        SWP_NOSIZE = 0x0001
                        SWP_NOACTIVATE = 0x0010
                        ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                                          SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                        self.special_window.raise_()
                    except Exception as e:
                        plugin_logger.debug(f"模式切换保持专用窗口置顶失败: {e}")
                return
            # 首次进入特殊模式：主窗口 QML 全屏过渡显示，同时准备专用全屏窗口保证完全置顶
            # 若主程序贴边隐藏导致窗口被隐藏，进入特殊模式时须重新显示
            if self.window and not self.window.isVisible():
                self.window.show()
            self.window.setMask(QRegion())
            self._mask_enabled = True
            self.window.setFlag(Qt.FramelessWindowHint, True)
            self.window.setFlag(Qt.WindowStaysOnTopHint, True)
            self._last_mouse_pos = QCursor.pos()
            self._idle_seconds = 0
            self._cursor_hidden = False
            self.window.setCursor(Qt.ArrowCursor)
            self._cursor_timer.start(500)
            if sys.platform == 'win32':
                try:
                    hwnd = int(self.window.winId())
                    HWND_TOPMOST = -1
                    SWP_NOMOVE = 0x0002
                    SWP_NOSIZE = 0x0001
                    ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                                      SWP_NOMOVE | SWP_NOSIZE)
                except Exception as e:
                    plugin_logger.debug(f"强制置顶失败: {e}")
            self.window.raise_()
            # QQuickWindow 无 activateWindow()，须用 QWindow 的 requestActivate()，否则抛 AttributeError
            self.window.requestActivate()
            # 关键：设为系统前台窗口，否则其它前台窗口会让任务栏浮在置顶窗口之上
            self._make_foreground_window(int(self.window.winId()))

            # 延迟再次强制置顶：等 QML 全屏过渡完成后重新置顶，确保覆盖任务栏
            QTimer.singleShot(400, self._force_topmost)
            QTimer.singleShot(1200, self._force_topmost)

            # 按钮按下即创建隐藏的专用全屏窗口（利用主窗口动画时间加载），动画完成后由信号驱动显示
            self._prepare_special_window()

    def on_unload(self):
        # 先打印卸载消息再释放日志句柄（否则写不进文件）
        plugin_logger.info("今日课程插件卸载")
        # 释放日志文件句柄（否则 Windows 下删除插件目录会失败）
        self._remove_logging()

        self._destroy_special_window()
        if self.window:
            try:
                self.window.removeEventFilter(self)
            except Exception:
                pass
        # 关闭笔迹 SQLite 存储（每笔已增量落盘，此处仅提交并释放句柄）
        if self._stroke_store:
            try:
                self._stroke_store.close()
            except Exception:
                pass
            self._stroke_store = None
        if self._cursor_timer:
            self._cursor_timer.stop()
            self._cursor_timer.deleteLater()
        if self._scroll_timer:
            self._scroll_timer.stop()
            self._scroll_timer.deleteLater()
        if self._width_timer:
            self._width_timer.stop()
            self._width_timer.deleteLater()
        if self._ui_fade_timeout_timer:
            try:
                self._ui_fade_timeout_timer.stop()
                self._ui_fade_timeout_timer.deleteLater()
            except Exception:
                pass
        if self.backend:
            try:
                self.backend._anim_optimize_timer.stop()
            except Exception:
                pass
        if self._configs:
            try:
                self._configs.configChanged.disconnect(self._on_config_changed)
            except:
                pass
        if self.backend:
            try:
                self.backend.layerChanged.disconnect(self._on_layer_changed)
            except:
                pass
        if self.settings_backend:
            try:
                self.settings_backend.settingsChanged.disconnect(self._on_plugin_settings_changed)
            except:
                pass
        if self._layer_timer:
            self._layer_timer.stop()
            self._layer_timer.deleteLater()
        if self._theme_timer:
            self._theme_timer.stop()
            self._theme_timer.deleteLater()
        if self._hide_window_timer:
            try:
                self._hide_window_timer.stop()
            except Exception:
                pass
        if self.ui_loader:
            try:
                self.ui_loader.xChanged.disconnect(self._update_mask)
                self.ui_loader.yChanged.disconnect(self._update_mask)
                self.ui_loader.widthChanged.disconnect(self._update_mask)
                self.ui_loader.heightChanged.disconnect(self._update_mask)
            except:
                pass
        # 断开主程序/后端信号，避免卸载后仍收到回调且信号强引用导致插件无法释放
        try:
            self.api.runtime.updated.disconnect(self.on_runtime_updated)
        except Exception:
            pass
        try:
            self.api.theme.changed.disconnect(self.on_theme_changed)
        except Exception:
            pass
        if _HAS_RIN_THEME:
            try:
                # 断开 RinUI 主题信号，避免卸载后仍收到回调/被信号强引用
                RinThemeManager().themeChanged.disconnect(self._on_rin_theme_changed)
            except Exception:
                pass
        if self.backend:
            try:
                self.backend.modeChanged.disconnect(self._on_mode_changed)
            except Exception:
                pass
            try:
                self.backend.positionChanged.disconnect(self._update_mask)
            except Exception:
                pass
            try:
                self.backend.widthChanged.disconnect(self._update_mask)
            except Exception:
                pass
        if self.window:
            self.window.close()
            self.window.deleteLater()
            self.window = None
        if self.engine:
            self.engine.deleteLater()
            self.engine = None
        # 释放后端 QObject（引擎已删除，QML context property 引用随之释放）
        if self.settings_backend:
            try:
                self.settings_backend.deleteLater()
            except Exception:
                pass
            self.settings_backend = None
        if self.backend:
            try:
                self.backend.deleteLater()
            except Exception:
                pass
            self.backend = None
        # 从 PluginBackendBridge 注册表移除本插件（主程序无注销接口，避免长期强引用）
        try:
            from src.core.plugin.bridge import PluginBackendBridge
            PluginBackendBridge._registry.pop(self.meta.get("id"), None)
        except Exception:
            pass
        # 对齐基类卸载契约
        try:
            super().on_unload()
        except Exception:
            pass

    def on_runtime_updated(self):
        if self.backend:
            self.backend.update_lessons()

    def on_theme_changed(self, theme_id):
        plugin_logger.debug(f"on_theme_changed 被调用，传入 theme_id: {theme_id}")
        # 主程序主题（包）切换时同步当前深浅色（Auto 模式跟随系统）
        if _HAS_RIN_THEME:
            try:
                is_dark = (RinThemeManager().get_theme() == "Dark")
                if is_dark != self.is_dark_theme:
                    self.is_dark_theme = is_dark
                    if self.backend:
                        self.backend.set_dark_theme(is_dark)
            except Exception:
                pass

    def _update_subjects_map(self):
        entries = self.api.runtime.current_day_entries
        if not entries:
            self._subjects_map = {}
            self._subjects_name_map = {}
            return

        subjects = []
        try:
            schedule = self.api._app.schedule_manager.schedule
            if schedule and hasattr(schedule, 'subjects'):
                subjects = schedule.subjects
        except Exception:
            pass

        if subjects:
            self._subjects_map = {}
            self._subjects_name_map = {}
            for subj in subjects:
                abbr = subj.simplifiedName or (subj.name[0] if subj.name else "?")
                self._subjects_map[subj.id] = abbr
                self._subjects_name_map[subj.id] = subj.name
        else:
            self._subjects_map = {}
            self._subjects_name_map = {}

    def _get_entry_abbr(self, entry):
        subject_id = entry.get("subjectId")
        if subject_id and subject_id in self._subjects_map:
            return self._subjects_map[subject_id]

        title = entry.get("title", "")
        if title:
            return title[0] if title else "?"

        entry_type = entry.get("type", "")
        if entry_type == "break":
            return "休"
        elif entry_type == "activity":
            return "活"
        elif entry_type == "preparation":
            return "预"
        else:
            return "?"