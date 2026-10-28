"""
Class Widgets 2.0 - 今日课程显示插件 (独立全屏窗口版)
显示当日所有课程缩写，并高亮当前课程，使用mask仅显示UI区域
"""

import os
import sys
import json
import time
import math
import array
import sqlite3
import ctypes
import darkdetect
from loguru import logger
from PySide6.QtCore import QObject, QUrl, Slot, Property, Signal, QTimer, QEvent, QPointF, QPoint, QSize, QMetaObject
from PySide6.QtGui import (QGuiApplication, QScreen, QRegion, QCursor,
                           QPainter, QPainterPath, QPainterPathStroker,
                           QPen, QColor, QImage, QPolygonF, QTransform)
from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlComponent
from PySide6.QtQuick import QQuickImageProvider, QQuickItem
from ClassWidgets.SDK import CW2Plugin
from PySide6.QtCore import Qt

# perfect-freehand 库（随插件打包在 libs/）：速度驱动的粗细变化笔触轮廓生成。
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs"))
    from perfect_freehand import get_stroke
    _HAS_PERFECT_FREEHAND = True
except Exception:
    get_stroke = None
    _HAS_PERFECT_FREEHAND = False

# 深浅色主题跟随主程序 RinUI ThemeManager（Light/Dark/Auto），无 RinUI 时回退 darkdetect。
try:
    from RinUI.core.theme import ThemeManager as RinThemeManager
    _HAS_RIN_THEME = True
except Exception:
    RinThemeManager = None
    _HAS_RIN_THEME = False

plugin_logger = logger.bind(plugin="lessons-displayer")

# 说明：悬停渐隐的“非按钮区点击”曾尝试 Windows WM_NCHITTEST 穿透（nativeEventFilter 不触发 →
# SetWindowLongPtrW 子类化）。子类化与 Qt Quick 输入链冲突（真机按钮 hover/点击失效），已弃用；
# 现为“显示层整窗透明输入 + 独立输入层承接按钮”方案（见 _HoverInputBackend 与 Plugin 悬停输入层方法）。

class _HoverInputBackend(QObject):
    """输入层 QML 的 hoverInputBackend：独立普通 QObject。

    悬停渐隐激活时输入层用独立 QQmlEngine 加载，QML 回调一个普通 QObject 的 @Slot 最可靠
    （把 Plugin 自身作为 context 对象时，其 Python @Slot 在新建引擎中可能不可调用——
    离屏已验证普通 QObject 可调、Plugin 不可调）。点击坐标交给 Plugin 解析并触发动作。
    """

    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin

    @Slot(int, int, int)
    def hoverInputClicked(self, x, y, button):
        try:
            p = self.plugin
            if p is not None:
                p._handle_hover_input_click(int(x), int(y), int(button))
        except Exception as e:
            plugin_logger.debug(f"悬停输入层点击处理失败: {e}")

DEFAULT_UI_WIDTH = 100
UI_HEIGHT = 54

# 插件设置默认值：配置文件有对应项则用之，否则回落默认；"恢复默认设置"= 删除配置文件。
DEFAULT_SETTINGS = {
    "animation_performance": True, # 动画性能优化（高级设置，默认启用）
    "widgets_layer": "follow",   # 小组件图层：跟随软件设置(follow)/始终置顶(top)/始终置底(bottom)
    "countdown_style": "default", # 倒计时样式：默认字号(default)/大字号(large)
    "auto_close_after_class": False, # 下课后自动关闭特殊模式（默认关闭，用户开启后跟随其设置）
    "auto_close_delay": 3,       # 下课后自动关闭的延迟时间数值
    "auto_close_unit": "min",    # 延迟时间单位：min(分)/sec(秒)
    "device_type": "interactive_panel", # 设备类型：交互智能平板(interactive_panel)/投影设备或其他(projector)
    "special_mode_action": "blackboard", # 手写板模式（平板设备点击顶部"手写板模式"胶囊按钮）进入的模式：blackboard(黑板)/whiteboard(白板)
    "hide_in_mini_mode": False,   # 小组件进入迷你模式时隐藏灵动条小组件（默认关闭；仅一般模式生效）
    "pen_speed_pressure": True,   # 笔触粗细跟随速度（无压感设备用速度模拟压力：慢→粗、快→细）
    "pen_speed_sensitivity": "standard", # 速度灵敏度：soft(柔和)/standard(标准)/sensitive(灵敏)
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


# ========== 笔迹几何核心：向心 Catmull-Rom → 三次贝塞尔 ==========
#
# 为什么不用"均匀" Catmull-Rom（张力 1/6，即 α=0）：它假设相邻采样点等距。快速书写
# 时同一笔内相邻段长度可能相差两个数量级（真机数据里既有 1.6px 的密集采样、也有
# 750px 的大跳），此时控制点臂长 (p2-p0)/6 会取到邻近"长段"的值再套到极短段上，
# 曲线冲出弦外很远。实测真机数据：弦长仅 4.7px 的短段，其曲线相对弦的最大偏离达
# 78px → 笔迹自己绕出一个圈（"打结"）。全笔 215 段里有 17 段过冲超过弦长 30%。
# 向心参数化（α=0.5）可证明不产生尖点与自交回环，从根本上消除打结。
_CR_ALPHA = 0.5
# 控制点臂长相对弦长的上限：兜底消除"大跳夹极小段"这类病态采样下的残留回环。
# 取 0.55 时曲线相对弦的偏离有严格上界 ≈0.41×弦长（不可能出现肉眼可见的圈）；
# 而正常曲率的稀疏采样（R=400 圆、弧长 260px）臂长/弦长仅 ≈0.26，完全不受影响。
_CR_ARM_LIMIT = 0.55
# 贝塞尔离散化容差（px）：自适应细分使"弦到曲线"的最大偏差不超过该值。
# 0.25px 远小于 1px 像素，肉眼绝无折线；同时它是细分的**收敛条件**，
# 直线段只需 1 步（原来固定 6 步，在 750px 的大跳段上等于 125px 一根折线 ——
# 这正是"快速书写笔迹有折线"的根因；而 1.6px 的短段又被白细分 6 倍纯属浪费）。
_CURVE_TOL = 0.25
# 单段细分步数上限（性能保护；曲率自适应后绝大多数段只需 1~4 步）。
_CURVE_MAX_STEPS = 32


def _dedupe_indexed(points, eps=0.02):
    """去掉连续重复点（零长度段），返回 (pts, idx)。

    向心参数化对零长度段敏感（节点间距为 0 会导致切向量发散）→ 统一先清理；
    idx[i] 为 pts[i] 在原点列中的索引（橡皮切分还原稀疏点需要该映射）。
    """
    pts = []
    idx = []
    for i, p in enumerate(points):
        if pts:
            q = pts[-1]
            if abs(p[0] - q[0]) <= eps and abs(p[1] - q[1]) <= eps:
                continue
        pts.append(p)
        idx.append(i)
    return pts, idx


def _cr_bezier(p0, p1, p2, p3, alpha=_CR_ALPHA):
    """向心 Catmull-Rom：由相邻四点求 p1→p2 段的三次贝塞尔控制点 (c1, c2)。

    节点间距取 |Δ|^alpha（alpha=0.5 即向心）；p1/p2 处的切向量按节点参数求导，
    再换算到本段参数域（乘 (t2-t1)/3）。端点用"相邻点自身"补点（节点差被钳到
    极小值），使首末段自然退化为沿弦 1/3 处的直线贝塞尔——端部无切线突变。

    最后把两侧控制点臂长钳制到 ≤ _CR_ARM_LIMIT × 弦长：这是**消除打结的关键**
    兜底。真机数据在快速书写时会出现"大跳（500~750px）夹极小段（4.7px）"的采样
    （多点触控/高采样率设备的成对上报），此时向心参数化仍会让 4.7px 的短段获得
    约 20px 的臂长、冲出 ~12px 的小圈。钳制后曲线相对弦的偏离有严格上界
    （≈0.75×0.55=0.41 倍弦长），肉眼不可能看到回环；而正常曲率的采样
    （圆 R=400 稀疏采样时臂长/弦长 ≈ 0.26）远未触及该上限，不受影响。
    """
    d0 = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) ** alpha or 1e-6
    d1 = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) ** alpha or 1e-6
    d2 = math.hypot(p3[0] - p2[0], p3[1] - p2[1]) ** alpha or 1e-6
    t0 = 0.0
    t1 = t0 + d0
    t2 = t1 + d1
    t3 = t2 + d2
    k = (t2 - t1) / 3.0
    m1x = (p2[0] - p0[0]) / (t2 - t0)
    m1y = (p2[1] - p0[1]) / (t2 - t0)
    m2x = (p3[0] - p1[0]) / (t3 - t1)
    m2y = (p3[1] - p1[1]) / (t3 - t1)
    a1x, a1y = m1x * k, m1y * k
    a2x, a2y = m2x * k, m2y * k
    # 臂长钳制（保持方向、只缩短）→ 曲线不会绕回自身
    chord = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    limit = _CR_ARM_LIMIT * chord
    if limit > 0.0:
        n1 = math.hypot(a1x, a1y)
        if n1 > limit:
            s = limit / n1
            a1x *= s
            a1y *= s
        n2 = math.hypot(a2x, a2y)
        if n2 > limit:
            s = limit / n2
            a2x *= s
            a2y *= s
    return ((p1[0] + a1x, p1[1] + a1y), (p2[0] - a2x, p2[1] - a2y))


class _CrSeg:
    """向心 CR 的一段（p1→p2 三次贝塞尔）+ 该段的自适应细分步数。

    字段用 __slots__ 紧凑存放；i 为该段起点在（去重后）点列中的索引，
    便于调用方顺带取到该点携带的压力值。
    """
    __slots__ = ("i", "x0", "y0", "c1x", "c1y", "c2x", "c2y", "x1", "y1", "steps")

    def __init__(self, i, p1, c1, c2, p2, steps):
        self.i = i
        self.x0, self.y0 = float(p1[0]), float(p1[1])
        self.c1x, self.c1y = c1
        self.c2x, self.c2y = c2
        self.x1, self.y1 = float(p2[0]), float(p2[1])
        self.steps = steps


def _cr_segments(pts, max_gap=None):
    """把（已去重的）点列切成向心 CR 段列表 [_CrSeg, ...]。

    每段的细分步数由"曲线相对弦的最大偏离"自适应决定：直线段 1 步、急弯段最多
    _CURVE_MAX_STEPS 步。既消除了固定步数在大跳段上的折线，也避免了在短段上
    无谓细分（真机 216 点笔迹：固定 6 步 → 1291 个密集点；自适应 → 1017 个）。

    max_gap 不为 None 时，额外强制"子段长度 ≤ max_gap"——用于**逐点几何判定**
    （橡皮用 contains() 逐点判断是否被擦）：只有曲率自适应时直线段只有两个端点，
    若中段被橡皮扫过而两端点都在橡皮外，就会漏擦。渲染/命中判定不需要该约束
    （渲染精度由 _CURVE_TOL 保证，命中判定用点到线段距离）。
    """
    n = len(pts)
    segs = []
    for i in range(n - 1):
        p0 = pts[max(0, i - 1)]
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[min(n - 1, i + 2)]
        c1, c2 = _cr_bezier(p0, p1, p2, p3)
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        chord = math.hypot(dx, dy)
        steps = 1
        if chord > 1e-6:
            # 曲线相对弦的偏离：D(t)=B(t)-弦(t) 的控制点为 0,a,b,0，
            # 取其在弦法向上的分量上界 ×3/4 即最大偏离（≈ 实际峰值）。
            ax = c1[0] - (p1[0] + dx / 3.0)
            ay = c1[1] - (p1[1] + dy / 3.0)
            bx = c2[0] - (p1[0] + dx * 2.0 / 3.0)
            by = c2[1] - (p1[1] + dy * 2.0 / 3.0)
            dev = 0.75 * max(abs(ax * dy - ay * dx),
                             abs(bx * dy - by * dx)) / chord
            if dev > _CURVE_TOL:
                # 等分 n 段后误差 ≈ dev/n² → n = sqrt(dev/tol)
                steps = int(math.ceil(math.sqrt(dev / _CURVE_TOL)))
                if steps > _CURVE_MAX_STEPS:
                    steps = _CURVE_MAX_STEPS
        if max_gap and chord > max_gap:
            need = int(math.ceil(chord / max_gap))
            if need > steps:
                steps = need
        segs.append(_CrSeg(i, p1, c1, c2, p2, steps))
    return segs


def _is_degenerate(pts):
    """单点或全部重合（零长度）：Qt 不渲染零长度线段的圆头，需按圆点专门处理。"""
    if len(pts) <= 1:
        return True
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return max(xs) - min(xs) < 0.01 and max(ys) - min(ys) < 0.01


def _stroke_path(points, width):
    """把笔划点列（逻辑坐标）平滑成向心 Catmull-Rom → 三次贝塞尔 QPainterPath。

    相邻两点之间一段三次贝塞尔，曲线精确穿过每个输入点；快速/稀疏采样也不会折线，
    更不会像均匀参数化那样过冲打结（见上方 _CR_ALPHA 注释）。
    单点或全部重合的退化路径回退为圆点（笔=圆点、橡皮=点擦圆），否则 Qt 不渲染
    零长度线段的 round cap，点擦/单击会失效。
    """
    path = QPainterPath()
    if not points:
        return path
    pts = _dedupe_indexed(points)[0]
    if _is_degenerate(pts):
        r = max(0.5, width / 2.0)
        path.addEllipse(QPointF(pts[0][0], pts[0][1]), r, r)
        return path
    path.moveTo(pts[0][0], pts[0][1])
    for s in _cr_segments(pts):
        path.cubicTo(s.c1x, s.c1y, s.c2x, s.c2y, s.x1, s.y1)
    return path


def _stroke_dense_points_p(points, steps=None):
    """把笔划点（[x,y] 或 [x,y,p]）向心 CR 密集化，返回 [x,y,p]（压力沿段线性插值）。

    与 _stroke_path 同一构造；喂给 perfect-freehand 之前先把稀疏/快速笔划平滑成曲线，
    否则快速绘制（采样点少）的笔迹轮廓会呈折线。steps 省略时按曲率自适应细分
    （推荐：平滑与点数兼顾）；点状/重合退化返回单点。
    """
    if not points:
        return []
    raw = [[float(p[0]), float(p[1]),
            float(p[2]) if len(p) > 2 else 0.5] for p in points]
    pts = _dedupe_indexed(raw)[0]
    if _is_degenerate(pts):
        return [list(pts[0])]
    out = [list(pts[0])]
    for s in _cr_segments(pts):
        pa = pts[s.i][2]
        pb = pts[s.i + 1][2]
        n_st = max(1, int(s.steps if steps is None else steps))
        for k in range(1, n_st + 1):
            t = k / n_st
            mt = 1.0 - t
            x = (mt ** 3 * s.x0 + 3 * mt * mt * t * s.c1x
                 + 3 * mt * t * t * s.c2x + t ** 3 * s.x1)
            y = (mt ** 3 * s.y0 + 3 * mt * mt * t * s.c1y
                 + 3 * mt * t * t * s.c2y + t ** 3 * s.y1)
            out.append([x, y, pa + (pb - pa) * t])
    return out


# 无压感设备的"速度→粗细（压力）"映射参数（单独为不支持压感的设备优化）。
# 书写速度越快压力越低（笔触越细）、越慢压力越高（笔触越粗）。
# 每档灵敏度：v_slow=低于此速度保持全粗、v_fast=高于此速度达到最细、curve=压力响应曲线指数
# （指数越小，慢速段保留越久、快速段才明显变细；指数越大，速度一快就迅速变细）。
_PEN_SPEED_MAP_CFG = {
    "soft":      {"v_slow": 40.0,  "v_fast": 2800.0, "curve": 0.55},
    "standard":  {"v_slow": 60.0,  "v_fast": 1800.0, "curve": 0.85},
    "sensitive": {"v_slow": 90.0,  "v_fast": 1100.0, "curve": 1.35},
}
_PEN_SPEED_MAP_MIN_P = 0.08   # 最快速度时的最细压力（粗细 ≈ width*(0.5 - thinning*(0.5-p))）
_PEN_SPEED_MAP_EMA = 0.5      # 瞬时速度 EMA 平滑系数（抗采样抖动；越大收敛越快、越小越平滑但略滞后）
_PEN_START_SAMPLES = 5        # 落笔起始采样帧数：用前 N 段平均速度定起始粗细
                              # ——起点粗细 = 落笔那一刻的真实速度（静止→粗、正常→适中、
                              # 高速→细）；测定后用平均速度初始化 EMA 进入正常平滑。



def _pressure_from_speed(speed, sensitivity="standard"):
    """速度 → 压力（粗细）映射：无压感设备的专用曲线。

    speed 为移动速度(px/s)；返回 [MIN_P, 1.0] 的压力值（越大越粗）。
    - soft:      慢速段保留更久，快速段才明显变细（适合抖动较大的鼠标/触摸）
    - standard:  线性渐变，常规书写感（默认）
    - sensitive: 速度一快就迅速变细，速度变化表现最夸张（适合稳定输入）
    """
    cfg = _PEN_SPEED_MAP_CFG.get(sensitivity, _PEN_SPEED_MAP_CFG["standard"])
    t = (speed - cfg["v_slow"]) / (cfg["v_fast"] - cfg["v_slow"])
    t = 0.0 if t <= 0.0 else (1.0 if t >= 1.0 else t)
    p = 1.0 - (t ** cfg["curve"])
    return _PEN_SPEED_MAP_MIN_P + (1.0 - _PEN_SPEED_MAP_MIN_P) * p


# ---------- 形状笔（线型）----------
# 形状笔画出的线在数据上仍是 op="pen" 的笔划（额外带 style 字段）——这样命中/圈选/
# 橡皮切分/预烘焙图层/撤销/多页/缩略图全部直接复用既有链路，只有"渲染"与"视觉
# 外扩范围"按线型分支。
# 与手写笔的区别：① 粗细均匀（不走 perfect-freehand 的速度→粗细）；② 几何只用
# 首末两点连成直线；③ 线型可含 dash 图案/正弦/平行双线/箭头/梳齿。
# 为保证"圈选/擦除与所见一致"，虚线/点线仍是**同一条笔划**（渲染上断续、几何上连续）：
# 圈选按整条中心线命中（只能选中一整条），橡皮按中心线拦腰切分（切成两笔）。
_LINE_SHAPES = ("line", "dash", "dashdot", "wave", "dot", "double",
                "arrow", "dblarrow", "ray", "hatch")
_LINE_SHAPE_NAMES = {"line": "直线", "dash": "虚线", "dashdot": "点虚线",
                     "wave": "波浪线", "dot": "点状虚线", "double": "双实线",
                     "arrow": "箭头", "dblarrow": "双向箭头",
                     "ray": "光线", "hatch": "剖面线"}

# ---------- 坐标系（形状菜单第 3 页"坐标系"，**每行两列**）----------
# 数据上：每根坐标轴 = 一笔 op="pen" 的**箭头线**（style = 直线菜单的 "arrow" → 箭头样式
# 与直线菜单完全一致，用户要求）；同一坐标系的所有轴带同一个 `grp`（圈选整块 / 被橡皮切开
# 后解除分组）、整块只压一条 add_many 撤销。
#   · planeaxes 平面直角坐标系：**一步到位**（按下 = 原点，拖拽的 |Δx| / |Δy| 决定横/纵轴
#     在这一侧的长度；原点同时是两条轴的中点 → 横轴朝右、纵轴朝上各一个箭头）；
#   · spaceaxes 空间直角坐标系：**两步**（① 与四棱柱底面同样的"对角线拖拽 → 底面平面矩形"
#     画 xy 平面（贴正方形时吸附 + 提示「x、y 轴等长」，两轴 = 从原点那一角沿相邻两边）；
#     ② 原点弹升维手柄，拖出竖直的 z 轴（贴"z = y 轴长"时吸附 + 提示「z、y 轴等长」））。
# 轴的方向/长度用 3D 里量（z 与 y 轴在两套测画法下轴向系数都是 1 → 纸面长度即轴长）。
_AXIS_MENU_KINDS = ("planeaxes", "spaceaxes")
_AXIS_KIND_NAMES = {"planeaxes": "平面直角坐标系",
                    "spaceaxes": "空间直角坐标系"}
_AXIS_ARROW_STYLE = "arrow"       # 轴的笔划样式（= 直线菜单的"箭头"）
_AXIS_MIN_LEN = 12.0              # 轴太短视为误触（px）

# ---------- 图形（形状工具的第二类：闭合多边形）----------
# 数据上同样是 op="pen" 的一笔（额外带 style="fig:<kind>"），points 就是**图形轮廓的
# 顶点序列（首尾同点，闭合）**。这样：
#   ① 圈选/命中/橡皮切分/撤销/多页/缩略图全部复用既有链路；
#   ② 橡皮拦腰擦断后，碎片是该点列的**子序列（开链）**，直接按折线画即为断开的弧，
#      无需特殊处理 → 天然满足"图形被切成多处断点后各算一笔"。
# 与"线型"的区别：图形的 points 是好几个顶点（线型只有首末两点），且**不支持线型
# 图案修改**（_line_style_of 对图形返回 ""，所以不出现端点手柄/线型菜单项）。
_SHAPE_KINDS = ("tri", "rtri", "rect", "pent", "hex", "oct", "star", "circle",
                "sector", "ellipse", "hyp", "para", "polfree")
_SHAPE_KIND_NAMES = {"tri": "等腰三角", "rtri": "直角三角", "rect": "矩形",
                     "pent": "五边形", "hex": "六边形", "oct": "八边形",
                     "star": "星形", "circle": "圆", "sector": "扇形",
                     "ellipse": "椭圆", "hyp": "双曲线", "para": "抛物线",
                     "polfree": "多边形随心画"}
# 立体图形 id（菜单名/形状引擎在 `_register_solid` 里登记，见文件上方"立体图形"一节）。
# **单独一列**：立体图形的绘制机制（两阶段 = 底面 + 升维、多笔 + 分组、成对漏）与平面图形
# 不同，菜单也是独立的"立体形状"页；但 beginLine/endLine 的入参仍走同一套（`style` = id）。
_SOLID_MENU_KINDS = ("triprism", "quadprism", "cylinder",
                     "tripyramid", "quadpyramid", "cone",
                     "trifrustum", "quadfrustum", "conefrustum", "sphere")
# 吸附提示用的名称（吸附时图形必为等边，所以叫法也不同）
# 椭圆/双曲线第一阶段拖拽时的提示文字是"焦点"；双曲线第二阶段的提示文字是"渐近线"
# （"hypas" 只是个"提示用"的伪 id，不出现在形状菜单里）；抛物线拖拽时的提示文字是
# "焦准距线段"（伪 id "para2"）。
_FIG_SNAP_NAMES = {"tri": "等边三角形", "rect": "正方形", "pent": "正五边形",
                   "hex": "正六边形", "oct": "正八边形", "star": "正星形",
                   "circle": "正圆", "ellipse": "焦点", "hyp": "焦点",
                   "hypas": "渐近线", "ellipse2": "双焦半径", "para2": "焦准距线段",
                   "sector": "扇半径",
                   "axiseq": "x、y 轴等长", "axiseqz": "z、y 轴等长",
                   # 立体图形升维：底面是正方形时高度吸到底面边长 → 正六面体（正方体）
                   "cube": "正六面体",
                   # 立体图形升维：底面是正三角形时高度吸到"正四面体"的高 → 正四面体
                   "tetra": "正四面体",
                   # 多边形随心画：鼠标靠近"另一端还没连线的端点"时吸上去闭合（带小图标）
                   "polfree": "闭合形状",
                   # 立体图形第一阶段（画底面）：主提示文字固定为"底面"（等边吸附的文字
                   # 走第二个提示，见 figureAlignName 里的 "fig" 分支）
                   "solidbase": "底面",
                   # 画圆 / 画球时：主提示文字固定为"半径"（鼠标起点 = 圆心/球心，连线 = 半径）
                   "radius": "半径",
                   # 多边形随心画的**等长/平行**吸附（小图标 = 等于号 / 平行标记）
                   "pfeq": "等长", "pfpara": "平行",
                   # "sector2"（第二阶段）的文字是动态的"圆心角 xx°"，见 figureSnapName
                   # 直角三角吸到 30°/45°/60° "三角形线"上的提示
                   "rtri45": "等腰直角三角形", "rtri30": "30° 直角三角形",
                   "rtri60": "60° 直角三角形"}
# 横平竖直吸附（椭圆/双曲线定焦点、抛物线定焦准距线段）后的第二个提示文字：
# "h" = 吸成水平排布（两焦点同 y / 焦准距线段水平）；"v" = 竖直排布
_FIG_ALIGN_NAMES = {"h": "水平排列", "v": "竖直排列", "eq": "等长"}
# **线型笔划**（直线/虚线/波浪线/箭头/…）横平竖直吸附的提示文字：没有"排列"可言，
# 直接叫"水平"/"竖直"（与图形用同一套 _fig_align 状态，只换措词）。
_LINE_ALIGN_NAMES = {"h": "水平", "v": "竖直", "eq": "等长"}
# 第二个提示左侧的小图标 id：**两个指向两侧的小箭头**（水平 = 左右、竖直 = 上下）
_FIG_ALIGN_ICONS = {"h": "alignh", "v": "alignv", "eq": "pfeq"}
# 只用于"提示文字/小图标"的伪 id（不在形状菜单里，也不参与等边吸附）：
#   hypas    = 双曲线第二阶段（渐近线）
#   ellipse2 = 椭圆第二阶段（双焦半径：探针到两焦点的两条连线）
#   para2    = 抛物线拖拽中（焦准距线段：准足 → 焦点，中点正是按下点）
#   pfeq/pfpara = 多边形随心画的等长/平行吸附（小图标 = 等于号 / 平行标记）
# （多边形随心画的**夹角文字**已改为独立属性 figureAngleText/figureAngleAnchor，不再走伪 id）
_FIG_HINT_KINDS = ("hypas", "ellipse2", "para2", "sector", "sector2",
                   "pfeq", "pfpara", "rtri30", "rtri45", "rtri60",
                   "solidbase", "radius", "cube", "tetra", "solidright",
                   "axiseq", "axiseqz")
# "直X柱 / 直X锥 / 直X台"提示：默认 = 当前立体图形本身；这里只登记特例
# （三棱台第二步升维出来的其实是个**三棱锥** → 提示「直三棱锥」+ 小图用三棱锥，
#  与文字一致（用户要求））
_FIG_SOLIDRIGHT_KINDS = {"trifrustum": "tripyramid",
                         "quadfrustum": "quadpyramid",
                         "conefrustum": "cone"}
# 直角三角（fig:rtri）的"特殊角射线"：与**水平横线**的夹角（度）→ 吸附提示用伪 id。
# 这几条射线就是用户说的"45°/30°/60° 三角形线"：吸中 45° 那条 ⇒ 等腰直角三角形。
_RTRI_RAYS = ((30.0, "rtri30"), (45.0, "rtri45"), (60.0, "rtri60"))
# 提示胶囊里小图标的长宽比（w/h）：30° → 横边/竖边 = 1/tan30°；60° → 1/tan60°；45° → 1
_FIG_RAY_ASPECTS = {"rtri30": 1.0 / math.tan(math.radians(30.0)),
                    "rtri45": 1.0,
                    "rtri60": 1.0 / math.tan(math.radians(60.0))}
_FIG_PREFIX = "fig:"
# 双曲线存盘时拆成 4 笔：两支线（实线，带两焦点头部点）+ 两条渐近线（虚线、无头部点）。
# 抛物线存盘时拆成 2 笔：曲线（实线，头部点 = 焦点）+ 准线（虚线线段、无头部点）。
# 它们不是菜单项，但 `_figure_of` 必须认（否则渲染/命中/圈选/图层都当成手写笔）：
_HYP_STYLE_BRANCH = "fig:hypb"
_HYP_STYLE_ASYM = "fig:hypa"
_PARA_STYLE_CURVE = "fig:para"
_PARA_STYLE_DIRECTRIX = "fig:parad"
_FIG_EXTRA_KINDS = ("hypb", "hypa", "parad")
# 圆：轮廓段数（128 段时最大圆（半径千像素级）的弦高误差 < 0.4px，肉眼看不出多边形）
_CIRCLE_SEGS = 128
# 椭圆：轮廓段数（同圆的理由）；_ELLIPSE_MIN_B = 第一阶段默认预览的半短轴下限（px）
_ELLIPSE_SEGS = 128
_ELLIPSE_MIN_B = 24.0
# 双曲线：单支单侧采样段数；渐近线与实轴夹角的容许范围（防退化）；支线绘制范围下限
_HYP_SEGS = 40
# 渐近线与实轴夹角的容许范围（防退化）。**取很小**：夹角只该在鼠标几乎贴着实轴/虚轴时兜底，
# 而渐近线端点要肉眼看着"止于鼠标"——夹角越大，端点偏离鼠标越明显（1.5° 时 ≈ 2.6% 长度）。
_HYP_ANGLE_MIN = math.radians(1.5)
_HYP_ANGLE_MAX = math.radians(88.5)
# 支线绘制范围 = 与渐近线端点**到几何重心等距**（同一个圆上）；只留一个极小下限避免 T=0 退化。
_HYP_EXT_MIN_A = 1.01
# 抛物线：曲线采样段数；绘制范围（沿对称轴、从顶点算起）系数 X = _PARA_EXT * p，
# 其中 p = 顶点→焦点。取 2 即"曲线沿轴画到焦准距处"（焦准距 = 2p）→ 曲线末端横向
# 位移 = 2*sqrt(p*X) = 2*sqrt(2)*p，得到一个不胖不瘦的"梳形"抛物线。
_PARA_SEGS = 80
_PARA_EXT = 2.0
# 图形的"头部点"：存盘时放在点列最前面、**不属于轮廓**的特征点
# （圆的圆心 / 椭圆、双曲线的两焦点 / 抛物线的焦点）
_FIG_HEAD_PTS = {"circle": 1, "sector": 1, "ellipse": 2, "hyp": 2, "hypb": 2, "para": 1}
# 头部点是"开链"的图形（双曲线的一支、抛物线曲线：首尾不同点，不能用首尾同点判定完整性）
# 及它们的点列长度——完整性靠点数精确匹对（碎片点数必然更少）
_FIG_OPEN_KINDS = ("hypb", "para")
_FIG_OPEN_BODY_PTS = {"hypb": 2 * _HYP_SEGS + 1, "para": _PARA_SEGS + 1}
# 需要虚线轮廓的图形笔划（双曲线的渐近线、抛物线的准线）
_FIG_DASHED = ("hypa", "parad")


def _fig_dashed(fig):
    """该图形笔划是否要画成虚线：渐近线/准线 + **立体图形的被遮挡棱**（`fig:<kind>h`）。"""
    return fig in _FIG_DASHED or bool(_solid_of(fig)[0]) and _solid_of(fig)[1]
# 图案**位置依赖**的笔划（周期性图案：虚线的划/缺口、点状虚线的点、光线箭头、
# 中面线梳齿、波浪相位，以及渐近线/准线的虚线）——橡皮切出的片段必须带上 `pat`
# （图案基准轴 = 擦除前原线的两端），否则图案会按片段自己的起点重新起算，
# 表现为"擦除后划/缺口/箭头整体平移"（用户报的问题）。
_PATTERN_STYLES = ("dash", "dashdot", "dot", "wave", "arrow", "dblarrow", "ray",
                   "hatch", _FIG_PREFIX + "hypa", _FIG_PREFIX + "parad")


def _is_pattern_style(style):
    """该 style 的笔划图案是否**位置依赖**（橡皮切碎片时要带上 `pat`；见 `_PATTERN_STYLES`）。

    立体图形的被遮挡棱（`fig:<kind>h`）也是虚线 → 必须算进去，否则切完碎片后
    虚线相位会从碎片自己的起点重新起算。
    """
    st = style or ""
    if st in _PATTERN_STYLES:
        return True
    return st.startswith(_FIG_PREFIX) and _solid_of(st[len(_FIG_PREFIX):])[1]
# 两阶段图形（先定两焦点、再拖探针定形）第一阶段至少要多长才算有效
_ELLIPSE_MIN_C = 6.0
# 两阶段图形的 id（`endLine` 松手后不提交、进入第二阶段）
_TWO_STAGE_FIGS = ("ellipse", "hyp")
# 需要"第二阶段拖探针/手柄"机制的图形：椭圆/双曲线（定两焦点 → 拖探针），
# 扇形（定圆心 + 第一条半径 → 拖探针/手柄定第二条半径）。
_STAGE_FIGS = ("ellipse", "hyp", "sector")
# 扇形：半径下限（px，太短视为误触）、默认圆心角（未完成第二阶段就切走时的兜底）
_SECTOR_MIN_R = 12.0
_SECTOR_DEFAULT_DEG = 90.0
# 扇形第二阶段圆心角的**下限**（用户要求：小于 1° 时取 1°，而不是回退 90°）
_SECTOR_MIN_DEG = 1.0
# 扇形第二阶段圆心角的吸附候选（用户要求：30°、45° 的倍数；带符号累加 → 可 > 180°）
_SECTOR_SNAP_DEGS = tuple(sorted({d for _k in (30, 45) for d in range(_k, 360, _k)}))

# 多边形随心画（fig:polfree）：用户逐条边画出来的自由多边形（多步绘制）。
# ① 第一条边：横平竖直吸附（提示「水平」/「竖直」）；
# ② 之后每一条边：以"上一条边的反向射线"与"新边"的**内角**做 30°/45° 倍数吸附，
#    提示文字是动态的「xx°」（**无小图标**）；鼠标靠近"另一端未连线的端点"时吸附过去
#    （提示「闭合形状」+ 小图标）；
# ③ 没闭合就接着给手柄画下一条边；切工具/改选形状时直接把缺口闭合后提交。
_PF_MIN_EDGE = 4.0       # 第一条边短于该长度视为误触（丢弃）
_PF_MIN_STEP = 3.0       # 后续边短于该长度视为误触（不新增顶点）
# 内角吸附候选：30°、45° 的倍数（内角 ≤ 180°）
_PF_ANGLE_DEGS = tuple(sorted({d for _k in (30, 45) for d in range(_k, 181, _k)}))
# 内角提示胶囊的锚点：夹角内角的**角平分线**上、距顶点**固定 28px**（胶囊几何中心就在那里）
_PF_HINT_R = 28.0
# 缺口连线吸附允许把终点挪多远（px）：超过就不吸附。
# 为什么需要：缺口连线的平行吸附解 = "正在画的边（射线）" ∩ "过 far 平行于参照边的直线"，
# 两条直线接近平行时交点在很远的地方（参数 t 可达上万）→ 终点会"跳到十万八千里"（用户报）；
# 而正在画的边 / 缺口连线的**等长**吸附位移天然 ≤ _FIG_SNAP_PX，不缺这个保护。
_PF_GAP_SNAP_MAX = 32.0


def _figure_of(stroke):
    """取"图形"笔划的图形 id（tri/rect/…/hyp；双曲线存盘时是 hypb/hypa；立体图形 triprismh…）。

    线条/手写笔返回 ""。立体图形（含"被遮挡棱"那部分 `fig:<kind>h`）由各自的形状引擎注册。
    """
    st = stroke.get("style") or ""
    if not st.startswith(_FIG_PREFIX):
        return ""
    k = st[len(_FIG_PREFIX):]
    if k in _SHAPE_KINDS or k in _FIG_EXTRA_KINDS or _solid_of(k)[0]:
        return k
    return ""


def _is_shape_stroke(stroke):
    """是否"矢量形状"（线型线 或 图形）：均匀粗细、不跟随速度变粗细、不走 CR 平滑。"""
    return bool(_line_style_of(stroke) or _figure_of(stroke))


def _pat_json(pat):
    """pat（图案基准轴 [x0,y0,x1,y1]）→ 存库用的 JSON 文本；空/非法 → ""。"""
    if not pat:
        return ""
    try:
        vals = [float(v) for v in pat]
    except Exception:
        return ""
    return json.dumps(vals[:4]) if len(vals) >= 4 else ""


def _snap_stroke(s):
    """整笔快照（撤销/擦除的 old 记录）：**必须带上 pat**（图案基准轴）。

    历史教训：整笔快照漏字段会让"撤销/移动"后静默丢失该字段（style 就丢过一次，
    导致虚线被降级成实线）——新增笔划字段时只需要改这里一处。
    """
    out = {"op": s.get("op", "pen"), "color": s.get("color", ""),
           "width": float(s.get("width", 4.0)), "style": s.get("style", ""),
           "points": [list(p) for p in (s.get("points") or [])]}
    if s.get("pat"):
        out["pat"] = [float(v) for v in s["pat"]]
    if s.get("grp"):
        out["grp"] = str(s["grp"])
    return out


def _set_grp(stroke, grp):
    """写入/清除笔划的"同一立体图形"分组 id（为空则删键，避免污染快照比较）。"""
    if grp:
        stroke["grp"] = str(grp)
    else:
        stroke.pop("grp", None)


_GRP_SEQ = 0


def _new_grp():
    """生成一个新的"同一立体图形"分组 id（时间戳 + 自增序号 → 进程内唯一、跨重启不复用）。"""
    global _GRP_SEQ
    _GRP_SEQ += 1
    return "%x-%x" % (time.time_ns() & 0xFFFFFFFFFFFF, _GRP_SEQ)


def _set_pat(stroke, pat):
    """写入/清除笔划的图案基准轴（pat 为空则删键，避免污染快照比较与 JSON）。"""
    if pat and len(pat) >= 4:
        stroke["pat"] = [float(v) for v in pat]
    else:
        stroke.pop("pat", None)


def _map_pat(stroke, fn):
    """把图案基准轴按同一映射变换（移动/缩放/旋转后图案跟着走）→ 新 pat 或 None。"""
    p = stroke.get("pat")
    if not p or len(p) < 4:
        return None
    a = fn(float(p[0]), float(p[1]))
    b = fn(float(p[2]), float(p[3]))
    return [float(a[0]), float(a[1]), float(b[0]), float(b[1])]


# 正多边形的"顶点数 / 起始角(度)"——起始角决定朝向（QML 侧 ShapeIconPreview.qml 同值）
_FIG_POLY_N_START = {
    "pent": (5, -90.0),     # 尖顶：一个顶点朝上
    "hex": (6, 0.0),        # 平顶：上、下两条对边**横着**
    "oct": (8, 22.5),       # 平顶平边：上/下是水平边、左/右是竖直边（与六边形同风格）
}
# 五角星内圈/外圈半径比 = cos72°/cos36° = 1/φ² ≈ 0.38197（正五角星的星形轮廓）
_STAR_INNER_RATIO = math.cos(math.radians(72.0)) / math.cos(math.radians(36.0))


def _figure_unit_polygon(kind):
    """图形的**单位轮廓**顶点（外接圆半径 1；星形为 10 个顶点）。

    `_figure_points` 与 `_figure_aspect` 共用，避免两处角度公式漂移；
    QML 侧 `ShapeIconPreview.qml` 是这份公式的镜像副本，两处必须同步。
    - 五边形：第一个顶点朝上（-90°）；
    - 六边形：第一个顶点**朝右**（0°）→ 上、下两条对边是**横着**的（平顶朝法）；
    - 八边形：起始 22.5° → 上/下是水平边、左/右是竖直边；
    - 星形（五角星）：一角朝上，外圈 5 个尖角 + 内圈 5 个凹角交替（10 个顶点）。
    """
    if kind == "star":
        out = []
        for i in range(5):
            a = math.radians(-90.0 + 72.0 * i)
            out.append((math.cos(a), math.sin(a)))
            b = math.radians(-90.0 + 72.0 * i + 36.0)
            out.append((math.cos(b) * _STAR_INNER_RATIO,
                        math.sin(b) * _STAR_INNER_RATIO))
        return out
    if kind == "circle":
        return [(math.cos(2.0 * math.pi * i / _CIRCLE_SEGS),
                 math.sin(2.0 * math.pi * i / _CIRCLE_SEGS))
                for i in range(_CIRCLE_SEGS)]
    if kind == "ellipse":
        # 椭圆不参与"等边吸附"（有自己的焦点轴线吸附）→ 这里给单位圆保证通用工具可用
        return [(math.cos(2.0 * math.pi * i / _CIRCLE_SEGS),
                 math.sin(2.0 * math.pi * i / _CIRCLE_SEGS))
                for i in range(_CIRCLE_SEGS)]
    if kind == "rtri":
        # 直角三角（菜单/提示小图标用）：**直角顶点在左下角**，两条直角边 = 方框底边（横）
        # 与左边（竖），斜边自右下向左上。长宽比 1:1 → 小图是等腰直角三角形；
        # 提示胶囊按 _FIG_RAY_ASPECTS 给框，框长宽比不同时就是 30°/60° 直角三角形。
        return [(0.0, 1.0), (1.0, 1.0), (0.0, 0.0)]
    if kind == "sector":
        # 扇形不用辅助矩形（圆心 + 半径 + 圆心角）→ 给一个 90° 单位扇形供通用工具使用
        return [(math.cos(math.radians(-90.0 * i / 8.0)),
                 math.sin(math.radians(-90.0 * i / 8.0))) for i in range(9)]
    if kind == "polfree":
        # 多边形随心画（菜单/提示里的小图标）：**用户手画的那一个**（5 顶点：底边 → 右侧 →
        # 左上尖角 → 左侧内凹角），顶点取自用户在主程序插件目录里画出的 `fig:polfree`
        # 笔迹（已归一化到单位包围盒 0..1 × 0..1）；真实绘制由用户逐条边决定，不用这套顶点。
        return [(0.2042, 1.0), (0.7538, 1.0), (1.0, 0.5303), (0.0, 0.0), (0.3016, 0.4867)]
    if kind in ("hyp", "para") + _FIG_EXTRA_KINDS:
        # 双曲线/抛物线同样不靠辅助矩形（由焦点 + 探针定形）→ 单位圆供通用工具使用
        return [(math.cos(2.0 * math.pi * i / _CIRCLE_SEGS),
                 math.sin(2.0 * math.pi * i / _CIRCLE_SEGS))
                for i in range(_CIRCLE_SEGS)]
    n, start = _FIG_POLY_N_START.get(kind, (6, 0.0))
    return [(math.cos(math.radians(start + 360.0 * i / n)),
             math.sin(math.radians(start + 360.0 * i / n))) for i in range(n)]


def _figure_aspect(kind):
    """图形"等边（正多边形）"所需的辅助矩形长宽比 w/h。

    - 矩形： 1:1；
    - 三角形：底=w、高=h 且两腰相等 ⇒ w = √((w/2)²+h²) ⇒ w/h = 2/√3；
    - 五/六/八边形与星形：单位轮廓包围盒的长宽比（与 `_figure_points` 的仿射映射
      同一套，长宽比相等时映射就是等比缩放 → 正多边形/正星形）。
      八边形 ≈ 1:1（平顶平边）、星形 = 五边形 1.0515（尖角是外圈决定的包围盒）。
    """
    if kind == "rect":
        return 1.0
    if kind == "tri":
        return 2.0 / math.sqrt(3.0)
    if kind == "circle":
        return 1.0                    # 圆不受辅助矩形长宽比限制（永远是正圆）
    if kind == "ellipse":
        return 1.0                    # 椭圆也不靠辅助矩形（由两焦点 + 探针定形）
    if kind in ("hyp", "para") + _FIG_EXTRA_KINDS:
        return 1.0                    # 双曲线/抛物线同理（焦点 + 探针 / 顶点 + 焦点）
    raw = _figure_unit_polygon(kind)
    xs = [p[0] for p in raw]
    ys = [p[1] for p in raw]
    spanx = max(xs) - min(xs)
    spany = max(ys) - min(ys)
    return spanx / spany if spany > 1e-9 else 1.0


def _figure_points(kind, x0, y0, x1, y1):
    """由"按下起点 → 当前终点"确定的横平竖直辅助矩形（不显示），把图形内接其中。

    返回**闭合轮廓点列**（首尾同点）。五/六/八边形/星形取单位轮廓后把其包围盒仿射
    映射到辅助矩形 → 辅助矩形比例等于 `_figure_aspect` 时就是正多边形/正星形，
    且四边都与辅助矩形相切（内接得"满"）。
    圆的模型与其他图形**不同**：起点就是圆心、半径 = 起终点距离（与辅助矩形无关）→
    拖动方向任意都得到正圆；返回点列的首点是圆心（"图形包含圆心"），其后是闭合轮廓。
    """
    l, r = min(x0, x1), max(x0, x1)
    t, b = min(y0, y1), max(y0, y1)
    cx, cy = (l + r) / 2.0, (t + b) / 2.0
    if kind == "circle":
        ox, oy = float(x0), float(y0)
        rr = math.hypot(float(x1) - ox, float(y1) - oy)
        loop = [[ox + rr * math.cos(2.0 * math.pi * i / _CIRCLE_SEGS),
                 oy + rr * math.sin(2.0 * math.pi * i / _CIRCLE_SEGS)]
                for i in range(_CIRCLE_SEGS)]
        loop.append(list(loop[0]))                     # 显式闭合（浮点安全）
        return [[ox, oy]] + loop                       # 首点 = 圆心
    if kind in _TWO_STAGE_FIGS:
        # 两阶段图形（椭圆 / 双曲线）：起点 = 几何重心，终点 = 一个焦点；另一焦点关于中心对称。
        # **第一阶段（定焦点）不画轮廓**（用户要求）：点列只有两个焦点，轮廓在第二阶段
        # （拖拽定形）才生成 —— 椭圆见 _refresh_focus_stage / 双曲线见 _hyperbola_figure_strokes。
        ox, oy = float(x0), float(y0)
        f1 = (float(x1), float(y1))
        f2 = (2.0 * ox - f1[0], 2.0 * oy - f1[1])
        return [[f1[0], f1[1]], [f2[0], f2[1]]]
    if kind == "para":
        # 抛物线（**一步成形**）：起点 = 顶点（焦准距线段的中点）、终点 = 焦点。
        # 点列 = [焦点]（头部点，不进轮廓）+ 曲线开链（与双曲线的一支同理）。
        return _parabola_figure_strokes(x0, y0, x1, y1)[0]["points"]
    if kind == "sector":
        # 扇形（**两阶段**）：第一阶段 起点 = 圆心、终点 = 第一条半径端点（点列就是这 2 点）；
        # 松手后进入第二阶段（不提交），轮廓由 _refresh_focus_stage 用"圆心 + 两条半径"生成。
        return [[float(x0), float(y0)], [float(x1), float(y1)]]
    if kind == "rect":
        loop = [[l, t], [r, t], [r, b], [l, b]]
    elif kind == "tri":
        loop = [[cx, t], [r, b], [l, b]]
    elif kind == "rtri":
        # 直角三角（**一步成形**）：起点 = 直角顶点；两条直角边一横一竖，
        # 都朝终点所在象限 → 横边边长 = |x1-x0|、竖边边长 = |y1-y0|。
        # 直角就在起点上（不是辅助矩形的一角，与等腰三角/矩形不同）。
        dx_, dy_ = float(x1) - float(x0), float(y1) - float(y0)
        loop = [[float(x0), float(y0)], [float(x0) + dx_, float(y0)],
                [float(x0), float(y0) + dy_]]
    else:
        raw = _figure_unit_polygon(kind)
        n = len(raw)
        xs = [p[0] for p in raw]
        ys = [p[1] for p in raw]
        spanx = max(xs) - min(xs)
        spany = max(ys) - min(ys)
        scx = (r - l) / spanx if spanx > 1e-9 else 1.0
        scy = (b - t) / spany if spany > 1e-9 else 1.0
        loop = [[l + (px - min(xs)) * scx, t + (py - min(ys)) * scy] for px, py in raw]
    loop = [[float(px), float(py)] for px, py in loop]
    loop.append(list(loop[0]))          # 闭合（首尾同点）
    return loop


_FIG_SNAP_PX = 12.0     # 图形绘制的"等边吸附"阈值（px）：鼠标离可等边直线多近就吸附
_ASPECT_SNAP_PX = 12.0  # 四角缩放的"等比例缩放直线"吸附阈值（px）
_ASPECT_GUIDE_EXT = 56.0   # 等比例缩放直线在吸附点之后再延伸的长度（与图形吸附一致）


def _same_pt(a, b, eps=1e-6):
    """两点坐标是否重合（只比 x/y，忽略压力分量）——闭合轮廓/圆心判定用。"""
    if not a or not b:
        return False
    return abs(float(a[0]) - float(b[0])) <= eps and abs(float(a[1]) - float(b[1])) <= eps


def _ellipse_outline(cx, cy, a, b, ux=1.0, uy=0.0):
    """椭圆闭合轮廓点列（首尾同点）：中心 (cx,cy)、半长轴 a、半短轴 b，长轴单位方向 (ux,uy)。

    末尾**显式**追加首点副本（不依赖 cos(2π) 与 cos(0) 的浮点相等）→ 闭合判定用 == 也成立。
    """
    px, py = -uy, ux                    # 长轴的法向 = 短轴方向
    pts = []
    for i in range(_ELLIPSE_SEGS):
        t = 2.0 * math.pi * i / _ELLIPSE_SEGS
        ca, sa = math.cos(t), math.sin(t)
        pts.append([cx + a * ca * ux + b * sa * px,
                    cy + a * ca * uy + b * sa * py])
    pts.append(list(pts[0]))            # 闭合（首尾同点）
    return pts


def _ellipse_axes(f1, f2, probe):
    """由两焦点 + 椭圆上一点（探针）解椭圆参数 → (cx, cy, a, b, ux, uy)。

    2a = |P−F1| + |P−F2|（椭圆定义，也就是"绳长"）；c = |F1F2|/2；b = √(a²−c²)。
    长轴方向 = 两焦点连线方向（两焦点重合时取水平，退化为圆）。
    探针离两焦点距离之和 ≤ 两焦点间距时（a ≤ c，构不成椭圆）把 a 夹到 c →
    椭圆退化成线段，但**不会出现负的 b / 虚数**。
    """
    cx, cy = (f1[0] + f2[0]) / 2.0, (f1[1] + f2[1]) / 2.0
    vx, vy = f2[0] - f1[0], f2[1] - f1[1]
    c = math.hypot(vx, vy) / 2.0
    if c > 1e-6:
        ux, uy = vx / (2.0 * c), vy / (2.0 * c)
    else:
        ux, uy = 1.0, 0.0
    s = (math.hypot(probe[0] - f1[0], probe[1] - f1[1])
         + math.hypot(probe[0] - f2[0], probe[1] - f2[1]))
    a = max(s / 2.0, c)
    b = math.sqrt(max(0.0, a * a - c * c))
    return cx, cy, a, b, ux, uy


def _ellipse_figure_points(f1, f2, probe):
    """椭圆存盘点列 = **[F1, F2] + 闭合轮廓**（前两点是两焦点，不进轮廓，见 `_fig_ink_pts`）。"""
    cx, cy, a, b, ux, uy = _ellipse_axes(f1, f2, probe)
    return [[float(f1[0]), float(f1[1])], [float(f2[0]), float(f2[1])]] \
        + _ellipse_outline(cx, cy, a, b, ux, uy)


def _ellipse_default_probe(cx, cy, f1):
    """椭圆第一阶段的默认探针位置：短轴方向、半短轴 = max(c, `_ELLIPSE_MIN_B`)。

    第一阶段只知道中心与一个焦点（2a 还没定）→ 用这个默认探针给出一个不退化、不夸张的
    椭圆预览；第二阶段拖手柄时探针改为鼠标位置。
    """
    c = math.hypot(f1[0] - cx, f1[1] - cy)
    if c > 1e-6:
        ux, uy = (f1[0] - cx) / c, (f1[1] - cy) / c
    else:
        ux, uy = 1.0, 0.0
    b0 = max(c, _ELLIPSE_MIN_B)
    return (cx - uy * b0, cy + ux * b0)


def _hyp_axis(f1, f2):
    """两焦点 → (cx, cy, c, ux, uy)：几何重心、半焦距、实轴单位向量（F1 → F2 方向）。

    两焦点重合时实轴取水平（用 `_ELLIPSE_MIN_C` 兜底半焦距）。
    """
    cx, cy = (f1[0] + f2[0]) / 2.0, (f1[1] + f2[1]) / 2.0
    vx, vy = f2[0] - f1[0], f2[1] - f1[1]
    dv = math.hypot(vx, vy)
    c = max(dv / 2.0, _ELLIPSE_MIN_C)
    ux, uy = (vx / (2.0 * c), vy / (2.0 * c)) if dv > 1e-6 else (1.0, 0.0)
    return cx, cy, c, ux, uy


def _hyp_clamped_probe(f1, f2, probe):
    """把探针方向夹到 `_HYP_ANGLE_MIN..MAX`（鼠标几乎贴着实轴/虚轴时防退化）。

    **只转方向、保留长度**（|probe_c − 重心| = |鼠标 − 重心|，仍在同一圆上）。
    ⚠️ 渐近线方向、a/b、绘制范围 X、蓝色引导线**必须全部用这个夹好的探针**：
    以前只有 a/b 用了夹角、而渐近线却按鼠标原始方向画 —— 鼠标几乎贴着实轴拖时，
    支线的渐近斜率 tan6°=0.105 远大于画出的渐近线斜率 tan1.6°=0.028，
    **支线跑到渐近线外面**（用户报"怎么在渐近线外面"，实测超出 16.7px）。
    """
    cx, cy, _c, ux, uy = _hyp_axis(f1, f2)
    nx, ny = -uy, ux
    dx, dy = float(probe[0]) - cx, float(probe[1]) - cy
    px = dx * ux + dy * uy
    py = dx * nx + dy * ny
    r = math.hypot(px, py)
    if r <= 1e-9:
        return cx + ux, cy + uy               # 退化：给一个沿实轴的单位探针
    ang = math.atan2(abs(py), abs(px))
    ang_c = min(max(ang, _HYP_ANGLE_MIN), _HYP_ANGLE_MAX)
    if abs(ang_c - ang) <= 1e-12:
        return float(probe[0]), float(probe[1])
    lx = r * math.cos(ang_c)
    ly = r * math.sin(ang_c)
    if px < 0.0:
        lx = -lx
    if py < 0.0:
        ly = -ly
    return cx + lx * ux + ly * nx, cy + lx * uy + ly * ny


def _hyperbola_params(f1, f2, probe):
    """由两焦点 + 探针（鼠标）解双曲线 → (cx, cy, a, b, ux, uy, X)。

    模型（用户描述）：几何重心 = 两焦点中点；**"几何重心 → 鼠标"的连线就是一条渐近线的一半**
    （这一半止于鼠标，另一半关于重心对称；另一条渐近线关于实轴镜像）。
    参数：探针方向与实轴的夹角 θ 决定 a/b —— a = c·cosθ、b = c·sinθ（c² = a² + b²）；
    θ 夹到 `_HYP_ANGLE_MIN..MAX`（防退化），**夹好的探针由 `_hyp_clamped_probe` 统一给出**，
    渐近线/引导线也用它（否则支线可能跑到渐近线外面，详见该函数注释）。
    X = 支线的绘制范围（局部实轴坐标）**由渐近线的显示范围决定**：取支线末端到几何重心的
    距离 = 鼠标（= 渐近线端点）到重心的距离 —— 即 X² = (half·cosθ)² + (a·sinθ)²。
    这样两处的截断点**落在同一个圆上**（角度不同，因此间距接近理论最小）；若改用
    “实轴分量相同”（X = half·cosθ）则鼠标靠近重心时 X 会退回 a、支线退化成顶点一个点。
    （只为防退化补一个 X >= 1.01a 的下限。）
    实轴方向 = 两焦点连线方向（两焦点重合时取水平）。
    """
    cx, cy, c, ux, uy = _hyp_axis(f1, f2)
    nx, ny = -uy, ux                       # 虚轴方向
    cp = _hyp_clamped_probe(f1, f2, probe)  # 已夹好的探针（渐近线/引导线同用）
    dx, dy = cp[0] - cx, cp[1] - cy
    px = dx * ux + dy * uy                 # 探针在实轴上的分量
    py = dx * nx + dy * ny                 # 探针在虚轴上的分量
    ang_c = math.atan2(abs(py), abs(px))   # 已夹到 [_HYP_ANGLE_MIN, _HYP_ANGLE_MAX]
    a = c * math.cos(ang_c)
    b = c * math.sin(ang_c)
    half = math.hypot(dx, dy)              # 渐近线半段长 = 探针到重心的距离
    X = math.hypot(half * math.cos(ang_c), a * math.sin(ang_c))
    X = max(a * _HYP_EXT_MIN_A, X)
    return cx, cy, a, b, ux, uy, X


def _hyp_branch_points(cx, cy, a, b, ux, uy, X, side):
    """双曲线一支的开链点列（side=+1 沿 +u 开口，-1 沿 -u）。

    用双曲参数化 x = a·cosh t、y = b·sinh t（t: T→0→T）→ 采样均匀、顶点处不会扎堆；
    终点在 x = X 的两侧（X = 绘制范围），**过顶点连成一条**（就是真实的一支形状）。
    """
    nx, ny = -uy, ux
    T = math.acosh(max(1.0, X / max(a, 1e-9)))
    n = _HYP_SEGS
    out = []
    for i in range(n + 1):                 # 上半支：t 从 T 减到 0（终点为顶点）
        t = T * (1.0 - i / float(n))
        x, y = a * math.cosh(t), b * math.sinh(t)
        out.append([cx + side * x * ux + y * nx, cy + side * x * uy + y * ny])
    for i in range(1, n + 1):              # 下半支：t 从 0 增到 T（跳过已画的顶点）
        t = T * i / float(n)
        x, y = a * math.cosh(t), -b * math.sinh(t)
        out.append([cx + side * x * ux + y * nx, cy + side * x * uy + y * ny])
    return out


def _hyp_asymptote_points(cx, cy, ux, uy, probe, side):
    """一条渐近线的两个端点（整条过几何重心的线段）。

    side = +1：经过鼠标的那条 —— 鼠标侧的一半**严格是 [几何重心, 鼠标]**，
               另一端点在重心的另一侧、与鼠标关于重心对称（用户要求）；
    side = -1：另一条 —— 把"重心→鼠标"关于实轴镜像后同样取对称两端点。
    """
    dx, dy = probe[0] - cx, probe[1] - cy
    if side < 0:
        nx, ny = -uy, ux
        along = dx * ux + dy * uy
        perp = dx * nx + dy * ny
        dx, dy = along * ux - perp * nx, along * uy - perp * ny
    return [[cx + dx, cy + dy], [cx - dx, cy - dy]]


def _hyperbola_figure_strokes(f1, f2, probe):
    """双曲线 = **4 笔**：[右支, 左支, 渐近线1, 渐近线2]。

    支线的点列 = [F1, F2]（头部点，不进轮廓）+ 支线开链 → 两支都会把两焦点画成小圆点；
    渐近线就是两点线段（`_draw_shape_line` 用虚线画）。四笔各自是一笔，圈选/橡皮/撤销
    自然地按笔处理（用户要求"视为四笔"）。
    **渐近线必须用 `_hyp_clamped_probe` 夹好的探针**（与 a/b 同一角度）→ 支线永远在
    两条渐近线之内（否则鼠标贴着实轴拖时支线会跑到渐近线外面）。
    """
    cx, cy, a, b, ux, uy, X = _hyperbola_params(f1, f2, probe)
    cp = _hyp_clamped_probe(f1, f2, probe)
    head = [[float(f1[0]), float(f1[1])], [float(f2[0]), float(f2[1])]]
    out = []
    for side in (1.0, -1.0):
        out.append({"op": "pen", "style": _HYP_STYLE_BRANCH,
                    "points": [list(p) for p in head]
                    + _hyp_branch_points(cx, cy, a, b, ux, uy, X, side)})
    for side in (1.0, -1.0):
        out.append({"op": "pen", "style": _HYP_STYLE_ASYM,
                    "points": _hyp_asymptote_points(cx, cy, ux, uy, cp, side)})
    return out


def _parabola_params(vx, vy, fx, fy):
    """由"顶点 V（按下点 = 焦准距线段的中点）→ 焦点 F（松开点）"解抛物线。

    返回 (vx, vy, ux, uy, p, X)：
    · u = 对称轴单位向量（V → F）；p = |F − V|（顶点到焦点 = 半焦准距）；
    · **准线** = 过 V − p·u 且垂直于 u 的直线（焦准距 = 2p，其**中点正是顶点 V**）；
    · X = 曲线沿对称轴的绘制范围（局部 x，从顶点算起）= `_PARA_EXT * p`。
    用户要求：起点是焦准距线段的中点（= 顶点）、终点是焦点 → 准线与曲线唯一确定。
    """
    dx, dy = float(fx) - float(vx), float(fy) - float(vy)
    p = math.hypot(dx, dy)
    ux, uy = (dx / p, dy / p) if p > 1e-9 else (1.0, 0.0)
    return float(vx), float(vy), ux, uy, p, _PARA_EXT * p


def _parabola_curve_points(vx, vy, ux, uy, p, X):
    """抛物线曲线（**开链**点列，从一侧末端经顶点到另一侧末端）。

    局部坐标（原点 = 顶点、x 沿对称轴、y 沿法向）：y^2 = 4px；
    用参数 m（= y / (2p)）均匀采样：x = p·m^2、y = 2p·m，m ∈ [−M, M]、M = √(X/p)
    → 点距沿曲线基本均匀（顶点处不扎堆、末端也不稀疏）。
    """
    if p <= 1e-9:
        return [[float(vx), float(vy)]]
    nx, ny = -uy, ux
    m_max = math.sqrt(max(0.0, X / p))
    n = _PARA_SEGS
    out = []
    for i in range(n + 1):
        m = -m_max + 2.0 * m_max * i / float(n)
        x, y = p * m * m, 2.0 * p * m
        out.append([vx + x * ux + y * nx, vy + x * uy + y * ny])
    return out


def _parabola_figure_strokes(vx, vy, fx, fy):
    """抛物线 = **2 笔**：[曲线（实线，头部点 = 焦点）, 准线（虚线线段）]。

    曲线点列 = [焦点]（头部点，不进轮廓）+ 曲线开链 → 曲线这笔会把焦点画成小圆点
    （用户要求"图形包含焦点"）；准线是两点线段，`_draw_shape_line` 按 `_FIG_DASHED`
    用虚线画（与双曲线的渐近线、菜单"虚线"同一套图案）。
    准线长度与曲线两末端齐平（半长 = 曲线末端 |y| = 2√(pX)），像教科书里的标准图。
    """
    vx, vy, ux, uy, p, X = _parabola_params(vx, vy, fx, fy)
    nx, ny = -uy, ux
    half = 2.0 * math.sqrt(max(0.0, p * X))
    foot_x, foot_y = vx - p * ux, vy - p * uy           # 准足（准线与对称轴的交点）
    return [
        {"op": "pen", "style": _PARA_STYLE_CURVE,
         "points": [[float(fx), float(fy)]]
         + _parabola_curve_points(vx, vy, ux, uy, p, X)},
        {"op": "pen", "style": _PARA_STYLE_DIRECTRIX,
         "points": [[foot_x + half * nx, foot_y + half * ny],
                    [foot_x - half * nx, foot_y - half * ny]]},
    ]


def _hyp_default_probe(cx, cy, f1):
    """双曲线第二阶段的默认探针：渐近线取 45°（b/a = 1，最"标准"的双曲线形状）。"""
    c = math.hypot(f1[0] - cx, f1[1] - cy)
    if c > 1e-6:
        ux, uy = (f1[0] - cx) / c, (f1[1] - cy) / c
    else:
        ux, uy = 1.0, 0.0
    nx, ny = -uy, ux
    a = max(c, 1e-6) / math.sqrt(2.0)
    return (cx + a * ux + a * nx, cy + a * uy + a * ny)


def _fig_stage1(kind, pts):
    """是否处于"两阶段图形的第一阶段"（只有两焦点、轮廓尚未生成）。

    ⚠️ 只有 ellipse/hyp 这两种两阶段图形才有该状态；`circle`/`hypb`/`para` 的
    "点数 ≤ 头部点数"只可能是橡皮切出的**极小残段**（甚至只剩 1 个点）——
    不能当成"两焦点预览"（否则残段会被当成空轮廓而静默不画，用户看到"被烘没了"）。
    """
    n = _FIG_HEAD_PTS.get(kind, 0)
    return bool(n) and kind in _TWO_STAGE_FIGS and len(pts) <= n


def _fig_head_valid(kind, pts):
    """该笔划的"头部点"是否有效（= **完整图形**，不是橡皮切出的碎片）。

    - 闭合图形（圆 / 椭圆 / 多边形）：轮廓**首尾同点**且至少 3 个点；
    - 开链图形（双曲线的一支 / 抛物线曲线）：点数恰好 = 头部点 + 主体点数。

    ⚠️ 闭合图形必须排除"2 点小碎片"：碎片首尾**必然**同点（只有那两个点），旧写法
    （只判首尾同点）会把它误判成完整图形 → ① 它的首点被当成圆心/焦点（head），
    ② `_fig_ink_pts` 只剩 1 个点 → 墨迹路径为空 → **圈选选不中**、渲染退化成"假圆心"
    上的一个点（残留变少、缺口显大），③ 橡皮再切分它时 original 长度与 knots 索引错位。
    """
    n = _FIG_HEAD_PTS.get(kind, 0)
    if n <= 0 or len(pts) <= n:
        return False
    if kind in _FIG_OPEN_KINDS:
        return len(pts) == n + _FIG_OPEN_BODY_PTS.get(kind, -1)
    return len(pts) >= n + 3 and _same_pt(pts[n], pts[-1])


def _fig_ink_pts(kind, pts):
    """图形用于**绘制与判定**的点列（与存盘点列的差别只在头部点）。

    圆的圆心、椭圆/双曲线的两焦点存在点列最前面（"图形包含圆心/两焦点"），但**不属于轮廓**：
    完整图形（轮廓闭合 / 支线完整）返回去掉头部点的部分；被橡皮切出的碎片本身就是轮廓子列
    （且不含头部点）→ 原样返回。
    **两阶段图形第一阶段**（只有两个焦点、轮廓还没生成）返回空 → 不画任何折线，只画两焦点。
    """
    n = _FIG_HEAD_PTS.get(kind, 0)
    if n <= 0 or not pts:
        return pts
    if _fig_stage1(kind, pts):
        return []           # 两阶段图形第一阶段（只有两焦点）→ 没有轮廓可画
    if _fig_head_valid(kind, pts):
        return pts[n:]
    return pts


def _fig_head_pts(kind, pts):
    """图形的头部点（圆心 / 两焦点）——仅当是**完整图形**时才有效，碎片返回空。"""
    n = _FIG_HEAD_PTS.get(kind, 0)
    if n <= 0 or not pts:
        return []
    if _fig_stage1(kind, pts):
        return pts          # 第一阶段：这两点就是两焦点
    if kind == "sector" and len(pts) == 2:
        # 扇形的"只有一条半径"中间态（第一阶段 / 第二阶段尚未拖动）：首点 = 圆心
        return pts[:1]
    if not _fig_head_valid(kind, pts):
        return []
    return pts[:n]


def _fig_has_center(kind, pts):
    """该图形笔划是否带"头部点"（= 完整图形：首点为圆心/两焦点且轮廓闭合）。"""
    return bool(_fig_head_pts(kind, pts))


# ========== 立体图形（斜二测 / 正等测两种测画方式）==========
# 共同约定（用户要求："教科书上的画法"，左手坐标系）：
#   · y 轴、x 轴都在**水平的底面平面** xOy 上，z 轴竖直向上；
#   · 3D → 纸面（u 向右、v 向下）是一个**线性**投影（两种测画法只是系数不同，见
#     `_solid_proj_coeff`）；它在底面平面上的限制可逆 → `_solid_unproj` 反算回底面平面
#     （所以 "在底面平面里是真等腰/真等边/正圆" 对两种测画法都成立）；
#   · 视线方向（3D，指向画面内部）= 投影的**零空间**方向 → `_solid_view_dir`；
#     面是否朝前（可见）= 面的**外向法向**与它的点积 < 0（外向法向按"背离立体中心"定向）。
# 绘制分两大阶段（与椭圆/双曲线同款两阶段机制，状态见 `_sf_base`）：
#   ① 底面阶段：画位于 xOy 平面的底面 —— 画法**复用对应平面图形**
#      （轮廓 + 等边吸附 + 提示文字，见 `_SOLID_BASE_KIND`）；
#   ② 升维阶段：底面中心弹出**一个**手柄（图标 = 上下双向箭头），拖手柄或在画布任意位置
#      拖动都能升维：第二个面（棱柱/圆柱的顶面、圆锥的**顶点**）的中心跟随鼠标在 **yOz 方向**
#      自由移动（沿 y 轴平移 dy + 沿 z 轴升降 dz）→ 柱体 / 锥体都可以画斜的；鼠标贴近
#      "过底面中心的竖直线"时就近吸附成直角柱 / 直角锥（提示「直X柱」「直圆锥」）。
# 一个立体图形由**多笔**组成（可见棱实线 / 被遮挡棱虚线，同双曲线的"四笔"思路）：
#   · 可见棱：外轮廓一条 + 内部可见棱若干（都实线，style = fig:<kind>）；
#   · 被遮挡棱：若干条（虚线，style = fig:<kind>h）—— 单独成笔才能让橡皮切分后
#     碎片仍然是虚线（虚线样式在 style 上，不依赖几何）；
#   · 所有笔划带同一个 `grp`（分组 id）→ 圈选/单击时当作一个整体；被橡皮切分时清空分组。
_SOLID_K = 0.5 * math.cos(math.radians(45.0))   # 斜二测投影系数（0.5 = 折半、45° = 斜轴倾角）
_SOLID_MIN_H = 6.0            # 升维高度下限（px）：小于它视为误触/退化
_SOLID_DEFAULT_H_K = 1.6      # 未拖过探针时的默认高度 = 底面外接尺度 × 该系数
_SOLID_HIDDEN_SUFFIX = "h"    # 被遮挡棱的 style 后缀：fig:triprismh
# **测画方式**（用户要求：形状菜单里选中圆柱后再弹一个小菜单选"正等测 / 斜二测"）：
#   · "iso"     = 正等测（国标"正等轴测图"，简化系数 1：三轴纸面互成 120°、z 轴竖直、
#                   x 轴 30° 右上、y 轴 30° 左上；底面正方形投影成"菱形"）；
#   · "oblique" = 斜二测（`_SOLID_K`：y 轴 1:1 水平向右、x 轴 45° 折半、z 轴竖直）。
# 只有 `_SOLID_PROJ_CHOOSABLE` 里的立体图形（圆柱 / 圆锥 —— 底面是圆、侧面光滑的两种）支持
# 让用户选；其余一律用 `_SOLID_PROJ_FIXED`（斜二测 —— 与加这个功能之前画出来完全一样）。
_SOLID_PROJ_NAMES = {"iso": "正等测", "oblique": "斜二测"}
_SOLID_PROJ_KINDS = ("iso", "oblique")
_SOLID_PROJ_DEFAULT = "iso"       # 菜单默认选择（用户要求：默认正等测）
_SOLID_PROJ_CHOOSABLE = ("cylinder", "cone", "conefrustum")
_SOLID_PROJ_FIXED = "oblique"
# 某些立体图形**固定**用某种测画方式（不允许用户选）：球要求固定用**正等测**（用户要求）
_SOLID_PROJ_FIXED_BY_KIND = {"sphere": "iso"}
# 立体图形注册表（每个立体图形一个"形状引擎"，由各自的子 agent 编写与维护）：
_SOLID_KIND_NAMES = {}        # id -> 菜单名
_SOLID_BASE_KIND = {}         # id -> 底面画法（平面图形 id：复用其轮廓/等边吸附/提示）
_SOLID_ENGINES = {}           # id -> callable(base_pts, height, mode) -> (verts3, faces)
_SOLID_KINDS = []             # 注册顺序（= 菜单顺序）
# 各"底面画法"的底面顶点数（= 平面图形轮廓的顶点数；新加底面类型时在这里登记）
# circle（圆柱底面）= 圆的采样点数（投影后是个椭圆）
_SOLID_BASE_VERTS = {"tri": 3, "rtri": 3, "rect": 4,
                     "pent": 5, "hex": 6, "oct": 8,
                     "circle": _CIRCLE_SEGS}
# 侧面是**光滑曲面**的立体（圆柱 / 圆锥）：棱的可见性不能按"两个相邻平面"分类
# （那会把扇形逼近的每条母线都当成棱）→ 走专用笔划构造 `_solid_cyl_strokes` / `_solid_cone_strokes`。
# 其中"锥体"（升维时第二个面收成**一个点**）另列一份：`_SOLID_CONE_KINDS`。
_SOLID_SMOOTH_KINDS = ("cylinder", "cone")
_SOLID_CONE_KINDS = ("cone",)
# **球**：没有"底面 + 升维"两阶段 —— 它**一步成型**（拖拽 = 投影后的半径），笔划也不用
# "面可见性分类"（外壳就是轮廓圆 + 两个椭圆）→ 完全走专用构造 `_solid_sphere_strokes`，
# 不进 `_solid_strokes` / 两阶段机制（它的 `_SOLID_BASE_KIND` 留空）。
_SOLID_SPHERE_KINDS = ("sphere",)
# 球（以及画圆）拖拽的**最短半径**（px）：小于它视为误触
_SPHERE_MIN_R = 4.0
# **台体**（三棱台 / 四棱台 / 圆台）：比其它立体多**一步**（共三步）—— ① 画底面
# （分别与三棱锥 / 四棱锥 / 圆锥同）② 升维出对应的锥体 ③ 拖体心手柄/任意位置拖拽，
# 用与底面平行的平面截锥体得到顶面 → 台体。
# 剪裁比 ρ = "顶面顶点 = 顶点 + ρ·(底面顶点 − 顶点)"：ρ = 1 → 顶面 = 底面、ρ = 0 → 收成顶点。
_SOLID_FRUSTUM_KINDS = ("trifrustum", "quadfrustum", "conefrustum")
# 底面是**圆**的台体（圆台）：侧面光滑 → 棱的可见性不能按"两个相邻平面"分类
# （128 个梯形侧面会画出一堆假棱）→ 走专用笔划构造 `_solid_cfrustum_strokes`
# （与圆柱 `_solid_cyl_strokes` / 圆锥 `_solid_cone_strokes` 同一族）。
_SOLID_CFRUSTUM_KINDS = ("conefrustum",)
_SOLID_FRUSTUM_DEFAULT_RHO = 0.5    # 第三步没拖过就切走 → 默认截在中间
_SOLID_FRUSTUM_RHO_MIN = 0.05       # ρ 的下/上余量（顶面必须**严格**在锥体内部）


def _register_solid(kind, name, base_kind, engine):
    """注册一个立体图形：菜单名 + 底面画法（平面图形 id）+ 形状引擎。

    形状引擎签名：`engine(base_pts, height, mode) -> (verts3, faces)`
      · base_pts = 底面**投影后**的顶点（纸面坐标，顺序 = 用户画出来的顺序）；
      · height   = 升维高度（纸面 px，沿 +z 向上）；
      · mode     = 测画方式（"iso" = 正等测 / "oblique" = 斜二测）—— 引擎要用它反投影；
      · verts3   = [(x, y, z), ...]（3D，左手系：底面在 xOy 平面、z 向上、x / y 都在水平面内）；
                   **前 len(base_pts) 个必须与 base_pts 一一对应**（底面）；
      · faces    = [[面顶点下标, ...], ...]（顶点绕面一圈，顺序任意 —— 通用绘制器按
                   "背离立体中心"自动定向，不必保证外向）。
    通用绘制器 `_solid_strokes` 负责：投影 → 面可见性 → 棱分类（外轮廓/内部可见/被遮挡）
    → 拼折线 → 每笔的 style/points。形状引擎只管"这个立体是什么"（顶点 + 面）。
    """
    _SOLID_KIND_NAMES[kind] = name
    _SOLID_BASE_KIND[kind] = base_kind
    _SOLID_ENGINES[kind] = engine
    if kind not in _SOLID_KINDS:
        _SOLID_KINDS.append(kind)


def _solid_of(fig):
    """图形 id 是否立体图形：返回 (立体图形 id, 是否"被遮挡棱"那部分)；不是则 ("", False)。"""
    if fig in _SOLID_ENGINES:
        return fig, False
    if fig.endswith(_SOLID_HIDDEN_SUFFIX):
        b = fig[:-len(_SOLID_HIDDEN_SUFFIX)]
        if b in _SOLID_ENGINES:
            return b, True
    return "", False


def _solid_base_n(kind):
    """立体图形底面的顶点数（未知底面画法返回 0）。"""
    return _SOLID_BASE_VERTS.get(_SOLID_BASE_KIND.get(kind, ""), 0)


def _solid_base_needs_rect(kind):
    """底面绘制阶段是否要额外交代那个**辅助矩形**（蓝色虚线）。

    底面本身就填满辅助矩形的（矩形/正方形底面，如四棱柱）→ 不用再画（用户要求）：
    底面的墨迹轮廓就是矩形的投影，再画一条蓝虚线完全重叠。
    圆形底面（圆柱 / 圆锥）也不是"内接在矩形里的多边形" → 同样不画（它的辅助线是半径，
    见 moveLine）。
    """
    return _SOLID_BASE_KIND.get(kind, "") not in ("rect", "circle")


def _solid_proj_coeff(mode="oblique"):
    """测画方式的投影系数 (u_x,u_y,u_z, v_x,v_y,v_z)（u 向右、v 向下，左手系）。

    · 斜二测（oblique，k = `_SOLID_K` = 0.5·cos45°≈0.35355）：y 轴纸面 1:1 水平向右、
      x 轴 45° 折半（右上）、z 轴竖直向上 → u = y + k·x、v = −(z + k·x)。
    · 正等测（iso）：用户指定“**底面圆投影出的椭圆长短轴长度之比为 4:√2**”。
      取“三轴轴向变形系数均为 1、水平两轴关于竖直线对称”的那一族（水平轴与水平线夹角 θ、
      x⁀→(cosθ, −sinθ)、y⁀→(−cosθ, −sinθ)、z⁀→(0, −1)）→ 底面圆的椭圆半轴 = cosθ·√2·R 与 sinθ·√2·R
      → 比值 = 1/tanθ = 4/√2 → tanθ = √2/4 = 1/(2√2) → sinθ = 1/3、cosθ = 2√2/3（θ≈19.47°）：
        u = (2√2/3)·(x − y)、v = −(x + y)/3 − z。
      （轴向变形系数仍全为 1 ✓；零空间 = (3, 3, −2) → 观察者在 +x+y 一侧上方，看得到顶面。）
      ⚠️ 国标“轴间角 120°”的等测图椭圆比值是 √3≈1.73，与本需求（4:√2≈2.83）不同 —— 按用户指定为准。
    """
    if mode == "iso":
        c = 2.0 * math.sqrt(2.0) / 3.0        # cosθ（θ = arcsin(1/3)）
        s = 1.0 / 3.0                          # sinθ
        return (c, -c, 0.0, -s, -s, -1.0)
    k = _SOLID_K
    return (k, 1.0, 0.0, -k, 0.0, -1.0)


def _solid_proj(x, y, z, mode="oblique"):
    """3D（左手系）→ 纸面坐标 (u, v)（u 向右、v 向下）。"""
    ux, uy, uz, vx, vy, vz = _solid_proj_coeff(mode)
    x, y, z = float(x), float(y), float(z)
    return [ux * x + uy * y + uz * z, vx * x + vy * y + vz * z]


def _solid_proj3(verts3, mode="oblique"):
    return [_solid_proj(v[0], v[1], v[2], mode) for v in verts3]


def _solid_unproj(u, v, mode="oblique"):
    """纸面点 → 底面平面（z = 0）上的 3D 点 (x, y, 0)。

    在底面平面上解 2×2 线性方程组（两种测画法通用）：
      u = u_x·x + u_y·y、v = v_x·x + v_y·y（z 分量不参与）。
    """
    ux, uy, _uz, vx, vy, _vz = _solid_proj_coeff(mode)
    det = ux * vy - uy * vx
    if abs(det) < 1e-12:
        return [0.0, 0.0, 0.0]
    u, v = float(u), float(v)
    return [(u * vy - v * uy) / det, (v * ux - u * vx) / det, 0.0]


def _solid_plane_dir(dx, dy, mode="oblique"):
    """底面平面里的方向 (dx, dy) → 纸面上的方向（投影的线性部分）。

    底面等边吸附用它：平面里 4 条射线投影后仍是 4 条射线（线性映射把过原点的直线
    映成过原点的直线）。
    """
    ux, uy, _uz, vx, vy, _vz = _solid_proj_coeff(mode)
    return (ux * dx + uy * dy, vx * dx + vy * dy)


def _solid_uz(mode="oblique"):
    """纸面 u 的线性系数 (u_x, u_y)。

    ⚠️ 现在只在"轴方向退化"时兜底用（`_solid_cyl_sil_idx` 里 `off ≈ 0` 的分支，正常
    不会发生）：圆柱轮廓母线早已改成"**平行于两个圆心连线**且与两个椭圆都相切"的算法，
    不再等价于"投影后切线竖直"。
    """
    ux, uy, _uz, _vx, _vy, _vz = _solid_proj_coeff(mode)
    return (ux, uy)


def _solid_shift_from(cx, cy, probe, mode="oblique"):
    """纸面点 → 第二个面相对底面中心的 **3D 平移 (dy, dz)**（限定在 yOz 平面内）。

    用户要求：升维时第二个面/底面的中心跟随鼠标终点移动，且只能在 **yOz 方向**自由移动
    （即在底面平面内沿 y 轴平移 + 沿 z 轴升降，不沿 x 轴“向外”跑）。
    第二个面中心在 3D 里 = 底面中心 + (0, dy, dz) → 纸面上 = (cx,cy) + dy·(u_y,v_y) + dz·(u_z,v_z)
    → 解 2×2 线性方程组（两种测画法下 (u_y,v_y) 与 (u_z,v_z) 都线性无关 → 鼠标位置唯一对应一组 (dy,dz)）。
    """
    _ux, uy, uz, _vx, vy, vz = _solid_proj_coeff(mode)
    du, dv = float(probe[0]) - float(cx), float(probe[1]) - float(cy)
    det = uy * vz - uz * vy
    if abs(det) < 1e-12:
        return 0.0, 0.0
    return (du * vz - dv * uz) / det, (dv * uy - du * vy) / det


def _solid_vertical_offset(probe, cx, cy, mode="oblique"):
    """鼠标到“过底面中心的竖直线”的**垂直距离**与该直线上的最近点参数 t（= dz）。

    用户在鼠标靠近“能让侧棱垂直于底面”的位置时吸附成直柱体 —— 屏幕上看就是“鼠标贴近
    那根竖直线” → 用纸面垂直距离 ≤ `_FIG_SNAP_PX` 判定（两种测画法通用：竖直线的纸面方向
    就是 z 轴的投影 (u_z, v_z)）。
    """
    _ux, _uy, uz, _vx, _vy, vz = _solid_proj_coeff(mode)
    du, dv = float(probe[0]) - float(cx), float(probe[1]) - float(cy)
    ln2 = uz * uz + vz * vz
    if ln2 < 1e-12:
        return 0.0, math.hypot(du, dv)
    t = (du * uz + dv * vz) / ln2
    return t, math.hypot(du - uz * t, dv - vz * t)


def _solid_view_dir(mode="oblique"):
    """视线方向（3D，指向画面内部）= 投影的零空间方向 → 面是否"朝前"靠它判。

    · 斜二测："纸面坐标不变"的方向 → (1, −k, −k)；
    · 正等测：零空间 (1, 1, −2/3) ∝ (3, 3, −2)（观察者在 +x+y 一侧的上方 → 看得到顶面）。
    """
    if mode == "iso":
        return (1.0, 1.0, -2.0 / 3.0)
    k = _SOLID_K
    return (1.0, -k, -k)


def _solid_proj_for(kind, requested=""):
    """某个立体图形**本次**采用的测画方式。

    只有 `_SOLID_PROJ_CHOOSABLE`（圆柱 / 圆锥）支持用户在菜单里选；其它立体图形一律用
    `_SOLID_PROJ_FIXED_BY_KIND` 里指定的（球 = 正等测），没指定的用 `_SOLID_PROJ_FIXED`
    （斜二测 —— 与加这个功能之前画出来完全一样）。
    """
    if kind in _SOLID_PROJ_CHOOSABLE and requested in _SOLID_PROJ_KINDS:
        return requested
    return _SOLID_PROJ_FIXED_BY_KIND.get(kind, _SOLID_PROJ_FIXED)


def _solid_face_front(face3, centre3, mode="oblique"):
    """面是否"朝前"（可见）：外向法向 · 视线方向 < 0。

    外向法向用"背离立体中心"定向（凸多面体通用）→ 调用方（形状引擎）不必保证
    面的顶点绕向，少一类容易写错的约定。
    """
    if len(face3) < 3:
        return False
    f = [(float(p[0]), float(p[1]), float(p[2])) for p in face3]
    a, b, c = f[0], f[1], f[2]
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    w = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (u[1] * w[2] - u[2] * w[1],
         u[2] * w[0] - u[0] * w[2],
         u[0] * w[1] - u[1] * w[0])
    fx = sum(p[0] for p in f) / len(f)
    fy = sum(p[1] for p in f) / len(f)
    fz = sum(p[2] for p in f) / len(f)
    d = (fx - centre3[0], fy - centre3[1], fz - centre3[2])
    if n[0] * d[0] + n[1] * d[1] + n[2] * d[2] < 0.0:
        n = (-n[0], -n[1], -n[2])
    vd = _solid_view_dir(mode)
    return (n[0] * vd[0] + n[1] * vd[1] + n[2] * vd[2]) < 0.0


def _solid_chains(edges):
    """把一组棱拼成尽量少的折线：edges = [(i, j), ...] → [[i, j, k, ...], ...]。

    优先从**度为奇数**的端点出发（开放链），剩下的闭环单独成一条；
    返回值里的下标是顶点下标（调用方自己映射成纸面坐标）。
    """
    adj = {}
    for a, b in edges:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    used = set()

    def ek(a, b):
        return (a, b) if a <= b else (b, a)

    starts = [v for v in sorted(adj) if len(adj[v]) % 2 == 1]
    starts += [v for v in sorted(adj) if len(adj[v]) % 2 == 0]
    out = []
    for v0 in starts:
        while True:
            nxt = [w for w in sorted(adj.get(v0, ())) if ek(v0, w) not in used]
            if not nxt:
                break
            chain = [v0]
            cur = v0
            while True:
                cand = None
                for w in sorted(adj.get(cur, ())):
                    if ek(cur, w) not in used:
                        cand = w
                        break
                if cand is None:
                    break
                used.add(ek(cur, cand))
                chain.append(cand)
                cur = cand
            if len(chain) >= 2:
                out.append(chain)
    return out


def _solid_strokes_from_verts(kind, verts3, faces, mode="oblique"):
    """通用绘制器的**后半段**：顶点/面表已由调用方给出 → 投影 + 面可见性 + 棱分类 → 多笔。

    （`_solid_strokes` 从"形状引擎"拿到 verts3/faces 后调它；三棱台这种"顶点/面表不能由
    注册的引擎签名（base, height, mode, dy）唯一确定"的图形也直接调它。）
    """
    if not verts3 or not faces:
        return []
    p2 = _solid_proj3(verts3, mode)
    gx = sum(float(v[0]) for v in verts3) / len(verts3)
    gy = sum(float(v[1]) for v in verts3) / len(verts3)
    gz = sum(float(v[2]) for v in verts3) / len(verts3)
    front = [_solid_face_front([verts3[i] for i in fc], (gx, gy, gz), mode) for fc in faces]
    # 棱 → 相邻面（凸多面体每条棱恰好属于两个面）
    e2f = {}
    for fi, fc in enumerate(faces):
        m = len(fc)
        for t in range(m):
            a, b = int(fc[t]), int(fc[(t + 1) % m])
            key = (a, b) if a <= b else (b, a)
            e2f.setdefault(key, []).append(fi)
    sil, vis, hid = [], [], []
    for (a, b), fl in e2f.items():
        fr = [front[i] for i in fl]
        if any(fr) and not all(fr):
            sil.append((a, b))
        elif all(fr):
            vis.append((a, b))
        else:
            hid.append((a, b))
    out = []
    for chain in _solid_chains(sil) + _solid_chains(vis):
        out.append({"op": "pen", "style": _FIG_PREFIX + kind,
                    "points": [list(p2[i]) for i in chain]})
    for chain in _solid_chains(hid):
        out.append({"op": "pen", "style": _FIG_PREFIX + kind + _SOLID_HIDDEN_SUFFIX,
                    "points": [list(p2[i]) for i in chain]})
    return out


def _solid_strokes(kind, base_pts, height, mode="oblique", dy=0.0):
    """立体图形 → 笔划列表（可见棱实线 / 被遮挡棱虚线），通用绘制器。

    ① 形状引擎给出 verts3（3D）与 faces（面顶点下标）；
    ② 按 `mode` 投影全部顶点；每个面按"外向法向 · 视线方向"判可见性；
    ③ 棱按相邻两个面分类：都朝前 → 内部可见棱；一前一后 → 外轮廓棱；都朝后 → 被遮挡棱；
    ④ 各类棱各拼成折线 → 外轮廓/内部可见棱（实线，style=fig:<kind>）、
       被遮挡棱（虚线，style=fig:<kind>h，见 `_FIG_DASHED`）。
    **第二个面 = 底面沿 (0, dy, height) 平移**（用户要求：升维时第二个面可在 yOz 方向
    自由移动）—— `dy = 0` 就是原来那个“沿 z 竖直拔高”的情况（旧调用全部照旧）。
    **侧面是光滑曲面的**（圆柱 / 圆锥，`_SOLID_SMOOTH_KINDS`）走专用构造：
    圆柱 = `_solid_cyl_strokes`（第二个面 = 平移后的圆环）、圆锥 = `_solid_cone_strokes`
    （第二个面退化成**一个点** = 顶点）。
    返回 [{"style": ..., "points": [...]}, ...]（**不含颜色/粗细**，由调用方补）。
    """
    if kind in _SOLID_CFRUSTUM_KINDS:
        # 圆台：侧面光滑（截圆锥面）→ 走专用构造（默认截切比 ρ = 0.5）；
        # 真要指定 ρ 请用 `_solid_frustum_strokes`
        return _solid_cfrustum_strokes(kind, base_pts, float(height), mode, dy,
                                       _SOLID_FRUSTUM_DEFAULT_RHO)
    if kind in _SOLID_SMOOTH_KINDS:
        if kind in _SOLID_CONE_KINDS:
            return _solid_cone_strokes(kind, base_pts, float(height), mode, dy)
        return _solid_cyl_strokes(kind, base_pts, float(height), mode, dy)
    eng = _SOLID_ENGINES.get(kind)
    nb = _solid_base_n(kind)
    if (eng is None or nb <= 0 or len(base_pts) < nb
            or (abs(float(height)) <= 1e-9 and abs(float(dy)) <= 1e-9)):
        return []
    bp = [[float(p[0]), float(p[1])] for p in base_pts[:nb]]
    try:
        verts3, faces = eng(bp, float(height), mode, float(dy))
    except Exception:
        plugin_logger.debug("立体图形形状引擎失败", exc_info=True)
        return []
    if not verts3 or not faces:
        return []
    return _solid_strokes_from_verts(kind, verts3, faces, mode)


def _solid_rect_corner_a(x0, y0, x1, y1, mode="oblique"):
    """拖拽（起点→终点）所定的底面平面矩形的**另一个角**（纸面坐标）。

    用户细则：起点→终点是这个矩形的**一条对角线**（不画出来）；矩形的两组对边分别沿 y 轴、
    x 轴（都在底面平面内）→ 投影后仍是个平行四边形（投影在底面平面内是线性的）。
    推导：底面平面矩形 x ∈ [x0p, x1p]、y ∈ [y0p, y1p]，其中 (x,y) = `_solid_unproj(纸面点)`；
    对角线两端就是起终点。于是纸面上的另两个角：
      E1 = 投影(x1p, y0p)（与**终点同 x**、与**起点同 y**）
      E2 = 投影(x0p, y1p)
    （斜二测时化为 `(u0 + v0 − v1, v1)` 与 `(u1 + v1 − v0, v0)` —— 与之前版本一致。）
    """
    p0 = _solid_unproj(x0, y0, mode)
    p1 = _solid_unproj(x1, y1, mode)
    e1 = _solid_proj(p1[0], p0[1], 0.0, mode)
    e2 = _solid_proj(p0[0], p1[1], 0.0, mode)
    return (float(e1[0]), float(e1[1])), (float(e2[0]), float(e2[1]))


def _solid_base_rect_guide(x0, y0, x1, y1, mode="oblique"):
    """底面第一阶段的**蓝色虚线辅助矩形（投影）**（引导线）。

    ⚠️ 必须按"**一段 4 个数**"的约定返回（这里是 4 段 = 16 个数），**不能**用"闭合点列"
    （5 个点 = 10 个数）：QML 的引导线 Canvas 按 `n = floor(len / 4)` 取段数，10 个数只会
    画出前 2 段 —— 表现为"矩形只画了一半"（用户报的问题：顶点所在的那条边没画出来）。
    顺序：起点 → E1（沿 x 的边）→ 终点（沿 y 的边 = 底边）→ E2（沿 x 的边）→ 起点（沿 y）。
    """
    e1, e2 = _solid_rect_corner_a(x0, y0, x1, y1, mode)
    x0, y0, x1, y1 = float(x0), float(y0), float(x1), float(y1)
    return [x0, y0, e1[0], e1[1],
            e1[0], e1[1], x1, y1,
            x1, y1, e2[0], e2[1],
            e2[0], e2[1], x0, y0]


def _axis_plane_strokes(ox, oy, lx, ly):
    """**平面直角坐标系**的两条轴（带箭头的笔划）：原点 = (ox, oy)。

    用户要求（一步到位）：鼠标起点 = 原点；起终点在纸面 x / y 上的偏移长度就是坐标系在这一侧
    的两条轴的长度；**原点是横轴的中点、也是纵轴的中点** → 横轴 = 原点左右各 lx、箭头朝右；
    纵轴 = 原点上下各 ly、箭头朝上。两笔都走直线菜单的 "arrow"（箭头样式完全一致）。
    """
    ox, oy = float(ox), float(oy)
    lx, ly = abs(float(lx)), abs(float(ly))
    return [
        {"op": "pen", "style": _AXIS_ARROW_STYLE,
         "points": [[ox - lx, oy], [ox + lx, oy]]},          # 横坐标轴（指向右）
        {"op": "pen", "style": _AXIS_ARROW_STYLE,
         "points": [[ox, oy + ly], [ox, oy - ly]]},          # 纵坐标轴（指向上）
    ]


def _axis_space_xy(ox, oy, x1, y1, mode="oblique"):
    """**空间直角坐标系第一步**的 xy 平面：返回 (吸附后的拖拽点, 蓝色虚线矩形引导线, 是否吸中正方形)。

    直接复用四棱柱底面那一套（拖拽 = 底面平面矩形的**对角线**；"正多边形"吸附 → 矩形在底面
    平面里是正方形）→ "x、y 轴等长"就是"矩形是正方形"。
    """
    sx, sy, snap_line = _solid_base_snap("quadprism", ox, oy, x1, y1, mode)
    return sx, sy, _solid_base_rect_guide(ox, oy, sx, sy, mode), (snap_line is not None)


def _axis_xy_pts(ox, oy, x1, y1, mode="oblique"):
    """xy 平面矩形的**原点角** + 它的两个相邻角（纸面坐标，列表长度 3）。

    用户要求（第七十九轮）："原点**严格**在鼠标起点，箭头线沿**相邻两个矩形边**发散" ——
    所以**不能**直接用 `_solid_base_pts` 的 4 个角：那 4 个角是按底面平面里的 min/max
    排的（起点未必是第 0 个）→ 这里显式用 `_solid_rect_corner_a` 取**与起点相邻**的两个角，
    原点就是传进来的起点本身（**不做吸附、不做取整**）。
    返回 [原点, 角1(沿底面平面 x 的边), 角2(沿底面平面 y 的边)]。
    """
    ox, oy = float(ox), float(oy)
    e1, e2 = _solid_rect_corner_a(ox, oy, x1, y1, mode)
    return [[ox, oy], [float(e1[0]), float(e1[1])], [float(e2[0]), float(e2[1])]]


def _axis_xy_arrows(pts):
    """xy 两条轴 = 从**原点**（= 鼠标起点）沿两条相邻矩形边发散的两笔箭头
    （长度 = 矩形边长）。`pts` = `_axis_xy_pts()` 的结果：[原点, 角1, 角2]。"""
    p0 = [float(pts[0][0]), float(pts[0][1])]
    out = []
    for p in (pts[1], pts[2]):
        out.append({"op": "pen", "style": _AXIS_ARROW_STYLE,
                    "points": [list(p0), [float(p[0]), float(p[1])]]})
    return out


def _axis_y_index(pts, mode="oblique"):
    """xy 两条轴里哪一条更接近 **y 方向**（0 = 原点→pts[1]、1 = 原点→pts[2]）——在**底面平面**里判。"""
    p0 = _solid_unproj(float(pts[0][0]), float(pts[0][1]), mode)
    best, k = None, 0
    for i, pi in enumerate((1, 2)):
        p = _solid_unproj(float(pts[pi][0]), float(pts[pi][1]), mode)
        d = (p[0] - p0[0], p[1] - p0[1])
        ln = math.hypot(d[0], d[1])
        if ln < 1e-9:
            continue
        score = abs(d[1] / ln)          # 与 +y 方向的夹角余弦绝对值（底面平面里两条边正交）
        if best is None or score > best:
            best, k = score, i
    return k


def _axis_edge_len(pts, i, mode="oblique"):
    """第 i 条 xy 轴（0 = 原点→pts[1]、1 = 原点→pts[2]）在**底面平面**里的长度 = 3D 里的轴长。"""
    pi = (1, 2)[i]
    p0 = _solid_unproj(float(pts[0][0]), float(pts[0][1]), mode)
    p = _solid_unproj(float(pts[pi][0]), float(pts[pi][1]), mode)
    return math.hypot(p[0] - p0[0], p[1] - p0[1])


def _axis_lines_cross(a0, a1, b0, b1):
    """两条**直线**（各由两点定）的交点（纸面坐标）；平行/退化时返回 None。

    平面直角坐标系的两条轴交于原点 —— 选中的两轴没共起点时用它反推原点（旋转/拖动后同样成立）。
    """
    x1, y1 = float(a0[0]), float(a0[1])
    x2, y2 = float(a1[0]), float(a1[1])
    x3, y3 = float(b0[0]), float(b0[1])
    x4, y4 = float(b1[0]), float(b1[1])
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-9:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def _axis_z_stroke(ox, oy, dy):
    """z 轴那一笔：从原点竖直向上（dy < 0）或向下（dy > 0），长度 = |dy|（纸面 = 3D，1:1）。"""
    ox, oy, dy = float(ox), float(oy), float(dy)
    return {"op": "pen", "style": _AXIS_ARROW_STYLE,
            "points": [[ox, oy], [ox, oy + dy]]}


def _solid_base_snap(kind, ox, oy, x, y, mode="oblique"):
    """底面第一阶段的"正多边形吸附"：把拖拽点吸到"底面平面里是正多边形"的射线上。

    底面平面矩形的两条边分别沿平面 y 轴与平面 x 轴；"底面是正多边形"（`_figure_aspect`）
    要求 |Δx| = |Δy| / asp → 在**底面平面**里是 4 条过起点的射线（方向 (±1, ±asp)）。
    投影在底面平面上是线性的 → 这 4 条射线在纸面上仍然是 4 条过起点的射线
    （方向 = `_solid_plane_dir`），于是两种测画法共用同一套算法。
    （斜二测时化简就是两条斜率 k/(asp − k) 与 −k/(asp + k) 的直线 —— 与之前版本完全一致。）
    取偏差最小的那条（≤ `_FIG_SNAP_PX`），返回 (px, py, 引导直线)，未吸附时 guide = None。
    """
    dx, dy = x - ox, y - oy
    if abs(dx) < 1e-6 or abs(dy) < 1e-6:
        return x, y, None            # 贴着水平/竖直方向时不吸附，避免抽动
    asp = _figure_aspect(_SOLID_BASE_KIND.get(kind, "tri"))
    best = None
    for pdx in (1.0, -1.0):
        for pdy in (1.0, -1.0):
            wu, wv = _solid_plane_dir(pdx, pdy * asp, mode)
            ln = math.hypot(wu, wv)
            if ln < 1e-9:
                continue
            ux, uy = wu / ln, wv / ln
            t = dx * ux + dy * uy
            if t < 6.0:
                continue         # 离起点太近不吸附（否则开始拖动就跳）
            px, py = ox + ux * t, oy + uy * t
            d = math.hypot(x - px, y - py)
            if d <= _FIG_SNAP_PX and (best is None or d < best[0]):
                best = (d, px, py, ux, uy, t)
    if best is None:
        return x, y, None
    _d, px, py, ux, uy, t = best
    ext = 56.0
    return px, py, [ox, oy, ox + ux * (t + ext), oy + uy * (t + ext)]


def _solid_cyl_ring(cx, cy, x1, y1, mode="oblique"):
    """圆柱 / 圆锥共用**底面（第一阶段）**：起点 = 底面平面里圆的圆心，终点 = **投影后圆上的一点**。

    用户细则："鼠标起点是圆的圆心，终点到起点的连线是投影后圆的半径" —— 于是：
      · 圆心（底面平面）= `_solid_unproj(起点)`；
      · 半径 = |`_solid_unproj(终点) − _solid_unproj(起点)`|（投影在底面平面里是线性的，
        两点之差就是底面平面里对应的向量）→ 拖拽终点恰好落在投影后的圆上；
      · 底面 = 底面平面里以该点为圆心、该半径的圆 → **投影后是椭圆**
        （斜二测：2R√(1+k²) × 2kR；正等测：2√3R/√2 × √2R）。
    返回投影后的闭合点列（`_CIRCLE_SEGS + 1` 个点，首尾同点）。
    """
    c = _solid_unproj(cx, cy, mode)
    p = _solid_unproj(x1, y1, mode)
    r = math.hypot(p[0] - c[0], p[1] - c[1])
    if r <= 1e-6:
        pt = [float(cx), float(cy)]
        return [[pt[0], pt[1]] for _ in range(4)]      # 退化（刚按下）→ 同点环
    out = []
    for i in range(_CIRCLE_SEGS + 1):
        t = 2.0 * math.pi * i / _CIRCLE_SEGS
        out.append(_solid_proj(c[0] + r * math.cos(t), c[1] + r * math.sin(t), 0.0, mode))
    return out


def _solid_cyl_sil_idx(mode, off, m):
    """圆柱两条轮廓母线在底面圆环上的**采样下标**（返回对径的两个下标）。

    用户口径：轮廓母线 = "连接上下底面中心的那条线"的**平行线**中，能**同时与上下两个椭圆
    相切**的两条。因为第二个圆环是底面圆环的平移（第二个 = 第一个 + `off`），过底面椭圆上
    某点 p 沿 `off` 拉的直线与第二个椭圆相切 ⟺ 该直线与第一个椭圆相切（平移不改变切向），
    所以只要解"**底面椭圆的切线平行于 `off`**"的两个切点 t。

    底面平面里 p(t) = R(cos t, sin t) → 纸面 (u, v) = (u_x·R cos t + u_y·R sin t,
    v_x·R cos t + v_y·R sin t)，纸面切向 T(t) = R·(−u_x sin t + u_y cos t,
    −v_x sin t + v_y cos t)。要求 T ∥ off（叉积 = 0）：
        sin t·(v_x·w_x − u_x·w_y) + cos t·(u_y·w_y − v_y·w_x) = 0
    → 取 A = v_x·w_x − u_x·w_y、B = u_y·w_y − v_y·w_x → `t0 = atan2(−B, A)`（对径另一解
    = t0 + π，采样成 i0 与 i0 + m//2）。`off` 恰好竖直时（`dy = 0`）本式退化为
    `tan t = u_y/u_x`（"投影后切线竖直"）—— 与老版本完全一致。
    """
    ux, uy, _uz, vx, vy, _vz = _solid_proj_coeff(mode)
    wx, wy = float(off[0]), float(off[1])
    a = vx * wx - ux * wy
    b = uy * wy - vy * wx
    if abs(a) < 1e-12 and abs(b) < 1e-12:
        # `off` 退化成 0（`dy = height = 0`，库内不会走到）→ 兜底用"切线竖直"
        _ux, _uy = _solid_uz(mode)
        t0 = math.atan2(_uy, _ux)
    else:
        t0 = math.atan2(-b, a)
    step = 2.0 * math.pi / m
    i0 = int(round(t0 / step)) % m
    return i0, (i0 + m // 2) % m


def _solid_cyl_strokes(kind, ring, height, mode="oblique", dy=0.0):
    """圆柱的笔划：顶面整圈实线 + 底面圆环按前后分段（前段实线 / 后段虚线）+ 两条轮廓母线。

    与棱柱的差别只在"侧面是光滑曲面"：
      · **顶面**（整圈都能露出的那个面）：一条闭合实线折线；
      · **底面**：以**两条轮廓母线的落点**分成前/后两段（前段实线、后段虚线）；
      · 侧棱：**只画这两条轮廓母线**（曲面光滑 → 中间那些母线不是棱，画出来会像扇形逼近）。
    **哪个圆环是顶面**：z 更大的那个 —— 第二个面 z = `height`、底面 z = 0。用户报过的问题：
    把第二个面拖到第一个面**下方**时，第一个面才是顶面 → 那时整圈实线应当画在**底面圆环**
    上、被遮挡的半圈虚线落在第二个面上（之前写死"第二个面整圈实线"）。
    **两条轮廓母线（用户口径）**：先连上下两个圆心得到"轴"的纸面方向；再找**平行于它**且
    **同时与上下两个椭圆相切**的两条线 —— 这两条线就是圆柱的两条侧棱。因为第二个圆环是
    底面圆环的**平移**（第二个 = 第一个 + `off`），过底面椭圆上"切线平行于 `off`"的切点 p
    沿 `off` 拉的直线必然也与第二个椭圆相切（平移不改变切向）→ 只需在底面圆环上找两个
    切点（`_solid_cyl_sil_idx`），侧棱 = p → p + `off`。
    ⚠️ 这与"投影后切线**竖直**处（u 极值）"**不等价** —— 那只在 `off` 恰好竖直（即 `dy = 0`
    的老情况，两种测画法的 z 轴投影都是竖直的）时才成立。`dy ≠ 0` 时轴是斜的，必须按
    `off` 求切点，否则侧棱会与椭圆不相切、且前/后分段点也错。
    **哪半圈可见**：两个切点把"底面圆环"分成两段，**外弧**（远离顶面圆环的那一段）才是
    可见的（实线）—— 它正是两个椭圆并集的凸包边界上的一段（靠近顶面圆环的那段被挡住）。
    判据：取两段中点、比"沿**顶面圆心 → 底面圆心**方向的投影"谁更远。
    ⚠️ 别用"离观察者最近的采样点"判（旧写法）：那只在**轴竖直**（`dy = 0`）时与"外弧"等价；
    轴被拖斜甚至接近水平（`dy` 大）时两者矛盾 → 会把露在轮廓外的半圈画成虚线（用户报的图）。
    **第二个面** = 底面圆环沿 (0, dy, height) 平移后的投影（用户要求：升维时第二个面可在
    yOz 方向自由移动）—— 平移量先当成一个**纸面位移** `off` 算出来，顶圈与两条侧棱都用它，
    于是 `dy = 0` 时与原来（竖直拔高）完全一样。
    """
    if len(ring) < 4:
        return []
    h = float(height)
    dy = float(dy)
    ring = [[float(p[0]), float(p[1])] for p in ring]
    # 兼容两种入参：`_solid_cyl_ring` **带**闭合点（首尾同点）、`_sf_base`（`_solid_base_pts`）
    # **不带** —— 统一去掉闭合点后再按 m 段等分，两条轮廓母线才落在正确的对径采样点上。
    if len(ring) > 3 and (abs(ring[0][0] - ring[-1][0]) < 1e-9
                          and abs(ring[0][1] - ring[-1][1]) < 1e-9):
        ring = ring[:-1]
    m = len(ring)
    if m < 3:
        return []
    # 第二个面相对底面中心的**纸面位移**（沿 (0, dy, h) 平移 → 纸面 = dy·(u_y,v_y) + h·(u_z,v_z)）
    _ux2, uy2, uz2, _vx2, vy2, vz2 = _solid_proj_coeff(mode)
    off = [uy2 * dy + uz2 * h, vy2 * dy + vz2 * h]
    top = [[p[0] + off[0], p[1] + off[1]] for p in ring]
    # 两条轮廓母线在底面圆环上的采样下标 = 切线平行于 `off` 的两个切点（对径）
    i0, i1 = _solid_cyl_sil_idx(mode, off, m)
    arc_a = [(i0 + t) % m for t in range((i1 - i0) % m)]          # i0 → i1
    arc_b = [(i1 + t) % m for t in range((i0 - i1) % m)]          # i1 → i0
    # 顶面 = z 更大的那个圆环（第二个面 z = h、底面 z = 0）：整圈实线画在它上面，
    # 前段实线/后段虚线画在**另一个**（底面）圆环上。
    if h >= 0.0:
        lid_ring, bot_ring = top, ring
    else:
        lid_ring, bot_ring = ring, top
    # 两个切点把"底面圆环"分成两段 → **外弧**（远离顶面圆环的那一段）才是可见的（实线）：
    # 它正是两个椭圆并集的凸包边界（顶面圆环把自己的那一侧挡住了）。
    # 判据：外弧 = 沿"**顶面圆心 → 底面圆心**"方向更远的那一段（取两段中点比较点积）。
    # ⚠️ 别用"离观察者最近的采样点"判：那只在**轴竖直**（`dy = 0`）时与"外弧"一致；
    # 轴被拖斜、甚至接近水平（`dy` 大）时两者会矛盾 —— 会把露在轮廓外的半圈画成虚线、
    # 把被挡住的半圈画成实线（用户报的"侧面/底面画法不对"）。
    _crx = sum(p[0] for p in ring) / m                 # 底面圆环中心（纸面）
    _cry = sum(p[1] for p in ring) / m
    _sgn = -1.0 if h >= 0.0 else 1.0                   # 顶面圆心 → 底面圆心的方向 = _sgn·off
    _ox, _oy = _sgn * off[0], _sgn * off[1]
    _q = max(1, m // 4)                                # 每段长度 m/2 个采样 → 中点在下标 +m/4
    _ma, _mb = (i0 + _q) % m, (i1 + _q) % m
    _da = (ring[_ma][0] - _crx) * _ox + (ring[_ma][1] - _cry) * _oy
    _db = (ring[_mb][0] - _crx) * _ox + (ring[_mb][1] - _cry) * _oy
    front_idx, back_idx = (arc_a, arc_b) if _da > _db else (arc_b, arc_a)
    out = [{"op": "pen", "style": _FIG_PREFIX + kind,
            "points": [list(p) for p in lid_ring] + [list(lid_ring[0])]}]      # 顶面整圈

    def _arc(src, idxs):
        pts = [list(src[idxs[0]])]
        for k in idxs:
            pts.append(list(src[(k + 1) % m]))
        return pts

    out.append({"op": "pen", "style": _FIG_PREFIX + kind, "points": _arc(bot_ring, front_idx)})
    out.append({"op": "pen", "style": _FIG_PREFIX + kind + _SOLID_HIDDEN_SUFFIX,
                "points": _arc(bot_ring, back_idx)})
    for i in (i0, i1):                      # 两条轮廓母线（平行于 off、与上下两椭圆都相切）
        out.append({"op": "pen", "style": _FIG_PREFIX + kind,
                    "points": [list(ring[i]), [ring[i][0] + off[0], ring[i][1] + off[1]]]})
    return out


def _solid_cone_sil_idx(mode, ring, off, m):
    """圆锥两条轮廓母线在底面圆环上的采样下标（= 从**顶点**向底面椭圆作切线的两个切点）。

    用户口径（与圆柱同源）：轮廓母线 = 从顶点引出、与底面椭圆相切的两条线。
    做法：把问题搬回**底面平面** —— 投影在底面平面上的限制 M 是可逆线性映射，而线性映射把
    "相切"保成"相切"（叉积只差一个 det 因子），于是"从纸面顶点 A 向底面椭圆作切线"等价于
    "从 A 的原像 p = M⁻¹·off 向底面圆作切线"：
      · R = 底面圆半径（底面平面里）、d = |p|（p 一般不在圆上：off 含 z 分量）；
      · d ≤ R（顶点落在圆内 → 投影上顶点在底面椭圆**内部**，切线不存在、整个底面椭圆都是
        轮廓）→ 返回 None（调用方据此不画轮廓母线）；
      · 否则 θ = atan2(p_y, p_x)、α = arccos(R/d) → 两个切点角度 = θ ∓ α。
    自检：顶点很高（d → ∞）时 α → 90°，切点角度 → θ ± 90° —— 与圆柱的"纸面切线竖直处"
    （斜二测 θ = −19.47° → 70.53°/250.53°；正等测 θ = 45° → 135°/−45°）**完全吻合** ✓。
    切点再按"底面平面角度 → 采样下标"（第 i 个采样点 = 角度 2πi/m）取**最接近的采样点**，
    与圆柱同一套约定。
    """
    ux, uy, _uz, vx, vy, _vz = _solid_proj_coeff(mode)
    det = ux * vy - uy * vx
    if abs(det) < 1e-12 or m < 3:
        return None
    wx, wy = float(off[0]), float(off[1])
    px = (vy * wx - uy * wy) / det          # M⁻¹·off（顶点在底面平面上的"原像"）
    py = (ux * wy - vx * wx) / det
    d = math.hypot(px, py)
    cx = sum(float(p[0]) for p in ring) / m
    cy = sum(float(p[1]) for p in ring) / m
    c0 = _solid_unproj(cx, cy, mode)         # 底面中心（底面平面）
    p0 = _solid_unproj(ring[0][0], ring[0][1], mode)
    rad = math.hypot(p0[0] - c0[0], p0[1] - c0[1])
    if rad <= 1e-9 or d <= rad * (1.0 + 1e-9):
        return None                          # 切线不存在（顶点在底面椭圆内部）
    alpha = math.acos(max(-1.0, min(1.0, rad / d)))
    th = math.atan2(py, px)
    step = 2.0 * math.pi / m
    i0 = int(round((th - alpha) / step)) % m
    i1 = int(round((th + alpha) / step)) % m
    if i0 == i1:
        return None                          # α 太小 → 两个切点落回同一个采样点（退化成一点）
    return i0, i1


def _solid_cone_strokes(kind, ring, height, mode="oblique", dy=0.0):
    """圆锥的笔划：底面圆环（可见段实线 / 被遮挡段虚线）+ 两条轮廓母线（顶点 → 两个切点）。

    用户要求：圆锥画法与圆柱类似，只是升维时**把底面连接到一点**（顶点 = 底面中心 +
    (0, dy, height)）—— 顶点同样可以在 yOz 方向自由拖动、同样有"直圆锥"吸附（复用
    `_solid_shift` 那一套，提示文字 = "直" + 菜单名 = 「直圆锥」）。
    · 顶点在底面平面**上方**（`dz > 0`）且切线存在 → 底面圆环"**背离顶点**"的那段可见（实线）、
      朝向顶点的那段被侧面挡住（虚线）—— 与圆柱底面那圈同源的判据；
    · 顶点在底面平面**下方或与底面共面**（`dz ≤ 0`）→ 底面圆盘整个朝上（立体在底面平面下方，
      没有任何东西能挡住它）→ **整圈实线**（与圆柱"第二个面在下方时原底面是顶面"同理）；
    · 切线不存在（顶点落在投影椭圆内部 → 圆锥被压得很扁）→ 整圈实线、不画轮廓母线
      （此时底面椭圆本身就是整个轮廓）。
    顶点相对底面中心的纸面位移 `off` 与圆柱同一套算法 → `dy = 0` 时就是"竖直拔高"。
    """
    if len(ring) < 4:
        return []
    h = float(height)
    dy = float(dy)
    ring = [[float(p[0]), float(p[1])] for p in ring]
    # 兼容两种入参（带 / 不带闭合点），与 `_solid_cyl_strokes` 同一约定
    if len(ring) > 3 and (abs(ring[0][0] - ring[-1][0]) < 1e-9
                          and abs(ring[0][1] - ring[-1][1]) < 1e-9):
        ring = ring[:-1]
    m = len(ring)
    if m < 3:
        return []
    _ux, uy, uz, _vx, vy, vz = _solid_proj_coeff(mode)
    off = [uy * dy + uz * h, vy * dy + vz * h]        # 顶点相对底面中心的纸面位移
    cx = sum(p[0] for p in ring) / m
    cy = sum(p[1] for p in ring) / m
    apex = [cx + off[0], cy + off[1]]
    closed = [list(p) for p in ring] + [list(ring[0])]
    sil = _solid_cone_sil_idx(mode, ring, off, m)
    if sil is None:
        # 顶点在底面椭圆内部（很扁的圆锥）→ 整个轮廓就是底面椭圆本身
        return [{"op": "pen", "style": _FIG_PREFIX + kind, "points": closed}]
    i0, i1 = sil
    arc_a = [(i0 + t) % m for t in range((i1 - i0) % m)]          # i0 → i1
    arc_b = [(i1 + t) % m for t in range((i0 - i1) % m)]          # i1 → i0

    def _arc(idxs):
        pts = [list(ring[idxs[0]])]
        for k in idxs:
            pts.append(list(ring[(k + 1) % m]))
        return pts

    out = []
    if h > 0.0:
        # 可见弧 = **背离顶点**的那段（两段中点沿 −off 方向更远的那个）—— 它正是
        # "底面椭圆与顶点并集的凸包边界"上的一段。
        _q = max(1, m // 4)
        _ma, _mb = (i0 + _q) % m, (i1 + _q) % m
        _da = -((ring[_ma][0] - cx) * off[0] + (ring[_ma][1] - cy) * off[1])
        _db = -((ring[_mb][0] - cx) * off[0] + (ring[_mb][1] - cy) * off[1])
        front_idx, back_idx = (arc_a, arc_b) if _da > _db else (arc_b, arc_a)
        out.append({"op": "pen", "style": _FIG_PREFIX + kind, "points": _arc(front_idx)})
        out.append({"op": "pen", "style": _FIG_PREFIX + kind + _SOLID_HIDDEN_SUFFIX,
                    "points": _arc(back_idx)})
    else:
        # 顶点在底面平面下方/共面 → 底面圆盘全部可见 → 整圈实线
        out.append({"op": "pen", "style": _FIG_PREFIX + kind, "points": closed})
    for i in (i0, i1):      # 两条轮廓母线：顶点 → 底面椭圆上的切点
        out.append({"op": "pen", "style": _FIG_PREFIX + kind,
                    "points": [list(ring[i]), list(apex)]})
    return out


def _solid_sphere_strokes(kind, cx, cy, r, mode="iso"):
    """球的笔划：**轮廓圆 + 两个"半径圆"的投影椭圆**（各分可见/被遮挡两段），共 5 笔。

    用户要求（球的画法）：
      · 只有**一步**：拖拽的起点 = 球心，终点到起点的距离 = **投影后的半径** →
        轮廓圆（半径 = 该长度）= 球在屏幕面上的投影（工程制图约定：球的正等测图就是个圆）；
      · 再用两个椭圆（"球体在相应位置的半径圆在屏幕上的投影"）勾勒：
        ① 与 xOy 平行的**过球心**的平面截球面所得的圆（"赤道"）→ 投影椭圆**长轴水平**：
           **下半部分实线、上半部分虚线**（观察者在上前方 → 近侧/下半可见）；
        ② 长轴在屏幕上**竖直**的椭圆：**左半部分实线、右半部分虚线**。
    两个椭圆的宽高比 = 该测画法下"水平大圆"投影椭圆的宽高比（正等测 = 4:√2 →
    半轴 (r, r·√2/4) 与 (r·√2/4, r)，即把同一个椭圆旋转 90°，正好与轮廓圆内接）。
      · 轮廓圆半径 = r（= 拖拽长度）；两个椭圆的长半轴也是 r（内接于轮廓圆 ✓）。
    `kind` 只用来拼 style（`fig:sphere` / 被遮挡段 `fig:sphereh`）。
    """
    cx, cy = float(cx), float(cy)
    r = max(0.0, float(r))
    ux, uy, _uz, vx, vy, _vz = _solid_proj_coeff(mode)
    awx = math.hypot(ux, uy)          # 单位"水平大圆"投影椭圆的半宽
    awy = math.hypot(vx, vy)          # ……的半高（正等测 = 4/3 与 √2/3 → 比值 4:√2）
    kk = (awy / awx) if awx > 1e-9 else 1.0      # 短半轴 / 长半轴
    n = _CIRCLE_SEGS
    out = []
    # ① 轮廓圆（实线、闭合）
    ring = [[cx + r * math.cos(2.0 * math.pi * i / n),
             cy + r * math.sin(2.0 * math.pi * i / n)] for i in range(n)]
    out.append({"op": "pen", "style": _FIG_PREFIX + kind, "points": ring + [list(ring[0])]})

    def _half(ax, ay, t0, t1, solid):
        """投影椭圆的半圈（参数 t 与纸面坐标：(cx + ax·cos t, cy + ay·sin t)）。"""
        m = max(2, n // 2)
        pts = [[cx + ax * math.cos(t0 + (t1 - t0) * i / m),
                cy + ay * math.sin(t0 + (t1 - t0) * i / m)] for i in range(m + 1)]
        return {"op": "pen",
                "style": _FIG_PREFIX + kind + ("" if solid else _SOLID_HIDDEN_SUFFIX),
                "points": pts}

    # ② 赤道（与 xOy 平行的大圆）：半轴 (r, r·kk)；v 向下 → sin t > 0 是下半圈
    out.append(_half(r, r * kk, 0.0, math.pi, True))              # 下半（实线）
    out.append(_half(r, r * kk, math.pi, 2.0 * math.pi, False))   # 上半（虚线）
    # ③ 长轴竖直的大圆：半轴 (r·kk, r)；cos t < 0 是左半圈
    out.append(_half(r * kk, r, 0.5 * math.pi, 1.5 * math.pi, True))     # 左半（实线）
    out.append(_half(r * kk, r, -0.5 * math.pi, 0.5 * math.pi, False))   # 右半（虚线）
    return out


def _solid_base_outline(kind, x0, y0, x1, y1, mode="oblique"):
    """立体图形**底面（第一阶段）**的轮廓 = 底面图形的**投影**（闭合点列）。

    用户细则：起点→终点是底面平面矩形的一条**对角线**（不画），矩形两组对边分别沿底面
    平面的 y 轴、x 轴 → 投影后是一个平行四边形（`_solid_base_rect_guide`）。
    底面图形则是：**与鼠标终点相邻的那条 y 边为底边**、顶点在**对边（另一条 y 边）的中点**
    —— 在底面平面里就是一个等腰三角形（底边 = 矩形的一条边、高 = 矩形的另一条边）。
    做法：把两个对角点的 `_solid_unproj` 当作底面平面矩形的两个对角 → 用对应平面图形的画法
    `_figure_points` 在底面平面里构造（所以"等腰三角"就是真等腰、吸附就是真等边）→ 逐点投影。
    **两种测画法（正等测 / 斜二测）共用这套：差别只在 `_solid_unproj` / `_solid_proj`。**
    """
    bs = _SOLID_BASE_KIND.get(kind, "tri")
    x0, y0, x1, y1 = float(x0), float(y0), float(x1), float(y1)
    if bs == "circle":
        # 圆柱 / 圆锥：起点 = 圆心、终点在投影后的圆上
        return _solid_cyl_ring(x0, y0, x1, y1, mode)
    if abs(y1 - y0) <= 1e-6:
        # 退化成一条水平线（刚按下）：给一个同点的退化三角形，避免空点列
        return [[x0, y0], [x1, y1], [x1, y1], [x0, y0]]
    p0 = _solid_unproj(x0, y0, mode)             # 按下点在底面平面上的坐标
    p1 = _solid_unproj(x1, y1, mode)             # 鼠标终点在底面平面上的坐标
    # **角色分配**（用户细则）：与**鼠标终点相邻**的那条 y 边是底边（不一定是靠下的那条），
    # 顶点在它的**对边**中点。`_figure_points` 把图形的"顶点"放在辅助矩形的**上边**
    # （合成坐标最小的一侧）→ 选一个符号 s 让"鼠标那一侧"成为辅助矩形的**下边**：
    # 合成竖直坐标取 b = s·x（底面平面 x），s 使 s·x_鼠标 是两者中较大的那个。
    s = 1.0 if p1[0] >= p0[0] else -1.0
    plane = _figure_points(bs, p0[1], s * p0[0], p1[1], s * p1[0])
    if not plane:
        return []
    out = []
    for p in plane:
        xp = s * float(p[1])                     # 底面平面 x（还原符号）
        yp = float(p[0])                         # 底面平面 y
        out.append(_solid_proj(xp, yp, 0.0, mode))
    return out


def _solid_base_pts(kind, x0, y0, x1, y1, mode="oblique"):
    """底面轮廓的**顶点**（去掉闭合点）。"""
    loop = _solid_base_outline(kind, x0, y0, x1, y1, mode)
    return [list(p) for p in loop[:-1]] if len(loop) > 1 else []


def _solid_base_centre(bpts):
    """底面顶点在纸面上的中心（= 顶点平均；仿射投影保重心）。"""
    if not bpts:
        return (0.0, 0.0)
    return (sum(float(p[0]) for p in bpts) / len(bpts),
            sum(float(p[1]) for p in bpts) / len(bpts))


def _solid_second_centre(bpts, dy, dz, mode="oblique"):
    """第二个面（顶面/底面）中心在**纸面上**的位置 = 底面中心 + (0, dy, dz) 的投影位移。"""
    cx, cy = _solid_base_centre(bpts)
    _ux, uy, uz, _vx, vy, vz = _solid_proj_coeff(mode)
    return (cx + uy * float(dy) + uz * float(dz),
            cy + vy * float(dy) + vz * float(dz))


def _solid_default_h(bpts, mode="oblique"):
    """默认升维高度 = 底面"外接尺度"（**底面平面里**顶点到中心的平均距离）× `_SOLID_DEFAULT_H_K`。

    用户要求：没完成第二阶段就切走 → 生成默认图形。注意要在**底面平面**里量尺寸
    （纸面上的底面是被压扁的投影，直接量会偏小；而且不同测画法的压扁比不同）；
    等边三角形底面时平均半径 = 边长/√3 → 默认高度 ≈ 0.92 × 边长，接近教科书里的比例。
    """
    if not bpts:
        return 0.0
    p3 = [_solid_unproj(p[0], p[1], mode) for p in bpts]
    cx = sum(v[0] for v in p3) / len(p3)
    cy = sum(v[1] for v in p3) / len(p3)
    r = sum(math.hypot(v[0] - cx, v[1] - cy) for v in p3) / len(p3)
    return max(_SOLID_MIN_H, r * _SOLID_DEFAULT_H_K)


# ---------- 形状引擎：正柱体（三棱柱 / 四棱柱 / 圆柱）----------
def _solid_engine_prism(base_pts, height, mode="oblique", dy=0.0):
    """**柱体通用形状引擎**：底面沿 (0, dy, height) 平移 → 第二个面（用户要求：升维时
    第二个面可在 yOz 方向自由移动：`dy` = 沿 y 轴平移、`height` = 沿 z 轴升降）。

    三棱柱用它（`_register_solid("triprism", ...)`）；四棱柱/…同理换个底面注册即可。
    ① 底面顶点：投影坐标按 `mode` 反算回 xOy 平面上的 3D 点（z = 0）；
    ② 第二个面 = 底面各点**沿 (0, dy, height) 平移**（`dy = 0` 即"沿 z 竖直拔高"的正柱体，
       与之前版本完全一样）；
    ③ 面表：底面、第二个面、毎条底边对应的一个侧面（凸多边形，每条棱恰好两个面）。
    棱的可见性分类、折线拼接、虚线都是通用绘制器 `_solid_strokes` 的事。
    """
    n = len(base_pts)
    if n < 3:
        return [], []
    bottom = [_solid_unproj(p[0], p[1], mode) for p in base_pts]
    top = [[v[0], v[1] + float(dy), float(height)] for v in bottom]
    verts3 = bottom + top
    faces = [list(range(n)), [n + i for i in range(n)]]
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, j, n + j, n + i])
    return verts3, faces


def _solid_engine_none(base_pts, height, mode="oblique", dy=0.0):
    """**占位形状引擎**：给"形状不适合用 顶点+面 描述"的立体图形用（目前只有球）。

    球的笔划完全由 `_solid_sphere_strokes` 生成（外壳 = 轮廓圆 + 两个椭圆），既没有底面
    也没有"面表" → 这里返回空表，通用绘制器 `_solid_strokes` 自然什么都不画（有它兜底，
    万一哪条路径误把球送进通用绘制器也不会画出乱几何）。
    """
    return [], []


def _solid_engine_pyramid(base_pts, height, mode="oblique", dy=0.0):
    """**锥体通用形状引擎**：底面（任意多边形 / 圆的采样点）+ **顶点**（= 底面中心 + (0, dy, height)）。

    与柱体引擎的唯一差别是"第二个面收成了一点"（用户要求：锥体升维时把底面连接到一点）。
    三棱锥 / 四棱锥**直接用这个引擎**：侧面是平面三角形 → 通用绘制器 `_solid_strokes` 的
    "面可见性"分类完全适用（底面朝向后方 → 底面那些背面侧的棱自动变虚线）。
    圆锥也登记它（底面是圆的采样多边形），但实际绘制走专用构造 `_solid_cone_strokes`
    （`_SOLID_CONE_KINDS`）—— 否则 128 条母线会被逐条当成棱画出来。
    面表 = 底面（一个面）+ 毎条底边对应的一个三角侧面（凸多面体，每条棱恰好属于两个面）。
    """
    n = len(base_pts)
    if n < 3:
        return [], []
    bottom = [_solid_unproj(p[0], p[1], mode) for p in base_pts]
    cxs = sum(v[0] for v in bottom) / n
    cys = sum(v[1] for v in bottom) / n
    verts3 = bottom + [[cxs, cys + float(dy), float(height)]]
    apex_i = n
    faces = [list(range(n))]
    for i in range(n):
        faces.append([i, (i + 1) % n, apex_i])
    return verts3, faces


_register_solid("triprism", "三棱柱", "tri", _solid_engine_prism)
_register_solid("quadprism", "四棱柱", "rect", _solid_engine_prism)
# 圆柱：底面画法 circle（起点 = 圆心、终点 = 投影后圆上一点），侧面光滑 → 走 `_solid_cyl_strokes`
# （引擎不被使用；登记正柱体引擎只是让注册表完整 —— 万一要几何近似时它就是 128 棱柱）
_register_solid("cylinder", "圆柱", "circle", _solid_engine_prism)
# 三棱锥：底面 tri（与三棱柱共用那套"对角线拖拽 → 等腰三角形底面"画法、带蓝色虚线辅助矩形），
# 升维时第二个面收成一个点（顶点）→ 与四棱锥/圆柱/圆锥共用同一套升维逻辑。
# ⚠️ 用户要求：**直三棱锥有正四面体吸附**（底面是正三角形时）。
_register_solid("tripyramid", "三棱锥", "tri", _solid_engine_pyramid)
def _solid_engine_frustum(base_pts, height, mode="oblique", dy=0.0, rho=None):
    """**台体（三棱台）形状引擎**：底面 + 顶面（= 底面按"顶点收缩比 ρ"缩小后的相似形）。

    用户要求（三棱台第三步）：拖体心手柄/任意位置拖拽 → 在鼠标终点生成一个**与底面平行**、
    截三棱锥的顶面（顶面必须在三棱锥范围内）→ 由此画出完整三棱台。
    构造：顶点 A = 底面中心 + (0, dy, height)（与三棱锥同一个顶点），顶面顶点
        T_i = A + ρ·(B_i − A)
    → ρ = 1 时 T = 底面（扁平退化）、ρ = 0 时收缩到顶点；`rho=None` 用默认
    `_SOLID_FRUSTUM_DEFAULT_RHO`（"没拖过就切走"的默认三棱台）。
    面表 = 底面 + 顶面 + 每条底边的梯形侧面（凸多面体，每条棱恰好属于两个面）。
    """
    n = len(base_pts)
    if n < 3:
        return [], []
    if rho is None:
        rho = _SOLID_FRUSTUM_DEFAULT_RHO
    rho = max(0.0, min(1.0, float(rho)))
    bottom = [_solid_unproj(p[0], p[1], mode) for p in base_pts]
    cxs = sum(v[0] for v in bottom) / n
    cys = sum(v[1] for v in bottom) / n
    apex = [cxs, cys + float(dy), float(height)]
    top = [[apex[0] + rho * (v[0] - apex[0]),
            apex[1] + rho * (v[1] - apex[1]),
            apex[2] + rho * (v[2] - apex[2])] for v in bottom]
    verts3 = bottom + top
    faces = [list(range(n)), [n + i for i in range(n)]]
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, j, n + j, n + i])
    return verts3, faces


def _solid_cfrustum_strokes(kind, ring, height, mode="oblique", dy=0.0,
                            rho=_SOLID_FRUSTUM_DEFAULT_RHO):
    """**圆台**的笔划：上下两个椭圆（顶面整圈实线 + 底面按前/后分段）+ 两条轮廓母线。

    用户要求（圆台）：底面画法与圆锥完全一致（起点 = 圆心、终点在投影后的圆上、可在菜单里选
    测画方式）；升维方式参考三棱台 —— 第二步升维出**圆锥**（顶点 = 底面中心 + (0, dy, height)），
    第三步用平行于底面的平面截圆锥 → 上下底是**相似的两个圆**（半径比 = ρ）、侧面是光滑圆锥面
    的一截。所以笔划与圆柱同族：
      · **哪个椭圆是"顶面"**：截口（半径 ρR）在锥体内 —— `height > 0` 时它在底面**上方**
        → 它整个外露（整圈实线）；`height ≤ 0` 时它在底面**下方**（锥体朝下）→ 底面圆盘
        整个朝上、底面圆环整圈实线，被遮挡的那半个在截口上（与圆柱"第二个面拖到下方"同理）。
      · **底面/截口椭圆的分段**：两条轮廓母线把"下面那个椭圆"分成两段 —— **外弧**（背离另一个
        椭圆中心的那段）可见（实线），另一段被侧面挡住（虚线）。判据与圆柱/圆锥同一套
        （取两段中点、比"沿另一圆心方向"的投影）。
      · **两条轮廓母线**：圆台的轮廓母线就是**同一个虚顶点圆锥**的轮廓母线（沿一条母线，曲面的
        法向不变 → 是轮廓母线的参数完全一样）→ 直接用 `_solid_cone_sil_idx` 算切点下标，
        母线 = 底面环上切点 → 截口环上对应点（每点 = 顶点 + ρ·(底面点 − 顶点)，投影是仿射的
        ✓ 所以直接在纸面上插值）。
      · **切线不存在**（虚顶点落在底面椭圆内部 → 轴几乎卧倒）：退化成"底面椭圆整圈实线 +
        截口整圈虚线"（截口这时在底面椭圆内部 → 被挡住）。
    `rho` = 截切比（ρ = 1 → 截口 = 底面；ρ = 0 → 退化成圆锥、截口缩成顶点）。
    """
    if len(ring) < 4:
        return []
    h = float(height)
    dy = float(dy)
    rho = max(0.0, min(1.0, float(rho)))
    ring = [[float(p[0]), float(p[1])] for p in ring]
    # 兼容两种入参（带 / 不带闭合点），与 `_solid_cyl_strokes` 同一约定
    if len(ring) > 3 and (abs(ring[0][0] - ring[-1][0]) < 1e-9
                          and abs(ring[0][1] - ring[-1][1]) < 1e-9):
        ring = ring[:-1]
    m = len(ring)
    if m < 3:
        return []
    _ux, uy, uz, _vx, vy, vz = _solid_proj_coeff(mode)
    off = [uy * dy + uz * h, vy * dy + vz * h]        # 虚顶点相对底面中心的纸面位移
    cx = sum(p[0] for p in ring) / m
    cy = sum(p[1] for p in ring) / m
    apex = [cx + off[0], cy + off[1]]
    # 截口（顶面）圆环：每点 = 顶点 + ρ·(底面点 − 顶点)（投影是仿射的 → 纸面上同样处理）
    cut = [[apex[0] + rho * (p[0] - apex[0]), apex[1] + rho * (p[1] - apex[1])] for p in ring]
    sil = _solid_cone_sil_idx(mode, ring, off, m)
    if sil is None:
        # 切线不存在 → 轮廓就是底面椭圆；截口在它内部（被挡住）
        return [{"op": "pen", "style": _FIG_PREFIX + kind,
                 "points": [list(p) for p in ring] + [list(ring[0])]},
                {"op": "pen", "style": _FIG_PREFIX + kind + _SOLID_HIDDEN_SUFFIX,
                 "points": [list(p) for p in cut] + [list(cut[0])]}]
    i0, i1 = sil
    arc_a = [(i0 + t) % m for t in range((i1 - i0) % m)]          # i0 → i1
    arc_b = [(i1 + t) % m for t in range((i0 - i1) % m)]          # i1 → i0
    # 上面那个椭圆 = 整圈露出的那个面（height > 0 → 截口在上；否则底面在上）。
    # 截口圆环的中心 = 顶点 + ρ·(底面中心 − 顶点) = 底面中心 + off·(1 − ρ)。
    c_cut = (cx + off[0] * (1.0 - rho), cy + off[1] * (1.0 - rho))
    if h > 0.0:
        lid, lid_c, bot, bot_c = cut, c_cut, ring, (cx, cy)
    else:
        lid, lid_c, bot, bot_c = ring, (cx, cy), cut, c_cut
    # 外弧 = 沿"上面那个椭圆的中心 → 下面那个椭圆的中心"方向更远的那一段（与圆柱同判据）
    _ox, _oy = bot_c[0] - lid_c[0], bot_c[1] - lid_c[1]
    _q = max(1, m // 4)
    _ma, _mb = (i0 + _q) % m, (i1 + _q) % m
    _da = (ring[_ma][0] - cx) * _ox + (ring[_ma][1] - cy) * _oy
    _db = (ring[_mb][0] - cx) * _ox + (ring[_mb][1] - cy) * _oy
    front_idx, back_idx = (arc_a, arc_b) if _da > _db else (arc_b, arc_a)

    def _arc(src, idxs):
        pts = [list(src[idxs[0]])]
        for k in idxs:
            pts.append(list(src[(k + 1) % m]))
        return pts

    out = [{"op": "pen", "style": _FIG_PREFIX + kind,
            "points": [list(p) for p in lid] + [list(lid[0])]}]                 # 上面整圈
    out.append({"op": "pen", "style": _FIG_PREFIX + kind, "points": _arc(bot, front_idx)})
    out.append({"op": "pen", "style": _FIG_PREFIX + kind + _SOLID_HIDDEN_SUFFIX,
                "points": _arc(bot, back_idx)})
    for i in (i0, i1):                      # 两条轮廓母线：底面环切点 → 截口环上对应点
        out.append({"op": "pen", "style": _FIG_PREFIX + kind,
                    "points": [list(ring[i]), list(cut[i])]})
    return out


def _solid_frustum_strokes(kind, base_pts, height, mode="oblique", dy=0.0,
                           rho=_SOLID_FRUSTUM_DEFAULT_RHO):
    """台体笔划：底面是**圆**的（圆台）走光滑侧面专用构造；多边形的（三/四棱台）走通用绘制器。

    ⚠️ 多边形台体不走 `_solid_strokes`：那里顶点/面表由注册的引擎（base, height, mode, dy）
    唯一确定，而台体还要一个"截切比 ρ" → 这里自己建 verts3/faces 再调
    `_solid_strokes_from_verts`。圆台则要有专门的"两个椭圆 + 两条切线"构造（同圆柱/圆锥）。
    """
    if kind in _SOLID_CFRUSTUM_KINDS:
        return _solid_cfrustum_strokes(kind, base_pts, height, mode, dy, rho)
    nb = _solid_base_n(kind)
    if nb <= 0 or len(base_pts) < nb:
        return []
    bp = [[float(p[0]), float(p[1])] for p in base_pts[:nb]]
    try:
        verts3, faces = _solid_engine_frustum(bp, float(height), mode, float(dy), float(rho))
    except Exception:
        plugin_logger.debug("台体形状引擎失败", exc_info=True)
        return []
    return _solid_strokes_from_verts(kind, verts3, faces, mode)


# 四棱锥：底面 rect（与四棱柱共用那套"对角线拖拽 → 正方形/矩形底面"画法），
# 升维时第二个面收成一个点（顶点）→ 与三棱锥/圆柱/圆锥共用同一套升维逻辑。
# ⚠️ 用户要求：**直四棱锥不做正六面体吸附**（但不影响"直四棱锥"提示）。
_register_solid("quadpyramid", "四棱锥", "rect", _solid_engine_pyramid)
# 圆锥：底面同样是 circle（起点 = 圆心、终点在投影后的圆上），侧面光滑 → 走 `_solid_cone_strokes`；
# 升维阶段"第二个面"退化成**一个点**（顶点 = 底面中心 + (0, dy, height)）→ 同样可以在 yOz
# 方向自由拖动、同样有"直圆锥"吸附（复用 `_solid_shift` 的那套）。
_register_solid("cone", "圆锥", "circle", _solid_engine_pyramid)
# 三棱台：底面 tri（与三棱锥同）；**比其它立体多一步**（画底面 → 升维出三棱锥 → 截顶面），
# 最终笔划走 `_solid_frustum_strokes`（带截切比 ρ），引擎只用于注册表完整性。
_register_solid("trifrustum", "三棱台", "tri", _solid_engine_frustum)
# 四棱台 / 圆台：底面画法与四棱锥 / 圆锥完全一致（rect / circle），升维方式与三棱台一致
# （三步：底面 → 升维出四棱锥 / 圆锥 → 截顶面）→ 同样走 `_solid_frustum_strokes`
# （带截切比 ρ）；圆台的侧面光滑，内部再由 `_solid_cfrustum_strokes` 接管。
_register_solid("quadfrustum", "四棱台", "rect", _solid_engine_frustum)
_register_solid("conefrustum", "圆台", "circle", _solid_engine_frustum)
# 球：**没有底面/升维**（一步成型），笔划走专用构造 `_solid_sphere_strokes`；
# 这里登记的引擎永远不会被调用（`base_kind` 留空 → 通用绘制器的"底面顶点数 = 0"分支直接返回空），
# 登记它只是让注册表完整（`_solid_of` / 菜单 / 分组 / 橡皮 这些机制都按注册表走）。
_register_solid("sphere", "球", "", _solid_engine_none)


def _figure_snap(kind, ox, oy, x, y):
    """等边吸附：把当前点吸到过起点 (ox,oy) 的"可等边直线"上。

    可等边直线 = 固定一角时，使辅助矩形长宽比达到 `_figure_aspect(kind)` 的另一角轨迹
    → 就是两条对角线方向（自左下到右上、自左上到右下，与用户描述一致）。
    返回 (px, py, guide)；guide = [x0,y0,x1,y1] 引导线（蓝色虚线用），未吸附时为 None。
    """
    dx, dy = x - ox, y - oy
    if abs(dx) < 1e-6 or abs(dy) < 1e-6:
        return x, y, None            # 贴着水平/竖直方向时不吸附，避免抽动
    ratio = _figure_aspect(kind)
    vx = ratio if dx > 0 else -ratio     # 保证方向与鼠标同象限
    vy = 1.0 if dy > 0 else -1.0
    ln = math.hypot(vx, vy)
    ux, uy = vx / ln, vy / ln
    t = dx * ux + dy * uy            # 投影长度（同象限 ⇒ 恒 >= 0）
    if t < 6.0:
        return x, y, None            # 离起点太近不吸附（否则开始拖动就跳）
    px, py = ox + ux * t, oy + uy * t
    if math.hypot(x - px, y - py) > _FIG_SNAP_PX:
        return x, y, None
    ext = 56.0                       # 引导线在吸附点后再延伸一段（"适当长度"）
    return px, py, [ox, oy, ox + ux * (t + ext), oy + uy * (t + ext)]


def _sector_rot(ux, uy, deg):
    """把单位向量按 deg 旋转（屏幕坐标 y 向下 → 正角度在视觉上是**顺时针**）。"""
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    return ux * ca - uy * sa, ux * sa + uy * ca


def _sector_angle(u1x, u1y, u2x, u2y):
    """从 u1 到 u2 的**带符号**夹角（度，正 = 屏幕上顺时针，范围 (-180, 180]）。

    屏幕坐标 y 向下：cross = u1x*u2y - u1y*u2x > 0 表示 u2 在 u1 的顺时针侧，
    与 `_sector_rot` 的正方向一致。
    """
    cross = u1x * u2y - u1y * u2x
    dot = u1x * u2x + u1y * u2y
    return math.degrees(math.atan2(cross, dot))


def _sector_figure_points(cx, cy, rx, ry, sweep_deg):
    """扇形存盘点列 = **[圆心]（头部点）+ 闭合轮廓**。

    轮廓 = [半径1端点, 弧…, 半径2端点, 圆心, 半径1端点]（首尾同点 → 闭合）；
    弧从半径1扫过 sweep_deg（带符号，正 = 屏幕上顺时针），|sweep_deg| 就是显示的圆心角。
    """
    cx, cy = float(cx), float(cy)
    rr = math.hypot(float(rx), float(ry))
    if rr <= 1e-9:
        return [[cx, cy]]
    ux, uy = float(rx) / rr, float(ry) / rr
    n = max(2, int(abs(sweep_deg) / 360.0 * _CIRCLE_SEGS) + 1)
    loop = [[cx + float(rx), cy + float(ry)]]
    for i in range(1, n + 1):
        vx, vy = _sector_rot(ux, uy, sweep_deg * i / float(n))
        loop.append([cx + vx * rr, cy + vy * rr])
    loop.append([cx, cy])                     # 回到圆心（第二条半径）
    loop.append(list(loop[0]))                # 再回到半径1端点（第一条半径 + 闭合）
    return [[cx, cy]] + loop


def _guide_circle(cx, cy, rr, segs=48):
    """整圆的蓝色虚线引导线（扁平分段 [x0,y0,x1,y1, ...]，供 QML 引导线 Canvas 画）。"""
    out = []
    for i in range(segs):
        a0 = 2.0 * math.pi * i / segs
        a1 = 2.0 * math.pi * (i + 1) / segs
        out += [cx + rr * math.cos(a0), cy + rr * math.sin(a0),
                cx + rr * math.cos(a1), cy + rr * math.sin(a1)]
    return out


def _pf_nearest_end_idx(pts, x, y):
    """多边形随心画：在画布任意位置按下时，从链的哪一端接着画。

    取离鼠标**起点**近的那一端；一样近时（用户规则）→ 取**靠右**的端点；
    x 也一样（竖直排列）→ 取**靠下**的端点。返回该端点在链里的下标（0 或 len-1）。
    """
    if not pts:
        return 0
    a, b = pts[0], pts[-1]
    da = math.hypot(float(x) - float(a[0]), float(y) - float(a[1]))
    db = math.hypot(float(x) - float(b[0]), float(y) - float(b[1]))
    if abs(da - db) > 1e-9:
        return 0 if da < db else len(pts) - 1
    if abs(float(a[0]) - float(b[0])) > 1e-9:
        return 0 if float(a[0]) > float(b[0]) else len(pts) - 1
    return 0 if float(a[1]) > float(b[1]) else len(pts) - 1


def _pf_edge_snap(prev, start, mx, my):
    """多边形随心画的"下一条边"：把鼠标方向按**内角**做 30°/45° 倍数吸附。

    内角 = 上一条边的反向射线（顶点 → 上一顶点）与"顶点 → 鼠标"的夹角（0°~180°）。
    吸附保持鼠标方向所在的旋转侧（与扇形同规则）、边长不变。
    返回 (端点 [x,y], 内角 度)；退化（鼠标就在顶点上）时端点 = 鼠标、角度 0。
    """
    dvx, dvy = prev[0] - start[0], prev[1] - start[1]     # 顶点 → 上一顶点（上一条边的反向）
    dl = math.hypot(dvx, dvy)
    mvx, mvy = float(mx) - start[0], float(my) - start[1]
    ml = math.hypot(mvx, mvy)
    if dl <= 1e-9 or ml <= 1e-9:
        return [float(mx), float(my)], 0.0
    ux, uy = mvx / ml, mvy / ml
    sa = _sector_angle(dvx / dl, dvy / dl, ux, uy)          # (-180, 180]
    ang = abs(sa)
    thr = min(15.0, math.degrees(math.asin(min(1.0, _FIG_SNAP_PX / max(ml, 1e-6)))))
    best = None
    for c in _PF_ANGLE_DEGS:
        d2 = abs(ang - c)
        if d2 <= thr and (best is None or d2 < best[0]):
            best = (d2, c)
    if best is None:
        return [float(mx), float(my)], ang
    sgn = 1.0 if sa >= 0.0 else -1.0                        # 正好 0° 算顺时针侧
    nx, ny = _sector_rot(dvx / dl, dvy / dl, sgn * best[1])
    return [start[0] + nx * ml, start[1] + ny * ml], best[1]


def _pf_bisect_pt(prev, start, end):
    """夹角**内角的角平分线**上、距顶点（start）**固定 28px** 的一点——内角提示胶囊的锚点。

    用户要求：角度文字提示框的**几何中心永远距角顶点 28px**、且在角平分线上 →
    这里给出这个点，QML 侧把胶囊**以该点为中心**摆放（居中于平分线、在内角一侧），
    于是胶囊中心与顶点的距离恒为 28px（不随角度/边长变化）。
    """
    v1x, v1y = float(prev[0]) - float(start[0]), float(prev[1]) - float(start[1])
    v2x, v2y = float(end[0]) - float(start[0]), float(end[1]) - float(start[1])
    l1, l2 = math.hypot(v1x, v1y), math.hypot(v2x, v2y)
    if l1 <= 1e-9 or l2 <= 1e-9:
        return [float(start[0]), float(start[1])]
    bx, by = v1x / l1 + v2x / l2, v1y / l1 + v2y / l2
    bl = math.hypot(bx, by)
    if bl <= 1e-6:
        # 两边几乎反向（夹角 ≈ 180°）→ 平分线退化，改用新边的法向兜底
        bx, by = -v2y / l2, v2x / l2
        bl = 1.0
    return [float(start[0]) + bx / bl * _PF_HINT_R,
            float(start[1]) + by / bl * _PF_HINT_R]


def _pf_interior_angle(prev, start, end):
    """顶点 start 处、两边（start→prev 与 start→end）的**内角**（度，0~180）。"""
    v1x, v1y = float(prev[0]) - float(start[0]), float(prev[1]) - float(start[1])
    v2x, v2y = float(end[0]) - float(start[0]), float(end[1]) - float(start[1])
    l1, l2 = math.hypot(v1x, v1y), math.hypot(v2x, v2y)
    if l1 <= 1e-9 or l2 <= 1e-9:
        return 0.0
    return abs(_sector_angle(v1x / l1, v1y / l1, v2x / l2, v2y / l2))


def _pf_ref_edges(pts):
    """多边形随心画的"已有的边"：链上相邻顶点 → [(下标 i, 单位方向 (ux,uy), 长度), ...]。"""
    out = []
    for i in range(len(pts) - 1):
        ax, ay = float(pts[i][0]), float(pts[i][1])
        bx, by = float(pts[i + 1][0]), float(pts[i + 1][1])
        ln = math.hypot(bx - ax, by - ay)
        if ln > 1e-9:
            out.append((i, (bx - ax) / ln, (by - ay) / ln, ln))
    return out


def _pf_match_para(refs, ux, uy, ln, skip=()):
    """在已有边里找与方向 (ux,uy) **平行**（含反向）且偏差在容许范围内的一条（取偏差最小）。

    容许角 = 12px 在该长度处的等效角（上限 15°），与角度吸附同一套阈值。
    `skip` = 不参与匹配的边下标集合（**相邻边**：共用端点的那一条，见 `_pf_snap_solution`）。
    返回 (偏差度, 下标, 单位方向 ex, ey) 或 None。
    """
    thr = min(15.0, math.degrees(math.asin(min(1.0, _FIG_SNAP_PX / max(ln, 1e-6)))))
    best = None
    for (i, ex, ey, _el) in refs:
        if i in skip:
            continue
        sd = _sector_angle(ux, uy, ex, ey)
        dev = min(abs(sd), 180.0 - abs(sd))
        if dev <= thr and (best is None or dev < best[0]):
            best = (dev, i, ex, ey)
    return best


def _pf_match_eq(refs, ln):
    """在已有边里找与长度 ln **等长**（差 ≤ 12px）的一条（取差最小）。

    返回 (长度差, 下标, 边长) 或 None。
    """
    best = None
    for (i, _ex, _ey, el) in refs:
        d = abs(ln - el)
        if d <= _FIG_SNAP_PX and (best is None or d < best[0]):
            best = (d, i, el)
    return best


def _pf_para_dir(ex, ey, ux, uy):
    """取与参考方向 (ux,uy) 同侧的那一支平行方向（±ex,±ey）。"""
    sd = _sector_angle(ux, uy, ex, ey)
    return (ex, ey) if abs(sd) <= 90.0 else (-ex, -ey)


def _pf_ray_hit_line(start, ux, uy, px, py, dx, dy):
    """射线 start + t*(ux,uy)（t ≥ 0）与过 (px,py)、方向 (dx,dy) 的直线的交点；平行/反向时 None。"""
    den = ux * dy - uy * dx
    if abs(den) < 1e-9:
        return None
    t = ((px - float(start[0])) * dy - (py - float(start[1])) * dx) / den
    if t < 0.0:
        return None
    return [float(start[0]) + ux * t, float(start[1]) + uy * t]


def _pf_gap_near_mouse(end, m):
    """缺口连线吸附的"手感"保护：终点离鼠标太远（> `_PF_GAP_SNAP_MAX`）就不吸附。

    用户反馈：鼠标在一个位置、终点却被吸到很远的地方（"差得十万八千里"）。
    根因是近乎平行的两条直线求交（见 `_PF_GAP_SNAP_MAX` 注释）→ 这种解必须丢掉，
    让终点就停在鼠标处（角度吸附的结果）。
    """
    return (math.hypot(float(end[0]) - float(m[0]), float(end[1]) - float(m[1]))
            <= _PF_GAP_SNAP_MAX)


def _pf_ray_hit_circle(start, ux, uy, cx, cy, rr, t_hint):
    """射线 start + t*(ux,uy)（t ≥ 0）与以 (cx,cy) 为心、半径 rr 的圆的交点（取离 t_hint 最近的解）。"""
    wx, wy = float(start[0]) - float(cx), float(start[1]) - float(cy)
    b = 2.0 * (wx * ux + wy * uy)
    c = wx * wx + wy * wy - rr * rr
    disc = b * b - 4.0 * c
    if disc < 0.0:
        return None
    sq = math.sqrt(disc)
    cands = [t for t in ((-b + sq) / 2.0, (-b - sq) / 2.0) if t >= 0.0]
    if not cands:
        return None
    t = min(cands, key=lambda v: abs(v - t_hint))
    return [float(start[0]) + ux * t, float(start[1]) + uy * t]


def _pf_snap_solution(pts, m, ang_end):
    """等长/平行吸附的最终解——**等长与角度吸附不互斥**（用户要求）。

    优先级：闭合 > 平行 > （等长 ∥ 角度）：
    · “平行”定的是**方向**，与角度吸附（也改方向）互斥 → 平行优先；
    · “等长”只改**长度** → 与角度吸附可以同时成立：方向取角度吸附后的方向、
      长度取参照边的长度（`ang_end` = 角度吸附后的端点，未吸附时就是鼠标点）。
    先试“正在画的那条边”（用户手下的那条），没命中再试“缺口连线”。

    ⚠️ **不做“与相邻边平行”**（用户要求移除）：正在画的边与相邻边（共用起点 `pts[-1]`
    的那一条）一旦平行，两条线就落在同一条直线上 → 视觉上“两线重合”（缺口连线同理：
    它与 `far = pts[0]` 处的第一条边共用端点）。所以平行匹配要跳过相邻边；
    近共线/近反向的拖拽仍由 30°/45° 倍数**角度吸附**兜底（不会重合）。
    返回 None 或 (端点, 平行参照边下标|None, 等长参照边下标|None, 是否缺口连线)。
    """
    if not pts or len(pts) < 2:
        return None
    start = pts[-1]
    far = pts[0]
    refs = _pf_ref_edges(pts)
    if not refs:
        return None
    ux = float(ang_end[0]) - float(start[0])
    uy = float(ang_end[1]) - float(start[1])
    ln_ang = math.hypot(ux, uy)
    if ln_ang <= 1e-9:
        return None
    ux, uy = ux / ln_ang, uy / ln_ang          # 角度吸附后的单位方向
    vx = float(m[0]) - float(start[0])
    vy = float(m[1]) - float(start[1])
    ln_raw = math.hypot(vx, vy)
    if ln_raw <= 1e-9:
        return None
    rux, ruy = vx / ln_raw, vy / ln_raw        # 鼠标原始方向（平行判定用它，不受角度吸附干扰）
    # ① 正在画的那条边（跳过后**相邻边**：平行就重合，用户要求移除）
    par = _pf_match_para(refs, rux, ruy, ln_raw, (refs[-1][0],))
    eq = _pf_match_eq(refs, ln_raw)
    if par is not None or eq is not None:
        px, py = ux, uy
        if par is not None:
            px, py = _pf_para_dir(par[2], par[3], rux, ruy)   # 平行：方向吸到严格平行
        ln_new = eq[2] if eq is not None else ln_raw          # 等长：长度吸到相等（可与角度共存）
        return ([float(start[0]) + px * ln_new, float(start[1]) + py * ln_new],
                None if par is None else par[1],
                None if eq is None else eq[1], False)
    # ② 缺口连线（far → 鼠标）：方向仍用角度吸附后的 u（等长/平行只挪鼠标点去满足缺口约束）
    gvx = float(m[0]) - float(far[0])
    gvy = float(m[1]) - float(far[1])
    gln = math.hypot(gvx, gvy)
    if gln > 1e-9:
        # 缺口连线与 far 处的第一条边共用端点 → 同样跳过（平行就重合）
        gpar = _pf_match_para(refs, gvx / gln, gvy / gln, gln, (refs[0][0],))
        if gpar is not None:
            end = _pf_ray_hit_line(start, ux, uy, far[0], far[1],
                                   gpar[2], gpar[3])
            # 两直线近共线时交点在很远的地方 → 丢弃（终点停在鼠标处，不"跳"）
            if end is not None and _pf_gap_near_mouse(end, m):
                return (end, gpar[1], None, True)
        geq = _pf_match_eq(refs, gln)
        if geq is not None:
            end = _pf_ray_hit_circle(start, ux, uy, far[0], far[1], geq[2], ln_raw)
            if end is not None and _pf_gap_near_mouse(end, m):
                return (end, None, geq[1], True)
    return None


def _pf_highlight_segs(pts, sol):
    """等长/平行命中的"这两边"（参照边 + 正在形成的那条线）→ 蓝色描边段列表。

    正在形成的那条线若是**缺口连线**，则不在这里描边（改由 QML 引导线层
    把它画成"笔迹虚线 + 外侧 2px 蓝"，见 `figureSnapBoldGuide`/`figureGapColor`）。
    """
    end, ip, ie, is_gap = sol[0], sol[1], sol[2], sol[3]
    out = []
    for idx in (ip, ie):
        if idx is None:
            continue
        a, b = pts[idx], pts[idx + 1]
        out += [float(a[0]), float(a[1]), float(b[0]), float(b[1])]
    if not is_gap:
        anchor = pts[-1]
        out += [float(anchor[0]), float(anchor[1]), float(end[0]), float(end[1])]
    return out


def _figure_ray_snap(ox, oy, x, y):
    """直角三角的"特殊角射线"吸附：把终点就近吸到过起点、与水平横线夹 30°/45°/60° 的射线上。

    这三条射线就是"30°/45°/60° 三角形线"（吸中 45° 那条 ⇒ 等腰直角三角形）。
    返回 (px, py, guide, snap_id)；未吸附时 guide=None、snap_id=""。
    guide = [x0,y0,x1,y1]（蓝色 1px 虚线用；吸附点后再延伸一段，与 `_figure_snap` 一致）。
    """
    dx, dy = float(x) - float(ox), float(y) - float(oy)
    if math.hypot(dx, dy) < 6.0:
        return x, y, None, ""       # 离起点太近不吸附（否则刚开始拖动就跳）
    sx = 1.0 if dx >= 0.0 else -1.0
    sy = 1.0 if dy >= 0.0 else -1.0
    best = None                      # (垂直距离, 投影长, ux, uy, snap_id)
    for deg, sid in _RTRI_RAYS:
        a = math.radians(deg)
        ux, uy = math.cos(a) * sx, math.sin(a) * sy
        t = dx * ux + dy * uy        # 投影长度（同象限 ⇒ >= 0）
        if t <= 0.0:
            continue
        perp = math.hypot(x - (ox + ux * t), y - (oy + uy * t))
        if best is None or perp < best[0]:
            best = (perp, t, ux, uy, sid)
    if best is None or best[0] > _FIG_SNAP_PX:
        return x, y, None, ""
    _, t, ux, uy, sid = best
    ext = 56.0
    px, py = ox + ux * t, oy + uy * t
    return px, py, [ox, oy, ox + ux * (t + ext), oy + uy * (t + ext)], sid


def _polyline_dense_track(points, max_gap=None):
    """形状线/图形的密集点列：(dense, knots)，**按直线段**采样（不走向心 CR 平滑）。

    图形是多边形，CR 会把角拉圆 —— 命中/橡皮判定要与"看得到的直边"一致，所以形状笔划
    一律用折线密集化。knots 语义与 _stroke_dense_track 一致（控制点索引，插值点 -1）。
    """
    pts, idx = _dedupe_indexed(points)
    if not pts:
        return [], []
    if _is_degenerate(pts):
        return [[pts[0][0], pts[0][1]]], [idx[0]]
    gap = float(max_gap) if max_gap else 4.0
    gap = max(1.0, gap)
    dense = [[pts[0][0], pts[0][1]]]
    knots = [idx[0]]
    for i in range(len(pts) - 1):
        ax, ay = pts[i][0], pts[i][1]
        bx, by = pts[i + 1][0], pts[i + 1][1]
        seg = math.hypot(bx - ax, by - ay)
        n = max(1, int(math.ceil(seg / gap)))
        for k in range(1, n + 1):
            tt = k / float(n)
            dense.append([ax + (bx - ax) * tt, ay + (by - ay) * tt])
            knots.append(idx[i + 1] if k == n else -1)
    return dense, knots


def _arrow_geometry(w):
    """箭头（V 形）的臂长与半角（rad）。绘制与 _shape_extent 共用，避免两处漂移。"""
    return max(6.0, w * 2.5), math.radians(30.0)


def _ray_step(w):
    """光线上相邻箭头的目标间距（越粗间距越大）；数量 = max(1, ⌊线长/间距⌋)。

    间距取 max(160, 48w)——在上一版 max(80, 24w) 基础上再翻倍，即**箭头密度再减半**。
    """
    return max(160.0, w * 48.0)


def _hatch_geometry(w):
    """剖面线杭齿的长度与间距。"""
    return max(4.0, w * 2.0), max(5.0, w * 2.5)


def _draw_arrow_head(painter, pen, tx, ty, ux, uy, hl, half):
    """在 (tx,ty) 处画一个指向 (ux,uy) 的 V 形箭头（两条斜交于直线的线段）。

    臂从尖端向后展开 hl，与主线夹角 half；尖端就在线上 → 不超出两端点。
    """
    nx, ny = -uy, ux
    bl = math.cos(half) * hl
    sl = math.sin(half) * hl
    painter.setPen(pen)
    for s in (1.0, -1.0):
        painter.drawLine(QPointF(tx, ty),
                         QPointF(tx - ux * bl + nx * sl * s,
                                 ty - uy * bl + ny * sl * s))


def _line_style_of(stroke):
    """取"形状线"的线型 id；手写笔/旧数据返回 ""（渲染与手写笔一致）。"""
    st = stroke.get("style") or ""
    return st if st in _LINE_SHAPES else ""


def _shape_extent(stroke):
    """形状线超出中心线的视觉半宽（px）；非形状线返回 0（调用方沿用原 width/2 等）。

    必须用于：预烘焙图层外扩、选择框、圈选网格包围盒、命中容差、圈选墨迹 ribbon ——
    否则波浪线（振幅）与双实线（平行偏移）的实际覆盖范围会被图层裁掉 / 选不中。
    """
    style = _line_style_of(stroke)
    w = float(stroke.get("width", 4.0))
    if _figure_of(stroke):
        return w * 0.5                            # 图形：墨迹就是轮廓，不外扩
    if not style:
        return 0.0
    if style in ("arrow", "dblarrow", "ray"):
        hl, half = _arrow_geometry(w)
        return math.sin(half) * hl + w * 0.5    # 箭头臂的法向分量 + 线半宽
    if style == "hatch":
        tl, _gap = _hatch_geometry(w)
        return math.sqrt(0.5) * tl + w * 0.5    # 梳齿 45° → 法向分量 = tl/√2
    if style == "wave":
        return w * 0.5 + w * 0.5                 # 正弦振幅 + 线半宽
    if style == "double":
        return max(1.2, w * 0.5) + max(1.0, w * 0.45) / 2.0   # 法向偏移 + 单线半宽
    return w * 0.5                               # 虚线/点虚线/点状虚线


def _pattern_axis(stroke, pts):
    """图案基准轴 → (x0, y0, x1, y1, off, rlen)。

    `stroke["pat"]` = **擦除前原线**的两端（橡皮切出的片段会带上它）：周期性图案
    （虚线的划/缺口、点状虚线的点、光线箭头、剖面线梳齿、波浪相位）一律按**原线**
    参数化，片段只画落在自己区间内的部分 → **擦除后图案位置不变**（用户要求）。
    没有 pat（或不是片段）时基准轴就是本笔两端（off = 0，与旧行为逐像素一致）。
    """
    p0, p1 = pts[0], pts[-1]
    ref = stroke.get("pat")
    if ref and len(ref) >= 4:
        x0, y0, x1, y1 = float(ref[0]), float(ref[1]), float(ref[2]), float(ref[3])
    else:
        x0, y0 = float(p0[0]), float(p0[1])
        x1, y1 = float(p1[0]), float(p1[1])
    rlen = math.hypot(x1 - x0, y1 - y0)
    if rlen <= 1e-9:
        return (x0, y0, x1, y1, 0.0,
                math.hypot(float(p1[0]) - float(p0[0]), float(p1[1]) - float(p0[1])))
    ux, uy = (x1 - x0) / rlen, (y1 - y0) / rlen
    off = (float(p0[0]) - x0) * ux + (float(p0[1]) - y0) * uy
    return x0, y0, x1, y1, off, rlen


def _dash_runs(total, pattern, phase):
    """把 [0,total] 上"相位为 phase"的周期图案切成若干墨段 [(s0,s1), ...]。

    pattern = [划, 空, (划, 空)]（已乘笔宽）；phase = 片段起点在图案上的相位（弧长）。
    相位为 0 时结果与 Qt 的 setDashPattern 完全一致（划从 0 开始），
    但多了一个"起始相位" → 擦除切出的片段能接回原位置。
    """
    per = float(sum(pattern))
    if per <= 1e-9 or total <= 0.0:
        return [(0.0, max(0.0, total))] if total > 0.0 else []
    out = []
    pos = -(phase % per)          # 从"包含片段起点的那个循环"的起点开始走
    guard = 0
    while pos < total and guard < 200000:
        guard += 1
        for k in range(0, len(pattern), 2):
            d = pattern[k]
            if pos + d > 0.0 and pos < total:
                out.append((max(0.0, pos), min(total, pos + d)))
            pos += d
            if k + 1 < len(pattern):
                pos += pattern[k + 1]
    return out


def _draw_dashed_path(painter, pen, pts, pattern, phase):
    """沿折线按"弧长 + 起始相位"画周期短划（替代 Qt 的 setDashPattern，以便带相位）。

    RoundCap 下每个短划渲染长度 = 名义长度 + 笔宽（与 Qt 的 dash 图案一致）→
    相位为 0 时与旧渲染逐像素等价。
    """
    lens = [0.0]
    for i in range(1, len(pts)):
        lens.append(lens[-1] + math.hypot(float(pts[i][0]) - float(pts[i - 1][0]),
                                          float(pts[i][1]) - float(pts[i - 1][1])))
    total = lens[-1]
    if total <= 1e-9:
        return

    def _at(s):
        s = max(0.0, min(total, s))
        for i in range(1, len(lens)):
            if s <= lens[i] + 1e-9:
                seg = lens[i] - lens[i - 1]
                f = 0.0 if seg <= 1e-9 else (s - lens[i - 1]) / seg
                return (float(pts[i - 1][0]) + (float(pts[i][0]) - float(pts[i - 1][0])) * f,
                        float(pts[i - 1][1]) + (float(pts[i][1]) - float(pts[i - 1][1])) * f)
        return (float(pts[-1][0]), float(pts[-1][1]))

    path = QPainterPath()
    for s0, s1 in _dash_runs(total, pattern, phase):
        if s1 - s0 <= 1e-9:
            continue
        a, b = _at(s0), _at(s1)
        path.moveTo(a[0], a[1])
        path.lineTo(b[0], b[1])
    painter.setPen(pen)
    painter.drawPath(path)


def _draw_shape_line(painter, stroke, light=True):
    """以均匀粗细绘制形状线（线型见 stroke["style"]）；非形状线返回 False 交回调用方。

    各种线型（均以笔宽 w 为基准，跟随"粗细/颜色"设置）：
    - line 直线：均匀粗细的实线（与手写笔的区别：不随速度变粗细）；
    - dash 虚线：dash 图案 [1.6w, 3.6w]。注意 **RoundCap 会把每段划两端各延长 w/2**，
      所以渲染出来是：划 ≈ 1.6w + w = 2.6w、间隔 ≈ 3.6w − w = 2.6w（划短、间隔宽，
      与旧参数 [4w, 2.5w] 渲染成划 5w / 间隔 1.5w 相比明显更稀疏）；
    - dashdot 点虚线：图案 [2.2w, 3.2w, 0.02w, 3.2w]——渲染后 ≈ 长划 3.2w、间隔 2.2w。
      中间那段取"极短长度"，配上 RoundCap 后总长 ≈ 0.02w + w ≈ w，就是一个**正圆**
      （Qt 的 dash 图案不接受 ≤0 的值，故用近似 0 的极小值；用 0.6w 会画成 1.6w 的胶囊）；
    - dot 点状虚线：**逐点画圆**（每个循环节一个直径=w 的圆，间距 2.2w）；
    - wave 波浪线：沿方向的正弦折线（振幅 0.5w、波长 4w）；
    - double 双实线：两条平行线（各 0.45w，法向偏移 0.5w）；
    - arrow 箭头：实线 + 终点一个 V 形箭头（两条斜交于直线的线段，起点无箭头）；
    - dblarrow 双向箭头：实线 + 首末两端各一个 V 形箭头（尖端朝外）；
    - ray 光线：实线 + 沿线**均匀分布**的 V 形箭头（都指向终点）。数量与线长正相关：
      n = max(1, ⌊L/间距⌋)（间距 max(160, 48w)），短线的 1 个箭头落在中点；
      第 i 个箭头放在第 i 段的中心 t=(i+0.5)/n → 均匀、对称、不贴两端。
    - hatch 剖面线：实线 + 一侧一组平行梳齿（像梳齿），每根与主线成 45°，
      并且**由起点看向终点时位于右侧**（屏幕坐标 y 向下：沿 u 前进的右侧 = n=(-uy,ux)）。
    - 图形（style="fig:tri|rect|pent|hex|oct|star|circle|ellipse"）：**沿 stroke["points"] 直接画折线**——
      完整图形就是闭合轮廓（首尾同点），被橡皮切断的碎片则是开链，同一段代码天然
      兼顾两种情况（无需按 bbox 反推多边形）。圆的首点是圆心、椭圆前两点是两焦点
      （不参与轮廓，见 `_fig_ink_pts`）：完整图形额外把圆心/两焦点画成小圆点，碎片不画。
    """
    fig = _figure_of(stroke)
    if fig:
        pts = stroke.get("points") or []
        if not pts:
            return True
        w = max(0.5, float(stroke.get("width", 4.0)))
        color = QColor(_pen_display_color(stroke.get("color", "mono"), light))
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.setBrush(Qt.NoBrush)
        pen = QPen(color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        ink = _fig_ink_pts(fig, pts)
        # 退化残段（橡皮切剩 1 个点、或两/多点重合）：画成一个小圆点 = 这一小节自身的墨。
        # 不要静默丢掉：用户要求"只有连 1 个像素都凑不出来才移除"（旧写法下这种残段
        # 在折线路径里画不出任何东西，看起来像"被烘没了"）。
        degenerate = bool(ink) and (len(ink) < 2 or all(
            abs(q[0] - ink[0][0]) < 0.01 and abs(q[1] - ink[0][1]) < 0.01 for q in ink))
        if degenerate:
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            rr = max(1.5, w * 0.5)
            painter.drawEllipse(QPointF(ink[0][0], ink[0][1]), rr, rr)
            painter.setBrush(Qt.NoBrush)
        elif _fig_dashed(fig):
            # 双曲线的渐近线 / 抛物线的准线 / 立体图形的被遮挡棱：**用与形状菜单"虚线"
            # 完全相同的 dash 图案**
            # （划 1.6w / 间隔 3.6w；RoundCap 两端各 +w/2 → 渲染 ≈ 划 2.6w / 间隔 2.6w）
            # 并带"图案相位"：橡皮切出的片段按原线接回原位（擦除后划/缺口位置不变）
            _z0x, _z0y, _z1x, _z1y, poff, _rl = _pattern_axis(stroke, ink)
            _draw_dashed_path(painter, pen, ink, [w * 1.6, w * 3.6], poff)
        else:
            painter.setPen(pen)
            painter.drawPath(_polyline_path(ink))
        head = _fig_head_pts(fig, pts)
        if head:
            # 头部点：圆心（圆）/ 两焦点（椭圆）——直径 = 笔宽，与轮廓同色同粗
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            rr = max(1.5, w * 0.5)
            for hp in head:
                painter.drawEllipse(QPointF(hp[0], hp[1]), rr, rr)
            painter.setBrush(Qt.NoBrush)
        return True
    style = _line_style_of(stroke)
    if not style:
        return False
    pts = stroke.get("points") or []
    w = max(0.5, float(stroke.get("width", 4.0)))
    color = QColor(_pen_display_color(stroke.get("color", "mono"), light))
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
    painter.setBrush(Qt.NoBrush)
    if not pts:
        return True
    x0, y0 = float(pts[0][0]), float(pts[0][1])
    x1, y1 = float(pts[-1][0]), float(pts[-1][1])
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 1e-6:
        # 退化（按下即松开/两点重合）：画一个圆点，与手写笔"点状笔迹"一致
        r = max(0.5, w / 2.0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(x0, y0), r, r)
        painter.setBrush(Qt.NoBrush)
        return True
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux          # 单位法向（波浪振幅 / 双线偏移）
    # 图案相位：`stroke["pat"]`（擦除前原线的两端）存在时，片段按原线接回原位；
    # 无 pat → poff = 0、rlen = 本笔长度（与旧渲染逐像素一致）。
    _pax, _pay, _pbx, _pby, poff, rlen = _pattern_axis(stroke, pts)
    if style == "wave":
        amp = w * 0.5
        wave_len = max(10.0, w * 4.0)
        n = max(2, int(math.ceil(length / max(1.5, wave_len / 16.0))))
        path = QPainterPath()
        path.moveTo(x0, y0)
        for i in range(1, n + 1):
            t = i / n
            off = math.sin(2.0 * math.pi * (poff + t * length) / wave_len) * amp
            path.lineTo(x0 + dx * t + nx * off, y0 + dy * t + ny * off)
        painter.setPen(QPen(color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(path)
    elif style == "double":
        lw = max(1.0, w * 0.45)
        off = max(1.2, w * 0.5)
        painter.setPen(QPen(color, lw, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for s in (-1.0, 1.0):
            path = QPainterPath()
            path.moveTo(x0 + nx * off * s, y0 + ny * off * s)
            path.lineTo(x1 + nx * off * s, y1 + ny * off * s)
            painter.drawPath(path)
    elif style == "dot":
        r = max(0.5, w / 2.0)
        spacing = max(2.0, w * 2.2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        # 点位置按基准轴参数化（绝对 s = k·spacing → 局部 t = s - poff）：
        # 擦除切出的片段继续落在原位，不会因起点变化而"点点位移"
        k = int(math.ceil(poff / spacing)) if poff > 0.0 else 0
        while True:
            t = k * spacing - poff
            if t > length + 1e-6:
                break
            if t >= -1e-6:
                tt = max(0.0, t)
                painter.drawEllipse(QPointF(x0 + ux * tt, y0 + uy * tt), r, r)
            k += 1
        painter.setBrush(Qt.NoBrush)
    elif style in ("arrow", "dblarrow", "ray"):
        pen = QPen(color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        hl, half = _arrow_geometry(w)
        # 箭头钉在**原线**的两端：片段不含该端（已被擦掉）就不画 → 擦除后箭头位置不变
        has_start = abs(poff) < 0.5
        has_end = abs(poff + length - rlen) < 0.5
        if style == "arrow":
            # 起点无箭头、终点有箭头（V 的尖端落在终点上）
            if has_end:
                _draw_arrow_head(painter, pen, x1, y1, ux, uy, hl, half)
        elif style == "dblarrow":
            if has_end:
                _draw_arrow_head(painter, pen, x1, y1, ux, uy, hl, half)
            if has_start:
                _draw_arrow_head(painter, pen, x0, y0, -ux, -uy, hl, half)
        else:
            # 光线：箭头在**原线**上均匀分布（数量由原线长度决定）→ 位置不因擦除而变；
            # 短则中点一个箭头；长则沿线多个（数量 ∝ 线长）
            n = max(1, int(rlen / _ray_step(w)))
            for i in range(n):
                t = (i + 0.5) * rlen / n - poff
                if -1e-6 <= t <= length + 1e-6:
                    tt = max(0.0, min(length, t))
                    _draw_arrow_head(painter, pen, x0 + ux * tt, y0 + uy * tt,
                                     ux, uy, hl, half)
    elif style == "hatch":
        pen = QPen(color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        tl, gap = _hatch_geometry(w)
        # 梳齿方向：与主线成 45° 且位于"由起点看向终点"的**右侧**。
        # 屏幕坐标 y 向下 → 前进方向 u 的右侧即 n=(-uy, ux)；梳齿方向取 (−u+n)/√2
        # （即向后方倾斜），与 u 的夹角正好 45°。
        hx, hy = (-ux + nx) / math.sqrt(2.0), (-uy + ny) / math.sqrt(2.0)
        # 梳齿位置按基准轴参数化（原线上每 gap 一根，居中半格起）→ 擦除后位置不变
        k = int(math.ceil(poff / gap - 0.5)) if poff > 0.0 else 0
        while True:
            s = (k + 0.5) * gap
            t = s - poff
            if t > length + 1e-6 or s > rlen + 1e-6:
                break
            if t >= -1e-6:
                tt = max(0.0, t)
                px, py = x0 + ux * tt, y0 + uy * tt
                painter.drawLine(QPointF(px, py), QPointF(px + hx * tl, py + hy * tl))
            k += 1
    else:
        pen = QPen(color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        if style == "line":
            painter.setPen(pen)
            painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
            return True
        if style == "dash":
            # 划短、间隔宽（RoundCap 两端各 +w/2 → 渲染 ≈ 划 2.6w / 间隔 2.6w）
            pattern = [w * 1.6, w * 3.6]
        else:                 # dashdot 点虚线：长划 + 正圆点
            # 第三段取极小值（≈0 长度）：RoundCap 两端各补 w/2 → 总长 ≈ w = 正圆
            pattern = [w * 2.2, w * 3.2, w * 0.02, w * 3.2]
        _draw_dashed_path(painter, pen, [(x0, y0), (x1, y1)], pattern, poff)
    return True


def _build_stroke_outline(stroke):
    """用 perfect-freehand 生成带粗细变化的笔触轮廓 QPainterPath（缓存到 stroke["_outline"]）。

    输入点可为 [x,y]（旧数据）或 [x,y,pressure]；pressure 由绘制时速度得出（慢→粗、快→细）。
    无库/退化/异常时返回 None，调用方回退固定粗细描边。活动笔划（无 id）不缓存。
    """
    if get_stroke is None:
        return None
    if _is_shape_stroke(stroke):
        return None   # 形状线/图形是均匀粗细（_draw_shape_line），不生成压力轮廓
    cached = stroke.get("_outline") if stroke.get("id") is not None else None
    if cached is not None:
        return cached
    pts = stroke.get("points") or []
    width = float(stroke.get("width", 4.0))
    if not pts or width <= 0:
        return None
    try:
        # 先把中心线按曲率自适应地向心 CR 密集化（含压力插值）：直线段 1 步、
        # 急弯段多步，曲线偏差始终 < _CURVE_TOL → 快速/稀疏笔迹既不折线也不打结，
        # 且点数比原来的固定 6 步更少（渲染更轻）。
        dense = _stroke_dense_points_p(pts)
        outline = get_stroke(dense, size=width, thinning=0.5,
                             streamline=0.5, smoothing=0.5,
                             simulate_pressure=False, last=True,
                             cap_start=True, cap_end=True)
    except Exception:
        return None
    if not outline:
        return None
    path = QPainterPath()
    # WindingFill 是唯一的"自交不镂空"保障（见下方性能说明），不要改成 OddEvenFill。
    path.setFillRule(Qt.WindingFill)
    path.moveTo(outline[0][0], outline[0][1])
    for x, y in outline[1:]:
        path.lineTo(x, y)
    path.closeSubpath()
    # 性能说明（实测，1536x960 画布）：
    #   旧实现在此处调用 path.simplified() 求并集，它是布尔运算，单帧最高 40ms，
    #   且结果元素数从 3752 膨胀到 10372、后续 drawPath 又慢一倍（合计 ~71ms/帧）。
    #   现改为完全依赖 WindingFill：对真机满屏涂鸦实测，simplified() 相对 WindingFill
    #   的"实心 vs 空白"差异为 **0 像素**（仅 11090/1474560 个边缘像素有 <16 的
    #   抗锯齿差），即它没有带来任何视觉收益，纯属开销，故移除。
    if stroke.get("id") is not None:
        stroke["_outline"] = path
    return path


def _draw_stroke(painter, stroke, light=True):
    """在给定 QPainter 上绘制一笔（pen 用颜色描边 / eraser 用 Clear 擦除）。

    注意：QPainter 的合成模式会跨调用持续，重放时橡皮（Clear）后的笔画必须
    显式回到 SourceOver，否则后续笔画会被错误地"擦除"。
    单点/重合点（点状笔迹）用 fillPath 填充闭合圆，避免被 pen 描边再放大
    一倍（addEllipse 半径=width/2 + width 描边 → 外径=width，直径=2*width）。
    pen 颜色为逻辑名（"mono"/"red"...），按 light（是否浅色模式）解析为显示 hex。
    非点状 pen：优先用 perfect-freehand 生成的粗细变化轮廓填充（无库时回退固定粗细描边）。
    """
    if not stroke or not stroke.get("points"):
        return
    points = stroke["points"]
    width = stroke.get("width", 4.0)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    is_dot = len(points) == 1 or (max(xs) - min(xs) < 0.01 and max(ys) - min(ys) < 0.01)
    if stroke["op"] == "eraser":
        path = _stroke_path(points, width)
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
        # 形状线（虚/点/波浪/双实线）与图形：均匀粗细，走独立渲染
        if _is_shape_stroke(stroke):
            _draw_shape_line(painter, stroke, light)
            return
        color = _pen_display_color(stroke.get("color", "mono"), light)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        if is_dot:
            painter.fillPath(_stroke_path(points, width), QColor(color))
        else:
            outline = _build_stroke_outline(stroke)
            if outline is not None:
                # 粗细变化笔触：填充 perfect-freehand 生成的轮廓
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(color))
                painter.drawPath(outline)
                # 关键：重置 brush，避免残留填充后续封闭路径
                painter.setBrush(Qt.NoBrush)
            else:
                # 回退（无库/异常）：固定粗细描边
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(color), width,
                                    Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.drawPath(_stroke_path(points, width))


# 选择工具的统一选中蓝（描边/填充/矩形边框/虚线共用，深浅色一致）
SELECTION_BLUE = "#1E88E5"

# 圈选空间网格索引的格宽（px）：笔迹按包围盒落入格，圈选只查圈选包围盒覆盖的格
# → 候选快速剪枝，避免对全部笔划逐一做精确判定；格宽越大越省内存、剪枝越粗。
_SEL_GRID_CELL = 256.0

# ---------- 撤销快照的内存控制 ----------
# 撤销栈要在内存里保留"被修改/删除/擦除笔划的旧点列"，是编辑会话里除预烘焙图层
# （见 _LAYER_BUDGET_BYTES）之外唯一会随操作次数持续增长的内存。
# ① 点列紧凑编码：list[list[float]] 每个点要 1 个 list 对象 + 2~3 个 float 对象
#    （实测 ≈190 字节/点）；改存扁平 array('d') 只要 8 字节/数值（≈24 字节/点）
#    → 快照内存约降到 1/8，且纯数据、不产生 Python 对象。
# ② 预算裁剪：仍按"条数 + 字节"双上限裁掉最老的记录，保证长时间会话有界。
_UNDO_MAX_OPS = 400                      # 单页撤销深度上限（条）
_UNDO_BUDGET_BYTES = 24 * 1024 * 1024    # 单页撤销快照内存上限（24MB）
# 紧凑点列里"该点没有压力"的占位值（见 _pack_points：同一笔划可能混合元数）
_NO_PRESSURE = float('nan')


def _pack_points(points):
    """把点列压成 (array('d') 扁平数值, 每点维度) —— 撤销快照专用的紧凑表示。

    3 = [x, y, pressure]（笔划），2 = [x, y]。渲染/几何代码仍用 list[list]（本表示
    只在撤销栈里存活），取值时经 _unpack_points 还原。
    """
    if not points:
        return (array.array('d'), 2)
    # 同一笔划里可能**部分点带压力、部分不带**：橡皮切分手写笔时，切边界点取
    # 密集点列（只有 x,y），区间内的控制点又是原始的 [x,y,pressure]。
    # 旧实现假定"要么全带、要么全不带"（按首点定 dim）→ 这种混合笔划会 IndexError，
    # 导致删除/拖动碎片时 _push_undo 抛异常（表现为"删除不立即生效"）。
    # 现在：dim 取"任一点带压力则为 3"，缺压力的点用 NaN 占位，还原时再变回二元。
    dim = 3 if any(len(p) > 2 for p in points) else 2
    a = array.array('d')
    if dim == 3:
        for p in points:
            a.append(float(p[0]))
            a.append(float(p[1]))
            a.append(float(p[2]) if len(p) > 2 else _NO_PRESSURE)
    else:
        for p in points:
            a.append(float(p[0]))
            a.append(float(p[1]))
    return (a, dim)


def _unpack_points(packed):
    """还原 _pack_points 的紧凑点列为 list[list[float]]（撤销回滚时用）。

    兼容普通 list[list] 输入（旧数据/未走 _pack_undo_op 的路径）→ 原样返回副本。
    """
    if not packed:
        return []
    if isinstance(packed, tuple) and len(packed) == 2 and isinstance(packed[0], array.array):
        a, dim = packed
        if dim == 3:
            out = []
            for i in range(0, len(a) - 2, 3):
                if math.isnan(a[i + 2]):      # NaN = 该点原本没有压力
                    out.append([a[i], a[i + 1]])
                else:
                    out.append([a[i], a[i + 1], a[i + 2]])
            return out
        return [[a[i], a[i + 1]] for i in range(0, len(a) - 1, 2)]
    try:
        return [list(p) for p in packed]
    except Exception:
        return []


def _packed_bytes(packed):
    """紧凑点列占用的字节数（预算估算用）；非紧凑表示返回 0（极少见）。"""
    if isinstance(packed, tuple) and packed and isinstance(packed[0], array.array):
        return len(packed[0]) * 8 + 64
    return 0


def _json_default(o):
    """json 序列化兜底：撤销快照里的紧凑点列 array('d') → 普通列表（写 ops 日志用）。"""
    if isinstance(o, array.array):
        return list(o)
    raise TypeError(f"不可序列化的类型: {type(o).__name__}")


def _pack_undo_op(op):
    """把撤销记录的"旧几何"点列换成紧凑编码（不改原对象，返回新 dict）。

    只处理三种携带完整点列的操作：modify（旧形状）/ delete（被删笔划）/ erase
    （被擦原笔划）；add / clone / clear 只存 id 或文件名，无需处理。
    顺带在 `_bytes` 里记下本条记录的内存估算，供 _trim_undo_stack 做预算裁剪。
    """
    t = op.get("type")
    size = 128
    if t == "modify":
        changes = []
        for ch in op.get("changes", []):
            old = ch.get("old") or {}
            new_old = dict(old)
            new_old["points"] = _pack_points(old.get("points") or [])
            size += 160 + _packed_bytes(new_old["points"])
            changes.append({"id": ch.get("id"), "old": new_old})
        out = {"type": "modify", "changes": changes}
    elif t == "delete":
        strokes = []
        for st in op.get("strokes", []):
            packed = _pack_points(st.get("points") or [])
            size += 192 + _packed_bytes(packed)
            strokes.append({"id": st.get("id"), "op": st.get("op", "pen"),
                            "color": st.get("color", ""),
                            "width": float(st.get("width", 4.0)),
                            "style": st.get("style", ""),
                            "pat": st.get("pat"),
                            "points": packed})
        out = {"type": "delete", "strokes": strokes}
    elif t == "erase":
        removed = []
        for it in op.get("removed", []):
            old = it.get("old") or {}
            packed = _pack_points(old.get("points") or [])
            size += 192 + _packed_bytes(packed)
            removed.append({"index": it.get("index", 0), "id": it.get("id", 0),
                            "old": {"op": old.get("op", "pen"),
                                    "color": old.get("color", ""),
                                    "width": float(old.get("width", 4.0)),
                                    "style": old.get("style", ""),
                                    "pat": old.get("pat"),
                                    "points": packed}})
        out = {"type": "erase", "removed": removed,
               "added_ids": list(op.get("added_ids", []))}
    else:
        out = dict(op)
    out["_bytes"] = size
    return out

# ---------- 笔划"预烘焙图层"（选择交互性能的核心）----------
# 实测（1536x960，一笔 216 点满屏涂鸦）：
#   墨迹 AA 填充 19.4ms + 选中蓝边（宽笔沿中心线 AA 描边）21.3ms = 40.7ms/帧；
#   而把这一笔预烘焙成小位图后，每帧只 drawImage 合成 → 0.27ms —— 差 150 倍。
# 根因：Qt 对"自交路径 + 抗锯齿"的填充极慢（同路径关 AA 只要 1.6ms），
# 而笔迹一旦自交（画圈、连笔、涂鸦、划改）就落入该慢路径；普通不自交手写笔画
# 本来只要 0.2ms（无需优化）。故：每笔按需烘焙"墨迹层"和"选中蓝边层"两个紧贴
# 包围盒的小 QImage 并缓存，重绘/拖动/圈选时只做位图合成。
# 内存预算：所有已烘焙图层之和超过该值后不再为新笔划烘焙（回退逐帧矢量绘制）。
_LAYER_BUDGET_BYTES = 96 * 1024 * 1024
# 图层相对笔划包围盒的外扩（px，覆盖抗锯齿边缘与蓝边）
_LAYER_PAD = 2.0
# 选中蓝边的宽度（px）：由墨迹图层做位图膨胀得到（见 _stroke_layer）。
_RIM_WIDTH = 2.0
# 膨胀方向（每 30° 一个，半径 = _RIM_WIDTH）：12 个方向足以让外扩在各方向上
# 都≈2px（最大方向偏差 cos15°≈3.5%），而位图 blit 比"沿中心线用宽笔做 AA 描边"
# 便宜约 7 倍（实测满屏涂鸦：10.9ms → 1.5ms）。
_RIM_DILATE = tuple(
    (_RIM_WIDTH * math.cos(math.pi * i / 6.0),
     _RIM_WIDTH * math.sin(math.pi * i / 6.0)) for i in range(12))
# 旋转/缩放预览的"矢量 / 图层"分界（毫秒预算）：预计矢量重绘耗时 ≤ 该值时走矢量
# （预览保持锐利，代价是每帧慢一些）；超过则走图层位图合成（每帧 ~0.3ms/笔，
# 但位图重采样会让缩放/旋转预览略软，松手提交时重绘为锐利矢量）。
# 平移路径恒走图层：整数偏移位图直拷，无重采样 → 既快又与矢量逐像素等价（实测 0 差异）。
# 每轮廓元素的实测成本（1536x960）：123 元素 0.2ms、3205 元素 40.7ms → ≈0.0127ms/元素。
_PREVIEW_VECTOR_MS_BUDGET = 25.0
_PREVIEW_VECTOR_MS_PER_ELEM = 0.0127


def _polyline_path(points):
    """按点列建**折线** QPainterPath（形状线/图形专用：不走向心 CR 平滑）。

    图形是多边形，_stroke_path 的 CR 会把折角拉圆 → 蓝边/圈选命中/缩略图都会跟
    "看到的折角"不一致，所以形状笔划一律用折线路径。
    """
    path = QPainterPath()
    if not points:
        return path
    path.moveTo(points[0][0], points[0][1])
    for p in points[1:]:
        path.lineTo(p[0], p[1])
    return path


def _draw_selection_outline(painter, stroke, light=True):
    """在被选中笔划下方画 2px 蓝色描边（先画宽 width+4 的蓝色，再画原笔划覆盖 → 边缘留 2px 蓝）。

    仅对 pen 笔划生效（橡皮是不可见的透明擦除区，不参与选择）。点状笔划先填
    半径+2 的蓝色圆，再被原笔划覆盖 → 外围 2px 蓝圈。
    """
    if not stroke or stroke.get("op") != "pen" or not stroke.get("points"):
        return
    points = _fig_ink_pts(_figure_of(stroke), stroke["points"])
    width = stroke.get("width", 4.0)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    is_dot = len(points) == 1 or (max(xs) - min(xs) < 0.01 and max(ys) - min(ys) < 0.01)
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
    if is_dot:
        x, y = points[0][0], points[0][1]
        r = max(0.5, width / 2.0) + 2.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(SELECTION_BLUE))
        painter.drawEllipse(QPointF(x, y), r, r)
        # 关键：重置 brush，否则残留蓝色会让后续 drawPath 填充封闭路径
        painter.setBrush(Qt.NoBrush)
    else:
        path = _polyline_path(points) if _is_shape_stroke(stroke) \
            else _stroke_path(points, width)
        painter.setBrush(Qt.NoBrush)
        # 形状线按线型的视觉半宽加宽蓝底（波浪/双实线比线宽更宽，否则蓝边被线本身盖住看不见）
        blue_w = max(width, 2.0 * _shape_extent(stroke)) + 4.0
        painter.setPen(QPen(QColor(SELECTION_BLUE), blue_w,
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
        """确保三张表存在（兼容旧文件：只有 meta/strokes，无 ops；老库无 seq/style 列则迁移）。"""
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
                " seq INTEGER,"
                " style TEXT,"
                " pat TEXT,"
                " grp TEXT,"
                " created_at TEXT)")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS ops("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " type TEXT NOT NULL,"
                " data TEXT NOT NULL,"
                " created_at TEXT)")
            # 迁移：老库无 seq 列 → 添加并回填 seq=id（保持现有绘制顺序）。
            # seq 用于橡皮切分后碎片笔划的顺序保持（渲染/重启按 COALESCE(seq,id) 排序）。
            # style：形状线（虚线/波浪线/双实线…）的线型 id；空=普通手写笔。
            cols = [r[1] for r in
                    self._conn.execute("PRAGMA table_info(strokes)").fetchall()]
            if "seq" not in cols:
                self._conn.execute("ALTER TABLE strokes ADD COLUMN seq INTEGER")
                self._conn.execute("UPDATE strokes SET seq = id WHERE seq IS NULL")
            if "style" not in cols:
                self._conn.execute("ALTER TABLE strokes ADD COLUMN style TEXT")
            # pat：图案基准轴（擦除前原线两端 JSON [x0,y0,x1,y1]）——周期性图案
            # （虚线划/缺口、光线箭头、剖面线梳齿…）按它参数化，擦除后位置不变。
            if "pat" not in cols:
                self._conn.execute("ALTER TABLE strokes ADD COLUMN pat TEXT")
            # grp：立体图形的"同一图形"分组 id——一个立体图形由多笔组成（可见棱 / 被遮挡棱），
            # 圈选时把它们当作**一个整体**（见 _select_inside_polygon）；被橡皮切分时清空
            # （用户要求：被分割成多部分后就不再当成整体）。
            if "grp" not in cols:
                self._conn.execute("ALTER TABLE strokes ADD COLUMN grp TEXT")
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
        # 文件名按毫秒时间戳；同一毫秒内连续新建（如快速连点"加页"）会撞名 → 两个页
        # 指向同一文件（惰性读取时内容互相污染），故撞名时追加序号。
        base = int(time.time() * 1000)
        path = os.path.join(self._data_dir, f"canvas_{base}.db")
        n = 1
        while os.path.exists(path) or os.path.exists(path + "-wal"):
            path = os.path.join(self._data_dir, f"canvas_{base}_{n}.db")
            n += 1
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

    def add_stroke(self, op, color, width, points, style="", pat=None, grp=""):
        """增量保存一笔（pen/eraser）；每笔即 commit，返回新行 id。

        style 为形状线线型 id（见 _LINE_SHAPES），空=普通手写笔。
        pat 为图案基准轴（擦除前原线两端）——橡皮切出的片段带它时图案位置不变。
        grp 为"同一立体图形"的分组 id（空 = 不分组）。
        """
        if self._conn is None:
            return None
        try:
            cur = self._conn.execute(
                "INSERT INTO strokes(op,color,width,points,style,pat,grp,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (op, color or "", float(width or 0.0),
                 json.dumps([[float(v) for v in p] for p in points]), style or "",
                 _pat_json(pat), grp or "",
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

    def insert_stroke(self, stroke_id, op, color, width, points, style="", pat=None,
                      grp=""):
        """以显式 id 插入一笔（撤销"擦除"时恢复被擦前的原始笔划，保持 id 顺序）。"""
        if self._conn is None:
            return
        try:
            self._conn.execute(
                "INSERT INTO strokes(id,op,color,width,points,style,pat,grp,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (int(stroke_id), op or "", color or "", float(width or 0.0),
                 json.dumps([[float(v) for v in p] for p in points]), style or "",
                 _pat_json(pat), grp or "",
                 time.strftime("%Y-%m-%d %H:%M:%S")))
            self._conn.commit()
        except Exception as e:
            plugin_logger.debug(f"显式插入笔迹失败: {e}")

    def set_all_seq(self, ordered_ids):
        """按传入的笔划 id 顺序批量写入绘制顺序号 seq（单个事务）。

        橡皮切分笔划后，用内存 _strokes 的当前顺序覆盖所有行，保证重启后
        load_all 仍按正确绘制顺序重放（碎片保持原位，不会跑到末尾）。
        """
        if self._conn is None:
            return
        try:
            self._conn.executemany("UPDATE strokes SET seq=? WHERE id=?",
                                   [(i, int(sid)) for i, sid in enumerate(ordered_ids)])
            self._conn.commit()
        except Exception as e:
            plugin_logger.debug(f"批量写顺序号失败: {e}")

    def update_stroke(self, stroke_id, op, color, width, points, style=None, pat=None,
                      grp=None):
        """整行更新一笔（撤销/移动/缩放/换色/换粗细等）。

        style=None 表示"不改线型"、pat=None 表示"不改图案基准轴"（绝大多数调用无需关心形状线）——
        这样换颜色/粗细、移动/缩放的提交都不会意外把虚线/波浪线降级、也不会丢失图案相位。
        pat 传空串/空列表表示"清除基准轴"（线端点手柄重定义整条线时用）。
        grp 同理：None = 不改；传空串 = 清除分组（橡皮切分立体图形时用）。
        """
        if self._conn is None:
            return
        try:
            pts = json.dumps([[float(v) for v in p] for p in points])
            sets = ["op=?", "color=?", "width=?", "points=?"]
            args = [op, color or "", float(width or 0.0), pts]
            if style is not None:
                sets.append("style=?")
                args.append(style or "")
            if pat is not None:
                sets.append("pat=?")
                args.append(_pat_json(pat))
            if grp is not None:
                sets.append("grp=?")
                args.append(grp or "")
            args.append(int(stroke_id))
            self._conn.execute("UPDATE strokes SET " + ",".join(sets) +
                               " WHERE id=?", args)
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
                (op_type, json.dumps(data, ensure_ascii=False, default=_json_default),
                 time.strftime("%Y-%m-%d %H:%M:%S")))
            self._conn.commit()
        except Exception as e:
            plugin_logger.debug(f"写操作日志失败: {e}")

    def load_all(self):
        """按绘制顺序读取全部笔迹（pen 与旧数据 eraser 交错，重放即还原画面），含 id。

        顺序优先取 seq（橡皮切分后保持原位），老库/普通追加行为 NULL 时回退 id 顺序。
        """
        if self._conn is None:
            return []
        try:
            rows = self._conn.execute(
                "SELECT id,op,color,width,points,style,pat,grp FROM strokes "
                "ORDER BY COALESCE(seq, id)").fetchall()
            out = []
            for sid, op, color, width, points, style, pat, grp in rows:
                try:
                    pts = json.loads(points)
                except Exception:
                    continue
                st = {"id": int(sid), "op": op, "color": color,
                      "width": float(width),
                      "style": style or "",
                      "points": [[float(v) for v in p] for p in pts]}
                if grp:
                    st["grp"] = str(grp)
                if pat:
                    try:
                        _pv = json.loads(pat)
                        if _pv and len(_pv) >= 4:
                            st["pat"] = [float(v) for v in _pv[:4]]
                    except Exception:
                        pass
                out.append(st)
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
    thumbsChanged = Signal()         # 页面缩略图版本变化（页内容完成性变化时刷新 QML 页面列表）
    pageAdded = Signal()             # 新增一页（QML 页面列表 ListModel 增量同步：append）
    pageRemoved = Signal(int)        # 删除一页（传删除前索引；QML 页面列表 ListModel 增量同步：remove）
    historyChanged = Signal()        # 历史页面（data 目录里未打开的页）列表变化（数据管理页监听）
    shapeFinished = Signal()         # 形状线一次绘制结束（接线处据此把工具回退到选择/笔/橡皮）
    solidProjChanged = Signal()      # 立体图形测画方式（正等测/斜二测）变化

    def __init__(self, parent=None):
        super().__init__(parent)
        self._strokes = []       # 全部向量笔迹（含橡皮），含 id
        self._image = QImage()   # 烘焙画布（逻辑像素尺寸，含选中描边）
        self._plain = None       # 无选中版画布缓存（圈选拖动只在其上叠加选中描边，免全量重绘）
        self._active = None      # 进行中笔迹 {op,color,width,points}
        self._last_pt = None
        self._last_t = None      # 上一采样时间戳（笔速→压力）
        self._last_pressure = 0.5
        # 无压感设备的"速度→粗细"映射状态（由 Plugin 接线/设置变化时传入）
        self._speed_map_enabled = True
        self._speed_map_sens = "standard"
        self._speed_ema = 0.0    # 移动速度 EMA（抗采样抖动）
        self._start_win = None   # 落笔起始速度采样窗口（前 N 段平均速度 → 起始粗细）
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
        self._sel_grid = None      # 圈选空间网格索引缓存（笔迹变化处置 None 失效）
        # 图形绘制状态（辅助矩形锚点/等边吸附引导线/吸附中的图形种类）与
        # 四角缩放的"等比例缩放直线"引导线（均在绘制/拖拽结束后清空）
        self._fig_origin = None
        self._fig_snap_guide = None
        self._fig_snap_kind = ""
        self._fig_align = ""           # 横平竖直吸附（"h"/"v"/""）→ 第二个提示"水平/竖直排列"
        self._scale_aspect_guide = []
        # 两阶段图形（椭圆 / 双曲线）的第二阶段状态：种类 / 两焦点 / 探针 / 正在拖的手柄序号
        # （0/1 = 焦点手柄；-1 = 自由探针）；_tf_probe_dragging 用于提示胶囊只在拖拽中显示
        self._tf_kind = ""
        self._tf_foci = None
        self._tf_probe = None
        self._tf_active = -1
        self._tf_probe_dragging = False
        # 扇形第二阶段：转角累计状态（越过 180° / 掠过第一条半径靠它保持单调）
        self._sector_last_raw = None      # 上一帧的带符号角（None = 本次拖拽还未采样）
        self._sector_acc = 0.0            # 未吸附的累计转角（度，带符号）
        self._sector_sweep_cur = _SECTOR_DEFAULT_DEG   # 当前几何/提示用的角度（已吸附）
        # 立体图形第二阶段（升维）：底面顶点（None = 不在该阶段）；种类记在 `_tf_kind`，
        # `_tf_foci` 填底面中心（复用两阶段机制），第二个面的位移由 `_solid_shift()` 按探针现算；
        # `_sf_proj` = 本次绘制采用的测画方式（"iso"/"oblique"，画底面时定下来后不再变）；
        # `_sf_snap` = 升维吸附状态（""/"right" 直柱体/直锥体 /"cube" 正六面体 /"tetra" 正四面体）
        self._sf_base = None
        self._sf_proj = _SOLID_PROJ_FIXED
        self._sf_snap = ""
        # **三棱台第三步**（拖"切顶面"）的状态：第二步松手时把顶点参数定在这里
        # （None = 还没定下顶点 → 仍在第二步；三棱台以外永远是 None）
        self._sf_apex_dy = None
        self._sf_apex_h = None
        # **坐标系**（形状菜单第 3 页）：`_ax_org` = 原点（纸面 = **鼠标起点**）；
        # `_ax_pts` = `_axis_xy_pts()` 的 3 点 [原点, 相邻角1, 相邻角2]（空间直角坐标系：
        # 第二步要据它重画 xy 两轴 + 算 z 轴吸附目标）；`_ax_ylen` = y 轴长（底面平面里量
        # = 3D 轴长，第二步 "z、y 轴等长" 的目标）。
        self._ax_org = None
        self._ax_pts = None
        self._ax_ylen = 0.0
        self._ax_kind = ""
        # 用户选择的测画方式（只对 `_SOLID_PROJ_CHOOSABLE` 里的立体图形生效；默认正等测）
        self._solid_proj_mode = _SOLID_PROJ_DEFAULT
        # 多边形随心画（fig:polfree）：多步绘制 —— `_pf_pts` = 已确认的顶点链（None = 不在该流程）；
        # `_pf_drawing` = 正在拖某条边；`_pf_probe` = 当前鼠标端；`_pf_end` = 吸附后的端点；
        # `_pf_angle` = 当前内角（提示「xx°」用）；`_pf_on_end` = 鼠标停在"另一端未连线端点"上
        self._pf_pts = None
        self._pf_drawing = False
        self._pf_probe = None
        self._pf_end = None
        self._pf_angle = 0.0
        self._pf_on_end = False
        self._pf_anchor = None      # 内角提示胶囊锚点（角平分线上的一点）
        self._pf_para_ref = None    # 平行吸附命中的参照边下标
        self._pf_eq_ref = None      # 等长吸附命中的参照边下标
        self._pf_hi = None          # 蓝色实线描边：命中的"这两边"
        self._pf_hi_gap = False     # 命中的是不是"缺口连线"（是则加粗那条蓝色虚线）
        # 拖拽组合修改快照（一次拖拽合并为一次撤销）
        self._modify_snapshot = None
        self._modify_base_rect = None   # 拖拽基准矩形（beginModify 快照；预览渲染/提交用）
        self._modify_preview = None     # 拖拽中的变换预览 (sx, sy, dx, dy)；None=无拖拽
        # 旋转拖拽状态（选中矩形中心为旋转中心；撤销复用 modify 快照）
        self._rot_center = None         # 旋转中心 (cx, cy)（beginRotate 快照）
        self._rot_angle = 0.0           # 旋转拖拽中的角度（顺时针正，预览/提交用）
        self._sel_rot_deg = 0.0         # 本选择累计旋转角（顺时针正；重选归 0，旋转后框保持姿态）
        self._rscale = None             # 旋转态缩放拖拽状态（beginRotatedScale 快照）
        self._line_handle = None        # 形状线端点手柄拖拽中 (stroke_id, which)
        # 坐标系轴端点拖拽的约束（用户要求）：(原点 x, 原点 y, 方向 x, 方向 y) ——
        # 箭头端只能沿**这根轴原来的方向**拖、且不能越过原点；旋转过的坐标系取旋转后的方向。
        self._axis_drag = None
        # 撤销栈（增量操作日志：add/clear/modify/delete）
        self._undo_stack = []
        # 多页结构：每页独立会话文件/笔迹/撤销栈（page=dict: file/strokes/undo）
        self._pages = []
        self._page_index = 0
        self._thumb_version = 0      # 页面缩略图版本（页内容完成性变化时递增，驱动 QML 刷新）
        self._thumb_cache = {}       # 页面缩略图缓存 {page_index: QImage}
        self._hist_thumb_cache = {}  # 历史页面缩略图缓存 {(文件名, mtime, 高): QImage}（关闭时清空）
        # 拖拽预览底图（无选中版 _plain 上挖掉选中墨迹）：一次拖拽只建一次，
        # 之后每帧只需 copy + blit 预烘焙图层 → 大量笔迹被选中也几乎零成本。
        self._preview_base = None

    # ---------- Python 侧接线 ----------
    def set_store(self, store):
        self._store = store

    def set_screen_info(self, w, h, dpr, mode):
        self._screen = (w, h, dpr or 1.0, mode)
        self._light = (mode == "whiteboard")   # 白板=浅色

    def set_pen_speed_map(self, enabled, sensitivity="standard"):
        """设置无压感设备的"速度→粗细"映射参数（Plugin 在接线/设置变化时调用）。

        enabled=True 时按速度模拟压力（慢→粗、快→细）；False 时固定粗细（pressure=0.5）。
        sensitivity ∈ {soft, standard, sensitive}，控制速度→粗细的响应曲线。
        """
        self._speed_map_enabled = bool(enabled)
        if sensitivity in _PEN_SPEED_MAP_CFG:
            self._speed_map_sens = sensitivity

    def set_canvas_size(self, w, h):
        """设置画布逻辑尺寸（屏幕宽高），由 Plugin 接线时传入。"""
        self._canvas_size = (max(1, int(w)), max(1, int(h)))

    def load_strokes(self, strokes):
        """载入既有笔迹并整幅重放渲染（进入特殊模式时恢复上次内容）。

        多页结构：优先按 data/pages.json 注册表恢复各页（每页独立会话文件/笔迹），
        否则默认单页（映射当前会话文件）。注册表缺失/损坏时退化为单页。
        """
        self._strokes = list(strokes or [])
        # 重新载入（进入特殊模式）→ 丢弃未完成的两阶段图形与进行中的笔划
        self._drop_focus_stage()
        self._active = None
        self._base = None
        self._last_pt = None
        self._pages = []
        self._page_index = 0
        reg = self._load_page_registry()
        if reg and reg.get("pages"):
            # 惰性：只读当前页的笔迹，其余页留 None，切过去时再从其会话文件读回
            # （避免启动时把每一页的全部点列都读进内存，也省掉多页逐一开库的开销）
            for f in reg["pages"]:
                self._pages.append({"file": f, "strokes": None, "undo": []})
            self._page_index = max(0, min(int(reg.get("current", 0) or 0),
                                          len(self._pages) - 1))
            cur = self._pages[self._page_index]["file"]
            if self._store:
                if cur and self._store.open_session(cur):
                    self._pages[self._page_index]["strokes"] = self._store.load_all()
                else:
                    # 当前页文件缺失（异常）→ 重建空白会话
                    w, h, dpr, mode = self._screen
                    self._store.new_session(w, h, dpr, mode)
                    self._pages[self._page_index]["file"] = self._store.current_file()
                    self._pages[self._page_index]["strokes"] = []
                    self._save_page_registry()
            if self._pages[self._page_index]["strokes"] is None:
                self._pages[self._page_index]["strokes"] = []
            self._strokes = self._pages[self._page_index]["strokes"]
            self._undo_stack = self._pages[self._page_index]["undo"]
        else:
            self._pages = [{"file": self._store.current_file() if self._store else None,
                            "strokes": self._strokes, "undo": self._undo_stack}]
            self._page_index = 0
        self._sel_grid = None   # 载入新笔迹 → 圈选索引失效
        self._plain = None      # 画布无选中版失效（下面 _render_all 会重建）
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

    def _bump_thumbs(self):
        """页内容完成性变化（笔迹完成/擦除/清屏/删除/撤销/切页等）→ 失效缩略图缓存并刷新。

        只丢掉**当前页**的缓存：其他页内容没变（且非当前页惰性持有笔迹，重绘要去
        数据库读回，代价高），而且 QML 在 thumbVersion 变化时会重取全部页缩略图。
        """
        self._thumb_version += 1
        self._thumb_cache.pop(self._page_index, None)
        self.thumbsChanged.emit()

    def page_thumb(self, index, max_h=140):
        """渲染指定页的缩略图（高 max_h px，宽按画板比例；轻量线描，性能好）。

        供 QML 页面列表菜单/数据管理页的 Image（image://whiteboard/thumb?page=N）使用；
        缓存到 _thumb_cache，页内容变化由 _bump_thumbs 失效。
        """
        index = int(index)
        if not (0 <= index < len(self._pages)):
            return QImage()
        cached = self._thumb_cache.get(index)
        if cached is not None:
            return cached
        # 当前页用活动笔迹 self._strokes（endStroke/擦除/移动/缩放/删除/撤销等操作实时修改的
        # 是它、不会立即写回 _pages）；非当前页惰性从会话文件读回（见 _page_strokes）——
        # 保证当前页缩略图即时反映最新内容，且多页时不必把所有页的点列都常驻内存。
        img = self._render_thumb(self._page_strokes(index), max_h)
        self._thumb_cache[index] = img
        return img

    def _render_thumb(self, strokes, max_h=140):
        """把一组笔迹画成缩略图（高 max_h px，宽按画板比例）——页面/历史页面共用。

        内容可适度失真（小图无需 perfect-freehand 精细轮廓，直接用 Catmull-Rom 路径 +
        固定宽度描边）。
        """
        max_h = int(max_h)
        cw, ch = self._canvas_size
        if cw <= 0 or ch <= 0:
            cw, ch = 1, 1
        tw = max(1, int(round(max_h * cw / ch)))
        img = QImage(tw, max_h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        if strokes:
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            p.scale(tw / cw, max_h / ch)
            # 缩略图上笔迹至少 ~2px 可见：4K 画布的细笔迹（4px）缩小 ~15 倍后不足 1px，
            # 几乎不可见；允许适度失真把笔宽抬到缩略图上可辨的粗细。
            min_w = max(2.0 / (tw / cw), 1.0)
            for s in strokes:
                pts = s.get("points") or []
                if not pts:
                    continue
                width = max(float(s.get("width", 4.0)), min_w)
                if s.get("op") == "eraser":
                    path = _stroke_path(pts, width)
                    p.setCompositionMode(QPainter.CompositionMode_Clear)
                    p.setBrush(Qt.NoBrush)
                    p.setPen(QPen(QColor(Qt.transparent), width,
                                  Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                    p.drawPath(path)
                else:
                    color = _pen_display_color(s.get("color", "mono"), self._light)
                    p.setCompositionMode(QPainter.CompositionMode_SourceOver)
                    p.setBrush(Qt.NoBrush)
                    p.setPen(QPen(QColor(color), width,
                                  Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                    # 形状线/图形：折线（否则多边形的折角在缩略图里会被 CR 拉圆）
                    p.drawPath(_polyline_path(_fig_ink_pts(_figure_of(s), pts))
                               if _is_shape_stroke(s)
                               else _stroke_path(pts, width))
            p.end()
        return img

    def history_thumb(self, name, max_h=140):
        """历史页面（data 目录里未打开的 canvas_*.db）的缩略图（数据管理页用）。

        缓存 key = (文件名, 修改时间) —— 文件变了时间就变，自动失效。
        """
        name = os.path.basename(str(name or ""))
        if not name or not self._store:
            return QImage()
        path = os.path.join(self._store.data_dir, name)
        try:
            mtime = float(os.path.getmtime(path))
        except Exception:
            return QImage()
        key = (name, mtime, float(max_h))
        cached = self._hist_thumb_cache.get(key)
        if cached is not None:
            return cached
        img = self._render_thumb(self._load_page_strokes_readonly(name), max_h)
        self._hist_thumb_cache[key] = img
        if len(self._hist_thumb_cache) > 48:      # 别无限积累（数据管理页关掉时还会清空）
            self._hist_thumb_cache.clear()
            self._hist_thumb_cache[key] = img
        return img

    def _page_strokes(self, index):
        """取指定页的向量笔迹：当前页用活动列表；非当前页按需惰性加载。

        非当前页为省内存会把 strokes 置 None（见 _release_other_pages），此时从它
        自己的会话文件只读读回——多页时不必把所有页的点列常驻内存。
        """
        if index == self._page_index:
            return self._strokes
        if not (0 <= index < len(self._pages)):
            return []
        page = self._pages[index]
        st = page.get("strokes")
        if st is None:
            st = self._load_page_strokes_readonly(page.get("file"))
        return st

    def _load_page_strokes_readonly(self, name):
        """只读打开指定会话文件并读出全部笔迹（非当前页缩略图用）。

        **不能**走 self._store.open_session——那会关掉当前会话的连接、破坏当前页状态。
        """
        if not name or not self._store:
            return []
        path = os.path.join(self._store.data_dir, name)
        if not os.path.exists(path):
            return []
        conn = None
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            rows = conn.execute(
                "SELECT id,op,color,width,points,style,pat FROM strokes "
                "ORDER BY COALESCE(seq, id)").fetchall()
            out = []
            for sid, op, color, width, points, style, pat in rows:
                try:
                    pts = json.loads(points)
                except Exception:
                    continue
                st = {"id": int(sid), "op": op, "color": color,
                      "width": float(width), "style": style or "",
                      "points": [[float(v) for v in p] for p in pts]}
                if pat:
                    try:
                        _pv = json.loads(pat)
                        if _pv and len(_pv) >= 4:
                            st["pat"] = [float(v) for v in _pv[:4]]
                    except Exception:
                        pass
                out.append(st)
            return out
        except Exception as e:
            plugin_logger.debug(f"只读读取页笔迹失败: {name}: {e}")
            return []
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _release_other_pages(self):
        """释放非当前页常驻的向量笔迹（切页/加页/删页后调用）。

        各页笔迹都已增量落盘（每笔完成即写库、橡皮/移动/删除/撤销也同步写库），
        离开页时把内存点列置 None、切回时从会话文件读回 → 多页不再把每一页的
        全部点列都常驻内存。仅在有存储且该页已有会话文件时生效（无库降级模式
        必须保留内存副本）。
        """
        if not self._store:
            return
        for i, page in enumerate(self._pages):
            if i == self._page_index:
                continue
            if page.get("strokes") is not None and page.get("file"):
                page["strokes"] = None

    def _prune_sel_layers(self):
        """回收"已非选中"笔划的选中外观图层（_layer_sel）。

        没有这一步时，_layer_sel 会为"曾经被选中过"的每一笔一直留在内存里（反复
        圈选/单击选择后不断累积，单张可达数百 KB~数 MB），是编辑会话里最主要的
        无谓内存增长。墨迹图层 _layer_ink 保留（重绘/拖动都要用，与选择无关）。
        """
        sel = set(self._selection or [])
        for s in self._strokes:
            if s.get("_layer_sel") is not None and s.get("id") not in sel:
                s.pop("_layer_sel", None)

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
        # 等长/平行命中的"这两边"先铺蓝色宽底，随后墨色盖回中间 → 只留两侧各 2px 蓝
        self._draw_pf_highlight(p)
        _draw_stroke(p, self._active, self._light)
        # 两阶段图形（双曲线）第二阶段：还要预览另外 3 笔（另一支 + 两条渐近线）
        for extra in self._stage_preview_strokes():
            _draw_stroke(p, extra, self._light)
        p.end()

    def _draw_pf_highlight(self, painter):
        """多边形随心画：等长/平行命中的"这两边"用**蓝色 2px 描边**标记。

        `_pf_hi` = 命中段（参照边 + 正在画的那条边）；画法与选中描边同一套：先按
        "线宽 + 4" 画蓝色（RoundCap/RoundJoin），接着 `_draw_stroke` 把**墨色盖回中间** →
        两侧各留 2px 蓝，**线条本身的颜色不变**（用户要求：不是把线改成蓝色）。
        命中的若是"缺口连线"（虚线）则不在这里描边——改由 QML 引导线层把它画成
        "笔迹颜色/粗细的虚线 + 外侧 2px 蓝"（`figureSnapBoldGuide`/`figureGapColor`）。
        """
        if not self._pf_hi or self._active is None:
            return
        w = max(1.0, float(self._active.get("width", 4.0)))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(SELECTION_BLUE), w + 4.0,
                            Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        segs = self._pf_hi
        for i in range(0, len(segs) - 3, 4):
            painter.drawLine(QPointF(float(segs[i]), float(segs[i + 1])),
                             QPointF(float(segs[i + 2]), float(segs[i + 3])))

    # ---------- 预烘焙图层（选择/重绘性能核心，详见 _LAYER_BUDGET_BYTES 注释）----------
    def _invalidate_stroke_cache(self, stroke):
        """笔划几何/样式变化 → 失效其全部派生缓存（轮廓 / 墨迹路径 / 预烘焙图层）。"""
        stroke.pop("_outline", None)
        stroke.pop("_ink_path", None)
        stroke.pop("_layer_ink", None)
        stroke.pop("_layer_sel", None)
        stroke.pop("_layer_res", None)   # 重烘焙后栅格位置=几何位置，亚像素残差归零

    def _invalidate_layers(self, strokes=None):
        """仅失效预烘焙图层（显示色变化：图层颜色在烘焙时已固化）。

        与 _invalidate_stroke_cache 的区别：轮廓（_outline）与颜色无关，模式切换时
        无需重算（重算一次 freehand 轮廓约 5~8ms），只需丢掉颜色固化的图层。
        """
        for s in (self._strokes if strokes is None else strokes):
            s.pop("_layer_ink", None)
            s.pop("_layer_sel", None)
            s.pop("_layer_res", None)

    @staticmethod
    def _translate_stroke_paths(stroke, dx, dy):
        """把笔划的缓存路径（_outline / _ink_path）按精确位移平移，保持与几何严格一致。

        平移提交走"图层搬运"时几何已变、但形状未变 → 路径只需平移、无需重算。
        若不同步平移：圈选命中会按**旧位置**判定（表现为"选不中"），而后续任何
        "只失效图层"的重烘焙（切换白板/熄屏、换颜色）会照旧路径绘制 → 笔迹跳回原处。
        """
        if dx == 0.0 and dy == 0.0:
            return
        t = QTransform()
        t.translate(dx, dy)
        for key in ("_outline", "_ink_path"):
            p = stroke.get(key)
            if p is None:
                continue
            try:
                stroke[key] = t.map(p)
            except Exception:
                stroke.pop(key, None)   # 映射失败 → 丢弃缓存，必要时重算

    def _shift_stroke_layers(self, strokes, dx, dy):
        """平移提交快速路径：整体搬移已烘焙图层的原点，彻底免掉重烘焙。

        实测搬运一个图层原点 0.00ms，而重烘焙一笔满屏自交涂鸦要 ~27ms（建轮廓 4.9
        + 墨迹 AA 填充 9.8 + 蓝边 10.9）——平移不改变笔迹形状，位图内容可原样复用。

        **必须取整搬运**（整数像素平移 = 位图直拷，无重采样），且整批笔划共用同一个
        整数位移，否则它们之间的相对位置会被亚像素取整破坏。

        取整规则（关键，写错过一次导致笔迹漂移）：设 r = 栅格位置 − 几何位置（残差），
        则栅格"还需移动" e = d − r，位移取 `ix = round(e)`，新残差 `r' = ix − e ∈ [-0.5, 0.5]`。
        注意是 `round(d − r)` 而不是 `round(d + r)`：后者会让实际残差变成 r + round(d+r) − d
        并逐次累加（笔迹越拖越偏，而蓝框仍跟着几何走）。

        要求整批笔划的残差一致（通常成立：同一次拖拽过的笔划残差必然相同）——不一致时
        返回 False，让调用方回退完整重烘焙（同时把残差统一归零）。
        """
        if not strokes:
            return False
        rx, ry = strokes[0].get("_layer_res", (0.0, 0.0))
        for s in strokes:
            if s.get("_layer_ink") is None:
                return False
            r = s.get("_layer_res", (0.0, 0.0))
            if abs(r[0] - rx) > 1e-6 or abs(r[1] - ry) > 1e-6:
                return False   # 残差不同（来自不同批次的拖拽）→ 交回完整重烘焙统一
        ix = int(round(dx - rx))
        iy = int(round(dy - ry))
        nres = (float(ix) - (dx - rx), float(iy) - (dy - ry))
        for s in strokes:
            for key in ("_layer_ink", "_layer_sel"):
                pair = s.get(key)
                if pair is not None:
                    s[key] = (pair[0], pair[1] + ix, pair[2] + iy)
            s["_layer_res"] = nres
            self._translate_stroke_paths(s, dx, dy)
        return True

    def _layer_total_bytes(self):
        """当前页已烘焙图层占用字节数（内存预算用；按需扫描，笔划数很少开销可忽略）。"""
        total = 0
        for s in self._strokes:
            for key in ("_layer_ink", "_layer_sel"):
                pair = s.get(key)
                if pair is not None:
                    img = pair[0]
                    total += img.width() * img.height() * 4
        return total

    def _stroke_layer(self, stroke, kind):
        """取/建笔划的预烘焙图层，返回 (QImage, ox, oy)（ox/oy = 图层左上角的画布坐标）。

        kind="ink"：墨迹；kind="sel"：选中外观（蓝边 + 墨迹合成在一起）。
        合成成单张"选中图层"是为了**减少每帧合成次数**：拖动/旋转/缩放时每笔只需
        1 次 drawImage（而不是蓝边、墨迹各一次），实测 12 次平滑 blit → 6 次约省一半。

        蓝边不再是"沿中心线用宽笔做一次 AA 描边"（那是重烘焙里最贵的一步，实测
        满屏涂鸦 10.9ms），而是**把墨迹图层做 12 方向位图膨胀 2px**（1.5ms，快约 7 倍）：
        先叠出外扩 2px 的形状，SourceIn 染成蓝色，再把墨迹盖回中间。
        几何上与原来略有差别：原做法是"中心线 ± (width/2+2)"的等宽 ribbon 挖掉墨迹，
        蓝边在墨迹最粗处只有 1px、最细处可达 3px；膨胀法则恒为均匀 2px（更贴合
        "只留 2px 蓝边"的意图）。

        活动笔划（无 id，逐帧变化）、旧数据蒙层橡皮（需 Clear 合成，无法独立烘焙）、
        超出内存预算时返回 None，调用方回退逐帧矢量绘制。
        """
        if stroke.get("id") is None or stroke.get("op") != "pen":
            return None
        key = "_layer_ink" if kind == "ink" else "_layer_sel"
        cached = stroke.get(key)
        if cached is not None:
            return cached
        pts = stroke.get("points") or []
        width = float(stroke.get("width", 4.0))
        if not pts or width <= 0:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        # 外扩：墨迹半径上界 = width*0.75（freehand radius = size*(0.25+0.5p)，p<=1）；
        # 形状线（波浪/双实线）比线宽更宽 → 取线型半宽；再加抗锯齿余量，选中图层再外扩蓝边宽度
        half = max(width * 0.75, _shape_extent(stroke)) + _LAYER_PAD \
            + (_RIM_WIDTH if kind == "sel" else 0.0)
        ox = int(math.floor(min(xs) - half))
        oy = int(math.floor(min(ys) - half))
        lw = max(1, int(math.ceil(max(xs) + half)) - ox)
        lh = max(1, int(math.ceil(max(ys) + half)) - oy)
        if self._layer_total_bytes() + lw * lh * 4 > _LAYER_BUDGET_BYTES:
            return None
        img = QImage(lw, lh, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        if kind == "sel":
            ink = self._stroke_layer(stroke, "ink")
            if ink is None:
                # 无墨迹图层（超预算等）→ 回退矢量：先蓝边再墨迹盖回
                p.translate(-ox, -oy)
                _draw_selection_outline(p, stroke, self._light)
                _draw_stroke(p, stroke, self._light)
            else:
                ix = float(ink[1] - ox)   # 墨迹层在本图层坐标系内的偏移（整数）
                iy = float(ink[2] - oy)
                for ddx, ddy in _RIM_DILATE:
                    p.drawImage(QPointF(ix + ddx, iy + ddy), ink[0])
                p.setCompositionMode(QPainter.CompositionMode_SourceIn)
                p.fillRect(img.rect(), QColor(SELECTION_BLUE))
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)
                p.drawImage(QPointF(ix, iy), ink[0])
        else:
            p.translate(-ox, -oy)
            _draw_stroke(p, stroke, self._light)
        p.end()
        stroke[key] = (img, ox, oy)
        return stroke[key]

    def _blit_stroke(self, painter, stroke, selected, ox=0.0, oy=0.0):
        """把一笔合成进画布：优先 blit 预烘焙图层，无图层时回退逐帧矢量绘制。

        选中笔划用"蓝边+墨迹"合成好的单张图层 → 每帧每笔 1 次 drawImage。
        ox/oy 为额外平移量（拖拽预览用）。调用方须保证：纯平移时把偏移取整，
        这样 drawImage 落在整数像素上，Qt 走位图直拷路径（无重采样、无模糊）。
        """
        kind = "sel" if selected else "ink"
        lay = self._stroke_layer(stroke, kind)
        if lay is not None:
            painter.drawImage(QPointF(lay[1] + ox, lay[2] + oy), lay[0])
            return
        if selected:
            _draw_selection_outline(painter, stroke, self._light)
        _draw_stroke(painter, stroke, self._light)

    def _selected_vector_cost(self):
        """选中笔划走矢量重绘的**预估耗时(ms)**。

        用于决定预览走矢量（清晰）还是图层（快但缩放/旋转会重采样变软）。
        Qt 的耗时与自交复杂度非线性相关，轮廓元素数是足够好的代理：
        实测 123 元素 ≈0.2ms、3205 元素 ≈40.7ms（≈0.0127ms/元素）。
        """
        sel = set(self._selection or [])
        total = 0
        for s in self._strokes:
            if s.get("id") in sel and s.get("op") == "pen":
                out = s.get("_outline")
                if out is None:
                    out = _build_stroke_outline(s)
                total += out.elementCount() if out is not None else 0
        return total * _PREVIEW_VECTOR_MS_PER_ELEM

    def _preview_use_vector(self):
        """旋转/缩放预览是否走矢量（清晰）——预计成本在预算内时。"""
        return self._selected_vector_cost() <= _PREVIEW_VECTOR_MS_BUDGET

    def _group_layer_res(self, sel_ids):
        """取本批选中笔划共同的"栅格残差"；不一致（来自不同批次拖拽）时返回 (0,0)。

        残差 = 图层栅格位置 − 几何位置（整数搬运留下的 ≤0.5px 亚像素对齐差）。
        同一次拖拽过的笔划残差必然相同；不同批次可能不同，此时提交会回退完整重烘焙，
        预览按 0 处理即可（误差 ≤0.5px，且松手会被精确纠正）。
        """
        res = None
        for s in self._strokes:
            if s.get("id") in sel_ids and s.get("op") == "pen":
                r = s.get("_layer_res", (0.0, 0.0))
                if res is None:
                    res = r
                elif abs(r[0] - res[0]) > 1e-6 or abs(r[1] - res[1]) > 1e-6:
                    return (0.0, 0.0)
        return res if res is not None else (0.0, 0.0)

    def _build_preview_base(self):
        """构造拖拽预览底图 = **只画未被选中的笔迹**（选中笔迹由预览以变换后的位置
        重画在最上层）。

        为什么不是"拿 _plain 把选中笔迹挖掉"：挖除（Clear 合成）是破坏性的——压在
        选中笔迹**下面**的未选中笔迹会被一起挖掉，拖拽过程中就看到未选中笔迹被裁掉
        一块（松手整幅重绘后才恢复）。只画未选中笔迹则天然没有这个副作用，也省掉了
        挖除所需的 Clear 与图层 alpha 处理。

        与 _render_all 的层次一致：未选中笔迹按原顺序、选中笔迹恒在最上层。
        一次拖拽只构造一次；之后每帧只需 copy + blit 图层。
        """
        if self._plain is None or self._plain.isNull():
            self._render_all()
        sel = set(self._selection or [])
        img = QImage(self._plain.width(), self._plain.height(),
                     QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        for s in self._strokes:
            if s.get("id") in sel and s.get("op") == "pen":
                continue
            self._blit_stroke(p, s, False)
        p.end()
        self._preview_base = img
        return img

    def _render_all(self):
        """整幅重绘：所有笔迹 + 选中描边；同时缓存"无选中版" _plain，
        供圈选拖动等仅选中变化的场景用 _render_selection_overlay 快速重绘。

        绘制走 _blit_stroke（预烘焙图层位图合成）：首次绘制某笔时烘焙一次
        （自交笔划的 AA 填充很贵，如满屏涂鸦单笔 19ms），之后每帧只要 0.3ms。
        """
        self._ensure_image()
        self._preview_base = None    # 底图基于 _plain → 一并失效
        # 1) 无选中版（纯笔迹）→ _plain（尺寸未变时复用已有缓冲，省一次整幅分配）
        w, h = self._image.width(), self._image.height()
        if (self._plain is None or self._plain.isNull()
                or self._plain.width() != w or self._plain.height() != h):
            self._plain = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        self._plain.fill(Qt.transparent)
        p = QPainter(self._plain)
        p.setRenderHint(QPainter.Antialiasing)
        for s in self._strokes:
            self._blit_stroke(p, s, False)
        p.end()
        # 2) 选中版 → _image（复制 plain 再叠加选中描边）
        #    注意：必须「先画蓝色描边(宽+4) 再画墨迹(宽)盖回中间」，否则蓝色会盖住整笔
        #    （_plain 已含墨迹，只画蓝边会通体变蓝）。墨迹盖回后只留 2px 蓝描边。
        self._image = self._plain.copy()
        sel = set(self._selection or [])
        p = QPainter(self._image)
        p.setRenderHint(QPainter.Antialiasing)
        for s in self._strokes:
            if s.get("id") in sel and s.get("op") == "pen":
                self._blit_stroke(p, s, True)
        p.end()
        # 3) 回收已非选中笔划的选中图层（选择变化后可能积下大量 _layer_sel）
        self._prune_sel_layers()

    def _render_selection_overlay(self):
        """仅重绘选中描边层（以缓存的 _plain 无选中版为底）：圈选拖动等高频
        选中变化时免去重绘全部笔迹，性能显著提升。笔迹变化仍走 _render_all。

        与 _render_all 第 2 步同规则：先画蓝描边(宽+4) 再画墨迹(宽)盖回中间，
        只留 2px 蓝描边——否则只画蓝边会让被选笔迹通体变蓝。
        """
        if self._plain is None or self._plain.isNull():
            self._render_all()
            return
        self._image = self._plain.copy()
        sel = set(self._selection or [])
        p = QPainter(self._image)
        p.setRenderHint(QPainter.Antialiasing)
        for s in self._strokes:
            if s.get("id") in sel and s.get("op") == "pen":
                self._blit_stroke(p, s, True)
        p.end()
        # 选择变化后 → 回收已非选中笔划的选中图层（圈选/单击反复选择时防累积）
        self._prune_sel_layers()

    def _render_modify_preview(self):
        """拖拽平移/缩放预览渲染：不修改向量数据、不重算 perfect-freehand 轮廓。

        每帧结构：预览底图（一次拖拽只构造一次：_plain 上挖掉选中墨迹）拷贝一份，
        再按变换合入选中笔迹。合入方式按成本二选一：
        - 纯平移：整数偏移 blit 预烘焙图层（位图直拷，无重采样/无模糊，任意数量笔迹
          每帧仅 ~0.3ms/笔）；
        - 缩放：选中笔迹较少时走矢量（painter 变换下重画，保持锐利），较多时走图层
          blit（快，但位图重采样会略软，松手提交时会重绘为锐利矢量）。
        """
        if self._plain is None or self._plain.isNull():
            self._render_all()
            return
        if not self._modify_preview:
            self._render_selection_overlay()
            return
        base = self._preview_base
        if base is None or base.isNull():
            base = self._build_preview_base()
        sel = set(self._selection or [])
        sx, sy, dx, dy = self._modify_preview
        x0, y0 = self._modify_base_rect[0], self._modify_base_rect[1]
        img = base.copy()
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        if sx == 1.0 and sy == 1.0:
            # 纯平移：取整偏移 → 位图整数像素直拷，笔迹之间相对关系严格保持。
            # 取整规则必须与提交时的 _shift_stroke_layers 完全一致（round(d - 残差)），
            # 否则松手瞬间笔迹会跳一下；残差不一致时提交会回退重烘焙，此处用 0 即可
            # （预览误差 ≤0.5px，松手被重烘焙精确纠正）。
            res = self._group_layer_res(sel)
            odx = float(round(dx - res[0]))
            ody = float(round(dy - res[1]))
            for s in self._strokes:
                if s.get("id") in sel and s.get("op") == "pen":
                    self._blit_stroke(p, s, True, odx, ody)
        else:
            # 线性映射 X = x1 + sx*(p - x0)（x1=x0+dx）等价于三连变换
            # translate(x1,y1) ∘ scale(sx,sy) ∘ translate(-x0,-y0)——缩放必须锚定
            # 基准矩形原点，否则会以画布原点(0,0)为中心缩放导致笔迹错位。
            # 选中框带姿态角时还要补 W = R_c2(θ) ∘ X ∘ R_c1(θ)⁻¹
            # （内容存的就是"视觉坐标"，故不能只做基准系映射），
            # c1/c2 = 旧/新基准矩形中心；与 _modify_map_pt 必须保持一致。
            deg = float(self._sel_rot_deg or 0.0)
            rot = abs(deg) > 0.01
            x1, y1 = x0 + dx, y0 + dy
            c1x, c1y = x0 + self._modify_base_rect[2] / 2.0, \
                y0 + self._modify_base_rect[3] / 2.0
            c2x, c2y = x1 + (c1x - x0) * sx, y1 + (c1y - y0) * sy
            p.save()
            if rot:
                p.translate(c2x, c2y)
                p.rotate(deg)
                p.translate(-c2x, -c2y)
            p.translate(x1, y1)
            p.scale(sx, sy)
            p.translate(-x0, -y0)
            if rot:
                p.translate(c1x, c1y)
                p.rotate(-deg)
                p.translate(-c1x, -c1y)
            if self._preview_use_vector():
                for s in self._strokes:
                    if s.get("id") in sel and s.get("op") == "pen":
                        _draw_selection_outline(p, s, self._light)
                        _draw_stroke(p, s, self._light)
            else:
                # 重选中的自交笔迹太多：矢量重绘每帧要几十毫秒 → 改走图层位图合成
                p.setRenderHint(QPainter.SmoothPixmapTransform, True)
                for s in self._strokes:
                    if s.get("id") in sel and s.get("op") == "pen":
                        self._blit_stroke(p, s, True)
            p.restore()
        p.end()
        self._image = img

    # ---------- QML 槽 ----------
    @Slot(str)
    def setMode(self, mode):
        """模式切换（whiteboard↔blackboard）时更新浅/深色并重放所有笔触，
        使已画笔触的显示色随之切换（黑/白互变、彩色深浅互变）。
        """
        light = (mode == "whiteboard")
        if light != self._light:
            self._light = light
            # 显示色变化 → 预烘焙图层里固化的颜色作废（轮廓与颜色无关，无需重算）
            self._invalidate_layers()
            self._render_all()
            self._bump()
            self._bump_thumbs()   # 显示色随模式变化 → 页面缩略图刷新

    # ---------- QML 槽 ----------
    @Slot(int, str, float, float, float)
    def beginStroke(self, op, color, width, x, y):
        """开始一笔：op 0=pen 1=eraser；width 为笔划粗细/橡皮直径。

        笔的起点不画独立圆（避免每笔起点出现一个大圆点）；橡皮按下即擦（点擦圆）。
        笔点记 [x,y,pressure]，pressure 由移动速度实时得出（慢→粗、快→细）。
        """
        is_pen = (op == 0)
        # 起点粗细由落笔后前 N 段平均速度决定（静止→粗、正常→适中、高速→细）：起点
        # 压力占位 0.5，第一个 move 时更新为起始平均速度对应的压力 → 起点圆头与起始段
        # 连续（无突兀大圆）。
        self._active = {"op": "pen" if is_pen else "eraser",
                        "color": color or "", "width": float(width),
                        "points": ([[float(x), float(y), 0.5]] if is_pen
                                   else [[float(x), float(y)]])}
        self._last_pt = (float(x), float(y))
        self._last_t = time.time()
        self._speed_ema = 0.0
        self._last_pressure = 0.5
        self._start_win = []
        self._ensure_image()
        self._base = self._image.copy()   # 快照：仅含已完成笔划
        if not is_pen:
            self._redraw_active()
            self._bump()

    @Slot(float, float)
    def moveStroke(self, x, y):
        if not self._active:
            return
        cur = (float(x), float(y))
        if abs(cur[0] - self._last_pt[0]) < 0.5 and abs(cur[1] - self._last_pt[1]) < 0.5:
            return
        prev = self._last_pt
        self._last_pt = cur
        if self._active["op"] == "eraser":
            self._active["points"].append([cur[0], cur[1]])
            if self._base is not None:
                # 橡皮拖动：只增量画新的一段（Clear 合成可累加），避免每帧整幅拷贝基础图
                p = QPainter(self._image)
                p.setRenderHint(QPainter.Antialiasing)
                p.setCompositionMode(QPainter.CompositionMode_Clear)
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(Qt.transparent),
                              float(self._active.get("width", 32.0)),
                              Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawLine(QPointF(prev[0], prev[1]), QPointF(cur[0], cur[1]))
                p.end()
            self._bump()
            return
        # 笔：移动速度 → 压力（慢→压力高=粗、快→压力低=细）。
        # 无压感设备的专用映射：先对瞬时速度做 EMA 平滑（抗采样抖动），
        # 再用灵敏度曲线换算压力；关闭"粗细跟随速度"时固定中等粗细（0.5）。
        now = time.time()
        dt = (now - self._last_t) if self._last_t else 0.016
        self._last_t = now
        dist = math.hypot(cur[0] - prev[0], cur[1] - prev[1])
        inst = (dist / dt) if dt > 0.001 else 0.0
        if self._start_win is not None:
            # 落笔起始阶段：用前 N 段瞬时速度的平均值定起始粗细——真实反映落笔那一刻的
            # 速度（静止按下→粗、正常书写→适中、高速移动中按下→细）；测定完成后用
            # 平均速度初始化 EMA 进入正常平滑。
            self._start_win.append(inst)
            avg = sum(self._start_win) / len(self._start_win)
            self._speed_ema = avg
            if len(self._start_win) >= _PEN_START_SAMPLES:
                self._start_win = None
            if self._speed_map_enabled:
                self._last_pressure = _pressure_from_speed(avg, self._speed_map_sens)
            else:
                self._last_pressure = 0.5
            # 第一个 move：把起点圆头压力同步为起始段压力（起点与笔迹连续，无突兀大圆）
            if len(self._active["points"]) == 1:
                self._active["points"][0][2] = self._last_pressure
        else:
            self._speed_ema = (_PEN_SPEED_MAP_EMA * inst
                               + (1.0 - _PEN_SPEED_MAP_EMA) * self._speed_ema)
            if self._speed_map_enabled:
                p = _pressure_from_speed(self._speed_ema, self._speed_map_sens)
                self._last_pressure = 0.5 * self._last_pressure + 0.5 * p
            else:
                self._last_pressure = 0.5
        self._active["points"].append([cur[0], cur[1], self._last_pressure])
        self._redraw_active()
        self._bump()

    @Slot()
    def endStroke(self):
        """结束一笔：笔=加入向量并增量落盘；橡皮=真正修改笔迹路径（切分/移除被擦部分）。"""
        if not self._active:
            return
        if self._active["points"]:
            if self._active["op"] == "pen":
                if len(self._active["points"]) == 1:
                    # 笔单击（按下即松、未拖动）→ 补一个起点小点，保证有点痕
                    self._redraw_active()
                    self._bump()
                if self._store:
                    a = self._active
                    sid = self._store.add_stroke(a["op"], a.get("color"),
                                                 a.get("width", 0.0), a["points"],
                                                 a.get("style", ""))
                    if sid is not None:
                        a["id"] = int(sid)
                        self._push_undo({"type": "add", "id": int(sid)})
                self._strokes.append(self._active)
                self._sel_grid = None   # 笔迹变化 → 圈选索引失效
                self._plain = None      # 画布无选中版失效（下次选中重绘时整幅重建）
                self._bump_thumbs()     # 笔迹完成 → 页面缩略图刷新
            else:
                # 橡皮：不再存"蒙层"笔划，而是真正修改笔迹路径（切分/移除被擦部分）；
                # 未擦到任何笔划时不产生撤销操作
                op = self._apply_eraser(self._active)
                if op:
                    self._push_undo(op)
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
        self._sel_grid = None   # 笔迹变化 → 圈选索引失效
        self._plain = None      # 画布无选中版失效（清屏后需重建）
        self._active = None
        self._last_pt = None
        self._base = None
        self._selection = []
        self._sel_rect = None
        self._sel_active = False
        self._drop_focus_stage()
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
        self._bump_thumbs()   # 清屏 → 页面缩略图刷新

    @Slot()
    def cancelStroke(self):
        """取消进行中的一笔（如切出画布），不落盘。"""
        self._active = None
        self._last_pt = None
        self._base = None
        self._fig_origin = None    # 图形绘制的起点（辅助矩形锚点）
        self._fig_snap_guide = None   # 图形等边吸附时的引导线 [x0,y0,x1,y1]
        self._fig_snap_kind = ""      # 当前吸附中的图形 id（未吸附为空）
        self._fig_align = ""          # 横平竖直吸附方向（h/v，未吸附为空）
        self._drop_focus_stage()    # 两阶段图形的第二阶段一并取消（不提交）

    def finishPendingDrawing(self):
        """切页 / 退出特殊模式前的收尾：把“多阶段图形”与“多步多边形”补完并**提交**。

        用户要求：绘制过程中切页 / 退出手写板模式，不能把正在画的形状丢掉。
        收尾规则与 `finishFocusStage` 完全一致（切工具同款）：
        · 多步多边形 → 把还没连上的缺口**闭合**后提交（只有一条边就提交一条开链）；
        · 两阶段图形（椭圆 / 双曲线 / 扇形）→ 已经拖出探针就用当前探针（所见即所得），
          还没拖过探针就按默认探针把图形补出来。
        **不发** `shapeFinished`（工具不是用户切走的，保持当前工具不变）。
        """
        if self._pf_pts is None and not self._tf_foci:
            return
        try:
            self.finishFocusStage()
        except Exception:
            plugin_logger.debug("切页/退模式前收尾失败", exc_info=True)

    def _drop_focus_stage(self):
        """放弃两阶段图形/多步多边形的第二阶段（取消笔划/清屏/切页/重新载入时）：只清状态，不提交。"""
        self._tf_kind = ""
        self._tf_foci = None
        self._tf_probe = None
        self._fig_align = ""           # 第二阶段没有横平竖直吸附，随手清干净
        self._tf_active = -1
        self._tf_probe_dragging = False
        self._sector_last_raw = None   # 扇形转角累计一并复位
        self._sector_acc = 0.0
        self._sf_base = None
        self._sf_proj = _SOLID_PROJ_FIXED   # 本次绘制的测画方式（beginLine 时定）
        self._sf_snap = ""                  # 升维吸附状态
        self._sf_apex_dy = None             # 三棱台：第三步已定的顶点参数（None = 未定）
        self._sf_apex_h = None
        self._ax_org = None                 # 坐标系：原点（纸面）／矩形底面的四个角／y 轴长
        self._ax_pts = None
        self._ax_ylen = 0.0
        self._ax_kind = ""
        self._pf_pts = None            # 多边形随心画的多步链一并放弃
        self._pf_drawing = False
        self._pf_probe = None
        self._pf_end = None
        self._pf_angle = 0.0
        self._pf_on_end = False
        self._pf_anchor = None
        self._pf_para_ref = None
        self._pf_eq_ref = None
        self._pf_hi = None
        self._pf_hi_gap = False

    # ---------- 形状（线型 + 图形）----------
    @Slot(str, str, float, float, float)
    def beginLine(self, style, color, width, x, y):
        """开始一个形状（按下）：记录起点（终点先随起点），拖动中实时预览。

        style 可为线型 id（dash/dashdot/wave/dot/double…）或图形 id
        （tri/rect/pent/hex/oct/star/circle/ellipse）；粗细与颜色取自手写笔设置（"根据笔工具的
        粗细、颜色"）。数据上仍是一笔 op="pen" 的笔划（额外带 style，图形存为
        "fig:<kind>"），因此命中/圈选/橡皮切分/图层/撤销/多页全部与手写笔同源。
        图形：由起点→当前点确定一个横平竖直辅助矩形（不显示），图形内接其中，
        points 就是轮廓顶点序列（闭合）；**两个例外**：
        · 圆：起点就是圆心、半径 = 起终点距离（与拖动方向无关，永远得到正圆），points 首点是圆心；
        · 椭圆：起点是椭圆中心、终点是一个焦点（另一焦点镜像得到），前两点是两焦点，
          且松手后**不结束**（进入第二阶段拖焦点手柄定 2a，见 endEllipseProbe）。
        """
        if self._tf_foci is not None:
            # 第二阶段：在画布**任意位置**按下 = 开始拖“自由探针”（不是在焦点手柄上）。
            # 效果与拖焦点手柄相同（椭圆定 2a / 双曲线定渐近线），松手才提交（见 endLine）。
            self.beginFocusProbe(-1, x, y)
            return
        if self._pf_pts is not None:
            # 多边形随心画的多步流程中：在画布**任意位置**按下 = 从"离鼠标最近的那一端"
            # 接着画下一条边（松手才结束这条边，见 endLine → endFocusProbe）。
            self.beginFocusProbe(-1, x, y)
            return
        if (style not in _LINE_SHAPES and style not in _SHAPE_KINDS
                and style not in _SOLID_MENU_KINDS
                and style not in _AXIS_MENU_KINDS):
            return
        self._ensure_image()
        self._fig_origin = (float(x), float(y))
        self._fig_snap_guide = None
        self._fig_snap_kind = ""
        self._fig_align = ""
        if style in _AXIS_MENU_KINDS:
            # 坐标系：按下点 = 坐标原点。数据上是一叠 **箭头线**（style = "arrow"，
            # 与直线菜单的箭头完全一致）→ 命中/圈选/橡皮切分/图层/撤销/多页全部复用。
            self._ax_org = (float(x), float(y))
            self._ax_pts = None
            self._ax_ylen = 0.0
            self._ax_kind = style
            if style == "spaceaxes":
                # 空间直角坐标系第一步：与四棱柱底面同样的"拖对角线定底面平面矩形"
                self._sf_proj = _solid_proj_for(style, self._solid_proj_mode)
            self._base = self._image.copy()
            self._active = {"op": "pen", "style": _AXIS_ARROW_STYLE, "color": color or "",
                            "width": float(width),
                            "points": [[float(x), float(y)], [float(x), float(y)]]}
            self._last_pt = (float(x), float(y))
            self._redraw_active()
            self._bump()
            return
        if style in _SHAPE_KINDS or style in _SOLID_MENU_KINDS:
            stored = _FIG_PREFIX + style
            if style == "polfree":
                # 多边形随心画：第一步就是**第一条边**（起点 → 终点）→ 先当两点链处理
                pts = [[float(x), float(y)], [float(x), float(y)]]
            elif style in _SOLID_MENU_KINDS:
                if style in _SOLID_SPHERE_KINDS:
                    # 球：**一步成型**（拖拽 = 投影后的半径）→ 不进两阶段机制。
                    # 主笔 = 轮廓圆（半径随时间变大）；两个椭圆在预览里现算。
                    # 测画方式固定正等测（`_SOLID_PROJ_FIXED_BY_KIND`）。
                    self._sf_proj = _solid_proj_for(style, self._solid_proj_mode)
                    pts = _solid_sphere_strokes(style, float(x), float(y), 0.0,
                                                self._sf_proj)[0]["points"]
                    self._fig_snap_kind = "radius"
                    self._fig_snap_guide = [float(x), float(y), float(x), float(y)]
                else:
                    # 立体图形第一阶段：先画**底面**（位于 xOy 平面）。轮廓画法复用对应平面
                    # 图形 → 拖拽中的轮廓在 moveLine 里按底面画法现算（含等边吸附）。
                    # **测画方式**（正等测/斜二测）在按下这一瞬定下来（用户选择只对支持的图形生效）。
                    self._sf_proj = _solid_proj_for(style, self._solid_proj_mode)
                    pts = _solid_base_outline(style, float(x), float(y), float(x), float(y),
                                              self._sf_proj)
                    # 主提示立刻显示「底面」（不等第一次 moveLine）
                    self._fig_snap_kind = "solidbase"
            else:
                pts = _figure_points(style, float(x), float(y), float(x), float(y))
        else:
            stored = style
            pts = [[float(x), float(y)], [float(x), float(y)]]
        self._base = self._image.copy()   # 仅含已完成笔划的快照（与 beginStroke 同规则）
        self._active = {"op": "pen", "style": stored, "color": color or "",
                        "width": float(width), "points": pts}
        self._last_pt = (float(x), float(y))
        self._redraw_active()
        self._bump()

    @Slot(float, float)
    def moveLine(self, x, y):
        """拖动中：终点跟随鼠标（线型只改第二点；图形按辅助矩形重算轮廓）。"""
        if self._tf_foci is not None and (self._tf_probe is not None
                                          or self._tf_kind in _AXIS_MENU_KINDS):
            # 第二阶段：自由探针（在画布上拖动，非手柄）→ 实时重算形状
            # ⚠️ 坐标系第二步**按下时刻意不写 `_tf_probe`**（见 beginFocusProbe：没拖过就不显示 z 轴），
            # 所以这里不能只看 `_tf_probe` —— 否则“在画板任意位置拖拽”会掉到下面的 `_move_axes`，
            # 变成把 xoy 两轴拖走（用户报的问题）；必须拖的是 z 轴。
            self.dragFocusProbe(x, y)
            return
        if self._pf_drawing:
            # 多边形随心画：正在拖某条边（手柄或画布任意位置）→ 实时重算这条边
            self.dragFocusProbe(x, y)
            return
        if not self._active or not _is_shape_stroke(self._active):
            return
        if self._ax_org is not None and self._active.get("style") == _AXIS_ARROW_STYLE:
            # 坐标系：按下点 = 坐标原点（一步到位的平面直角坐标系 / 空间直角坐标系第一步）
            self._move_axes(x, y)
            return
        cur = (float(x), float(y))
        if abs(cur[0] - self._last_pt[0]) < 0.5 and abs(cur[1] - self._last_pt[1]) < 0.5:
            return
        self._last_pt = cur
        fig = _figure_of(self._active)
        if fig and self._fig_origin:
            ox, oy = self._fig_origin
            if fig in _TWO_STAGE_FIGS:
                # 两阶段图形第一阶段：起点 = 几何重心，终点 = 一个焦点；
                # 另一焦点 = 关于中心镜像。两焦点"横平竖直"就近吸附：
                #   鼠标接近使两焦点同 y（横着）或同 x（竖着）的位置 → 就近吸上去。
                # 引导线 = 两焦点之间的蓝色虚线；胶囊提示文字为"焦点"（见 _FIG_SNAP_NAMES）；
                # 吸中时额外弹第二个提示"水平排列"/"竖直排列"（见 _FIG_ALIGN_NAMES）。
                dx, dy = cur[0] - ox, cur[1] - oy
                align = ""
                if abs(dy) <= _FIG_SNAP_PX and abs(dy) <= abs(dx):
                    dy = 0.0                      # 吸成横向排布（两焦点同 y）
                    align = "h"
                elif abs(dx) <= _FIG_SNAP_PX:
                    dx = 0.0                      # 吸成竖向排布（两焦点同 x）
                    align = "v"
                fx, fy = ox + dx, oy + dy
                self._fig_snap_guide = [ox - dx, oy - dy, fx, fy]
                self._fig_snap_kind = fig
                self._fig_align = align
                self._active["points"] = _figure_points(fig, ox, oy, fx, fy)
            elif fig == "circle":
                # 圆：起点=圆心、半径 = 起终点距离 → 不需要等边吸附（永远是正圆）；
                # 绘制过程中把"半径"作为引导线用蓝色虚线标出来，主提示文字「半径」。
                self._fig_snap_guide = [ox, oy, cur[0], cur[1]]
                self._fig_snap_kind = "radius" if math.hypot(cur[0] - ox,
                                                             cur[1] - oy) > 1.0 else ""
                self._fig_align = ""
                self._active["points"] = _figure_points("circle", ox, oy, cur[0], cur[1])
            elif fig == "sphere":
                # 球（**一步成型**，不是两阶段）：起点 = 球心、终点到起点的距离 = 投影后的半径。
                # 轮廓圆 = 球的投影（主笔 `_active`）；两个椭圆由 `_stage_preview_strokes` 现算。
                # 引导线 = 起点→鼠标的蓝色虚线；提示文字「半径」。
                rr_s2 = math.hypot(cur[0] - ox, cur[1] - oy)
                self._fig_snap_guide = [ox, oy, cur[0], cur[1]]
                self._fig_snap_kind = "radius" if rr_s2 > 1.0 else ""
                self._fig_align = ""
                self._active["points"] = _solid_sphere_strokes(
                    "sphere", ox, oy, rr_s2, self._sf_proj)[0]["points"]
            elif fig == "sector":
                # 扇形第一阶段：起点 = 圆心，终点 = 第一条半径的端点。
                # 这条半径做**横平竖直**就近吸附（吸中时弹第二个提示「水平」/「竖直」）；
                # 同时把"整个圆"用蓝色虚线标出来（引导线），主提示文字「扇半径」。
                dx, dy = cur[0] - ox, cur[1] - oy
                align = ""
                if abs(dy) <= _FIG_SNAP_PX and abs(dy) <= abs(dx):
                    dy = 0.0                      # 半径吸成水平
                    align = "h"
                elif abs(dx) <= _FIG_SNAP_PX:
                    dx = 0.0                      # 半径吸成竖直
                    align = "v"
                rr_s = math.hypot(dx, dy)
                self._fig_snap_guide = _guide_circle(ox, oy, rr_s) if rr_s > 1.0 else None
                self._fig_snap_kind = "sector" if rr_s > 1.0 else ""
                self._fig_align = align
                self._active["points"] = _figure_points("sector", ox, oy,
                                                        ox + dx, oy + dy)
            elif fig == "para":
                # 抛物线（**一步成形**，不做等边吸附）：起点 = 顶点 = 焦准距线段的中点，
                # 终点 = 焦点 → 准线与曲线唯一确定。
                # 引导线 = **焦准距线段**（准足 → 焦点，中点正是按下点）；提示文字"焦准距线段"。
                # 焦准距线段与椭圆/双曲线的焦点一样做"横平竖直"就近吸附（吸中时轴上/轴下）。
                dx, dy = cur[0] - ox, cur[1] - oy
                align = ""
                if abs(dy) <= _FIG_SNAP_PX and abs(dy) <= abs(dx):
                    dy = 0.0                      # 焦准距线段吸成水平（对称轴水平）
                    align = "h"
                elif abs(dx) <= _FIG_SNAP_PX:
                    dx = 0.0                      # 焦准距线段吸成竖直（对称轴竖直）
                    align = "v"
                sfx, sfy = ox + dx, oy + dy
                pvx, pvy, pux, puy, pp, _pX = _parabola_params(ox, oy, sfx, sfy)
                self._fig_snap_guide = [pvx - pp * pux, pvy - pp * puy, sfx, sfy]
                self._fig_snap_kind = "para2"
                self._fig_align = align
                self._active["points"] = _figure_points("para", ox, oy, sfx, sfy)
            elif fig == "polfree":
                # 多边形随心画的第一条边：只做**横平竖直**就近吸附（提示「水平」/「竖直」），
                # 没有引导线也没有主提示（后续边才弹内角提示，见 _refresh_polfree）。
                dx, dy = cur[0] - ox, cur[1] - oy
                align = ""
                if abs(dy) <= _FIG_SNAP_PX and abs(dy) <= abs(dx):
                    dy = 0.0                      # 吸成水平边
                    align = "h"
                elif abs(dx) <= _FIG_SNAP_PX:
                    dx = 0.0                      # 吸成竖直边
                    align = "v"
                self._fig_snap_guide = None
                self._fig_snap_kind = ""
                self._fig_align = align
                self._active["points"] = [[ox, oy], [ox + dx, oy + dy]]
            elif fig == "rtri":
                # 直角三角（**一步成形**）：起点 = 直角顶点，两条直角边横平竖直、
                # 都朝终点所在象限（|dx| / |dy| 就是两条直角边的边长）。
                # 拖拽方向与水平横线夹 30°/45°/60° 时吸到那条射线上（蓝色虚线引导），
                # 提示文字见 _FIG_SNAP_NAMES（45° → 「等腰直角三角形」）。
                rx, ry, rg, rsid = _figure_ray_snap(ox, oy, cur[0], cur[1])
                self._fig_snap_guide = rg
                self._fig_snap_kind = rsid       # 未吸附时为空 → 不弹提示
                self._fig_align = ""
                self._active["points"] = _figure_points("rtri", ox, oy, rx, ry)
            elif _solid_of(fig)[0]:
                # **立体图形第一阶段：画底面**。主提示文字固定为「底面」（`solidbase`），
                # 等边/正方形吸附的确认文字弹在它上方（`_fig_align = "fig"`，见 figureAlignName）。
                # · 棱柱：拖拽（起点→终点）是底面平面矩形的**一条对角线**，蓝色虚线画出这个
                #   矩形的投影（两条边分别沿底面平面 y / x 轴）；底面 = 与终点相邻的那条 y 边为
                #   底边、对边中点为顶点的等腰三角形（在底面平面里）。
                #   底面本身就填满辅助矩形的（四棱柱）不再画这个矩形（用户要求）。
                # · 圆柱 / 圆锥：起点 = 圆心、终点 = 投影后圆上的一点（连线 = 投影后圆的半径）→
                #   只画这条半径做引导线，**没有任何吸附**。
                # 测画方式 = 按下时定下的 `self._sf_proj`（正等测 / 斜二测）。
                proj = self._sf_proj
                if _SOLID_BASE_KIND.get(fig, "") == "circle":
                    # 圆形底面（圆柱 / 圆锥 / **圆台**）：起点 = 圆心、终点 = 投影后圆上的一点
                    # → 只画这条半径做引导线、**没有任何吸附**。
                    # ⚠️ 判据必须看"底面画法是不是圆"，不能看 `_SOLID_SMOOTH_KINDS`
                    #   （圆台是光滑侧面但不在那个元组里 → 会误走下面的"正多边形吸附"）。
                    self._fig_snap_guide = [ox, oy, cur[0], cur[1]]      # 半径（蓝色虚线）
                    self._fig_snap_kind = "solidbase"
                    self._fig_align = ""
                    self._active["points"] = _solid_base_outline(fig, ox, oy, cur[0], cur[1],
                                                                 proj)
                else:
                    sx_f, sy_f, snap_line = _solid_base_snap(fig, ox, oy, cur[0], cur[1], proj)
                    guide = (_solid_base_rect_guide(ox, oy, sx_f, sy_f, proj)
                             if _solid_base_needs_rect(fig) else [])
                    self._fig_snap_guide = (guide + list(snap_line)) if snap_line else guide
                    self._fig_snap_kind = "solidbase"
                    self._fig_align = "fig" if snap_line else ""
                    self._active["points"] = _solid_base_outline(fig, ox, oy, sx_f, sy_f, proj)
            else:
                # 等边吸附（仅多边形/星形）：终点吸到可等边直线上 + 引导线 + 吸附图形种类
                sx_f, sy_f, guide = _figure_snap(fig, ox, oy, cur[0], cur[1])
                self._fig_snap_guide = guide
                self._fig_snap_kind = fig if guide else ""
                self._fig_align = ""
                self._active["points"] = _figure_points(fig, ox, oy, sx_f, sy_f)
        else:
            # 线型笔划（直线/虚线/波浪线/箭头/…）：与图形一样做"横平竖直"就近吸附
            # （12px 阈值；吸中时弹第二个提示「水平」/「竖直」，见 _LINE_ALIGN_NAMES）。
            # 锚点 = 按下时的首点（线型的两端点就是 [起点, 当前点]）。
            self._fig_snap_guide = None
            self._fig_snap_kind = ""
            pts_a = self._active.get("points") or []
            x0a = float(pts_a[0][0]) if pts_a else cur[0]
            y0a = float(pts_a[0][1]) if pts_a else cur[1]
            dx, dy = cur[0] - x0a, cur[1] - y0a
            align = ""
            if abs(dy) <= _FIG_SNAP_PX and abs(dy) <= abs(dx):
                dy = 0.0                      # 吸成水平线
                align = "h"
            elif abs(dx) <= _FIG_SNAP_PX:
                dx = 0.0                      # 吸成竖直线
                align = "v"
            self._fig_align = align
            self._active["points"][1] = [x0a + dx, y0a + dy]
        self._redraw_active()
        self._bump()

    def _end_axes(self, base):
        """坐标系松手：**平面直角坐标系**一步到位直接提交；**空间直角坐标系**进入第二步。

        · 平面直角坐标系：横轴半长 |Δx| / 纵轴半长 |Δy| 都太短 → 视为误触（抽掉预览 + 回退工具）；
        · 空间直角坐标系：（贴正方形时）xy 平面画完 → **不提交、不回退工具**，在**坐标原点**
          弹出升维手柄（`_tf_foci` = 原点 → focusProbeActive / 切工具收尾 / 任意位置拖拽全现成）。
        """
        ox, oy = self._ax_org
        if self._ax_kind == "planeaxes":
            p = self._ax_pts or []
            ok_axis = (len(p) >= 4 and abs(p[1][0] - ox) >= _AXIS_MIN_LEN
                       and abs(p[2][1] - oy) >= _AXIS_MIN_LEN)
            if ok_axis:
                strokes, _hit = self._axes_strokes()
                self._commit_axes(strokes, True)
                return
            self._active = None
            self._base = None
            self._last_pt = None
            self._fig_origin = None
            self._fig_snap_guide = None
            self._fig_snap_kind = ""
            self._fig_align = ""
            self._drop_focus_stage()          # 含 _ax_* 的复位
            if base is not None:
                self._image = base.copy()     # 太短/取消 → 抽掉预览
            self._bump()
            self.shapeFinished.emit()
            return
        # 空间直角坐标系第一步（xy 平面）画完
        bpts = self._ax_pts or []
        ok_stage = (len(bpts) == 3
                    and _axis_edge_len(bpts, 0, self._sf_proj) >= _AXIS_MIN_LEN
                    and _axis_edge_len(bpts, 1, self._sf_proj) >= _AXIS_MIN_LEN)
        try:
            if ok_stage:
                self._ax_ylen = _axis_edge_len(bpts, _axis_y_index(bpts, self._sf_proj),
                                              self._sf_proj)
                self._tf_kind = "spaceaxes"
                self._tf_foci = ((ox, oy), (ox, oy))   # 手柄停在**坐标原点**
                self._tf_active = -1                    # 手柄不抢鼠标
                self._tf_probe = None                   # 还没拖过 → 默认 z 轴 = y 轴长
                self._fig_origin = None
                self._last_pt = None
                self._refresh_focus_stage()
                return                                  # ← 不发 shapeFinished：仍是形状模式
            self._active = None
            self._base = None
            self._last_pt = None
            self._fig_origin = None
            self._fig_snap_guide = None
            self._fig_snap_kind = ""
            self._fig_align = ""
            self._ax_org = None
            self._ax_pts = None
            self._ax_kind = ""
            if base is not None:
                self._image = base.copy()
            self._bump()
        finally:
            if not ok_stage:
                self.shapeFinished.emit()               # xy 平面太小 → 误触，照常回退工具

    def _move_axes(self, x, y):
        """坐标系拖动中：重算正在画的那根轴（+ 引导线/吸附提示）。

        · **平面直角坐标系**（一步到位）：横轴朝右、纵轴朝上，原点同时是两条轴的中点 →
          横轴的半长 = |Δx|、纵轴的半长 = |Δy|（`_active` = 横轴，纵轴在预览里现算）。
        · **空间直角坐标系第一步**：与四棱柱底面同样的"拖对角线定底面平面矩形"
          （贴正方形时就近吸附 + 蓝色虚线矩形 + 提示「x、y 轴等长」）；`_active` = x 轴
          （从原点那一角沿第一条相邻边），y 轴在预览里现算。

        ⚠️ 已进入第二步（`_tf_kind` 也是坐标系）时**直接返回**：那时拖的是 **z 轴**
        （经 `moveLine → dragFocusProbe`），绝不能反过来去改 xoy 平面（用户报过这个问题）。
        """
        if self._tf_kind in _AXIS_MENU_KINDS:
            return
        ox, oy = self._ax_org
        cur = (float(x), float(y))
        if self._ax_kind == "planeaxes":
            lx, ly = abs(cur[0] - ox), abs(cur[1] - oy)
            self._active["points"] = [[ox - lx, oy], [ox + lx, oy]]
            self._ax_pts = [[ox, oy], [ox + lx, oy], [ox, oy + ly], [ox, oy - ly]]
            self._ax_ylen = ly
            self._fig_snap_guide = None
            self._fig_snap_kind = ""
            self._fig_align = ""
        else:
            sx, sy, guide, hit = _axis_space_xy(ox, oy, cur[0], cur[1], self._sf_proj)
            # 原点**严格**在鼠标起点 + 两条轴沿**相邻两条矩形边**（用户要求）→
            # 用 `_axis_xy_pts`（而不是 `_solid_base_pts` 的角点顺序）
            self._ax_pts = _axis_xy_pts(ox, oy, sx, sy, self._sf_proj)
            if len(self._ax_pts) < 3:
                return
            self._active["points"] = _axis_xy_arrows(self._ax_pts)[0]["points"]
            self._fig_snap_guide = guide
            self._fig_snap_kind = "axiseq" if hit else ""
            self._fig_align = ""
        self._redraw_active()
        self._bump()

    def _axes_strokes(self, force_z=False):
        """当前坐标系的**全部轴笔划**（现算，供预览/提交共用）。

        · 平面直角坐标系：横轴 + 纵轴（`_ax_pts` = [原点, 横轴右端, 纵轴上端, 纵轴下端]）；
        · 空间直角坐标系：xy 两轴（从 `_ax_pts` = [原点, 相邻角1, 相邻角2] 算）+ z 轴。
        **第二步的 z 轴：拖拽前不显示**（用户要求：xoy 画完后不直接显示 z 轴箭头，待用户拖拽
        手柄/任意画板位置再显示）→ 只有 `_tf_probe is not None`（真拖过）才接上 z；
        `force_z=True`（**提交路径**：松手提交 / 切工具、切页、关白板的兜底）则无条件接上
        —— 此时 `_axis_z_dy()` 因未拖过而返回**默认值**（z = y 轴长、朝上），
        正是用户要的"没继续绘制就生成默认 z 轴"。
        返回 (笔划列表, z 轴是否吸附成"与 y 轴等长")。
        """
        if not self._ax_pts:
            return [], False
        if self._ax_kind == "planeaxes":
            ox, oy = self._ax_org
            p = self._ax_pts
            if len(p) < 4:
                return [], False
            return _axis_plane_strokes(ox, oy, abs(p[1][0] - ox), abs(p[2][1] - oy)), False
        out = _axis_xy_arrows(self._ax_pts)
        if self._tf_kind == "spaceaxes" and (force_z or self._tf_probe is not None):
            dz, hit = self._axis_z_dy()
            out.append(_axis_z_stroke(self._ax_org[0], self._ax_org[1], dz))
            return out, hit
        return out, False

    def _axis_z_dy(self):
        """z 轴的纸面竖直位移（**上为负**）+ 是否吸附成"与 y 轴等长"。

        用户要求：第二步拖手柄/任意位置拖拽 → 画**竖直方向**（向上或向下）的 z 轴 → 只取鼠标的
        竖直位移（横向分量忽略）；靠近"z 轴与 y 轴等长"时就近吸附并提示「z、y 轴等长」。
        还没拖过（`_tf_probe is None`）→ 默认 z 轴 = y 轴长、朝上
        （= 切工具/切页/关白板时的默认坐标系）。
        **拖过但鼠标离原点太近（|dz| < `_AXIS_MIN_LEN`）→ 把长度锁在最小长度**
        （用户要求：不要跳回默认长度；方向按鼠标在原点的哪一侧，正好在原点的水平线上时朝上）。
        """
        ox, oy = self._ax_org
        ylen = float(self._ax_ylen)
        if self._tf_probe is None:
            return -ylen, True               # 还没拖过 → 默认：z 轴 = y 轴长、指向上
        dz = float(self._tf_probe[1]) - float(oy)
        if abs(dz) < _AXIS_MIN_LEN:
            # 太近 → 长度锁最小（dz > 0 = 鼠标在原点下方 → z 朝下；dz ≤ 0 → 朝上）
            return (_AXIS_MIN_LEN if dz > 1e-9 else -_AXIS_MIN_LEN), False
        if ylen > 1e-6 and abs(abs(dz) - ylen) <= _FIG_SNAP_PX:
            dz = ylen if dz > 0 else -ylen   # 就近吸附（保留上/下方向）
            return dz, True
        return dz, False

    def _commit_axes(self, strokes, emit_finished):
        """提交坐标系：多根**箭头线**一起落盘（同一个 `grp`、只压一条 add_many 撤销）。"""
        act = self._active
        color = (act or {}).get("color", "")
        width = (act or {}).get("width", 4.0)
        self._drop_focus_stage()             # 含 _ax_* 的复位
        self._active = None
        self._base = None
        self._last_pt = None
        self._fig_origin = None
        self._fig_snap_guide = None
        self._fig_snap_kind = ""
        self._fig_align = ""
        try:
            if strokes:
                gid = _new_grp()
                ids = []
                for s in strokes:
                    s["op"] = "pen"
                    s["style"] = _AXIS_ARROW_STYLE
                    s["color"] = color
                    s["width"] = width
                    _set_grp(s, gid)
                    self._store_active_stroke(s, undo=False)
                    if s.get("id") is not None:
                        ids.append(int(s["id"]))
                if ids:
                    self._push_undo({"type": "add_many", "ids": ids})
            self._bump()
        finally:
            if emit_finished:
                self.shapeFinished.emit()

    def _store_active_stroke(self, act, undo=True):
        """提交进行中的形状笔划：落盘 + 加入向量 + 失效索引/缩略图（endLine / 两阶段图形共用）。

        undo=False 时不单独压撤销（供双曲线这种"多笔算一次操作"的批量提交用，
        由调用方最后压一条 add_many）。
        """
        if self._store:
            sid = self._store.add_stroke(
                "pen", act.get("color", ""), act.get("width", 4.0),
                act["points"], act.get("style", ""),
                pat=act.get("pat"), grp=act.get("grp", ""))
            if sid is not None:
                act["id"] = int(sid)
                if undo:
                    self._push_undo({"type": "add", "id": int(sid)})
        self._strokes.append(act)
        self._sel_grid = None   # 笔迹变化 → 圈选索引失效
        self._plain = None      # 画布无选中版失效（下次选中重绘时整幅重建）
        self._bump_thumbs()     # 笔迹完成 → 页面缩略图刷新

    @Slot()
    def endLine(self):
        """松开：提交这一条线（过短视为误触丢弃）；最后发 shapeFinished 让工具回退。

        与 endStroke 一致：提交时不再整幅重绘（当前 _image 已是"基础图 + 预览笔划"，
        就是最终画面），只失效 _plain/圈选索引，下次重绘时按图层烘焙。
        **椭圆例外**：第一阶段松手后不提交也不回退工具，而是进入第二阶段
        （两焦点处出现圆形白色手柄，拖手柄/在画布上拖动都可定 2a → endEllipseProbe 才提交）。
        """
        if self._tf_foci is not None:
            # 第二阶段中松手（自由探针拖拽结束）→ 按当前位置定下的形状提交并回退工具
            self.endFocusProbe()
            return
        if self._pf_pts is not None:
            # 多边形随心画：多步流程中松手 = 结束当前这条边（见 _pf_end_drag）
            self.endFocusProbe()
            return
        act = self._active
        base = self._base
        if self._ax_org is not None and act is not None \
                and act.get("style") == _AXIS_ARROW_STYLE:
            self._end_axes(base)
            return
        fig0 = _figure_of(act) if act else ""
        if fig0 == "para" and self._fig_origin:
            # 抛物线（一步成形）：提交"曲线 + 准线"两笔，但**只压一条 add_many 撤销**
            # （与双曲线一致：一次撤销移除整条抛物线）。过短视为误触丢弃。
            ox, oy = self._fig_origin
            head_act = (act.get("points") or []) if act else []
            fx0, fy0 = ((float(head_act[0][0]), float(head_act[0][1]))
                        if head_act else (ox, oy))
            big = math.hypot(fx0 - ox, fy0 - oy) >= 2.0
            self._active = None
            self._last_pt = None
            self._base = None
            self._fig_origin = None
            self._fig_snap_guide = None
            self._fig_snap_kind = ""
            self._fig_align = ""
            try:
                if big:
                    color = act.get("color", "")
                    width = act.get("width", 4.0)
                    ids = []
                    for s in _parabola_figure_strokes(ox, oy, fx0, fy0):
                        s["color"] = color
                        s["width"] = width
                        self._store_active_stroke(s, undo=False)
                        if s.get("id") is not None:
                            ids.append(int(s["id"]))
                    if ids:
                        self._push_undo({"type": "add_many", "ids": ids})
                elif base is not None:
                    self._image = base.copy()
                self._bump()
            finally:
                self.shapeFinished.emit()
            return
        if fig0 == "polfree" and self._fig_origin:
            # 多边形随心画：第一条边画完 → **不提交、不回退工具**，进入"多步绘制"：
            # 这条边的两个端点弹出手柄，之后逐条接着画，直到闭合（或切工具时直接闭合缺口）。
            ox, oy = self._fig_origin
            pts0 = (act.get("points") or []) if act else []
            p0 = ([float(pts0[0][0]), float(pts0[0][1])] if pts0 else [float(ox), float(oy)])
            p1 = ([float(pts0[1][0]), float(pts0[1][1])] if len(pts0) > 1 else list(p0))
            edge = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            self._fig_origin = None
            self._fig_snap_guide = None
            self._fig_snap_kind = ""
            self._fig_align = ""
            self._last_pt = None
            ok_edge = self._active is not None and edge >= _PF_MIN_EDGE
            try:
                if ok_edge:
                    self._pf_pts = [p0, p1]
                    self._active["points"] = [list(p0), list(p1)]
                    self._redraw_active()
                else:
                    self._active = None
                    self._base = None
                    if base is not None:
                        self._image = base.copy()
                self._bump()
            finally:
                if not ok_edge:
                    self.shapeFinished.emit()      # 边太短 → 当作误触，照常回退工具
            return
        if fig0 == "sphere" and self._fig_origin:
            # 球（**一步成型**）：提交"轮廓圆 + 两个椭圆（各分实线/虚线两半）"共 5 笔，
            # **只压一条 add_many 撤销**（与抛物线/双曲线一致），所有笔划同一个 `grp`
            # （圈选/单击时当作一个整体；被橡皮切分时清空）。半径太小视为误触丢弃。
            ox, oy = self._fig_origin
            pts_s = (act.get("points") or []) if act else []
            rr_s = (math.hypot(float(pts_s[0][0]) - ox, float(pts_s[0][1]) - oy)
                    if pts_s else 0.0)
            self._active = None
            self._base = None
            self._last_pt = None
            self._fig_origin = None
            self._fig_snap_guide = None
            self._fig_snap_kind = ""
            self._fig_align = ""
            try:
                if act is not None and rr_s >= _SPHERE_MIN_R:
                    color = act.get("color", "")
                    width = act.get("width", 4.0)
                    gid = _new_grp()
                    ids = []
                    for s in _solid_sphere_strokes("sphere", ox, oy, rr_s,
                                                   self._sf_proj or _SOLID_PROJ_DEFAULT):
                        s["color"] = color
                        s["width"] = width
                        _set_grp(s, gid)
                        self._store_active_stroke(s, undo=False)
                        if s.get("id") is not None:
                            ids.append(int(s["id"]))
                    if ids:
                        self._push_undo({"type": "add_many", "ids": ids})
                elif base is not None:
                    self._image = base.copy()   # 半径太小/取消 → 抽掉预览
                self._bump()
            finally:
                self.shapeFinished.emit()
            return
        if _solid_of(fig0)[0] and self._fig_origin:
            # **立体图形第一阶段（底面）画完** → 不提交、不回退工具，进入第二阶段（升维）：
            # 底面中心弹出一个手柄（图标 = 上下双向箭头），拖手柄或在画布任意位置拖动
            # 都能升维（只取鼠标的竖直分量 → 正柱体，顶面 = 底面沿 z 上移 h）。
            ox, oy = self._fig_origin
            pts_act0 = (act.get("points") or []) if act else []
            bpts = [[float(p[0]), float(p[1])] for p in pts_act0[:-1]]   # 去掉闭合点
            self._fig_origin = None
            self._fig_snap_guide = None
            self._fig_snap_kind = ""
            self._fig_align = ""
            self._last_pt = None
            bxs = [p[0] for p in bpts] or [float(ox)]
            bys = [p[1] for p in bpts] or [float(oy)]
            ok_stage = (len(bpts) >= 3
                        and (max(bxs) - min(bxs) >= 2.0 or max(bys) - min(bys) >= 2.0))
            try:
                if ok_stage:
                    self._sf_base = bpts
                    # 复用两阶段机制：`_tf_foci` 填底面中心（两分量相同）→
                    # focusProbeActive/finishFocusStage/切页收尾/任意位置拖拽全部现成可用。
                    self._tf_kind = fig0
                    self._tf_foci = (_solid_base_centre(bpts),
                                     _solid_base_centre(bpts))
                    self._tf_active = -1           # 手柄不抢鼠标（停在底面中心）
                    self._tf_probe = None          # 还没拖过 → 用默认高度（见 _solid_height）
                    self._refresh_focus_stage()
                    return                         # ← 不发 shapeFinished：仍是形状模式
                self._active = None
                self._base = None
                if base is not None:
                    self._image = base.copy()
                self._bump()
            finally:
                if not ok_stage:
                    self.shapeFinished.emit()      # 底面太小 → 当作误触，照常回退工具
            return
        if fig0 in _STAGE_FIGS and self._fig_origin:
            ox, oy = self._fig_origin
            pts_act0 = act.get("points") or []
            if len(pts_act0) >= 2:
                f1 = (float(pts_act0[0][0]), float(pts_act0[0][1]))
                f2 = (float(pts_act0[1][0]), float(pts_act0[1][1]))
                if fig0 == "sector":
                    # 扇形：f1 = 圆心（= 按下点，到 origin 恒为 0）→ 必须检查**半径长度**
                    ok_stage = math.hypot(f2[0] - f1[0], f2[1] - f1[1]) >= _SECTOR_MIN_R
                else:
                    ok_stage = math.hypot(f1[0] - ox, f1[1] - oy) >= _ELLIPSE_MIN_C
                if ok_stage:
                    self._tf_kind = fig0
                    self._tf_foci = (f1, f2)
                    # 探针立刻给默认值：两个手柄仍停在**两个焦点**上（_tf_active = -1），
                    # 同时把默认形状（椭圆：短轴 = max(c,24)；双曲线：渐近线 45°）画出来。
                    # 之后拖手柄 / 在画布其它位置拖动 → 探针改为鼠标位置，形状跟着变。
                    self._tf_active = -1
                    self._tf_probe = None          # 还没拖过 → 引导线仍是两焦点连线
                    self._fig_snap_kind = ""      # 提示只在拖拽中弹（见 _refresh_focus_stage）
                    self._fig_origin = None
                    self._last_pt = None
                    self._refresh_focus_stage()
                    return                        # ← 不发 shapeFinished：仍是形状模式
        self._active = None
        self._last_pt = None
        self._base = None
        self._fig_origin = None
        self._fig_snap_guide = None
        self._fig_snap_kind = ""
        self._fig_align = ""
        committed = False
        try:
            if act and _is_shape_stroke(act):
                pts_act = act.get("points") or []
                if _figure_of(act):
                    # 图形：按辅助矩形尺寸判定"误触"（轮廓首尾同点，不能用首末距）
                    axs = [p[0] for p in pts_act]
                    ays = [p[1] for p in pts_act]
                    big = (max(axs) - min(axs) >= 2.0 or max(ays) - min(ays) >= 2.0)
                else:
                    p0, p1 = pts_act[0], pts_act[1]
                    big = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) >= 2.0
                if big:
                    self._store_active_stroke(act)
                    committed = True
            if not committed and base is not None:
                self._image = base.copy()   # 误触/取消 → 抽掉预览
            self._bump()
        finally:
            self.shapeFinished.emit()

    # ---------- 两阶段图形第二阶段：拖探针定形（椭圆定 2a / 双曲线定渐近线）----------
    def _refresh_axes_stage(self):
        """坐标系第二阶段（空间直角坐标系的 z 轴）预览：按当前探针重算三根轴。

        `_active` = 第一笔（x 轴），其余（y 轴、z 轴）由 `_stage_preview_strokes` 现算；
        z 轴吸附成"与 y 轴等长"时弹提示「z、y 轴等长」（伪 id `axiseqz`）。
        """
        strokes, hit = self._axes_strokes()
        if not strokes:
            return
        if self._active is None:
            self._active = {"op": "pen", "style": _AXIS_ARROW_STYLE, "color": "",
                            "width": 4.0, "points": []}
        self._active["style"] = _AXIS_ARROW_STYLE
        self._active["points"] = [list(p) for p in strokes[0]["points"]]
        self._fig_snap_kind = "axiseqz" if hit else ""
        self._fig_align = ""
        self._fig_snap_guide = None
        self._redraw_active()
        self._bump()

    def _focus_stage_probe(self):
        """当前用于定形的探针：用户拖过就用它，否则用默认探针。

        （默认探针：椭圆 = 短轴上的点（半短轴 max(c, 24)）；双曲线 = 渐近线 45° 上的一点。
        这样一进入第二阶段就有个"不退化、不夸张"的形状可看，两条蓝色引导线则等真正
        拖动后才出现。）
        """
        if not self._tf_foci:
            return None
        if self._tf_probe is not None:
            return self._tf_probe
        if self._tf_kind in _AXIS_MENU_KINDS and self._ax_org is not None:
            # 空间直角坐标系第二步：还没拖过 → 默认探针 = "z 轴与 y 轴等长且指向上"
            # （用户要求：没完成第二步就切走/切页 → 生成**默认**空间直角坐标系）
            return (self._ax_org[0], self._ax_org[1] - float(self._ax_ylen))
        if self._sf_base is not None:
            # 立体图形第二阶段（升维）："探针" = 顶面中心；默认探针 = 默认高度处的顶面中心
            # （用户要求：没完成第二阶段就切走 → 生成一个默认立体图形）。
            # ⚠️ 三棱台第三步鼠标用来定"切顶面"而不是顶点 → 这里不能用默认探针代替
            # （`_sf_cut_rho()` 自己会退回默认 ρ，提交路径也不会用到本函数）。
            if self._sf_stage3():
                return None
            cx, cy = _solid_base_centre(self._sf_base)
            return (cx, cy - _solid_default_h(self._sf_base, self._sf_proj))
        f1, f2 = self._tf_foci
        if self._tf_kind == "sector":
            # 默认第二条半径 = 第一条半径旋转 90°（用户要求：未完成第二阶段就切走工具/改选形状
            # → 生成一个默认扇形，圆心角 90°）
            rx, ry = f2[0] - f1[0], f2[1] - f1[1]
            qx, qy = _sector_rot(rx, ry, _SECTOR_DEFAULT_DEG)
            return (f1[0] + qx, f1[1] + qy)
        cx, cy = (f1[0] + f2[0]) / 2.0, (f1[1] + f2[1]) / 2.0
        if self._tf_kind == "hyp":
            return _hyp_default_probe(cx, cy, f1)
        return _ellipse_default_probe(cx, cy, f1)

    def _stage_preview_strokes(self):
        """进行中的图形所需的"追加预览笔划"。

        双曲线第二阶段要同时显示 4 笔（两支线 + 两条渐近线，实/虚线不同）→ `_active` 装不下，
        这里按当前探针现算出来交给 `_redraw_active` 一起画；椭圆只有一笔轮廓，走 `_active` 即可。
        **还没拖过（`_tf_probe is None`）时不画任何预览**（用户要求：双曲线定完焦点也不显示
        渐近线/双曲线，拖动了才出现）。
        抛物线：曲线在 `_active` 里，第二笔（准线）在这里按"顶点 + 当前鼠标"现算。
        （**不做成额外状态**：现算就不会在"取消/清屏/切页"等路径上残留脏数据。）
        """
        act = self._active or {}
        if (self._ax_org is not None and act.get("style") == _AXIS_ARROW_STYLE):
            # 坐标系：`_active` = 第一根轴，其余几根轴（平面 = 纵轴；空间 = y 轴和 z 轴）在这里现算。
            # 不做成额外状态 → "取消/清屏/切页" 不会残留脏数据。
            strokes, _hit = self._axes_strokes()
            out = []
            for s in strokes[1:]:
                s2 = dict(s)
                s2["color"] = act.get("color", "")
                s2["width"] = act.get("width", 4.0)
                out.append(s2)
            return out
        if _figure_of(act) == "sphere" and self._fig_origin:
            # 球（一步成型）：主笔（轮廓圆）在 `_active` 里，另外 4 笔（两个椭圆各分
            # 实线/虚线两半）按当前半径现算 → 拖拽中就能看到完整的球。
            ox, oy = self._fig_origin
            pts0 = act.get("points") or []
            rr_s = (math.hypot(float(pts0[0][0]) - ox, float(pts0[0][1]) - oy)
                    if pts0 else 0.0)
            if rr_s < 1.0:
                return []                    # 刚按下（半径 ≈ 0）→ 不画退化的椭圆
            out = []
            for s in _solid_sphere_strokes("sphere", ox, oy, rr_s,
                                           self._sf_proj or _SOLID_PROJ_DEFAULT)[1:]:
                s["color"] = act.get("color", "")
                s["width"] = act.get("width", 4.0)
                out.append(s)
            return out
        if self._sf_base is not None:
            # 立体图形第二阶段：预览的**其余笔划**（可见棱 / 被遮挡棱）按当前高度现算。
            # 主笔（第一条折线）在 `_active` 里，所以这里跳过第 0 条。
            # **还没开始升维（`_tf_probe is None`）时一条都不画**：用户要求底面画完后
            # 不直接显示整个立体图形，只留底面 + 底面中心的手柄等待升维。
            # 三棱台第三步（拖"切顶面"）同理：还没拖过就不预览三棱台。
            # 三棱台**第二步**（升维出三棱锥）也不预览：用户要求此时只有底面是笔迹，
            # 其它轮廓线走蓝色虚线（`_sf_pyramid_guide`）。
            if self._tf_probe is None:
                return []
            if self._tf_kind in _SOLID_FRUSTUM_KINDS and not self._sf_stage3():
                return []
            out = []
            _dy0, _dz0 = self._sf_solid_params()
            _st0 = (_solid_frustum_strokes(self._tf_kind, self._sf_base, _dz0,
                                           self._sf_proj, _dy0, self._sf_cut_rho())
                    if self._tf_kind in _SOLID_FRUSTUM_KINDS
                    else _solid_strokes(self._tf_kind, self._sf_base, _dz0,
                                        self._sf_proj, _dy0))
            for s in _st0[1:]:
                s["color"] = act.get("color", "")
                s["width"] = act.get("width", 4.0)
                out.append(s)
            return out
        if _figure_of(act) == "para" and self._fig_origin:
            # 抛物线：曲线在 `_active` 里，第二笔（准线）在这里按"顶点 + 焦点"现算。
            # **焦点必须取 `_active` 的头部点**（已含横平竖直吸附），不能取原始鼠标位置：
            # 否则吸附时预览的准线角度与曲线/提交结果不一致（用户报的"准线没被吸附、
            # 换工具后才回正"就是这里用了 `_last_pt` 造成的）。
            ox, oy = self._fig_origin
            head = act.get("points") or []
            fx0, fy0 = ((float(head[0][0]), float(head[0][1]))
                        if head else (ox, oy))
            s = _parabola_figure_strokes(ox, oy, fx0, fy0)[1]
            s["color"] = act.get("color", "")
            s["width"] = act.get("width", 4.0)
            return [s]
        if self._tf_kind != "hyp" or not self._tf_foci or self._tf_probe is None:
            return []
        probe = self._focus_stage_probe()
        if probe is None:
            return []
        act = self._active or {}
        out = []
        for s in _hyperbola_figure_strokes(self._tf_foci[0], self._tf_foci[1], probe):
            s["color"] = act.get("color", "")
            s["width"] = act.get("width", 4.0)
            out.append(s)
        return out

    def _refresh_focus_stage(self):
        """按当前两焦点 + 探针重算第二阶段预览与引导线（按 `_tf_kind` 分派）。

        - 椭圆：`_active["points"]` = [F1,F2] + 轮廓；引导线 = 探针→两焦点（2 段，蓝色虚线）。
        - 双曲线：预览 4 笔由 `_stage_preview_strokes` 提供；引导线 = 几何重心→鼠标
          （正是被当作渐近线的那条连线），提示文字"渐近线"。
        没拖过（`_tf_probe is None`）时**不画图形本体**：椭圆只留两焦点、双曲线什么都不画
        （用户要求），引导线仍只画两焦点连线。
        """
        if not self._tf_foci:
            return
        if self._sf_base is not None:
            self._refresh_solid_stage()
            return
        if self._tf_kind in _AXIS_MENU_KINDS:
            # 空间直角坐标系第二步：三根轴的重算（若一旦进了第二步就只会是空间坐标系）
            self._refresh_axes_stage()
            return
        f1, f2 = self._tf_foci
        probe = self._tf_probe
        if self._tf_kind == "sector":
            # 扇形第二阶段：圆心 = f1、第一条半径 = f2−f1；第二条半径方向 = 圆心→鼠标
            # （半径长度不变），靠近 30°/45° 倍数时就近吸附。
            # 未拖动（probe 为 None）时**只显示圆心 + 第一条半径**（不画弧）。
            cx, cy = float(f1[0]), float(f1[1])
            rx, ry = float(f2[0]) - cx, float(f2[1]) - cy
            rr_s = math.hypot(rx, ry)
            if self._active is not None:
                if probe is None or rr_s <= 1e-9:
                    self._active["points"] = [[cx, cy], [cx + rx, cy + ry]]
                else:
                    sweep = self._sector_sweep(cx, cy, rx, ry, probe)
                    self._active["points"] = _sector_figure_points(cx, cy, rx, ry, sweep)
                self._redraw_active()
            self._fig_snap_guide = _guide_circle(cx, cy, rr_s) if rr_s > 1.0 else None
            self._fig_snap_kind = (("sector2" if probe is not None else "sector")
                                   if rr_s > 1.0 else "")
            self._fig_align = ""
            self._bump()
            return
        if self._tf_kind == "hyp":
            if probe is None:
                self._fig_snap_guide = [f1[0], f1[1], f2[0], f2[1]]
                self._fig_snap_kind = ""
                self._fig_align = ""
            else:
                cx = (f1[0] + f2[0]) / 2.0
                cy = (f1[1] + f2[1]) / 2.0
                # 引导线也用**夹好的探针**（与渐近线/支线同一角度，不会出现"引导线不在渐近线上"）
                cp = _hyp_clamped_probe(f1, f2, probe)
                self._fig_snap_guide = [cx, cy, cp[0], cp[1]]
                self._fig_snap_kind = "hypas"      # 提示文字"渐近线"
                self._fig_align = ""
            self._redraw_active()
            self._bump()
            return
        if probe is None:
            # 定完焦点先不显示椭圆（只看得到两焦点）
            if self._active is not None:
                self._active["points"] = [[float(f1[0]), float(f1[1])],
                                          [float(f2[0]), float(f2[1])]]
                self._redraw_active()
            self._fig_snap_guide = [f1[0], f1[1], f2[0], f2[1]]
            self._fig_snap_kind = ""
            self._fig_align = ""
            self._bump()
            return
        if self._active is not None:
            self._active["points"] = _ellipse_figure_points(f1, f2, probe)
            self._redraw_active()
        self._fig_snap_guide = [probe[0], probe[1], f1[0], f1[1],
                                probe[0], probe[1], f2[0], f2[1]]
        self._fig_snap_kind = "ellipse2"           # 提示文字"双焦半径"
        self._fig_align = ""
        self._bump()

    def _refresh_solid_stage(self):
        """立体图形第二阶段（升维）预览：按当前高度重算"可见棱 + 被遮挡棱"。

        `_active` 里放**第一条折线**（外轮廓），其余笔划由 `_stage_preview_strokes` 现算
        （与双曲线的"4 笔"同思路：`_active` 装不下多笔）。
        升维阶段**没有文字提示**、只有"底面中心 → 当前顶面中心"的竖直引导线（用户要求手柄
        图标是上下双向箭头）；**底面是正方形时**再有"正六面体吸附"：高度吸到边长，
        弹提示「正六面体」+ 在目标高度画一条水平引导线。
        """
        bpts = self._sf_base or []
        if not bpts:
            return
        frustum = self._tf_kind in _SOLID_FRUSTUM_KINDS
        stage3 = self._sf_stage3()
        # 顶点参数：三棱台第三步用第二步定下来的顶点，其余情况按鼠标现算
        dy, height = self._sf_solid_params()
        # **还没开始升维（`_tf_probe is None`）**：用户要求此时不预览整个立体图形（只留底面 +
        # 手柄等待升维）；三棱台第二步同理 —— 升维出来的三棱锥**只有底面是笔迹**，
        # 其它轮廓线用蓝色虚线（`_sf_pyramid_guide`），所以第二步不预览任何实体笔划。
        if self._tf_probe is not None and not (frustum and not stage3):
            strokes = (_solid_frustum_strokes(self._tf_kind, bpts, height, self._sf_proj, dy,
                                             self._sf_cut_rho())
                       if frustum else
                       _solid_strokes(self._tf_kind, bpts, height, self._sf_proj, dy))
            if strokes and self._active is not None:
                self._active["style"] = strokes[0]["style"]
                self._active["points"] = [list(p) for p in strokes[0]["points"]]
                self._redraw_active()
        self._fig_snap_kind = ""
        if frustum:
            # 三棱台：蓝色虚线轮廓 = **外层三棱锥的侧棱**（底面顶点 → 顶点）。第二步一拖动就
            # 出现；第三步（拖"切顶面"）全程保留 → 提交时由 `_commit_solid` 清掉（用户要求：
            # "这一步完成后，移除三棱锥的蓝色虚线轮廓线"）。
            self._fig_snap_guide = (self._sf_pyramid_guide()
                                    if (stage3 or self._tf_probe is not None) else None)
            if not stage3 and self._tf_probe is not None and self._sf_snap == "right":
                # 升维时"直三棱锥"吸附（用户要求；**不做正四面体吸附**）
                self._fig_snap_kind = "solidright"
        else:
            # 升维引导线：底面中心 → 当前第二个面中心（吸中时就是一根竖直线）。
            # 用户要求：第二个面中心跟随鼠标在 yOz 方向自由移动 → 这条橡皮筋就是它的轨迹。
            cx, cy = _solid_base_centre(bpts)
            px, py = _solid_second_centre(bpts, dy, height, self._sf_proj)
            # 还没开始升维（`_tf_probe is None`）时不画这条引导线（用户要求此时只留底面）
            self._fig_snap_guide = ([cx, cy, px, py]
                                    if (self._tf_probe is not None
                                        and (abs(dy) > 1e-9 or abs(height) > 1.0)) else None)
            # 吸附提示：① 贴近竖直线 → 「直三棱柱 / 直四棱柱 / 直圆柱 / 直圆锥」；
            #          ② 底面是正方形且高已吸到边长 → 「正六面体」（替掉直四棱柱）
            if self._sf_snap in ("cube", "tetra"):
                xs = [float(p[0]) for p in bpts]
                half = max(6.0, (max(xs) - min(xs)) / 2.0 + 12.0)
                self._fig_snap_kind = self._sf_snap
                self._fig_snap_guide = ((self._fig_snap_guide or [])
                                        + [px - half, py, px + half, py])
            elif self._sf_snap == "right":
                self._fig_snap_kind = "solidright"
        self._fig_align = ""
        self._bump()

    def _solid_base_sides(self):
        """底面各条边的长度（在**底面平面**里量 → 与升维高度同一套单位，可直接比较）。"""
        bpts = self._sf_base or []
        if len(bpts) < 3:
            return []
        p3 = [_solid_unproj(p[0], p[1], self._sf_proj) for p in bpts]
        n = len(p3)
        return [math.dist(p3[i][:2], p3[(i + 1) % n][:2]) for i in range(n)]

    def _solid_cube_target(self):
        """**正六面体吸附**的目标高度（升维）：底面是正方形时返回边长，否则 None。

        用户要求（四棱柱）：升维时具有正六面体吸附、吸附时提示「正六面体」。正六面体 =
        底面为正方形、且高 = 边长 —— 所以只在**底面是正方形**（四边形底面、四边长在 1% 内相等）
        时提供这个吸附；矩形底面不存在"正六面体"，不给。
        ⚠️ 用户要求（本轮）：**直四棱锥不做正六面体吸附** → 那种情况在 `_solid_snap_target`
        里提前排除（本函数只管"底面是不是正方形"这个几何事实）。
        侧面光滑的（圆柱 / 圆锥）也不给：底面是圆，不存在"正六面体"。
        """
        bpts = self._sf_base or []
        if self._tf_kind in _SOLID_SMOOTH_KINDS:
            return None      # 圆柱 / 圆锥：底面是圆，不存在"正六面体"
        if len(bpts) != 4:
            return None
        e = self._solid_base_sides()
        if max(e) - min(e) > 0.01 * max(e):
            return None                     # 不是正方形 → 不可能成为正六面体
        return sum(e) / len(e)

    def _solid_tetra_target(self):
        """**正四面体吸附**的目标高度（升维）：底面是正三角形时返回正四面体的高，否则 None。

        用户要求（三棱锥）：升维时具有正四面体吸附、吸附时提示「正四面体」。正四面体 =
        四个面都是等边三角形：底面正三角形边长为 s 时，顶点到底面中心（重心）的距离
            h = √(s² − (s/√3)²) = s·√(2/3) = s·√6/3
        （重心到顶点距离 = s/√3，故侧棱长 = √(h² + s²/3) = s ✓）。
        与正六面体一样，只在**底面是正三角形**（三边长在 1% 内相等）时提供。
        """
        bpts = self._sf_base or []
        if len(bpts) != 3:
            return None
        e = self._solid_base_sides()
        if max(e) - min(e) > 0.01 * max(e):
            return None                     # 不是正三角形 → 不可能是正四面体
        return sum(e) / len(e) * math.sqrt(6.0) / 3.0

    def _solid_snap_target(self):
        """升维时"立体图形吸附"的目标 → **(目标高度, 提示种类)**（种类 = ""/"cube"/"tetra"）。

        · 四棱柱 + 正方形底面 → 正六面体（高 = 边长）；
        · 三棱锥 + 正三角形底面 → 正四面体（高 = 边长 × √6/3）；
        · **四棱锥 → 一律不给**（用户要求：直四棱锥无需正六面体吸附）；
        · 其余（含圆柱/圆锥/三棱柱：底面不是正三角形/正方形）→ 没有。
        """
        if self._tf_kind == "tripyramid":
            t = self._solid_tetra_target()
            return (t, "tetra") if t is not None else (None, "")
        if self._tf_kind == "quadpyramid":
            return None, ""                 # 用户要求：直四棱锥不做正六面体吸附
        if self._tf_kind in _SOLID_FRUSTUM_KINDS:
            return None, ""                 # 用户要求：三棱台第二步**不做正四面体吸附**
        t = self._solid_cube_target()
        return (t, "cube") if t is not None else (None, "")

    def _solid_h_snap(self, h):
        """把升维高度按当前图形的"立体吸附目标"就近吸附（保留符号：向上/向下都成立）。

        返回 (高度, 是否吸中, 提示种类)；提示种类 = "cube"（正六面体）/ "tetra"（正四面体）。
        """
        t, kind = self._solid_snap_target()
        if t is None or h == 0.0:
            return h, False, ""
        if abs(abs(h) - t) <= _FIG_SNAP_PX:
            return (t if h > 0.0 else -t), True, kind
        return h, False, ""

    def _solid_height(self):
        """当前升维高度（纸面 px，沿 z；**可正可负**）—— = `_sf_solid_params()` 的 z 分量。

        保留这个名字是因为"高"在正六面体吸附/提交门槛等几处单独特指 z（测试也在用）。
        """
        return self._sf_solid_params()[1]

    # ---------- 三棱台（三步绘制）专用状态 ----------
    def _sf_stage3(self):
        """是否处于"三棱台第三步"（外层三棱锥已定、正在拖"切顶面"）。

        只有三棱台有第三步：`_tf_kind == "trifrustum"` 且顶点参数已经定下来。
        其它立体图形 `_sf_apex_*` 永远是 None → 行为与加台体之前完全一致。
        """
        return (self._tf_kind in _SOLID_FRUSTUM_KINDS and self._sf_base is not None
                and self._sf_apex_h is not None)

    def _sf_solid_params(self):
        """当前立体图形的顶点参数 **(dy, height)**。

        · 三棱台第三步：用第二步**已定下来**的顶点（此时鼠标是用来定"切顶面"的，不能再改顶点）；
        · 其它情况：按鼠标现算（= `_solid_shift()`，含"直柱体/直锥体"与立体吸附）。
        """
        if self._sf_stage3():
            return float(self._sf_apex_dy), float(self._sf_apex_h)
        return self._solid_shift()

    def _sf_goto_cut_stage(self):
        """三棱台：第二步松手 → 定下顶点、进入第三步（拖"切顶面"）。

        之后 `_tf_probe = None`（第三步还没拖过 → **不预览三棱台**，只画底面 + 外层三棱锥的
        蓝色虚线轮廓 + 体心手柄），与"底面画完后不直接显示整个立体图形"的约定同源。
        """
        dy, h = self._solid_shift()
        self._sf_apex_dy = float(dy)
        self._sf_apex_h = float(h)
        self._sf_snap = ""                  # 第三步没有吸附提示
        self._tf_probe = None
        self._tf_probe_dragging = False
        self._refresh_focus_stage()

    def _sf_cut_rho(self):
        """三棱台第三步：鼠标位置 → 顶面的**收缩比 ρ** ∈ [ρmin, 1−ρmin]。

        顶面顶点 T_i = 顶点 + ρ·(底面顶点 − 顶点) → 顶面中心也跟着沿"底面中心 → 顶点"移动。
        把鼠标投影到这条轴上取参数 t（0 = 底面中心、1 = 顶点）→ ρ = 1 − t，再夹住（用户要求：
        顶面必须在三棱锥范围内）。还没拖过（`_tf_probe is None`）→ 用默认 ρ（切在中间）。
        """
        if not self._sf_stage3() or self._tf_probe is None:
            return _SOLID_FRUSTUM_DEFAULT_RHO
        cx, cy = _solid_base_centre(self._sf_base)
        dy, h = self._sf_solid_params()
        ax, ay = _solid_second_centre(self._sf_base, dy, h, self._sf_proj)
        ux, uy = ax - cx, ay - cy
        ln2 = ux * ux + uy * uy
        if ln2 < 1e-9:
            return _SOLID_FRUSTUM_DEFAULT_RHO
        t = ((float(self._tf_probe[0]) - cx) * ux
             + (float(self._tf_probe[1]) - cy) * uy) / ln2
        return min(1.0 - _SOLID_FRUSTUM_RHO_MIN,
                   max(_SOLID_FRUSTUM_RHO_MIN, 1.0 - t))

    def _sf_pyramid_guide(self):
        """台体第一/二步的**蓝色虚线轮廓** = 外层锥体（三/四棱锥 / 圆锥）的轮廓线。

        用户要求（第二步）：升维出的锥体"只有底面以笔迹形式显示，其它轮廓线使用蓝色虚线"
        → 多边形底面时是各条侧棱（底面顶点 → 顶点）；**圆底面（圆台）时是圆锥的两条轮廓
        母线**（底面环切点 → 顶点）—— 不能把 128 个环点都连出去（那会画成一把伞）。
        切线不存在（虚顶点落在底面椭圆内）时退回画轴线（底面中心 → 顶点）。
        返回扁平的若干段 [x0,y0,x1,y1, ...]（QML 引导线层按 4 个数一段画）。
        """
        bpts = self._sf_base or []
        if not bpts:
            return None
        cx, cy = _solid_base_centre(bpts)
        dy, h = self._sf_solid_params()
        ax, ay = _solid_second_centre(bpts, dy, h, self._sf_proj)
        if self._tf_kind in _SOLID_CFRUSTUM_KINDS:
            _ux, uy, uz, _vx, vy, vz = _solid_proj_coeff(self._sf_proj)
            off = (uy * dy + uz * h, vy * dy + vz * h)
            sil = _solid_cone_sil_idx(self._sf_proj, bpts, off, len(bpts))
            if sil is None:
                return [float(cx), float(cy), ax, ay]
            out = []
            for i in sil:
                out += [float(bpts[i][0]), float(bpts[i][1]), ax, ay]
            return out
        out = []
        for p in bpts:
            out += [float(p[0]), float(p[1]), ax, ay]
        return out if out else None

    def _solid_shift(self):
        """当前第二个面相对底面中心的 3D 平移 **(dy, dz)**（用户要求：升维时第二个面的中心
        跟随鼠标终点移动，可在 **yOz 方向自由移动** —— 沿 y 轴平移 + 沿 z 轴升降，不往 x 方向跑）。

        鼠标纸面位置 → (dy, dz) 是唯一确定的（`_solid_shift_from` 解 2×2 线性方程组），
        然后就地吸附：
          · **直柱体吸附**：鼠标贴近"过底面中心的竖直线"（纸面垂直距离 ≤ `_FIG_SNAP_PX`）
            → dy 归 0（侧棱垂直于底面）→ 提示「直三棱柱 / 直四棱柱 / 直圆柱 /
            直三棱锥 / 直四棱锥 / 直圆锥」（`_sf_snap = "right"`）；
          · **立体吸附**：已在竖直线上、且底面是正三角形 / 正方形、|dz| 已接近目标高度 →
            dz 吸到目标，提示「正四面体」（三棱锥）/「正六面体」（四棱柱）
            （`_sf_snap = "tetra" / "cube"`，替掉"直X棱锥/直四棱柱"）。
            ⚠️ 用户要求：**直四棱锥不做正六面体吸附**（`_solid_snap_target` 里排除）。
        **符号有意义**：dz > 0 → 第二个面在原底面上方；dz < 0 → 拖到下方（原底面成为顶面）。
        还没拖过（`_tf_probe is None`）→ 默认：沿 z 向上的直柱体（`_solid_default_h`）。
        """
        self._sf_snap = ""
        bpts = self._sf_base or []
        if not bpts:
            return 0.0, 0.0
        if self._tf_probe is None:
            return 0.0, _solid_default_h(bpts, self._sf_proj)
        cx, cy = _solid_base_centre(bpts)
        # 先看鼠标是否贴近竖直线（屏幕判定）→ 是则 dy = 0（保留竖直方向上的投影长度）
        t_v, dist_v = _solid_vertical_offset(self._tf_probe, cx, cy, self._sf_proj)
        if dist_v <= _FIG_SNAP_PX:
            dy, dz = 0.0, t_v
            self._sf_snap = "right"
        else:
            dy, dz = _solid_shift_from(cx, cy, self._tf_probe, self._sf_proj)
        # 按住没动（位移极小）→ 压在 1px，避免预览跳空；真提交时由 `_SOLID_MIN_H` 拦误触
        if abs(dz) < 1.0 and abs(dy) < 1.0:
            dz = 1.0 if dz >= 0.0 else -1.0
        # 立体吸附：底面是正三角形 / 正方形 + 已经竖直 + 高已接近目标 → 吸到目标高度
        if abs(dy) < 1e-9:
            dz2, hit, k2 = self._solid_h_snap(dz)
            if hit:
                dz = dz2
                self._sf_snap = k2
        return dy, dz

    def _commit_solid(self, emit_finished):
        """提交立体图形：底面 + 升维的**多笔**（可见棱实线 / 被遮挡棱虚线）一次落盘。

        与双曲线同理：多笔**只压一条 add_many 撤销**（一次撤销移除整个立体图形）；
        并且所有笔划带同一个 `grp`（分组 id）→ 圈选时当作一个整体（被橡皮切分时清空）。
        """
        kind = self._tf_kind
        bpts = self._sf_base or []
        act = self._active
        self._tf_probe_dragging = False
        frustum = kind in _SOLID_FRUSTUM_KINDS
        stage3 = self._sf_stage3()
        # **三棱台第二步松手 → 不提交**：把顶点定下来、进入第三步（拖"切顶面"），
        # 此时蓝色虚线轮廓保持、手柄改弹在整个三棱锥的体心（用户要求）。
        # ⚠️ 只有"用户自己松手"（emit_finished=True）才进第三步；切工具/切页/关画板
        #    走 emit_finished=False → 直接按"默认三棱台"补完（用户要求），不再多出一步。
        if frustum and bpts and not stage3 and emit_finished and self._tf_probe is not None:
            self._sf_goto_cut_stage()
            return
        # 位移太小（拖到底面附近 / 误触）→ 不提交（与其它图形"过短丢弃"一致）。
        # 三棱台第三步的鼠标是用来定"切顶面"的（默认可落在体心上），不受这个门槛约束。
        raw_d = None
        if not stage3 and self._tf_probe is not None and bpts:
            _cx, _cy = _solid_base_centre(bpts)
            raw_d = math.hypot(float(self._tf_probe[0]) - _cx,
                               float(self._tf_probe[1]) - _cy)
        ok_d = stage3 or (raw_d is None) or (raw_d >= _SOLID_MIN_H)
        dy, height = self._sf_solid_params()
        if frustum:
            strokes = (_solid_frustum_strokes(kind, bpts, height, self._sf_proj, dy,
                                              self._sf_cut_rho())
                       if (bpts and ok_d) else [])
        else:
            strokes = (_solid_strokes(kind, bpts, height, self._sf_proj, dy)
                       if (bpts and ok_d) else [])
        color = (act or {}).get("color", "")
        width = (act or {}).get("width", 4.0)
        # ⚠️ **台体特有**：预览与最终笔划**不一致**（第二步按用户要求"只有底面是笔迹"、
        # 第三步没拖过时也不预览）→ 若只落盘不重画，`_image` 里只有底面（默认台体"没立即
        # 画出来 / 形状看起来消失"，要等下一次整幅重绘才出现，用户报的正是这个）。
        # 其它立体图形的预览 == 提交结果，不需要这一步。修法：拿提交前的快照 `_base`
        # （仅含已完成笔划）重画"快照 + 最终笔划"，与 `_redraw_active` 同一套。
        base_img = self._base if frustum else None
        self._drop_focus_stage()          # 含 _sf_base / _tf_foci 的复位
        self._active = None
        self._base = None
        self._last_pt = None
        self._fig_origin = None
        self._fig_snap_guide = None
        self._fig_snap_kind = ""
        self._fig_align = ""
        try:
            if strokes:
                gid = _new_grp()
                ids = []
                for s in strokes:
                    s["color"] = color
                    s["width"] = width
                    _set_grp(s, gid)
                    self._store_active_stroke(s, undo=False)
                    if s.get("id") is not None:
                        ids.append(int(s["id"]))
                if ids:
                    self._push_undo({"type": "add_many", "ids": ids})
                if base_img is not None and not base_img.isNull():
                    # 台体：把"快照 + 最终笔划"画回 `_image`（预览里没有这些笔划）
                    self._image = base_img.copy()
                    _p = QPainter(self._image)
                    _p.setRenderHint(QPainter.Antialiasing)
                    for s in strokes:
                        _draw_stroke(_p, s, self._light)
                    _p.end()
            self._bump()
        finally:
            if emit_finished:
                self.shapeFinished.emit()

    def _sector_sweep(self, cx, cy, rx, ry, probe):
        """扇形第二条半径的带符号圆心角（度）——**有状态**：拖拽中累计转角（可 > 180°）。

        侧别规则（用户要求）：
        ① 刚按下（本次拖拽首帧）→ 取"使圆心角 < 180° 的那一侧"（= 带符号角本身，(-180,180]）；
           恰好 0°/180° 时取**第一条半径的顺时针方向**一侧（正 = 屏幕顺时针）；
        ② 拖拽中把"上一帧方向 → 当前方向"的**带符号增量**累加 → 第二条半径掠过第一条半径时
           圆心角会继续增大（越过 180°）而不是跳到小角一侧；
        ③ 圆心角 < 1° → 夹到 1°（保留侧别；正好 0° 算顺时针侧）；
        ④ **转满一圈（360°）后接着转不卡手**：圆心角从 1° 重新开始增大（回到同一侧的小扇形）。

        长度 = 第一条半径（扇形定义），方向 = 圆心→鼠标；靠近 30°/45° 的倍数时就近吸附
        （阈值 = 12px 在半径处的等效角，上限 15°）。返回值是**吸附后**的角度（几何与提示共用）。
        """
        rr = math.hypot(rx, ry)
        if rr <= 1e-9:
            self._sector_sweep_cur = _SECTOR_DEFAULT_DEG
            return self._sector_sweep_cur
        ux, uy = rx / rr, ry / rr
        mvx, mvy = float(probe[0]) - cx, float(probe[1]) - cy
        ml = math.hypot(mvx, mvy)
        if ml <= 1e-9:
            self._sector_sweep_cur = _SECTOR_DEFAULT_DEG
            return self._sector_sweep_cur
        raw = _sector_angle(ux, uy, mvx / ml, mvy / ml)      # (-180, 180]
        if self._sector_last_raw is None:
            acc = raw                                       # 首帧：较小角那一侧（规则①）
        else:
            d = raw - self._sector_last_raw
            if d > 180.0:
                d -= 360.0                                  # 增量折算到 (-180, 180]
            elif d < -180.0:
                d += 360.0
            acc = self._sector_acc + d
        self._sector_last_raw = raw
        if acc > 360.0 or acc < -360.0:                     # ④ 转满一圈还在转 → 从 1° 重新开始
            sgn = 1.0 if acc >= 0.0 else -1.0
            acc = sgn * ((abs(acc) - _SECTOR_MIN_DEG) % 360.0 + _SECTOR_MIN_DEG)
        disp = acc
        if abs(disp) < _SECTOR_MIN_DEG:                     # ③ 太小 → 1°（保留侧别；0° 记顺时针）
            disp = _SECTOR_MIN_DEG if disp >= 0.0 else -_SECTOR_MIN_DEG
        thr = min(15.0, math.degrees(math.asin(min(1.0, _FIG_SNAP_PX / max(rr, 1e-6)))))
        best = None
        for m in _SECTOR_SNAP_DEGS:
            d2 = abs(abs(acc) - m)
            if d2 <= thr and (best is None or d2 < best[0]):
                best = (d2, m)
        if best is not None:
            disp = (1.0 if acc >= 0.0 else -1.0) * best[1]
        self._sector_acc = acc                              # 累计值始终跟未吸附、未夹角的原值走
        self._sector_sweep_cur = disp
        return disp

    def _sector_angle_display(self):
        """当前扇形预览的圆心角（度）——提示文字「圆心角 xx°」用（无副作用）。"""
        if self._tf_kind != "sector" or not self._tf_foci:
            return _SECTOR_DEFAULT_DEG
        return abs(self._sector_sweep_cur)

    # ---------- 多边形随心画（fig:polfree）：多步逐边绘制 ----------
    def _pf_begin(self, idx, x, y):
        """开始画下一条边：idx = 0/1 = 按的是哪个手柄（即链的首/尾端）；-1 = 画布任意位置。"""
        pts = self._pf_pts
        if not pts or len(pts) < 2:
            return
        if idx == 0:
            pick = 0
        elif idx == 1:
            pick = len(pts) - 1
        else:
            pick = _pf_nearest_end_idx(pts, x, y)
        if pick == 0:
            # 从链首接着画 → 把链倒过来，让"继续画的那一端"永远在链尾（追加即可）
            self._pf_pts = [[float(p[0]), float(p[1])] for p in reversed(pts)]
        self._pf_drawing = True
        self._tf_probe_dragging = True      # 拖拽中：手柄视觉隐藏（FocusHandles 读它）
        self._pf_probe = [float(x), float(y)]
        self._pf_end = [float(x), float(y)]
        self._pf_angle = 0.0
        self._pf_on_end = False
        self._refresh_polfree()

    def _refresh_polfree(self):
        """按当前鼠标位置重算"正在画的那条边" + 引导线 + 提示。

        吸附优先级（用户要求，从大到小）：
        ① 闭合多边形吸附（鼠标靠近"另一端未连线的端点"）→ 提示「闭合形状」；
        ② 等长/平行吸附（正在画的边 或 缺口连线与已有边等长/平行）→ 提示「平行」/「等长」
           （+ 蓝色 2px 描边命中的边；命中缺口连线时把蓝色虚线加粗）；
        ③ 30°/45° 倍数夹角吸附。
        **等长与角度吸附不互斥**（等长只改长度、角度只改方向）→ 同时命中就一起生效；
        而"平行"与角度吸附互斥（都改方向）→ 平行优先。
        **不管哪种吸附，夹角处一律出角度文字提示**（提示文字始终 = 最终几何的内角）。
        """
        pts = self._pf_pts
        if not pts or len(pts) < 2:
            return
        redraw = False
        if self._pf_drawing and self._pf_probe is not None:
            mx, my = float(self._pf_probe[0]), float(self._pf_probe[1])
            far = pts[0]
            # ③ 先把"角度吸附"的结果算出来（后面三种吸附都要用它 —— 等长可与它共存）
            ang_end, ang_deg = _pf_edge_snap(pts[-2], pts[-1], mx, my)
            # ① 鼠标靠近"另一端还没连线的端点" → 吸上去闭合（至少已有两条边才谈得上闭合）
            on_end = (len(pts) >= 3
                      and math.hypot(mx - far[0], my - far[1]) <= _FIG_SNAP_PX)
            self._fig_align = ""
            self._pf_para_ref = None
            self._pf_eq_ref = None
            self._pf_hi = None
            self._pf_hi_gap = False
            if on_end:
                self._pf_end = [float(far[0]), float(far[1])]
                self._fig_snap_kind = "polfree"
            else:
                # ② 等长/平行（也可与角度吸附组合）
                sol = _pf_snap_solution(pts, (mx, my), ang_end)
                if sol is not None:
                    self._pf_end = [float(sol[0][0]), float(sol[0][1])]
                    self._pf_para_ref = sol[1]
                    self._pf_eq_ref = sol[2]
                    self._pf_hi_gap = bool(sol[3])
                    if sol[1] is not None:
                        self._fig_snap_kind = "pfpara"
                        if sol[2] is not None:
                            self._fig_align = "eq"      # 同时等长 → 第二个提示：「等长」
                    else:
                        self._fig_snap_kind = "pfeq"
                    self._pf_hi = _pf_highlight_segs(pts, sol)
                else:
                    # 只有角度吸附 → 主提示不显示（只有夹角处的角度文字提示）
                    self._pf_end = [float(ang_end[0]), float(ang_end[1])]
                    self._fig_snap_kind = ""
            # 夹角文字提示（平行/等长/闭合时**照样显示**）：文字 = 最终几何的内角，
            # 锚点 = 角平分线上距顶点 28px 处（QML 把胶囊以该点为中心摆放）
            self._pf_angle = _pf_interior_angle(pts[-2], pts[-1], self._pf_end)
            self._pf_anchor = _pf_bisect_pt(pts[-2], pts[-1], self._pf_end)
            self._pf_on_end = on_end
            verts = [[float(p[0]), float(p[1])] for p in pts] + [list(self._pf_end)]
            if self._active is not None:
                self._active["points"] = verts
                redraw = True
            self._fig_snap_guide = ([verts[0][0], verts[0][1], verts[-1][0], verts[-1][1]]
                                    if len(verts) >= 3 else None)
        else:
            # 没在拖：链本身 + "两个未连线的端点"之间的蓝色虚线
            verts = [[float(p[0]), float(p[1])] for p in pts]
            if self._active is not None:
                self._active["points"] = verts
                redraw = True
            self._fig_snap_guide = ([verts[0][0], verts[0][1], verts[-1][0], verts[-1][1]]
                                    if len(verts) >= 3 else None)
            self._fig_snap_kind = ""
            self._fig_align = ""
            self._pf_angle = 0.0
            self._pf_anchor = None
            self._pf_para_ref = None
            self._pf_eq_ref = None
            self._pf_hi = None
            self._pf_hi_gap = False
        if redraw:
            self._redraw_active()
        self._bump()

    def _pf_end_drag(self):
        """松开：把这条边接到链上（停在另一端点上则直接闭合提交）。"""
        if not self._pf_drawing:
            return
        self._pf_drawing = False
        self._tf_probe_dragging = False
        pts = self._pf_pts
        if not pts or len(pts) < 2:
            return
        if self._pf_on_end:
            self._pf_commit_closure(True)
            return
        end = self._pf_end or list(pts[-1])
        if math.hypot(end[0] - pts[-1][0], end[1] - pts[-1][1]) >= _PF_MIN_STEP:
            self._pf_pts = [[float(p[0]), float(p[1])] for p in pts] + [list(end)]
        self._pf_probe = None
        self._refresh_polfree()

    def _pf_commit_closure(self, emit_finished):
        """闭合多边形并提交（`emit_finished` = 是否发 shapeFinished 回退工具）。"""
        pts = self._pf_pts
        act = self._active
        self._pf_drawing = False
        self._tf_probe_dragging = False
        close_ok = bool(pts) and len(pts) >= 3 and act is not None
        self._pf_pts = None
        self._pf_probe = None
        self._pf_end = None
        self._pf_angle = 0.0
        self._pf_on_end = False
        self._last_pt = None
        self._fig_origin = None
        # ⚠️ `_base` **不能提前清**：下面闭合那一步要用它当底图重画（`_redraw_active()` 在
        # `_base is None` 时会直接 return → 闭合边不会立即显示，用户报的"切工具后多边形没闭合"）
        try:
            if close_ok:
                # 缺口闭合：首点再追加一次（首尾同点 → 与其它图形一样是"闭合轮廓"）
                verts = [[float(p[0]), float(p[1])] for p in pts]
                verts.append([verts[0][0], verts[0][1]])
                act["points"] = verts
                self._active = act
                self._redraw_active()
                self._store_active_stroke(act)
            self._base = None
            self._active = None
            self._fig_snap_guide = None
            self._fig_snap_kind = ""
            self._fig_align = ""
            self._bump()
        finally:
            if emit_finished:
                self.shapeFinished.emit()

    def _pf_finish(self):
        """多步流程被"切走工具 / 改选其它形状"打断：结束当前边、**直接把缺口闭合**后提交。

        与 `finishFocusStage` 同规则：收尾时**不发 shapeFinished**（用户刚选的工具要保持）。
        只有一条边（没法闭合）时有长度就当一条开链提交，否则丢弃。
        """
        if self._pf_pts is None:
            return
        if self._pf_drawing:
            self._pf_end_drag()
            if self._pf_pts is None:
                return                  # 已经在 _pf_end_drag 里闭合提交了
        pts = [[float(p[0]), float(p[1])] for p in self._pf_pts]
        act = self._active
        self._pf_pts = None
        self._pf_drawing = False
        self._pf_probe = None
        self._pf_end = None
        self._pf_angle = 0.0
        self._pf_on_end = False
        self._tf_probe_dragging = False
        self._last_pt = None
        self._fig_origin = None
        # ⚠️ 同上：`_base` 必须在 `_redraw_active()` **之后**才清——切工具时要把"缺口闭合"
        # 后的多边形立刻画上去（不然用户看到还是没闭合的旧预览，要等下次整幅重绘才出现）
        try:
            if act is not None:
                if len(pts) >= 3:
                    pts.append([pts[0][0], pts[0][1]])   # 缺口直接闭合
                    act["points"] = pts
                    self._active = act
                    self._redraw_active()
                    self._store_active_stroke(act)
                elif (len(pts) == 2
                      and math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
                      >= _PF_MIN_EDGE):
                    act["points"] = pts
                    self._store_active_stroke(act)
            self._base = None
            self._active = None
            self._fig_snap_guide = None
            self._fig_snap_kind = ""
            self._fig_align = ""
            self._bump()
        except Exception:
            plugin_logger.debug("多边形随心画收尾失败", exc_info=True)

    @Slot(int, float, float)
    def beginFocusProbe(self, idx, x, y):
        """按下探针：idx = 0/1 表示按的是哪个焦点手柄（手柄跟鼠标走）；
        **idx = -1 表示在画布其它位置按下**（自由探针，两个手柄都停在焦点上）。
        多边形随心画（多步绘制）复用同一入口：idx = 0/1 = 链的首/尾端手柄，-1 = 任意位置。
        """
        if self._pf_pts is not None:
            self._pf_begin(int(idx), x, y)
            return
        if not self._tf_foci:
            return
        idx = int(idx)
        self._tf_active = idx if 0 <= idx <= 1 else -1
        # 坐标系第二步：按下**不算拖过**（`_tf_probe` 保持 None）→ z 轴仍不显示；
        # 真正拖拽时 `dragFocusProbe` 再写入探针（否则"按住不动就松手"会提交一根 1px 的 z 轴，
        # 与"没继续绘制 → 默认 z 轴"的意图相反）。手柄与画布任意位置同理。
        if self._tf_kind not in _AXIS_MENU_KINDS:
            self._tf_probe = (float(x), float(y))
        self._tf_probe_dragging = True
        # 新一次拖拽 → 转角累计重新开始（首帧按“使圆心角 < 180° 的那一侧”）
        self._sector_last_raw = None
        self._sector_acc = 0.0
        self._refresh_focus_stage()

    @Slot(float, float)
    def dragFocusProbe(self, x, y):
        """拖探针中（手柄或画布任意位置）：探针跟鼠标 → 实时重算形状。
        椭圆：2a = |P−F1| + |P−F2|；双曲线：几何重心→鼠标 的连线就是一条渐近线。
        多边形随心画：顶点→鼠标 就是正在画的那条边（做内角吸附）。
        """
        if self._pf_pts is not None:
            if not self._pf_drawing:
                return
            self._pf_probe = [float(x), float(y)]
            self._refresh_polfree()
            return
        if not self._tf_foci or self._active is None:
            return
        self._tf_probe = (float(x), float(y))
        self._refresh_focus_stage()

    @Slot()
    def endFocusProbe(self):
        """松开探针：提交形状并发 shapeFinished → 工具回退（椭圆 1 笔 / 双曲线 4 笔）。
        多边形随心画：只结束当前这条边（闭合时才提交 + 回退工具）。
        """
        if self._pf_pts is not None:
            self._pf_end_drag()
            return
        self._commit_focus_stage(True)

    def finishFocusStage(self):
        """第二阶段被"切走工具 / 改选其它形状"打断时收尾：按默认探针补出形状并**提交**。

        用户要求：焦点绘制完成后若直接切到选择/笔/橡皮（或在形状菜单里改选另一种形状），
        就按默认逻辑根据两焦点直接生成形状，并**进入新选中的工具的绘制模式**；此时工具已由
        用户切走，故**不发 shapeFinished**（否则会把用户刚选的工具又回退掉）。
        若用户已经拖出了探针，就用当前探针（保持所见即所得）。

        由插件在 `LessonsBackend.activeToolChanged` / `lineStyleChanged` 里调用
        （普通方法，仅 Python 调用）。

        多边形随心画（多步绘制）同理：切工具/改选形状时**直接把缺口闭合**后提交。
        """
        if self._pf_pts is not None:
            self._pf_finish()
            return
        if not self._tf_foci:
            return
        if self._tf_probe is None:
            # 还没拖过 → 先把默认探针写进状态并重算，再把图形提交出去
            self._tf_probe = self._focus_stage_probe()
            self._refresh_focus_stage()
        self._commit_focus_stage(False)

    def _commit_focus_stage(self, emit_finished):
        """提交第二阶段定形的图形：椭圆 1 笔 / 双曲线 4 笔（两支 + 两条渐近线）。

        emit_finished=True 时发 shapeFinished 回退工具。只有真画出了轮廓才提交
        （防御性地挡掉"只有两焦点就切走"的异常）。
        """
        kind = self._tf_kind
        foci = self._tf_foci
        if kind in _AXIS_MENU_KINDS:
            # 坐标系（空间直角坐标系第二步）走自己的提交（多根箭头线 + 分组）。
            # `force_z=True`：拖过就用鼠标的 z，没拖过就用**默认 z**（= y 轴长、朝上）
            # —— 用户要求：切工具/切形状/切页/关白板时也要交出完整的空间直角坐标系。
            strokes, _hit = self._axes_strokes(True)
            self._commit_axes(strokes, emit_finished)
            return
        if self._sf_base is not None:
            # 立体图形（底面 + 升维）走自己的提交（多笔 + 分组，见 `_commit_solid`）
            self._commit_solid(emit_finished)
            return
        probe = self._focus_stage_probe()
        act = self._active
        self._tf_probe_dragging = False
        self._drop_focus_stage()
        self._active = None
        self._base = None
        self._last_pt = None
        self._fig_origin = None
        self._fig_snap_guide = None
        self._fig_snap_kind = ""
        self._fig_align = ""
        try:
            if kind == "hyp" and foci and probe:
                # 双曲线：现算 4 笔（颜色/粗细沿用画笔设置）后逐笔落盘，
                # **但只压一条 add_many 撤销** —— 用户要求"一次撤销移除整个双曲线"
                color = (act or {}).get("color", "")
                width = (act or {}).get("width", 4.0)
                ids = []
                for s in _hyperbola_figure_strokes(foci[0], foci[1], probe):
                    s["color"] = color
                    s["width"] = width
                    self._store_active_stroke(s, undo=False)
                    if s.get("id") is not None:
                        ids.append(int(s["id"]))
                if ids:
                    self._push_undo({"type": "add_many", "ids": ids})
            elif act and _figure_of(act) in _STAGE_FIGS:
                ink = _fig_ink_pts(_figure_of(act), act.get("points") or [])
                if len(ink) >= 3:
                    self._store_active_stroke(act)
            self._bump()
        finally:
            if emit_finished:
                self.shapeFinished.emit()

    @Property('QVariantList', notify=imageVersionChanged)
    def focusProbeHandles(self):
        """两阶段图形第二阶段的两个手柄 [[x,y],[x,y]]：

        刚进入该阶段时 = 两个焦点（用户要求手柄出现在两焦点位置）；拖手柄时那个手柄跟鼠标走，
        在画布其它位置自由拖拽时两个手柄留在焦点上（不抢鼠标）。
        多边形随心画：手柄 = **链的两个未连线端点**（拖哪一端就从那一端接着画）。
        """
        if self._pf_pts is not None and len(self._pf_pts) >= 2:
            return [[float(self._pf_pts[0][0]), float(self._pf_pts[0][1])],
                    [float(self._pf_pts[-1][0]), float(self._pf_pts[-1][1])]]
        if not self._tf_foci:
            return []
        if self._tf_kind in _AXIS_MENU_KINDS and self._ax_org is not None:
            # 坐标系第二阶段（空间直角坐标系第二步）：**只一个手柄**，位于**坐标原点**
            return [[float(self._ax_org[0]), float(self._ax_org[1])]]
        if self._sf_base is not None:
            # 立体图形第二阶段：**只一个手柄**，位于**底面中心**（用户细则：绘制完底面就在
            # 底面中心弹出手柄）。图标是上下双向箭头（见 focusHandleIcon）→ 拖它只能改高度；
            # 拖拽中手柄视觉会隐藏（与其它两阶段图形一致），所以不必让它跟着鼠标跑。
            # 三棱台第三步：手柄改弹在**整个三棱锥的体心**（用户要求），样式不变（仍是双向箭头）。
            # 台体第三步：手柄改弹在**整个外层锥体的体心**（用户要求），样式不变（仍是双向箭头）。
            # 体心 = 底面中心 + (顶点 − 底面中心)/4 —— 正四面体（=(3C+A)/4）与四棱锥
            # （= 0.75C + 0.25A）、圆锥（= 1/4 高处）三者的体心都是这个式子 ✓
            cx, cy = _solid_base_centre(self._sf_base)
            if self._sf_stage3():
                dy, h = self._sf_solid_params()
                ax, ay = _solid_second_centre(self._sf_base, dy, h, self._sf_proj)
                return [[cx + (ax - cx) / 4.0, cy + (ay - cy) / 4.0]]
            return [[cx, cy]]
        if self._tf_kind == "sector":
            # 扇形：**只一个手柄**，位于第一条半径的中点（拖动它、或在画布任意位置拖动
            # 都能定第二条半径；拖拽中 QML 会隐藏手柄视觉）
            cx, cy = float(self._tf_foci[0][0]), float(self._tf_foci[0][1])
            rx, ry = float(self._tf_foci[1][0]), float(self._tf_foci[1][1])
            return [[(cx + rx) / 2.0, (cy + ry) / 2.0]]
        f = [[float(self._tf_foci[0][0]), float(self._tf_foci[0][1])],
             [float(self._tf_foci[1][0]), float(self._tf_foci[1][1])]]
        if self._tf_probe is not None and 0 <= self._tf_active <= 1:
            f[self._tf_active] = [float(self._tf_probe[0]), float(self._tf_probe[1])]
        return f

    @Property(bool, notify=imageVersionChanged)
    def focusProbeActive(self):
        """是否处于第二阶段（两焦点/扇形半径/多边形端点的手柄可拖）。"""
        return self._pf_pts is not None or self._tf_foci is not None

    @Property(bool, notify=imageVersionChanged)
    def focusProbeDragging(self):
        """是否正在拖探针/边（手柄按下 或 画布上按下拖动）——提示胶囊与手柄隐藏据此判断。"""
        return ((self._pf_pts is not None or self._tf_foci is not None)
                and self._tf_probe_dragging)

    @Property('QVariantList', notify=imageVersionChanged)
    def focusProbePoint(self):
        """当前探针位置 [x,y]（没在拖时为空）——提示胶囊在"拖手柄"时也用它定位。"""
        if self._pf_pts is not None:
            if not self._tf_probe_dragging or not self._pf_probe:
                return []
            return [float(self._pf_probe[0]), float(self._pf_probe[1])]
        if not self._tf_foci or not self._tf_probe_dragging or self._tf_probe is None:
            return []
        return [float(self._tf_probe[0]), float(self._tf_probe[1])]

    @Property(str, notify=imageVersionChanged)
    def focusHandleIcon(self):
        """第二阶段手柄里的图标：立体图形 = **上下双向箭头**（升维）；其它 = 移动图标。

        用户要求：升维手柄的样式与焦点手柄一致，但图标用
        `ic_fluent_arrow_bidirectional_up_down_20_regular`。
        """
        if self._sf_base is not None or self._tf_kind in _AXIS_MENU_KINDS:
            return "ic_fluent_arrow_bidirectional_up_down_20_regular"
        return "ic_fluent_arrow_move_20_regular"

    # ---------- 立体图形：测画方式（正等测 / 斜二测）----------
    def _solid_mode_changed(self):
        self.solidProjChanged.emit()
        self._bump()

    @Property(str, notify=solidProjChanged)
    def solidProjMode(self):
        """用户选择的**测画方式**（"iso" 正等测 / "oblique" 斜二测），默认正等测。

        只在形状菜单里选中**支持选择的立体图形**（圆柱 / 圆锥，见 `_SOLID_PROJ_CHOOSABLE`）
        时才生效 —— 其它立体图形仍然固定用斜二测。
        本次绘制的测画方式在**按下底面那一刻**定下来（`beginLine` → `_sf_proj`），
        所以画到一半改选择不会把已画的底面/预览弄乱。
        """
        m = self._solid_proj_mode
        return m if m in _SOLID_PROJ_KINDS else _SOLID_PROJ_DEFAULT

    @solidProjMode.setter
    def solidProjMode(self, mode):
        m = str(mode or "")
        if m not in _SOLID_PROJ_KINDS or m == self._solid_proj_mode:
            return
        self._solid_proj_mode = m
        self._solid_mode_changed()

    @Slot(str)
    def setSolidProjMode(self, mode):
        """QML 槽：设置测画方式（与 `solidProjMode` 属性等价，写法更直白）。"""
        self.solidProjMode = mode

    @Property("QVariantList", constant=True)
    def solidProjItems(self):
        """测画方式菜单的条目（顺序即菜单顺序）：正等测在前（默认）、斜二测在后。"""
        return [{"id": k, "name": _SOLID_PROJ_NAMES[k]} for k in _SOLID_PROJ_KINDS]

    @Slot(str, result=bool)
    def solidProjChoosable(self, kind):
        """该立体图形是否支持让用户选测画方式（圆柱 / 圆锥）→ QML 决定是否弹菜单。"""
        return str(kind or "") in _SOLID_PROJ_CHOOSABLE

    @Property(str, notify=imageVersionChanged)
    def focusProbeKind(self):
        """正在定形的图形 id（"ellipse" / "hyp" / "sector" / "polfree"）；不在该阶段为空。"""
        if self._pf_pts is not None:
            return "polfree"
        return self._tf_kind if self._tf_foci else ""

    @Property(int, notify=imageVersionChanged)
    def imageVersion(self):
        return self._image_version

    @Property('QVariantList', notify=imageVersionChanged)
    def figureSnapGuide(self):
        """蓝色虚线引导线，**扁平的若干段** [x0,y0,x1,y1, x0,y0,x1,y1, ...]；无引导时为空。

        图形等边吸附 / 圆半径 = 1 段；椭圆 = 两焦点连线（1 段）或探针到两焦点（2 段）。
        """
        return list(self._fig_snap_guide) if self._fig_snap_guide else []

    @Property(str, notify=imageVersionChanged)
    def figureSnapKind(self):
        """当前等边吸附中的图形 id（tri/rect/pent/hex）；未吸附为空字符串。"""
        return self._fig_snap_kind or ""

    @Property(str, notify=imageVersionChanged)
    def figureSnapName(self):
        """提示文字（等边三角形/正方形/…、平行/等长/闭合形状）；夹角角度文字走 `figureAngleText`。"""
        k = self._fig_snap_kind or ""
        if k == "sector2":
            return "圆心角 %d°" % int(round(self._sector_angle_display()))
        if k == "solidright":
            # 升维时吸附成"直柱体/直锥体"：按当前立体图形的菜单名现算
            # （直三棱柱/直四棱柱/直圆柱/直三棱锥/直四棱锥/直圆锥）
            # ⚠️ 三棱台第二步升维出来的其实是个**三棱锥** → 提示「直三棱锥」（用户要求）
            _kk = _FIG_SOLIDRIGHT_KINDS.get(self._tf_kind, self._tf_kind)
            return "直" + _SOLID_KIND_NAMES.get(_kk, "")
        return _FIG_SNAP_NAMES.get(k, "")

    @Property(str, notify=imageVersionChanged)
    def figureSnapIconKind(self):
        """提示胶囊左侧小图标的图形 id（= `figureSnapKind`，便于 QML 单独控制是否画图标）。

        例外："cube"（正六面体吸附）借用四棱柱的小图（画出来就是一个小正方体）；
        "tetra"（正四面体吸附）借用三棱锥的小图；
        "solidbase"（底面阶段主提示）借用**底面画法本身**的小图（等边三角形/正方形/圆）。
        """
        k = self._fig_snap_kind or ""
        if k == "cube":
            return "quadprism"
        if k == "tetra":
            return "tripyramid"
        if k == "radius":
            # 画圆 / 画球时的小图标 = 这个图形本身（「半径」提示左侧画个小圆 / 小球）
            return _figure_of(self._active) if self._active else ""
        if k == "solidbase":
            return _SOLID_BASE_KIND.get(self._solid_kind_now(), "")
        if k in ("axiseq", "axiseqz"):
            # 坐标系的"等长"吸附：小图标用**等于号**（与多边形随心画的"等长"同一套图标）
            return "pfeq"
        if k == "solidright":
            # 升维吸成直柱体/直锥体 → 小图标就用这个立体图形本身
            # （三棱柱/四棱柱/圆柱/三棱锥/四棱锥/圆锥）；三棱台第二步升维出的是三棱锥 →
            # 小图也用三棱锥（与提示文字「直三棱锥」一致）
            return _FIG_SOLIDRIGHT_KINDS.get(self._tf_kind, self._solid_kind_now())
        return k

    def _solid_kind_now(self):
        """当前正在画的立体图形 id（底面阶段看 `_active`，升维阶段看 `_sf_base`）；无则空串。"""
        if self._sf_base is not None:
            return self._tf_kind or ""
        act = self._active
        fig = _figure_of(act) if act else ""
        return _solid_of(fig)[0] or ""

    @Property(str, notify=imageVersionChanged)
    def figureAngleText(self):
        """夹角提示文字（多边形随心画拖边时，**不管哪种吸附都显示**）：如「45°」；无则空串。

        文字值 = **最终几何**的内角（含各种吸附之后），所以与看到的图形总是一致。
        """
        if self._pf_pts is None or not self._pf_drawing:
            return ""
        return "%d°" % int(round(self._pf_angle))

    @Property('QVariantList', notify=imageVersionChanged)
    def figureAngleAnchor(self):
        """夹角提示胶囊的中心点 = 角平分线上距顶点 **固定 28px** 处（空 = 不显示）。"""
        if self._pf_pts is None or not self._pf_drawing or not self._pf_anchor:
            return []
        return [float(self._pf_anchor[0]), float(self._pf_anchor[1])]

    @Property('QVariantList', notify=imageVersionChanged)
    def figureSnapHighlight(self):
        """等长/平行吸附命中的"这两边"（扁平 [x0,y0,x1,y1, …]）= 参照边 + 正在画的边。

        **由后端直接画进画布图**（`_draw_pf_highlight`：先铺线宽+4 的蓝底、再把墨色盖回中间
        → 两侧各留 2px 蓝，线本身颜色不变）；命中的是**缺口连线**时不在这里
        （改由 QML 引导线层画成"笔迹虚线 + 外侧 2px 蓝"，见 `figureSnapBoldGuide`/
        `figureGapColor`/`figureGapWidth`）。QML 不再单独画这层。
        """
        return list(self._pf_hi) if self._pf_hi else []

    @Property(bool, notify=imageVersionChanged)
    def figureSnapBoldGuide(self):
        """命中的是不是**缺口连线**（它参与了等长/平行吸附时，用户要求改样式）。"""
        return bool(self._pf_hi_gap)

    @Property(str, notify=imageVersionChanged)
    def figureGapColor(self):
        """缺口连线的"笔迹显示色"（hex，随深浅色模式解析；无进行中的笔划时空串）。

        QML 的引导线 Canvas 用它把缺口连线画成**笔迹的颜色、粗细**的虚线
        （与形状菜单"虚线"同图案），外侧再描 2px 蓝（用户要求）。
        """
        act = self._active
        if not act:
            return ""
        return _pen_display_color(act.get("color", "mono"), self._light)

    @Property(float, notify=imageVersionChanged)
    def figureGapWidth(self):
        """缺口连线的"笔迹粗细"（= 当前笔划宽度；无进行中的笔划时 0）。"""
        act = self._active
        if not act:
            return 0.0
        return max(0.5, float(act.get("width", 4.0)))

    @Property(str, notify=imageVersionChanged)
    def figureAlignKind(self):
        """横平竖直吸附方向："h"（水平排列）/ "v"（竖直排列）/ ""（未吸附）。

        椭圆与双曲线第一阶段（定焦点）与抛物线（定焦准距线段）共用。
        """
        return self._fig_align or ""

    @Property(str, notify=imageVersionChanged)
    def figureAlignName(self):
        """第二个提示的文字（吸附确认）。

        图形（椭圆/双曲线定焦点、抛物线定焦准距线段）→ 「水平排列」/「竖直排列」；
        **线型笔划**（直线/虚线/箭头/…）与**扇形第一阶段 / 多边形随心画第一条边**
        （都是"一条半径/一条线"）→ 「水平」/「竖直」（措词按当前笔划类型自动选，
        不需要额外状态：看 `_active` 是不是线型即可）。
        **立体图形底面阶段**（`_fig_align == "fig"`）→ 底面图形的等边吸附名
        （「等边三角形」/「正方形」）——主提示固定是「底面」，吸附确认弹在它上方。
        """
        if not self._fig_align:
            return ""
        if self._fig_align == "fig":
            return self._solid_base_snap_name()
        act = self._active
        # 线型笔划 / **扇形第一阶段** / **多边形随心画第一条边** → 措词「水平」/「竖直」
        if (act is not None
                and ((not _figure_of(act) and _line_style_of(act))
                     or _figure_of(act) in ("sector", "polfree"))):
            return _LINE_ALIGN_NAMES.get(self._fig_align, "")
        return _FIG_ALIGN_NAMES.get(self._fig_align, "")

    def _solid_base_snap_name(self):
        """立体图形底面阶段吸附确认的文字（底面画法的吸附名）；不是该阶段返回空串。"""
        act = self._active
        fig = _figure_of(act) if act else ""
        if not _solid_of(fig)[0]:
            return ""
        return _FIG_SNAP_NAMES.get(_SOLID_BASE_KIND.get(fig, ""), "")

    @Property(str, notify=imageVersionChanged)
    def figureAlignIcon(self):
        """第二个提示的左侧小图标 id：横平竖直 = alignh/alignv；
        立体图形底面吸附 = 底面画法本身（tri → 小等边三角形、rect → 小正方形）。"""
        if self._fig_align == "fig":
            act = self._active
            fig = _figure_of(act) if act else ""
            return _SOLID_BASE_KIND.get(fig, "") if _solid_of(fig)[0] else ""
        return _FIG_ALIGN_ICONS.get(self._fig_align or "", "")

    @Property('QVariantList', notify=imageVersionChanged)
    def scaleAspectGuide(self):
        """四角缩放时的"等比例缩放直线" [x0,y0,x1,y1]（QML 画蓝色 1px 虚线）；无则空。"""
        return list(self._scale_aspect_guide or [])

    @Property('QVariantMap', constant=True)
    def shapeAspects(self):
        """各图形"等边"所需辅助矩形长宽比（QML 画小图形提示时保持比例用）。

        直角三角的三个"特殊角"提示（rtri30/45/60）也在这里给长宽比 → 提示里的小图标
        就是对应形状的直角三角形（30° 扁、60° 瘦、45° 等腰直角）。
        """
        m = {k: _figure_aspect(k) for k in _SHAPE_KINDS}
        m.update(_FIG_RAY_ASPECTS)
        m.update({"sector": 1.0, "sector2": 1.0, "pfeq": 1.0, "pfpara": 1.0})
        return m

    # ---------- 笔划几何辅助 ----------
    def _stroke_dense_track(self, stroke, max_gap=None):
        """把笔划中心线按曲率自适应地向心 CR 密集化，返回 (dense, knots)。

        与渲染用的 _stroke_path/_build_stroke_outline 同一构造，保证"判定所见"
        与画面一致；点状/重合退化返回单点。
        knots[i] 为 dense[i] 对应的原始控制点索引（插值点为 -1）——橡皮切分后
        还原稀疏点需要它（避免碎片被反复密集化导致点数爆炸）。
        max_gap 见 _cr_segments：橡皮逐点判定需要"子段足够短"，否则直线段中段
        可能被整段跳过。
        """
        points = stroke.get("points") or []
        if not points:
            return [], []
        if _is_shape_stroke(stroke):
            # 形状线/图形：直边折线（CR 会把多边形的角拉圆，与看到的边不一致）。
            # 圆的圆心点不属于轮廓 → 判定/切分只用轮廓（_fig_ink_pts）。
            return _polyline_dense_track(
                _fig_ink_pts(_figure_of(stroke), points), max_gap)
        pts, idx = _dedupe_indexed(points)
        if _is_degenerate(pts):
            return [[pts[0][0], pts[0][1]]], [idx[0]]
        dense = [[pts[0][0], pts[0][1]]]
        knots = [idx[0]]
        for s in _cr_segments(pts, max_gap=max_gap):
            n_st = s.steps
            for k in range(1, n_st + 1):
                t = k / n_st
                mt = 1.0 - t
                dense.append([
                    mt ** 3 * s.x0 + 3 * mt * mt * t * s.c1x
                    + 3 * mt * t * t * s.c2x + t ** 3 * s.x1,
                    mt ** 3 * s.y0 + 3 * mt * mt * t * s.c1y
                    + 3 * mt * t * t * s.c2y + t ** 3 * s.y1,
                ])
                knots.append(idx[s.i + 1] if k == n_st else -1)
        return dense, knots

    def _stroke_dense_points(self, stroke):
        """笔划中心线的密集点列（包含/命中判定用）。"""
        return self._stroke_dense_track(stroke)[0]

    def _stroke_bbox(self, stroke, pad=0.0):
        """笔划点包围盒 [x, y, w, h]（可选外扩 pad=宽度/2 以包含笔划厚度）。"""
        pts = stroke.get("points") or []
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return [min(xs) - pad, min(ys) - pad,
                max(xs) - min(xs) + pad * 2, max(ys) - min(ys) + pad * 2]

    # ---------- 橡皮：真正修改笔迹路径 ----------
    @staticmethod
    def _split_runs(flags):
        """把标记数组切成连续保留（False）段的 [start, end] 列表。"""
        runs = []
        start = None
        for i, f in enumerate(flags):
            if not f and start is None:
                start = i
            elif f and start is not None:
                runs.append((start, i - 1))
                start = None
        if start is not None:
            runs.append((start, len(flags) - 1))
        return runs

    @staticmethod
    def _build_fragment_points(dense, a, b, original, knots):
        """把被切分出的保留段（密集区间 [a,b]）还原成稀疏笔划点：切边界点 + 区间内的原始控制点。

        关键：**不要整段保留密集点**——否则每次擦除都会把已是密集点的碎片再次密集化，
        点数指数爆炸，反复擦 3~4 次后单笔膨胀到几万点 → 渲染/命中/再擦除全部变 O(巨量)，
        界面永久无响应。
        knots[i] 为 dense[i] 对应的原始控制点索引（插值点为 -1，由 _stroke_dense_track
        给出同一套向心 CR 采样），故边界用 dense[a]/dense[b]（恰为控制点时用原始点），
        中间只保留区间内的原始控制点。
        """
        n = len(original)
        nk = len(knots)
        a = max(0, min(int(a), nk - 1))
        b = max(a, min(int(b), nk - 1))
        # 起点：切边界处恰为原始控制点则用原始点（保证稀疏），否则用插值点，
        # 并回退到其左侧最近的原始控制点作为"区间内控制点"的下界。
        ka = knots[a]
        if ka >= 0:
            pts = [original[ka]]
        else:
            pts = [dense[a]]
            j = a - 1
            while j >= 0 and knots[j] < 0:
                j -= 1
            ka = knots[j] if j >= 0 else -1
        # 终点 + 区间内控制点上界
        kb = knots[b]
        if kb >= 0:
            end_pt = original[kb]
            interior_end = kb
        else:
            end_pt = dense[b]
            j = b + 1
            while j < nk and knots[j] < 0:
                j += 1
            interior_end = knots[j] if j < nk else n
        for k in range(ka + 1, interior_end):
            if 0 <= k < n:
                pts.append(original[k])
        if pts[-1] != end_pt:
            pts.append(end_pt)
        # 防御：异常超长原始笔划降采样（正常情况不会触发）
        if len(pts) > 600:
            keep = pts[::3]
            if keep[-1] != pts[-1]:
                keep.append(pts[-1])
            pts = keep
        return pts

    def _apply_eraser(self, eraser):
        """把橡皮路径作用于全部 pen 笔划：移除被擦部分并把被切断的笔划切分为多段。

        性能版：不再用纯 Python 的 O(P×E) 距离双重循环，而是——
        ① 每笔先做包围盒相交预过滤（不相交的连密集采样都不做，擦一处只碰附近几笔）；
        ② 把橡皮路径用 QPainterPathStroker 描成实心 ribbon，用 contains() 在 C++ 侧
           判定点是否被擦（快 2~3 个数量级）。
        其余语义不变：不再保存"蒙层"橡皮笔划，真正修改笔迹路径；旧数据 op=="eraser"
        蒙层笔划保留（渲染仍用 Clear 合成，向后兼容）。

        返回撤销操作 dict（{"type":"erase","removed":[...],"added_ids":[...]}），
        未擦到任何笔划时返回 None。
        """
        radius = max(float(eraser.get("width", 32.0)) / 2.0, 1.0)
        pts = eraser.get("points") or []
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        # 橡皮包围盒（外扩 radius，用于每笔快速剔除）
        er_bbox = [min(xs) - radius, min(ys) - radius,
                   max(xs) - min(xs) + 2 * radius, max(ys) - min(ys) + 2 * radius]
        is_dot = len(pts) == 1 or (max(xs) - min(xs) < 0.01 and max(ys) - min(ys) < 0.01)
        if is_dot:
            # 单点/点擦：圆心距 <= radius + margin（O(1)/点）
            dx0, dy0 = pts[0][0], pts[0][1]

            def hits_core(p, margin):
                dx = p[0] - dx0
                dy = p[1] - dy0
                rr = radius + margin
                return dx * dx + dy * dy <= rr * rr
        else:
            # 多段：把橡皮折线描成实心 ribbon（宽度=橡皮直径、圆头圆角），contains() 判定
            # （C++ 侧，与拖动时的增量 Clear 预览一致：首点圆 + 相邻点圆头线段）
            center = QPainterPath()
            center.moveTo(pts[0][0], pts[0][1])
            for p in pts[1:]:
                center.lineTo(p[0], p[1])
            _ribbons = {}

            def hits_core(p, margin):
                # margin = 该笔划的墨迹半宽：橡皮要擦掉它**碰到的所有墨**，
                # 所以中心线点距橡皮 <= radius + margin（按笔宽建 ribbon 并缓存）
                rb = _ribbons.get(margin)
                if rb is None:
                    stk = QPainterPathStroker()
                    stk.setWidth(float(eraser.get("width", 32.0)) + 2.0 * margin)
                    stk.setCapStyle(Qt.PenCapStyle.RoundCap)
                    stk.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    rb = stk.createStroke(center)
                    _ribbons[margin] = rb
                return rb.contains(QPointF(p[0], p[1]))

        removed = []       # [{index, id, old}]  按原顺序（index=原笔划在重建列表中的位置）
        fragments = []     # [(index_in_new_list, frag_dict)]
        new_list = []
        broken_grps = set()    # 被切分的立体图形分组 id（切完要清掉分组）
        for s in self._strokes:
            if s.get("op") != "pen":
                # 旧数据蒙层橡皮：保留（渲染向后兼容），不参与路径修改
                new_list.append(s)
                continue
            bb = self._stroke_bbox(s)
            # 包围盒不相交 → 整笔跳过（不做密集采样/命中判定）
            if not bb or bb[0] > er_bbox[0] + er_bbox[2] or bb[0] + bb[2] < er_bbox[0] \
                    or bb[1] > er_bbox[1] + er_bbox[3] or bb[1] + bb[3] < er_bbox[1]:
                new_list.append(s)
                continue
            # 逐点判定需要"子段 ≤ 橡皮半径的一半"：自适应细分下直线段只有端点，
            # 若只测端点，中段被橡皮扫过时会整段漏擦（快速直线笔迹尤其明显）。
            dense, knots = self._stroke_dense_track(
                s, max_gap=max(4.0, radius * 0.5))
            if not dense:
                new_list.append(s)
                continue
            # 本笔的墨迹半宽：中心线点落在"橡皮区外扩该值"内 → 该点所在处的墨
            # 一定被橡皮碰到（碎片端点的圆头再回缩 w/2）→ **可见缺口 ≈ 橡皮直径**。
            # 旧写法只按 radius 判定 → 缺口总比橡皮小一个笔宽（用户报的"缺口稍稍小一点"）。
            _margin = max(0.5, float(s.get("width", 4.0)) / 2.0)

            def hits(p, _m=_margin):
                return hits_core(p, _m)

            flags = [hits(p) for p in dense]
            if not any(flags):
                new_list.append(s)
                continue
            orig_pts = s.get("points") or []
            fig_k = _figure_of(s)
            # 图形（尤其是圆）：碎片只能由**轮廓点列**构成——圆的圆心点不参与切分，
            # 否则碎片会带上一根从圆心到切点的“辐条”。knots 的索引也必须对应同一份点列。
            ink_pts = _fig_ink_pts(fig_k, orig_pts)
            # 图案基准轴：本笔若已是某次擦除的片段则继承它的 pat，否则用本笔两端。
            # 切出的碎片带上它 → 虚线划/缺口、光线箭头、梳齿、波浪相位全部接回原位。
            pat_ref = None
            if _is_pattern_style(s.get("style")) and len(ink_pts) >= 2:
                pat_ref = s.get("pat")
                if not pat_ref:
                    pat_ref = [float(ink_pts[0][0]), float(ink_pts[0][1]),
                               float(ink_pts[-1][0]), float(ink_pts[-1][1])]
            old_snap = _snap_stroke(s)
            if s.get("grp"):
                # 立体图形被橡皮切分 → 不再当作一个整体（用户要求）
                # 注意：碎片不带 grp，同一图形的其它笔划也要清掉（见下方 broken_grps）
                broken_grps.add(str(s["grp"]))
            removed.append({
                "index": len(new_list),
                "id": int(s.get("id", 0)),
                "old": old_snap})
            runs = self._split_runs(flags)
            # 闭合轮廓（图形的首尾同点）：首/末两段保留区在几何上是**连通**的
            # （都接着轮廓起点那个顶点），而 _split_runs 是线性切分 → 会被误当成
            # 两段（多切出一笔）。这里把两段合成一段。
            # 注意：**不能**用"把 dense/knots/flags 循环旋转"的办法——那会破坏
            # _build_fragment_points 依赖的"控制点索引单调递增"前提，碎片会丢中间
            # 控制点，退化成两点直线（表现为“单边擦除失效”/“同一位置出现两节”）。
            merge_wrap = (fig_k and len(ink_pts) >= 3
                          and _same_pt(ink_pts[0], ink_pts[-1]) and len(runs) >= 2
                          and runs[0][0] == 0 and runs[-1][1] == len(flags) - 1)

            def _cut_pt(keep, inside):
                """在 [keep, inside] 段上二分求"离开橡皮区域"的精确交点（返回同元数点）。

                密集采样点是离散的：切口若直接用"最后一个未被擦到的采样点"，缺口长度会
                随采样步长抖动（大图形上可达 ±半个步长，实测 R=120/129 点约 ±6px 弧长，
                表现为"擦除形状有误差、缺口时大时小"）。二分 18 次 → 交点在橡皮边界上
                （误差 < 1e-5 段长），缺口只由橡皮覆盖决定。
                """
                lo, hi = 0.0, 1.0          # t=0 → keep（未命中），t=1 → inside（命中）
                for _ in range(18):
                    mid = 0.5 * (lo + hi)
                    if hits((keep[0] + (inside[0] - keep[0]) * mid,
                             keep[1] + (inside[1] - keep[1]) * mid)):
                        hi = mid
                    else:
                        lo = mid
                t = 0.5 * (lo + hi)
                out = [keep[0] + (inside[0] - keep[0]) * t,
                       keep[1] + (inside[1] - keep[1]) * t]
                if len(keep) > 2:          # 保留压力等附加维度（元数必须一致）
                    out.extend(list(keep[2:]))
                return out

            frag_pts_list = []
            n_dense = len(dense)
            for a, b in runs:
                fp = self._build_fragment_points(dense, a, b, ink_pts, knots)
                if fp:
                    # 切口两端精确落到橡皮边界（a>0 / b<末点 ⇒ 该端确实是被切开的）
                    if a > 0 and a < n_dense:
                        fp[0] = _cut_pt(dense[a], dense[a - 1])
                    if 0 <= b < n_dense - 1:
                        fp[-1] = _cut_pt(dense[b], dense[b + 1])
                frag_pts_list.append(fp)
            if merge_wrap:
                tail = list(frag_pts_list[-1])
                skip = tail[-1]
                head = [p for p in frag_pts_list[0]
                        if abs(p[0] - skip[0]) > 1e-6 or abs(p[1] - skip[1]) > 1e-6]
                frag_pts_list = frag_pts_list[1:-1] + [tail + head]
            for frag_pts in frag_pts_list:
                # 只剩 1 个点的小残段也保留（渲染成一个圆点）：用户要求"只有连 1 个
                # 像素都凑不出来才移除"，不再按点数丢弃（旧写法 len < 2 直接 continue）
                if not frag_pts:
                    continue
                frag = {"op": "pen", "color": s.get("color", ""),
                        "width": float(s.get("width", 4.0)),
                        "style": s.get("style", ""),
                        "points": frag_pts}
                if pat_ref:
                    frag["pat"] = [float(v) for v in pat_ref]
                fragments.append((len(new_list), frag))
                new_list.append(frag)
        if not removed:
            return None
        # 落盘：删除被影响的原始行，插入碎片行，重排全部顺序号
        added_ids = []
        if self._store:
            for r in removed:
                self._store.delete_stroke(r["id"])
            for _, frag in fragments:
                sid = self._store.add_stroke(frag["op"], frag["color"],
                                             frag["width"], frag["points"],
                                             frag.get("style", ""),
                                             pat=frag.get("pat"))
                if sid is not None:
                    frag["id"] = int(sid)
                    added_ids.append(int(sid))
        else:
            # 无存储（极端/离屏）：用大基数临时 id，避免与已有 id 冲突
            base = 1000000
            for i, (_, frag) in enumerate(fragments):
                frag["id"] = base + i
                added_ids.append(base + i)
        self._strokes = new_list
        if broken_grps:
            for st in self._strokes:
                if str(st.get("grp") or "") in broken_grps:
                    _set_grp(st, "")
                    if self._store and st.get("id") is not None:
                        self._store.update_stroke(
                            int(st["id"]), st.get("op", "pen"), st.get("color", ""),
                            float(st.get("width", 4.0)), st.get("points") or [],
                            grp="")
        self._sel_grid = None   # 笔迹变化 → 圈选索引失效
        self._plain = None      # 画布无选中版失效（下面 _render_all 会重建）
        if self._store:
            self._store.set_all_seq([s["id"] for s in self._strokes])
        # 旧选择可能引用已删除/已切分的笔划 → 清除选择
        self._sel_poly = None
        self._selection = []
        self._sel_rect = None
        self._sel_active = False
        self._sel_color = ""
        self._sel_width = 0
        self._render_all()
        self._bump()
        self.selectionChanged.emit()
        self._bump_thumbs()   # 擦除 → 页面缩略图刷新
        return {"type": "erase", "removed": removed, "added_ids": added_ids}

    # ---------- 选择：内部 ----------
    def _select_ids(self, ids):
        """设置选中笔划 id 集合并重绘（圈选过程中实时调用）。

        只重绘选中描边层（_render_selection_overlay），不重绘全部笔迹——
        圈选拖动时被选笔划数多也能保持流畅。
        选择集合未变化时直接跳过重绘与版本刷新（圈选拖动中大量帧的集合是不变的，
        而重绘叠加层（含选中蓝边）原本是每帧最贵的部分）。
        """
        new_ids = list(ids)
        if (new_ids == self._selection and self._plain is not None
                and not self._plain.isNull()):
            return
        self._selection = new_ids
        self._preview_base = None   # 选择集合变化 → 拖拽预览底图失效
        self._update_selection_style()
        self._render_selection_overlay()
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
        self._sel_width = float(widths.pop()) if len(widths) == 1 else 0.0

    def _compute_selection_rect(self, reset_rot=True):
        """按选中笔划（含厚度）计算包围矩形，确认选择状态。"""
        if reset_rot:
            self._sel_rot_deg = 0.0   # 建立新（直）选择框 → 旋转姿态归零
        if not self._selection:
            self._sel_rect = None
            self._sel_active = False
            return
        xs = []
        ys = []
        for s in self._strokes:
            if s.get("id") not in self._selection:
                continue
            pad = max(float(s.get("width", 4.0)) / 2.0, _shape_extent(s))
            bb = self._stroke_bbox(s, pad)
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

    # ---------- 选择：圈选空间索引 + 墨迹相触判定 ----------
    def _build_sel_grid(self):
        """笔划包围盒的均匀空间网格索引：{(cx, cy): [stroke,...]}（仅 pen 笔划）。

        圈选时只遍历圈选包围盒覆盖的格内笔划 → 快速剪枝。若圈选区域碰到某笔划，
        二者的包围盒必然相交 → 该笔划必在圈选包围盒覆盖的某格中，剪枝安全不漏选。
        """
        grid = {}
        for s in self._strokes:
            if s.get("op") != "pen":
                continue
            bb = self._stroke_bbox(s, _shape_extent(s))
            if bb is None:
                continue
            c0x = int(bb[0] // _SEL_GRID_CELL)
            c1x = int((bb[0] + bb[2]) // _SEL_GRID_CELL)
            c0y = int(bb[1] // _SEL_GRID_CELL)
            c1y = int((bb[1] + bb[3]) // _SEL_GRID_CELL)
            for cx in range(c0x, c1x + 1):
                for cy in range(c0y, c1y + 1):
                    grid.setdefault((cx, cy), []).append(s)
        return grid

    def _grid_candidates(self, grid, pb):
        """圈选包围盒覆盖的格 → 去重候选笔划列表（候选集⊇真实相触笔划，安全剪枝）。"""
        c0x = int(pb.left() // _SEL_GRID_CELL)
        c1x = int(pb.right() // _SEL_GRID_CELL)
        c0y = int(pb.top() // _SEL_GRID_CELL)
        c1y = int(pb.bottom() // _SEL_GRID_CELL)
        seen = set()
        out = []
        for cx in range(c0x, c1x + 1):
            for cy in range(c0y, c1y + 1):
                for s in grid.get((cx, cy), ()):
                    if id(s) not in seen:
                        seen.add(id(s))
                        out.append(s)
        return out

    def _stroke_ink_path(self, stroke):
        """笔划墨迹填充路径（圈选相触判定用；优先渲染缓存轮廓，缺失回退固定宽度 ribbon）。

        _outline 为 perfect-freehand 的宽度可变轮廓（已求并集），是墨迹本身；缺失时用
        中心线按宽度描边成实心 ribbon（QPainterPathStroker，C++ 构造）并缓存 _ink_path。
        点状笔划直接返回实心圆路径。几何/粗细变化处与 _outline 一并失效 _ink_path。
        """
        out = stroke.get("_outline")
        if out is not None:
            return out
        cached = stroke.get("_ink_path")
        if cached is not None:
            return cached
        pts = stroke.get("points") or []
        width = float(stroke.get("width", 4.0))
        if not pts or width <= 0:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        is_dot = len(pts) == 1 or (max(xs) - min(xs) < 0.01 and max(ys) - min(ys) < 0.01)
        try:
            if is_dot:
                r = max(0.5, width / 2.0)
                path = QPainterPath()
                path.addEllipse(QPointF(pts[0][0], pts[0][1]), r, r)
                path.setFillRule(Qt.WindingFill)
            else:
                center = _polyline_path(_fig_ink_pts(_figure_of(stroke), pts)) \
                    if _is_shape_stroke(stroke) \
                    else _stroke_path(pts, width)
                stroker = QPainterPathStroker()
                # 形状线：ribbon 按线型视觉半宽加宽，否则波浪的峰谷/双线的外侧选不中
                stroker.setWidth(max(1.0, width, 2.0 * _shape_extent(stroke)))
                stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
                stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                path = stroker.createStroke(center)
                if path.isEmpty():
                    return None
                path.setFillRule(Qt.WindingFill)
            stroke["_ink_path"] = path
            return path
        except Exception:
            return None

    def _select_inside_polygon(self):
        """圈选（相触即选）：圈选区域碰到笔迹墨迹的任一部分，即选中该笔划。

        性能：① 笔迹包围盒均匀空间网格索引（_sel_grid，本次手势内复用）快速取候选；
        ② 精确判定用墨迹填充路径的 QPainterPath.intersects（C++ 单次调用，覆盖部分
        相交/包含/边界相触），替代对每笔逐密集点做 containsPoint 的 Python 循环。
        """
        poly_pts = self._sel_poly or []
        if len(poly_pts) < 3:
            self._select_ids([])
            return
        # 圈选区域填充路径（WindingFill + simplified：自交圈选按并集算区域）
        lpath = QPainterPath()
        lpath.setFillRule(Qt.WindingFill)
        lpath.moveTo(poly_pts[0][0], poly_pts[0][1])
        for p in poly_pts[1:]:
            lpath.lineTo(p[0], p[1])
        lpath.closeSubpath()
        try:
            lpath = lpath.simplified()
        except Exception:
            pass
        pb = lpath.boundingRect()
        grid = self._sel_grid
        if grid is None:
            grid = self._build_sel_grid()
            self._sel_grid = grid
        sel = []
        for s in self._grid_candidates(grid, pb):
            ip = self._stroke_ink_path(s)
            if ip is not None and ip.intersects(lpath):
                sel.append(s.get("id"))
        # 立体图形：由多笔组成（可见棱 / 被遮挡棱），圈选碰到其中任一笔就把**整个图形**
        # 一起选中（单击同理，见 `clickSelect`）→ 统一走 `_expand_grp`。
        self._select_ids(self._expand_grp(sel))

    def _expand_grp(self, ids):
        """把一批笔划 id 按**分组**（`grp`，立体图形的"整块"）扩成全组。

        用户要求：用选择工具**单击**立体图形的某一边时，只要这个图形没被橡皮分割，
        就应该选中整个图形（与圈选一致）。被橡皮切分过的已清空 grp → 不会扩张。
        """
        have = {i for i in (ids or []) if i is not None}
        groups = {str(s["grp"]) for s in self._strokes
                  if s.get("id") in have and s.get("grp")}
        if not groups:
            return [i for i in (ids or []) if i is not None]
        out = [i for i in (ids or []) if i is not None]
        seen = set(out)
        for s in self._strokes:
            sid = s.get("id")
            if str(s.get("grp") or "") in groups and sid not in seen:
                seen.add(sid)
                out.append(sid)
        return out

    def _hit_stroke(self, x, y):
        """返回点击点命中的最近 pen 笔划 id（到中心线距离 <= 半宽+3px），否则 None。

        判定用**点到密集折线各线段**的距离，而不是点到采样点：自适应细分后直线段
        可能只有两个端点（子段最长可达数百 px），只测采样点会漏掉整段中间的点击。
        """
        best = None
        best_d2 = float('inf')
        for s in self._strokes:
            if s.get("op") != "pen":
                continue
            # 容差：笔宽一半（形状线取线型视觉半宽，淡/波浪线更宽）+ 3px 宽容
            tol = max(float(s.get("width", 4.0)) / 2.0, _shape_extent(s)) + 3.0
            tol2 = tol * tol
            dense = self._stroke_dense_points(s)
            if not dense:
                continue
            if len(dense) == 1:
                d2 = (dense[0][0] - x) ** 2 + (dense[0][1] - y) ** 2
                if d2 <= tol2 and d2 < best_d2:
                    best_d2 = d2
                    best = s.get("id")
                continue
            for i in range(len(dense) - 1):
                ax, ay = dense[i]
                bx, by = dense[i + 1]
                vx = bx - ax
                vy = by - ay
                L2 = vx * vx + vy * vy
                if L2 < 1e-12:
                    d2 = (x - ax) ** 2 + (y - ay) ** 2
                else:
                    t = ((x - ax) * vx + (y - ay) * vy) / L2
                    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
                    ex = ax + t * vx
                    ey = ay + t * vy
                    d2 = (x - ex) ** 2 + (y - ey) ** 2
                if d2 <= tol2 and d2 < best_d2:
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
        self._render_selection_overlay()
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
        self._render_selection_overlay()
        self._bump()
        self.selectionChanged.emit()

    @Slot(float, float)
    def clickSelect(self, x, y):
        """单击选择：命中某笔划则选中它；**属于立体图形（有 grp）的一笔 → 整个图形一起选**；
        未命中：点在已选矩形内则保留，否则取消。

        用户要求：单击几何体的某一边时，只要这个几何体没被橡皮分割，就应当选中整个几何体
        （而不是只选中这一边）。梯形/形状线等单笔图形没有 grp，行为不变。
        """
        x, y = float(x), float(y)
        hit = self._hit_stroke(x, y)
        if hit is not None:
            self._selection = self._expand_grp([hit])
            self._sel_poly = None
            self._compute_selection_rect()
            self._update_selection_style()
            self._render_selection_overlay()
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
        self._render_selection_overlay()
        self._bump()
        self.selectionChanged.emit()

    @Slot(float, float, float, float)
    def applyTransform(self, x1, y1, w1, h1):
        """把选中笔划映射到目标矩形 (x1,y1,w1,h1)（平移或等比缩放）。

        拖拽中（beginModify..endModify 之间）：只记录相对基准矩形的变换并做"预览
        渲染"（painter 变换重画选中笔迹，不重算轮廓/不改向量/不写库）→ 大量笔迹
        被选中时平移/缩放流畅且过程中实时可见；endModify 时一次性提交到向量数据
        与存储。无拖拽上下文（_modify_snapshot 为空）时回退旧行为：直接逐事件映射。
        """
        r = self._sel_rect
        if not r or not self._selection:
            return
        # 拖拽预览路径（beginModify 之后）：以基准矩形映射，避免逐事件累积
        if self._modify_snapshot is not None and self._modify_base_rect is not None:
            x0, y0, w0, h0 = self._modify_base_rect
            if w0 <= 0 or h0 <= 0:
                return
            # 变换与选择矩形都没变（重复事件/鼠标抖动）→ 跳过整帧渲染与刷新
            new_preview = (w1 / w0, h1 / h0, x1 - x0, y1 - y0)
            new_rect = [x1, y1, w1, h1]
            if new_preview == self._modify_preview and new_rect == self._sel_rect:
                return
            self._modify_preview = new_preview
            # 选择矩形直接采用目标矩形（QML 矩形/把手/工具栏实时跟随鼠标）
            self._sel_rect = new_rect
            self._sel_active = True
            self._render_modify_preview()
            self._bump()
            self.selectionChanged.emit()
            return
        # 旧路径（无拖拽上下文兜底）：直接逐事件映射到向量数据
        x0, y0, w0, h0 = r
        if w0 <= 0 or h0 <= 0:
            return
        for s in self._strokes:
            if s.get("id") not in self._selection or s.get("op") != "pen":
                continue
            new_pts = []
            for pt in s.get("points", []):
                px, py = pt[0], pt[1]
                if len(pt) > 2:
                    new_pts.append([x1 + (px - x0) * (w1 / w0),
                                    y1 + (py - y0) * (h1 / h0), pt[2]])
                else:
                    new_pts.append([x1 + (px - x0) * (w1 / w0),
                                    y1 + (py - y0) * (h1 / h0)])
            s["points"] = new_pts
            # 图案基准轴跟着一起映射（否则移动/缩放后虚线的划与缺口、箭头会错位）
            _pat_new = _map_pat(s, lambda px, py: (x1 + (px - x0) * (w1 / w0),
                                                  y1 + (py - y0) * (h1 / h0)))
            _set_pat(s, _pat_new)
            self._invalidate_stroke_cache(s)   # 几何变化 → 失效全部派生缓存
            if self._store:
                self._store.update_stroke(s["id"], s.get("op"), s.get("color", ""),
                                          s.get("width", 4.0), s["points"],
                                          pat=_pat_new)
        self._sel_grid = None   # 笔迹几何变化 → 圈选索引失效
        self._plain = None      # 画布无选中版失效（下面 _render_all 会重建）
        # 选择矩形直接采用目标矩形（角点/边框精确跟随鼠标，笔迹严格在其中）
        self._sel_rect = [x1, y1, w1, h1]
        self._sel_active = True
        self._update_selection_style()
        self._render_all()
        self._bump()
        self.selectionChanged.emit()
        self._bump_thumbs()     # 直接映射（兜底）→ 页面缩略图刷新

    @Slot()
    def beginModify(self):
        """开始一次组合修改（拖拽平移/缩放）：记录选中笔划的旧快照与基准矩形。"""
        self._modify_snapshot = []
        self._modify_base_rect = list(self._sel_rect) if self._sel_rect else None
        self._modify_preview = None
        self._preview_base = None    # 新一次拖拽 → 预览底图重建
        for s in self._strokes:
            if s.get("id") in self._selection:
                self._modify_snapshot.append({"id": s["id"], "old": _snap_stroke(s)})

    def _modify_map_pt(self, px, py):
        """把一点按当前拖拽预览映射到屏幕坐标（**含选中框旋转姿态**）。

        非旋转态（_sel_rot_deg ≈ 0）：X(P) = (x0+dx, y0+dy) + (P−(x0,y0))·(sx,sy)。
        旋转态：内容是"视觉坐标"，故用 W = R_c2(θ) ∘ X ∘ R_c1(θ)⁻¹
        （c1/c2 = 旧/新基准矩形中心，c2 = X(c1)），与 _render_modify_preview 里的
        painter 变换必须逐字一致。
        """
        sx, sy, dx, dy = self._modify_preview
        x0, y0, w0, h0 = self._modify_base_rect
        qx = x0 + dx + (px - x0) * sx
        qy = y0 + dy + (py - y0) * sy
        deg = float(self._sel_rot_deg or 0.0)
        if abs(deg) < 0.01:
            return qx, qy
        th = math.radians(deg)
        cc, ss = math.cos(th), math.sin(th)
        c1x, c1y = x0 + w0 / 2.0, y0 + h0 / 2.0
        # R_c1(θ)⁻¹（逆旋回到基准系）
        ax_, ay_ = px - c1x, py - c1y
        bx_ = c1x + ax_ * cc + ay_ * ss
        by_ = c1y - ax_ * ss + ay_ * cc
        # X（基准系横平竖直映射）
        qx = x0 + dx + (bx_ - x0) * sx
        qy = y0 + dy + (by_ - y0) * sy
        # R_c2(θ)（c2 = X(c1)）
        c2x = x0 + dx + (c1x - x0) * sx
        c2y = y0 + dy + (c1y - y0) * sy
        ex_, ey_ = qx - c2x, qy - c2y
        return c2x + ex_ * cc - ey_ * ss, c2y + ex_ * ss + ey_ * cc

    def _commit_modify_preview(self):
        """把拖拽预览的变换真正应用到选中笔划向量/存储（endModify 时一次性提交）。

        拖拽期间向量数据未动、轮廓缓存未失效，这里按基准矩形一次性映射所有选中
        笔划（平移/等比缩放）、失效轮廓/墨迹/圈选索引缓存并写库。
        """
        sx, sy, dx, dy = self._modify_preview
        x0, y0, w0, h0 = self._modify_base_rect
        # 纯平移快速路径：形状不变 → 直接搬运已烘焙图层原点（免重烘焙，实测
        # 提交从 ~360ms 降到 ~10ms）。取整搬运见 _shift_stroke_layers。
        if sx == 1.0 and sy == 1.0:
            sel_strokes = [s for s in self._strokes
                           if s.get("id") in self._selection
                           and s.get("op") == "pen"]
            if self._shift_stroke_layers(sel_strokes, dx, dy):
                for s in sel_strokes:
                    new_pts = []
                    for pt in s.get("points", []):
                        rp = [pt[0] + dx, pt[1] + dy]
                        if len(pt) > 2:
                            rp.append(pt[2])
                        new_pts.append(rp)
                    s["points"] = new_pts
                    _pat_new = _map_pat(s, lambda px, py: (px + dx, py + dy))
                    _set_pat(s, _pat_new)
                    if self._store:
                        self._store.update_stroke(
                            s["id"], s.get("op"), s.get("color", ""),
                            s.get("width", 4.0), new_pts, pat=_pat_new)
                self._sel_grid = None   # 笔迹几何变化 → 圈选索引失效
                self._plain = None      # 画布无选中版失效（下面 _render_all 会重建）
                self._bump_thumbs()
                return
        for s in self._strokes:
            if s.get("id") not in self._selection or s.get("op") != "pen":
                continue
            new_pts = []
            for pt in s.get("points", []):
                nx, ny = self._modify_map_pt(pt[0], pt[1])
                if len(pt) > 2:
                    new_pts.append([nx, ny, pt[2]])
                else:
                    new_pts.append([nx, ny])
            s["points"] = new_pts
            _pat_new = _map_pat(s, self._modify_map_pt)
            _set_pat(s, _pat_new)
            self._invalidate_stroke_cache(s)   # 几何变化 → 失效全部派生缓存
            if self._store:
                self._store.update_stroke(s["id"], s.get("op"), s.get("color", ""),
                                          s.get("width", 4.0), s["points"],
                                          pat=_pat_new)
        self._sel_grid = None   # 笔迹几何变化 → 圈选索引失效
        self._plain = None      # 画布无选中版失效（下面 _render_all 会重建）
        self._bump_thumbs()     # 移动/平移/缩放提交 → 页面缩略图刷新

    @Slot()
    def endModify(self):
        """结束组合修改：拖拽预览有实际变换则一次性提交并压入一次 modify 撤销；
        无变化（纯点击/原地未动）忽略。
        """
        if not self._modify_snapshot:
            return
        changes = []
        if (self._modify_preview is not None and len(self._modify_preview) == 4
                and self._modify_preview[0] != "rot"):
            sx, sy, dx, dy = self._modify_preview
            if sx != 1.0 or sy != 1.0 or abs(dx) > 0.01 or abs(dy) > 0.01:
                # 有实际变换：一次性提交到数据/存储，撤销记录用拖拽开始时的快照
                self._commit_modify_preview()
                for item in self._modify_snapshot:
                    changes.append({"id": item["id"], "old": item["old"]})
                self._render_all()
                self._bump()
        else:
            # 无拖拽上下文（旧路径）：直接比较数据决定是否产生撤销
            for item in self._modify_snapshot:
                sid = item["id"]
                old = item["old"]
                for s in self._strokes:
                    if s.get("id") == sid:
                        new = _snap_stroke(s)
                        if new != old:
                            changes.append({"id": sid, "old": old})
                        break
        self._modify_preview = None
        self._modify_base_rect = None
        self._modify_snapshot = None
        self._preview_base = None    # 拖拽结束 → 释放预览底图
        if changes:
            self._push_undo({"type": "modify", "changes": changes})

    # ---------- 选择：旋转（绕选中矩形中心） ----------
    def _render_rotate_preview(self):
        """旋转拖拽预览渲染：不改向量，以预览底图（挖掉选中墨迹的 _plain）为底，
        再绕选中矩形中心旋转合入选中笔迹（角度存 _rot_angle，顺时针正）。

        与缩放预览同样按成本二选一：选中笔迹较少走矢量（锐利），较多走图层位图
        合成（快，旋转重采样会略软，松手提交时重绘为锐利矢量）。
        """
        if self._plain is None or self._plain.isNull():
            self._render_all()
            return
        if not self._rot_center or not self._rot_angle:
            self._render_selection_overlay()
            return
        cx, cy = self._rot_center
        deg = float(self._rot_angle)
        base = self._preview_base
        if base is None or base.isNull():
            base = self._build_preview_base()
        img = base.copy()
        sel = set(self._selection or [])
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.save()
        p.translate(cx, cy)
        p.rotate(deg)
        p.translate(-cx, -cy)
        if self._preview_use_vector():
            for s in self._strokes:
                if s.get("id") in sel and s.get("op") == "pen":
                    _draw_selection_outline(p, s, self._light)
                    _draw_stroke(p, s, self._light)
        else:
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            for s in self._strokes:
                if s.get("id") in sel and s.get("op") == "pen":
                    self._blit_stroke(p, s, True)
        p.restore()
        p.end()
        self._image = img

    @Slot()
    def beginRotate(self):
        """开始旋转：记录旋转中心（当前选中矩形中心）与选中笔划旧快照（撤销用）。"""
        if not self._selection or not self._sel_rect:
            return
        r = self._sel_rect
        self._rot_center = (r[0] + r[2] / 2.0, r[1] + r[3] / 2.0)
        self._rot_angle = 0.0
        self.beginModify()   # 快照选中笔划旧数据（撤销 rotate 复用 modify 分支）

    @Slot(float)
    def rotatePreview(self, deg):
        """旋转拖拽中：更新角度并渲染预览（不改向量）。"""
        try:
            d = float(deg)
            if self._rot_center is None or d == self._rot_angle:
                return          # 重复事件/角度未变 → 跳过整帧渲染与刷新
            self._rot_angle = d
            self._render_rotate_preview()
            self._bump()
        except Exception as e:
            plugin_logger.debug(f"旋转预览失败: {e}")

    @Slot()
    def endRotate(self):
        """结束旋转：有实际角度则把选中笔迹绕中心旋转（向量+落盘），提交一次撤销；
        角度并入本选择姿态 _sel_rot_deg（框保持旋转姿态，直到下次重选才重包围）。"""
        try:
            if self._modify_snapshot is None:
                self._rot_center = None
                self._rot_angle = 0.0
                return
            ang = float(self._rot_angle or 0.0)
            if abs(ang) > 0.01 and self._rot_center:
                cx, cy = self._rot_center
                rad = math.radians(ang)
                c, s = math.cos(rad), math.sin(rad)
                sel = set(self._selection or [])
                for st in self._strokes:
                    if st.get("id") not in sel or st.get("op") != "pen":
                        continue
                    new_pts = []
                    for pt in st.get("points", []):
                        dx, dy = pt[0] - cx, pt[1] - cy
                        rp = [cx + dx * c - dy * s, cy + dx * s + dy * c]
                        if len(pt) > 2:
                            rp.append(pt[2])
                        new_pts.append(rp)
                    st["points"] = new_pts
                    # 图案基准轴一起旋转，否则旋转后虚线的划/缺口、箭头会错位
                    _pat_new = _map_pat(st, lambda px, py: (
                        cx + (px - cx) * c - (py - cy) * s,
                        cy + (px - cx) * s + (py - cy) * c))
                    _set_pat(st, _pat_new)
                    self._invalidate_stroke_cache(st)   # 几何变化 → 失效全部派生缓存
                    if self._store:
                        self._store.update_stroke(st["id"], st.get("op"),
                                                  st.get("color", ""),
                                                  st.get("width", 4.0), st["points"],
                                                  pat=_pat_new)
                self._sel_grid = None   # 笔迹几何变化 → 圈选索引失效
                self._plain = None      # 画布无选中版失效（下面 _render_all 会重建）
                changes = [{"id": item["id"], "old": item["old"]}
                           for item in self._modify_snapshot]
                self._sel_rot_deg += ang   # 并入本选择姿态（框保持旋转、不重包围）
                self._render_all()
                self._bump()
                if changes:
                    self._push_undo({"type": "modify", "changes": changes})
                self._bump_thumbs()     # 旋转提交 → 页面缩略图刷新
            self._rot_center = None
            self._rot_angle = 0.0
            self._modify_preview = None
            self._modify_base_rect = None
            self._modify_snapshot = None
            self._preview_base = None
            # 不重算选中矩形：_sel_rect 保持旋转前的基准直框，角度并入 _sel_rot_deg，
            # QML 把框按 _sel_rot_deg 旋转显示（套住旋转后笔迹）；重选时才归零重包围
            self._update_selection_style()
            self.selectionChanged.emit()
        except Exception as e:
            plugin_logger.debug(f"提交旋转失败: {e}")

    # ---------- 选择：旋转态下的缩放（保持当前旋转姿态，锚定视觉对角等比缩放） ----------
    @Slot(str)
    def beginRotatedScale(self, corner):
        """旋转态下开始缩放：快照选中笔划起始点/基准矩形/累计旋转角；锚角=拖角对角（固定）。"""
        try:
            if not self._selection or not self._sel_rect:
                return
            r = self._sel_rect
            if r[2] <= 0 or r[3] <= 0:
                return
            self._rscale = {
                "corner": corner,
                "rect0": list(r),
                "cx": r[0] + r[2] / 2.0,
                "cy": r[1] + r[3] / 2.0,
                "theta": float(self._sel_rot_deg or 0.0),
                "strokes": [(s, [list(p) for p in (s.get("points") or [])])
                             for s in self._strokes
                             if s.get("id") in self._selection and s.get("op") == "pen"],
            }
            self.beginModify()   # 撤销快照（选中笔划旧数据）
        except Exception as e:
            plugin_logger.debug(f"开始旋转态缩放失败: {e}")

    # ---------- 选择：四角缩放的"等比例缩放直线"吸附 ----------
    def _scale_aspect_snap(self, mx, my, corner, x0, y0, w0, h0, theta=None):
        """等比例缩放吸附：返回 (px, py, guide)。

        "等比例缩放直线" = 过**被拖角对的锚角**（对角，缩放的固定点）、方向等于"原矩形中
        该拖角相对锚角的位移向量"的直线（选择带旋转姿态时整条线跟着转）。鼠标落在该线上
        ⇔ 新长/新宽 = 原长/原宽 → 缩放后宽高比与笔迹原本比例相同。
        px/py = 鼠标在该线上的投影（距离 > `_ASPECT_SNAP_PX` 时不吸附，原样返回）；
        guide = 蓝色虚线 [x0,y0,x1,y1]（锚角 → 吸附点再延长 `_ASPECT_GUIDE_EXT`）；未吸附=None。
        """
        if w0 <= 1e-6 or h0 <= 1e-6:
            return mx, my, None
        if corner == "tl":
            ax, ay, sx, sy = x0 + w0, y0 + h0, -1.0, -1.0
        elif corner == "tr":
            ax, ay, sx, sy = x0, y0 + h0, 1.0, -1.0
        elif corner == "br":
            ax, ay, sx, sy = x0, y0, 1.0, 1.0
        else:                                   # bl
            ax, ay, sx, sy = x0 + w0, y0, -1.0, 1.0
        deg = float(self._sel_rot_deg or 0.0) if theta is None else float(theta)
        th = math.radians(deg)
        cc, ss = math.cos(th), math.sin(th)
        cx, cy = x0 + w0 / 2.0, y0 + h0 / 2.0
        # 锚角在屏幕上的位置（旋转姿态下框绕自身中心转，锚角即"显示不动的那个角"）
        vax = cx + (ax - cx) * cc - (ay - cy) * ss
        vay = cy + (ax - cx) * ss + (ay - cy) * cc
        # 方向 = 原矩形"拖角 − 锚角"向量，再按当前姿态旋到屏幕系
        bxv, byv = sx * w0, sy * h0
        vdx = bxv * cc - byv * ss
        vdy = bxv * ss + byv * cc
        ln = math.hypot(vdx, vdy)
        if ln < 1e-6:
            return mx, my, None
        ux, uy = vdx / ln, vdy / ln
        t = (mx - vax) * ux + (my - vay) * uy
        if abs(t) < 6.0:
            return mx, my, None            # 离锚角太近不吸附（否则一开始拖动就跳）
        if t < 0.0:                        # 鼠标翻到锚角另一侧：沿那一侧画引导线
            ux, uy, t = -ux, -uy, -t
        px, py = vax + ux * t, vay + uy * t
        if math.hypot(mx - px, my - py) > _ASPECT_SNAP_PX:
            return mx, my, None
        return px, py, [vax, vay,
                        vax + ux * (t + _ASPECT_GUIDE_EXT),
                        vay + uy * (t + _ASPECT_GUIDE_EXT)]

    def _set_scale_aspect_guide(self, guide):
        g = [float(v) for v in guide] if guide else []
        if g != self._scale_aspect_guide:
            self._scale_aspect_guide = g
            # 只发通知（不动 imageVersion）→ QML 只重画引导线，不会重新取图
            self.imageVersionChanged.emit()

    @Slot(float, float, str, float, float, float, float, result="QVariantList")
    def snapScaleAspect(self, mx, my, corner, x0, y0, w0, h0):
        """非旋转态四角缩放（由 QML 驱动）：把鼠标吸到"等比例缩放直线"上，返回 [x, y]。"""
        try:
            px, py, guide = self._scale_aspect_snap(float(mx), float(my), str(corner),
                                                    float(x0), float(y0),
                                                    float(w0), float(h0))
        except Exception as e:
            plugin_logger.debug(f"等比例缩放吸附失败: {e}")
            px, py, guide = float(mx), float(my), None
        self._set_scale_aspect_guide(guide)
        return [px, py]

    @Slot()
    def clearScaleAspectGuide(self):
        """清除"等比例缩放直线"引导线（缩放拖拽开始/结束时调用）。"""
        self._set_scale_aspect_guide(None)

    @Slot(float, float)
    def rotatedScaleTo(self, mx, my):
        """旋转态缩放拖动中：**自由比例**（各轴独立）缩放，保持当前旋转姿态。

        做法与用户直觉严格一致：对角（视觉锚角）在屏幕上不动，被拖的视觉角始终跟着鼠标。
        在旋转参考系里量"鼠标 − 视觉锚"得到新长/宽；新矩形的**中心** = 两个视觉对角的
        中点（旋转不改变自身中心）→ 基准矩形 = 以该中心、尺寸 (nw,nh) 的横平竖直框；
        显示时 QML 把基准框绕自身中心转 θ → 正好套住拉伸后的点阵。
        鼠标接近"等比例缩放直线"时先吸附到该线上（与原比例一致），并给出蓝色虚线引导线。
        """
        try:
            rs = self._rscale
            if not rs or not rs["strokes"]:
                return
            corner = rs["corner"]
            x0, y0, w0, h0 = rs["rect0"]
            # 等比例缩放直线吸附（用拖拽开始时的基准矩形与姿态角）
            mx, my, guide = self._scale_aspect_snap(float(mx), float(my), corner,
                                                    float(x0), float(y0),
                                                    float(w0), float(h0),
                                                    rs["theta"])
            self._set_scale_aspect_guide(guide)
            cx, cy = rs["cx"], rs["cy"]
            th = math.radians(rs["theta"])
            cc, ss = math.cos(th), math.sin(th)
            # 锚角（拖角对角）在基准系；它的**视觉**位置保持不变
            if corner == "tl":
                ax, ay = x0 + w0, y0 + h0
            elif corner == "tr":
                ax, ay = x0, y0 + h0
            elif corner == "br":
                ax, ay = x0, y0
            else:  # bl
                ax, ay = x0 + w0, y0
            vax = cx + (ax - cx) * cc - (ay - cy) * ss
            vay = cy + (ax - cx) * ss + (ay - cy) * cc
            # 逆旋"鼠标 − 视觉锚"回 θ 参考系 → 各轴独立得到新长宽（自由比例）
            ddx, ddy = float(mx) - vax, float(my) - vay
            ux = ddx * cc + ddy * ss
            uy = -ddx * ss + ddy * cc
            minSize = 8.0
            nw = max(abs(ux), minSize)
            nh = max(abs(uy), minSize)
            # 新框（基准系）：中心 = 两视觉对角中点（旋转不改变自身中心）
            ncx = (vax + float(mx)) / 2.0
            ncy = (vay + float(my)) / 2.0
            nl = ncx - nw / 2.0
            nt = ncy - nh / 2.0
            # 复用统一的"目标矩形 + 预览"通道（预览渲染会按 _sel_rot_deg 补上绕中心的旋转）
            self.applyTransform(nl, nt, nw, nh)
        except Exception as e:
            plugin_logger.debug(f"旋转态缩放失败: {e}")

    @Slot()
    def endRotatedScale(self):
        """结束旋转态缩放：按与预览完全一致的映射把结果一次性提交到向量/存储并压入一次撤销。

        映射 = W = R_c2(θ) ∘ X ∘ R_c1(θ)⁻¹（见 _modify_map_pt）；任意长宽比（非等比）。
        拖拽期间只做预览（不改向量、不落盘）：原来每个鼠标事件都改写全部选中
        笔划并整幅重绘（含所有未选中笔迹），实测一次拖动能把一帧推到数百毫秒。
        """
        try:
            if self._rscale is None:
                return
            rs = self._rscale
            pv = self._modify_preview
            self._rscale = None
            changes = [{"id": item["id"], "old": item["old"]}
                       for item in (self._modify_snapshot or [])]
            if (isinstance(pv, tuple) and len(pv) == 4 and pv[0] != "rot"):
                for (stroke, start_pts) in rs["strokes"]:
                    new_pts = []
                    for pt in start_pts:
                        nx, ny = self._modify_map_pt(pt[0], pt[1])
                        if len(pt) > 2:
                            new_pts.append([nx, ny, pt[2]])
                        else:
                            new_pts.append([nx, ny])
                    stroke["points"] = new_pts
                    _pat_new = _map_pat(stroke, self._modify_map_pt)
                    _set_pat(stroke, _pat_new)
                    self._invalidate_stroke_cache(stroke)
                    if self._store:
                        self._store.update_stroke(
                            stroke["id"], stroke.get("op"),
                            stroke.get("color", ""),
                            stroke.get("width", 4.0), new_pts,
                            pat=_pat_new)
                self._sel_grid = None   # 笔迹几何变化 → 圈选索引失效
                self._plain = None      # 画布无选中版失效（下面 _render_all 会重建）
                self._update_selection_style()
                self._render_all()
                self._bump()
                if changes:
                    self._push_undo({"type": "modify", "changes": changes})
                self._bump_thumbs()
            self._modify_preview = None
            self._modify_base_rect = None
            self._modify_snapshot = None
            self._preview_base = None
            self.selectionChanged.emit()
        except Exception as e:
            plugin_logger.debug(f"提交旋转态缩放失败: {e}")
            self._modify_preview = None
            self._modify_base_rect = None
            self._modify_snapshot = None
            self._update_selection_style()
            self.selectionChanged.emit()
        except Exception as e:
            plugin_logger.debug(f"结束旋转态缩放失败: {e}")

    # ---------- 形状线：端点手柄（仅当选中的全是线；QML 用首末两个圆手柄改起/终点）---------
    def _selection_all_lines(self):
        """选中项是否非空且**全部**是形状线（决定选择框用“端点手柄”还是“矩形+四角”）。

        混了手绘笔迹就返回 False —— 笔迹没有“首末端点”的语义，仍用传统矩形形态。
        """
        if not self._selection:
            return False
        sel = set(self._selection)
        found = False
        for s in self._strokes:
            if s.get("id") in sel and s.get("op") == "pen":
                if not _line_style_of(s):
                    return False
                found = True
        return found

    @Slot(int, int)
    def beginLineHandle(self, stroke_id, which):
        """按下某条线的端点手柄（which 0=起点 1=终点）：快照旧几何，拖拽合并为一次撤销。

        **坐标系**（完整）例外（用户要求 3/4/5）：
        · 空间直角坐标系：原点那一端**不给手柄**（`has0=False`），只有箭头端能拖；
        · 平面直角坐标系：每条轴的两个端点都远离原点 → **两端都能拖**；
        · 不管拖哪一端，都只能沿该端**原本的方向**（= 从原点指向该端，旋转过的坐标系就是旋转后
          的方向）在原点以外伸缩 → 这里把 "原点 + 方向" 记到 `self._axis_drag`，`dragLineHandle`
          据此把鼠标投影到该方向上。
        """
        sid = int(stroke_id)
        which = int(which)
        for st in self._strokes:
            if st.get("id") != sid or not _line_style_of(st):
                continue
            drag = None
            info = self._coord_axis_ends().get(sid)
            if info is not None:
                org, has0, has1 = info
                if not (has1 if which == 1 else has0):
                    return                  # 原点那一端没有手柄 → 不接受拖拽
                pts = st.get("points") or []
                end = pts[-1] if which == 1 else pts[0]
                dx, dy = float(end[0]) - org[0], float(end[1]) - org[1]
                ln = math.hypot(dx, dy)
                if ln < 1e-6:
                    return
                drag = (float(org[0]), float(org[1]), dx / ln, dy / ln)
            self.beginModify()          # 快照（含 style）→ endModify 按旧数据比对压 undo
            self._line_handle = (sid, which)
            self._axis_drag = drag
            return

    @Slot(float, float)
    def dragLineHandle(self, x, y):
        """拖拽端点：把该线的起点/终点移到鼠标处并实时重绘（几何变化 → 缓存全部失效）。

        坐标系（`self._axis_drag` 非空）：端点**只能沿这根轴原方向移动**（横向偏移忽略），
        且不得越过原点（长度不小于 `_AXIS_MIN_LEN`）→ 见用户要求 3。
        """
        if not self._line_handle:
            return
        sid, which = self._line_handle
        if self._axis_drag:
            ox, oy, ux, uy = self._axis_drag
            t = (float(x) - ox) * ux + (float(y) - oy) * uy     # 鼠标在原方向上的投影
            t = max(t, _AXIS_MIN_LEN)                          # 不能越过原点（且不短于最短轴长）
            x, y = ox + ux * t, oy + uy * t
        for s in self._strokes:
            if s.get("id") != sid:
                continue
            pts = s.get("points") or []
            if len(pts) < 2:
                return
            pts[0 if which == 0 else len(pts) - 1] = [float(x), float(y)]
            # 端点被拖动 → 线条本身就成了新的图案基准（清除旧 pat，回到以自身起末
            # 点为基准的相位 0；否则虚线划与缺口会按已经不存在的那条旧线排列）
            _set_pat(s, None)
            self._invalidate_stroke_cache(s)   # 几何变化 → 失效全部派生缓存
            self._sel_grid = None      # 圈选索引失效
            self._plain = None         # 画布无选中版失效
            self._preview_base = None
            self._compute_selection_rect(reset_rot=False)   # 不重置旋转姿态
            if self._store:
                self._store.update_stroke(s["id"], s.get("op", "pen"),
                                          s.get("color", ""),
                                          float(s.get("width", 4.0)), s["points"],
                                          pat="")
            self._render_all()
            self._bump()
            self.selectionChanged.emit()
            return

    @Slot()
    def endLineHandle(self):
        """松开端点手柄：提交（endModify 比对旧快照 → 压入一条可撤销的 modify）。"""
        if not self._line_handle:
            return
        self._line_handle = None
        self._axis_drag = None
        self.endModify()
        self._bump_thumbs()   # 几何变化 → 页面缩略图刷新

    @Slot(float)
    def setSelectionWidth(self, w):
        """给选中笔划统一换粗细（支持 4.5 半粗）。形状线同样适用（线宽/图案按笔宽缩放）。"""
        w = float(w)
        if w <= 0 or not self._selection:
            return
        changes = []
        for s in self._strokes:
            if s.get("id") not in self._selection or s.get("op") != "pen":
                continue
            old = _snap_stroke(s)
            s["width"] = w
            self._invalidate_stroke_cache(s)   # 粗细变化 → 失效全部派生缓存
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
        self._bump_thumbs()   # 换粗细 → 页面缩略图刷新

    @Slot(str)
    def setSelectionColor(self, color):
        """给选中笔划统一换颜色（逻辑名，显示 hex 随模式映射）。形状线同样适用。"""
        if not self._selection:
            return
        color = color or ""
        changes = []
        for s in self._strokes:
            if s.get("id") not in self._selection or s.get("op") != "pen":
                continue
            old = _snap_stroke(s)
            s["color"] = color
            self._invalidate_layers([s])   # 颜色变化 → 失效颜色已固化的预烘焙图层
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
        self._bump_thumbs()   # 换颜色 → 页面缩略图刷新

    @Slot(str)
    def setSelectionLineStyle(self, style):
        """把选中的形状线统一改成指定线型（见 _LINE_SHAPES）。

        仅作用于**已经是形状线**的选中笔划：手绘笔迹不会被“变成线”（它们没有首末
        直线的语义）；线型变化会改变渲染形状 → 失效全部派生缓存并重绘。
        """
        if not self._selection or style not in _LINE_SHAPES:
            return
        changes = []
        for s in self._strokes:
            if s.get("id") not in self._selection or s.get("op") != "pen":
                continue
            cur = _line_style_of(s)
            if not cur or cur == style:
                continue          # 手绘笔迹 / 已是该线型 → 跳过（不产生无谓撤销）
            old = _snap_stroke(s)
            s["style"] = style
            self._invalidate_stroke_cache(s)   # 线型变化 → 失效全部派生缓存
            changes.append({"id": s.get("id"), "old": old})
            if self._store:
                self._store.update_stroke(s["id"], s.get("op"), s.get("color", ""),
                                          float(s.get("width", 4.0)), s["points"],
                                          style)
        if changes:
            self._push_undo({"type": "modify", "changes": changes})
        self._update_selection_style()
        self._render_all()
        self._bump()
        self.selectionChanged.emit()
        self._bump_thumbs()   # 换线型 → 页面缩略图刷新

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
        self.finishPendingDrawing()   # 切页前先收尾：正在画的多阶段/多步图形不能丢（用户要求）
        self.cancelStroke()
        self._pages[self._page_index]["file"] = self._store.current_file() if self._store else None
        self._pages[self._page_index]["strokes"] = self._strokes
        self._pages[self._page_index]["undo"] = self._undo_stack
        # 离开当前页 → 释放其预烘焙图层（切回时按需重建），控制多页时的内存总量
        self._invalidate_layers(self._strokes)
        self._preview_base = None
        if self._store:
            w, h, dpr, mode = self._screen
            self._store.new_session(w, h, dpr, mode)
            new_file = self._store.current_file()
        else:
            new_file = None
        self._strokes = []
        self._sel_grid = None   # 笔迹变化 → 圈选索引失效
        self._plain = None      # 画布无选中版失效（下面 _render_all 会重建）
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
        self._release_other_pages()   # 释放其他页常驻点列（各页已增量落盘）
        self._render_all()
        self._bump()
        self.selectionChanged.emit()
        self.canUndoChanged.emit()
        self.pageChanged.emit()
        self.pageAdded.emit()   # 页面列表增量同步：append 新页（避免 ListView 全重建/滚动重置）

    def _switch_to_page(self, index):
        """切到指定页（0-based）：保存当前页内存状态，打开目标页会话文件并载入其笔迹/撤销栈。"""
        n = len(self._pages)
        if index < 0 or index >= n or index == self._page_index:
            return
        self.finishPendingDrawing()   # 切页前先收尾：正在画的多阶段/多步图形不能丢（用户要求）
        self.cancelStroke()
        self._pages[self._page_index]["file"] = self._store.current_file() if self._store else None
        self._pages[self._page_index]["strokes"] = self._strokes
        self._pages[self._page_index]["undo"] = self._undo_stack
        # 离开当前页 → 释放其预烘焙图层（切回时按需重建），控制多页时的内存总量
        self._invalidate_layers(self._strokes)
        self._preview_base = None
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
        # 惰性页：切回时才从该页的会话文件读回笔迹（见 _release_other_pages）
        if page.get("strokes") is None:
            page["strokes"] = self._store.load_all() if self._store else []
        self._strokes = page["strokes"]
        self._release_other_pages()   # 释放其他页常驻点列（各页已增量落盘）
        self._sel_grid = None   # 笔迹变化 → 圈选索引失效
        self._plain = None      # 画布无选中版失效（下面 _render_all 会重建）
        self._preview_base = None
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
        self._bump_thumbs()   # 切页 → 页面缩略图刷新

    @Slot(int)
    def switchToPage(self, index):
        """切到指定页（页面列表菜单点击缩略图/行）。"""
        self._switch_to_page(int(index))

    # ---------- 数据管理：历史页面（data 目录里未打开的页面） ----------
    def _history_entries(self):
        """data 目录里**未打开**的页面文件（= 历史页面）→ [{file, title, mtime}]，新的在前。

        判据：文件名形如 `canvas_*.db`，且不在当前 `_pages` 的文件列表里（那些属于"已打开的页面"）。
        标题暂用文件修改时间（用户要求：先用系统时间戳）。
        """
        if not self._store:
            return []
        d = self._store.data_dir
        opened = {str(pg.get("file") or "") for pg in self._pages}
        try:
            names = [n for n in os.listdir(d)
                     if n.startswith("canvas_") and n.endswith(".db")]
        except Exception:
            names = []
        out = []
        for n in names:
            if n in opened:
                continue
            try:
                mt = float(os.path.getmtime(os.path.join(d, n)))
            except Exception:
                continue
            out.append({"file": n, "mtime": mt,
                        "title": time.strftime("%Y-%m-%d %H:%M", time.localtime(mt))})
        out.sort(key=lambda e: -e["mtime"])
        return out

    @Property('QVariantList', notify=historyChanged)
    def historyPages(self):
        """历史页面列表（数据管理页"历史页面"分区）：[{file, title, mtime}]，按修改时间倒序。"""
        return self._history_entries()

    @Slot()
    def clearDataManagerCache(self):
        """数据管理页关闭时清掉历史缩略图缓存（用户要求：关闭后及时释放资源）。"""
        self._hist_thumb_cache.clear()

    @Slot(str)
    def openHistoryPage(self, name):
        """把一个历史页面读出来，放到**当前页后面**新建的一页上（页数可以超过 10）。

        用户要求：点历史页 → 在当前显示的页之后新建一页，并把对应页的数据读出来放到这一页上。
        做法：只读打开历史文件读出笔迹 → 新建空白会话文件 → 把笔迹逐笔写进新文件 →
        把新页插到 `_page_index + 1` 并切过去。
        """
        base = os.path.basename(str(name or ""))
        if not self._store or not base:
            return
        src = os.path.join(self._store.data_dir, base)
        if not os.path.exists(src):
            return
        self.finishPendingDrawing()   # 先收尾（正在画的多阶段/多步图形不能丢）
        self.cancelStroke()
        # 保存当前页内存状态（与 addPage/deletePage 同一套）
        self._pages[self._page_index]["file"] = self._store.current_file() if self._store else None
        self._pages[self._page_index]["strokes"] = self._strokes
        self._pages[self._page_index]["undo"] = self._undo_stack
        self._invalidate_layers(self._strokes)
        self._preview_base = None
        # 读出历史页笔迹（只读打开，不碰当前会话）
        hist = self._load_page_strokes_readonly(base)
        # 新建会话文件作为新页
        w, h, dpr, mode = self._screen
        self._store.new_session(w, h, dpr, mode)
        new_file = self._store.current_file()
        strokes = []
        for s in hist:
            sid = self._store.add_stroke(s.get("op", "pen"), s.get("color", ""),
                                         float(s.get("width", 4.0)),
                                         s.get("points") or [],
                                         s.get("style", ""),
                                         pat=s.get("pat"), grp=s.get("grp", ""))
            if sid is not None:
                s["id"] = int(sid)
            strokes.append(s)
        if strokes:
            self._store.set_all_seq([int(s["id"]) for s in strokes
                                     if s.get("id") is not None])
        page = {"file": new_file, "strokes": strokes, "undo": []}
        self._pages.insert(self._page_index + 1, page)
        self._page_index += 1
        self._strokes = strokes
        self._undo_stack = page["undo"]
        self._sel_grid = None
        self._plain = None
        self._preview_base = None
        self._sel_poly = None
        self._selection = []
        self._sel_rect = None
        self._sel_active = False
        self._sel_color = ""
        self._sel_width = 0
        self._ensure_image()
        self._image.fill(Qt.transparent)
        self._save_page_registry()
        self._release_other_pages()
        self._render_all()
        self._bump()
        self.selectionChanged.emit()
        self.canUndoChanged.emit()
        self.pageChanged.emit()
        self.pageAdded.emit()      # 页数 +1（页面列表 ListModel append）
        self._thumb_cache.clear()  # 索引重排 → 缩略图全失效
        self._bump_thumbs()        # 版本 +1 → QML 重新请求缩略图（页面列表 + 数据管理页）
        self.historyChanged.emit() # 这个文件已变成"已打开的页面"

    @Slot(int)
    def deletePage(self, index):
        """删除指定页（0-based，页面列表菜单删除按钮）：删除其会话文件、后面的页前移
        （页码自动重排）；删除当前页时切到邻近页；至少保留 1 页。删除页不可撤销。"""
        index = int(index)
        n = len(self._pages)
        if n <= 1 or index < 0 or index >= n:
            return
        self.finishPendingDrawing()   # 删页前先收尾（否则正在画的形状会跟着页面一起消失）
        self.cancelStroke()
        # 先把当前页活动笔迹写回 _pages：画/擦除/移动/缩放/删除/撤销等操作只改 self._strokes
        # 未写回 _pages，若删除非当前页后下方重载 current 页，会把活动笔迹重置为旧快照
        # （擦除/新笔画丢失）。删除当前页时此处即为该页的保存。
        self._pages[self._page_index]["file"] = self._store.current_file() if self._store else None
        self._pages[self._page_index]["strokes"] = self._strokes
        self._pages[self._page_index]["undo"] = self._undo_stack
        self._invalidate_layers(self._strokes)   # 释放旧页图层（控制多页内存）
        self._preview_base = None
        # 删除页文件（含 -wal/-shm）
        if self._store:
            try:
                self._store.remove_file(self._pages[index].get("file"))
            except Exception as e:
                plugin_logger.debug(f"删除页文件失败: {e}")
        del self._pages[index]
        # 调整当前页索引并载入新当前页
        if self._page_index > index:
            self._page_index -= 1
        elif self._page_index >= len(self._pages):
            self._page_index = len(self._pages) - 1
        page = self._pages[self._page_index]
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
        # 惰性页：切回时才从该页的会话文件读回笔迹
        if page.get("strokes") is None:
            page["strokes"] = self._store.load_all() if self._store else []
        self._strokes = page["strokes"]
        self._release_other_pages()   # 释放其他页常驻点列（各页已增量落盘）
        self._sel_grid = None   # 笔迹变化 → 圈选索引失效
        self._plain = None      # 画布无选中版失效（下面 _render_all 会重建）
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
        self._thumb_cache.clear()   # 索引重排 → 清缩略图缓存（不 bump 版本）
        self.pageRemoved.emit(index)   # 页面列表增量同步：remove 删除项（避免 ListView 全重建/滚动重置）
        self.historyChanged.emit()     # 删页会移除文件 → 数据管理页的"历史页面"也可能变

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
        self._sel_grid = None   # 笔迹变化 → 圈选索引失效
        self._plain = None      # 画布无选中版失效（下面 _render_all 会重建）
        if self._store:
            for s in removed:
                self._store.delete_stroke(s["id"])
        self._push_undo({"type": "delete", "strokes": [
            dict(_snap_stroke(s), id=int(s.get("id", 0))) for s in removed]})
        self._sel_poly = None
        self._selection = []
        self._sel_rect = None
        self._sel_active = False
        self._sel_color = ""
        self._sel_width = 0
        self._render_all()
        self._bump()
        self.selectionChanged.emit()
        self._bump_thumbs()   # 删除选中笔迹 → 页面缩略图刷新

    @Slot()
    def cloneSelection(self):
        """克隆选中笔迹：整体按固定偏移(32,32)复制一份并落盘（浮动工具栏"克隆"按钮）。

        旧笔迹取消选中、克隆出的新笔迹选中（可撤销：一次撤删除全部克隆）。
        """
        if not self._selection:
            return
        selected = set(self._selection)
        off = 32.0
        # 无存储（内存模式降级）时手动分配自增 id
        try:
            nxt = max([int(s.get("id", 0)) for s in self._strokes] or [0])
        except Exception:
            nxt = 0
        new_strokes = []
        new_ids = []
        gmap = {}
        for s in self._strokes:
            if s.get("id") not in selected or s.get("op") != "pen":
                continue
            pts = []
            for p in (s.get("points") or []):
                q = [float(p[0]) + off, float(p[1]) + off]
                if len(p) > 2:
                    q.append(p[2])
                pts.append(q)
            color = s.get("color", "") or ""
            width = float(s.get("width", 4.0))
            style = s.get("style", "")
            # 图案基准轴一起偏移：克隆体的虚线划/缺口位置与原笔划一致（整体平移）
            pat = _map_pat(s, lambda px, py: (px + off, py + off))
            # 分组 id：克隆体是**新的**一个立体图形（不能与原图形同组）
            gsrc = s.get("grp") or ""
            gclone = ""
            if gsrc:
                if gsrc not in gmap:
                    gmap[gsrc] = _new_grp()
                gclone = gmap[gsrc]
            sid = None
            if self._store:
                sid = self._store.add_stroke("pen", color, width, pts, style, pat=pat,
                                             grp=gclone)
            if sid is None:
                nxt += 1
                sid = nxt
            _new_sk = {"id": int(sid), "op": "pen", "color": color,
                       "width": width, "style": style,
                       "points": pts}
            _set_pat(_new_sk, pat)
            _set_grp(_new_sk, gclone)
            new_strokes.append(_new_sk)
            new_ids.append(int(sid))
        if not new_strokes:
            return
        self._strokes.extend(new_strokes)
        self._sel_grid = None   # 笔迹变化 → 圈选索引失效
        self._plain = None      # 画布无选中版失效（下面 _render_all 会重建）
        self._push_undo({"type": "clone", "ids": list(new_ids)})
        # 旧笔迹取消选中、新笔迹选中
        self._sel_poly = None
        self._selection = list(new_ids)
        self._compute_selection_rect()
        self._update_selection_style()
        self._render_all()
        self._bump()
        self.selectionChanged.emit()
        self._bump_thumbs()   # 新增克隆笔迹 → 页面缩略图刷新

    # ---------- 撤销 ----------
    def _push_undo(self, op):
        """压入撤销栈并追加进当前会话 ops 表（增量操作日志）。

        内存控制（长时间会话不膨胀）：① 几何快照换成扁平 array('d') 紧凑编码
        （_pack_undo_op，约省 8 倍）；② 超过条数/字节双上限时丢弃最老的记录。

        **本方法绝不向外抛异常**：调用方（删除/克隆/拖拽提交…）都是"先改数据、再记
        撤销、最后重绘"，一旦记录阶段抛异常就会跳过重绘 → 画面上旧墨迹不消失（曾因
        _pack_points 不支持混合元数而真实发生过"点删除没反应"）。宁可丢一条撤销记录，
        也不能让画面/状态不一致。
        """
        try:
            op = _pack_undo_op(op)
        except Exception as e:
            plugin_logger.debug(f"撤销快照编码失败（已跳过该条撤销记录）: {e}")
            return
        self._undo_stack.append(op)
        try:
            self._trim_undo_stack()
            self.canUndoChanged.emit()
            if self._store:
                self._store.log_op(op.get("type", ""), op)
        except Exception as e:
            plugin_logger.debug(f"撤销记录后处理失败（不影响画面与内存撤销栈）: {e}")

    def _trim_undo_stack(self):
        """按条数（_UNDO_MAX_OPS）与字节（_UNDO_BUDGET_BYTES）双上限裁剪撤销栈。

        从最老的开始丢——保留最近若干步可撤销（常规会话远达不到上限，不会触发）。
        """
        st = self._undo_stack
        if not st:
            return
        total = 0
        for o in st:
            total += o.get("_bytes", 0)
        while st and (len(st) > _UNDO_MAX_OPS or total > _UNDO_BUDGET_BYTES):
            dropped = st.pop(0)   # 深度受上限约束，pop(0) 的 O(n) 可忽略
            total -= dropped.get("_bytes", 0)

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
            elif t == "add_many":
                # 批量新增（双曲线 = 两支线 + 两渐近线共 4 笔）：一次撤销全部移除
                ids = set(int(i) for i in op.get("ids", []))
                if ids:
                    self._strokes = [s for s in self._strokes
                                     if int(s.get("id", -1)) not in ids]
                    if self._store:
                        for sid in ids:
                            self._store.delete_stroke(sid)
            elif t == "clone":
                # 撤销克隆：删除克隆出的新笔迹（旧笔迹保留）
                ids = set(op.get("ids", []))
                if ids:
                    self._strokes = [s for s in self._strokes
                                     if s.get("id") not in ids]
                    if self._store:
                        for sid in ids:
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
                    pts = _unpack_points(st.get("points"))
                    sty = st.get("style", "")
                    sid = None
                    if self._store:
                        sid = self._store.add_stroke(st.get("op", "pen"),
                                                     st.get("color", ""),
                                                     st.get("width", 4.0),
                                                     pts, sty, pat=st.get("pat"),
                                                     grp=st.get("grp", ""))
                    new_sk = {
                        "_orig_id": int(st.get("id", 0)),
                        "id": int(sid) if sid is not None else int(st.get("id", 0)),
                        "op": st.get("op", "pen"),
                        "color": st.get("color", ""),
                        "width": float(st.get("width", 4.0)),
                        "style": sty,
                        "points": pts}
                    _set_pat(new_sk, st.get("pat"))
                    _set_grp(new_sk, st.get("grp"))
                    self._strokes.append(new_sk)
                self._strokes.sort(key=lambda s: s.get("_orig_id", s.get("id", 0)))
                # 重排顺序号：新 id 会大于其它笔划，须让 DB 顺序与内存一致（否则重启后乱序）
                if self._store:
                    self._store.set_all_seq([s["id"] for s in self._strokes])
            elif t == "erase":
                # 撤销擦除：删除切分出的碎片笔划，按原位恢复被擦前的原始笔划（显式 id），
                # 最后重排全部顺序号，保证绘制顺序一致
                added = set(op.get("added_ids", []))
                if added:
                    self._strokes = [s for s in self._strokes
                                     if s.get("id") not in added]
                    if self._store:
                        for sid in added:
                            self._store.delete_stroke(sid)
                for item in op.get("removed", []):
                    old = item.get("old") or {}
                    old_id = int(item.get("id", 0))
                    stroke = {"id": old_id,
                              "op": old.get("op", "pen"),
                              "color": old.get("color", ""),
                              "width": float(old.get("width", 4.0)),
                              "style": old.get("style", ""),
                              "points": _unpack_points(old.get("points"))}
                    _set_pat(stroke, old.get("pat"))
                    _set_grp(stroke, old.get("grp"))
                    idx = min(int(item.get("index", 0)), len(self._strokes))
                    self._strokes.insert(idx, stroke)
                    if self._store:
                        self._store.insert_stroke(old_id, stroke["op"],
                                                  stroke["color"], stroke["width"],
                                                  stroke["points"],
                                                  stroke["style"],
                                                  pat=stroke.get("pat"),
                                                  grp=stroke.get("grp", ""))
                if self._store:
                    self._store.set_all_seq([s["id"] for s in self._strokes])
            elif t == "modify":
                for ch in op.get("changes", []):
                    sid = ch.get("id")
                    old = ch.get("old") or {}
                    for s in self._strokes:
                        if s.get("id") == sid:
                            s["op"] = old.get("op", s.get("op", "pen"))
                            s["color"] = old.get("color", "")
                            s["width"] = float(old.get("width", 4.0))
                            # 仅在快照里确实带了 style 时才动它（旧快照无此键 → 保持原线型，
                            # 否则撤销“换色/换粗细”会把虚线/波浪线静默降级成实线）
                            if "style" in old:
                                s["style"] = old.get("style", "")
                            _set_pat(s, old.get("pat"))
                            _set_grp(s, old.get("grp"))
                            s["points"] = _unpack_points(old.get("points"))
                            self._invalidate_stroke_cache(s)  # 恢复几何/样式 → 全部缓存失效
                            if self._store:
                                self._store.update_stroke(
                                    sid, s["op"], s["color"], s["width"],
                                    s["points"], s["style"], pat=s.get("pat") or "",
                                    grp=s.get("grp") or "")
                            break
        except Exception as e:
            plugin_logger.debug(f"撤销失败: {e}")
        # 撤销后旧选择可能引用已删/已改的笔划 → 清除选择
        self._sel_grid = None   # 笔迹变化 → 圈选索引失效
        self._plain = None      # 画布无选中版失效（下面 _render_all 会重建）
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
        self._bump_thumbs()   # 撤销 → 页面缩略图刷新

    # ---------- 选择/撤销属性 ----------
    @Property(bool, notify=selectionChanged)
    def hasSelection(self):
        return bool(self._sel_active and self._selection)

    def _line_handles_data(self):
        """选中线的首末端点列表（含拖拽预览映射）；非“全是线”时返回空。

        拖拽预览期间（平移/缩放，向量数据尚未提交）端点也要按同一变换映射，
        否则拖拽时手柄会停在原位、不跟着线一起动：与 _commit_modify_preview 用
        同一套映射 P' = base + d + (P − base)·s（rot 预览不属于本模式，不映射）。

        **坐标系**（完整）例外：端点是否给手柄由 `has0`/`has1` 决定（用户要求 3/4）——
        空间直角坐标系的原点那一端不给手柄；平面直角坐标系的两个端点都给；
        混选（坐标系 + 其它线型）时只影响轴笔划，其它线照常两个手柄（用户要求 5）。
        """
        if not self._selection_all_lines():
            return []
        sx = sy = 1.0
        dx = dy = 0.0
        bx = by = 0.0
        mp = self._modify_preview
        if (isinstance(mp, (tuple, list)) and len(mp) == 4
                and not isinstance(mp[0], str) and self._modify_base_rect):
            sx, sy, dx, dy = (float(v) for v in mp)
            bx, by = float(self._modify_base_rect[0]), float(self._modify_base_rect[1])
        ends = self._coord_axis_ends()
        sel = set(self._selection)
        out = []
        for s in self._strokes:
            if s.get("id") in sel and _line_style_of(s):
                pts = s.get("points") or []
                if len(pts) >= 2:
                    x0, y0 = float(pts[0][0]), float(pts[0][1])
                    x1, y1 = float(pts[-1][0]), float(pts[-1][1])
                    info = ends.get(int(s.get("id", -1)))
                    has0 = True if info is None else bool(info[1])
                    has1 = True if info is None else bool(info[2])
                    out.append({"id": int(s.get("id", 0)),
                                "x0": bx + dx + (x0 - bx) * sx,
                                "y0": by + dy + (y0 - by) * sy,
                                "x1": bx + dx + (x1 - bx) * sx,
                                "y1": by + dy + (y1 - by) * sy,
                                "has0": has0,
                                "has1": has1})
        return out

    def _coord_axis_ends(self):
        """当前选择里的**完整坐标系** → {笔划 id: (原点, 可拖端0, 可拖端1)}；没有则空字典。

        判据：某个 `grp` 组**整组都在选择里**、且整组都是 `style="arrow"` 的直线 ——
        坐标系的几根轴就是这么存的（`_commit_axes`）；普通手画箭头线没有 grp、被橡皮切过的
        碎片 grp 已清空 → 都不算。
        **混选（坐标系 + 其它线型/笔迹）同样识别**（用户要求 5）：只对轴笔划加约束，其它线不变。
        原点：所有轴的**共同起点**（空间直角坐标系：三轴共起点）；否则取两轴交点（平面直角
        坐标系：两轴交于原点）。
        可拖端：端点离原点 > 0.5px 才给手柄 —— 空间直角坐标系的原点那一端不给（用户要求），
        平面直角坐标系的两个端点都不在原点 → **两端都能拖**（用户要求 4）。
        """
        out = {}
        if not self._selection:
            return out
        sel = set(self._selection)
        picked = {}
        for s in self._strokes:
            g = str(s.get("grp") or "")
            if g and s.get("id") in sel:
                picked.setdefault(g, []).append(s)
        for g, got in picked.items():
            members = [s for s in self._strokes if str(s.get("grp") or "") == g]
            if len(members) < 2 or len(got) != len(members):
                continue          # 组不完整（被橡皮切开 / 只选了一部分）→ 不按坐标系处理
            ok = True
            for s in members:
                if (s.get("op") != "pen"
                        or str(s.get("style") or "") != _AXIS_ARROW_STYLE
                        or len(s.get("points") or []) < 2):
                    ok = False
                    break
            if not ok:
                continue
            org = self._coord_axis_origin(members)
            if org is None:
                continue
            for s in members:
                pts = s.get("points") or []
                p0 = (float(pts[0][0]), float(pts[0][1]))
                p1 = (float(pts[-1][0]), float(pts[-1][1]))
                has0 = math.hypot(p0[0] - org[0], p0[1] - org[1]) > 0.5
                has1 = math.hypot(p1[0] - org[0], p1[1] - org[1]) > 0.5
                out[int(s.get("id", -1))] = (org, has0, has1)
        return out

    @staticmethod
    def _coord_axis_origin(sts):
        """坐标系的原点：所有轴的**共同起点**；否则两轴交点；算不出返回 None。"""
        p0 = [(float(s["points"][0][0]), float(s["points"][0][1])) for s in sts]
        if all(abs(p[0] - p0[0][0]) < 0.5 and abs(p[1] - p0[0][1]) < 0.5 for p in p0):
            return p0[0]
        if len(sts) == 2:
            t0 = (float(sts[0]["points"][-1][0]), float(sts[0]["points"][-1][1]))
            t1 = (float(sts[1]["points"][-1][0]), float(sts[1]["points"][-1][1]))
            return _axis_lines_cross(p0[0], t0, p0[1], t1)
        return None

    @Property('QVariantList', notify=selectionChanged)
    def selectionLineHandles(self):
        """仅当“选中项全是形状线”时，返回每条线的首末端点（QML 据此画圆形端点手柄）。

        含手绘笔迹的混选返回空 → QML 回退到“蓝色矩形 + 四角缩放”的传统形态；
        旋转手柄在两种形态下都保留。
        """
        return self._line_handles_data()

    @Slot(float, float, result='QVariantList')
    def hitLineEndpoint(self, x, y):
        """命中端点手柄时返回 [笔划 id, which]（0=起点 1=终点）；未命中返回空列表。

        QML 侧端点手柄是**纯视觉**的（不挂 MouseArea）：拖拽由覆盖层那两个稳定的
        MouseArea 统一分发。因为手柄项会随 selectionLineHandles 模型变化被 Repeater
        重建，挂在手柄上的 MouseArea 会在拖拽中途被销毁、丢掉鼠标 grab—— 表现为
        “端点只能拖动几 px”。半径 16 与手柄命中尺寸（EndHandle.hitR）一致。
        坐标系：只命中有手柄的那一端（`has0`/`has1`；空间直角坐标系原点那一端无手柄）。
        """
        best = []
        best_d2 = 16.0 * 16.0
        for h in self._line_handles_data():
            cand = []
            if h.get("has0") is not False:
                cand.append((0, h["x0"], h["y0"]))
            if h.get("has1") is not False:
                cand.append((1, h["x1"], h["y1"]))
            for which, hx, hy in cand:
                d2 = (hx - x) ** 2 + (hy - y) ** 2
                if d2 <= best_d2:
                    best_d2 = d2
                    best = [int(h["id"]), int(which)]
        return best

    @Property(str, notify=selectionChanged)
    def selectionLineStyle(self):
        """选中项的共同线型（全是同一种线时才非空；供浮动工具栏的线型菜单高亮）。"""
        if not self._selection_all_lines():
            return ""
        sel = set(self._selection)
        styles = set()
        for s in self._strokes:
            if s.get("id") in sel and _line_style_of(s):
                styles.add(_line_style_of(s))
        return styles.pop() if len(styles) == 1 else ""

    @Property('QVariantList', notify=selectionChanged)
    def selectionRect(self):
        return list(self._sel_rect) if self._sel_rect else []

    @Property(str, notify=selectionChanged)
    def selectionColor(self):
        return self._sel_color

    @Property(float, notify=selectionChanged)
    def selectionWidth(self):
        return self._sel_width

    @Property(float, notify=selectionChanged)
    def selectionRotation(self):
        """本选择累计旋转角（顺时针正）：旋转后框保持姿态；重选归零。"""
        return self._sel_rot_deg

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

    @Property(int, notify=thumbsChanged)
    def thumbVersion(self):
        """页面缩略图版本（QML 页面列表 Image 的 v 参数，变化时刷新）。"""
        return self._thumb_version

    @Property(float, constant=True)
    def canvasAspect(self):
        """画布宽高比（页面缩略图宽度 = 140 * aspect）。"""
        cw, ch = self._canvas_size
        return (cw / ch) if ch > 0 else 1.0

    @Property("QVariantList", notify=pageChanged)
    def pageMtimes(self):
        """各**已打开**页面文件的修改时间（秒），与页码一一对应。

        文件管理页用它把缩略图按"修改时间更晚的先加载"排序（越新的越可能正在看）。
        取不到（无会话/文件不存在）时给 0。
        """
        out = []
        base = getattr(self._store, "data_dir", "") if self._store else ""
        for p in self._pages:
            mt = 0.0
            f = p.get("file") if isinstance(p, dict) else None
            if f and base:
                try:
                    mt = os.path.getmtime(os.path.join(base, f))
                except OSError:
                    mt = 0.0
            out.append(mt)
        return out


class WhiteboardImageProvider(QQuickImageProvider):
    """把 WhiteboardBackend 的烘焙 QImage 提供给 QML Image（image://whiteboard/...）。

    id 形如：
    - "canvas?v=N" → 主画布烘焙图
    - "thumb?page=N&v=M" → 指定页缩略图（页面列表菜单 / 数据管理页用）
    - "hist?file=<文件名>&v=M" → 历史页面（data 目录里未打开的页）缩略图（数据管理页用）
    """

    def __init__(self, backend):
        super().__init__(QQuickImageProvider.Image)
        self._backend = backend

    def requestImage(self, id, size, requestedSize):
        if id.startswith("hist"):
            name = ""
            try:
                for kv in id.split("?")[1].split("&"):
                    if kv.startswith("file="):
                        name = kv[5:]
                        break
            except Exception:
                name = ""
            return self._backend.history_thumb(name)
        if id.startswith("thumb"):
            page = 0
            try:
                for kv in id.split("?")[1].split("&"):
                    if kv.startswith("page="):
                        page = int(kv[5:])
                        break
            except Exception:
                page = 0
            return self._backend.page_thumb(page)
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
    miniModeChanged = Signal()   # 小组件迷你模式（QML 0.7 缩放/自动隐藏用）
    hoverFadeChanged = Signal() # 主程序"悬停渐隐"开关（QML 淡出非按钮区/拦截列表事件用）
    hoverFadeFactorChanged = Signal()  # 悬停渐隐透明度因子（QML opacity 绑定，notify 驱动渐变）
    # 绘图工具状态（特殊模式工具栏）：activeTool 0=选择 1=笔 2=橡皮；笔粗细/颜色
    activeToolChanged = Signal()
    lineStyleChanged = Signal()    # 形状线型变化（形状菜单高亮；选中后切到形状工具）
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
        self._ui_anchor = "centercenter"  # 小组件锚点（update_position 每轮刷新；QML 缩放原点选择用）
        self._ui_width = DEFAULT_UI_WIDTH
        self._opacity = 0
        self._mode = "normal"
        self._mini_mode = False           # 小组件迷你模式（由 _update_mini_mode 跟随主程序配置刷新）
        self._current_icon = "ic_fluent_question_20_regular"
        self._current_remaining_text = ""
        self._font_family = ""
        self._font_weight = 400

        # 自动关闭特殊模式相关
        self._auto_close_timer = QTimer()
        self._auto_close_timer.timeout.connect(self._on_auto_close_timeout)
        self._auto_close_timer.setSingleShot(True)
        self._in_auto_close_status = False
        self._prev_auto_close_status = None   # 上次状态检查的 current_status（用于检测"下课"转换）

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

        # 小组件迷你模式（跟随主程序 preferences.mini_mode；QML 据此 0.7 缩放/自动隐藏）
        self._update_mini_mode()

        # 悬停渐隐开关（跟随主程序 interactions.hover_fade；QML 据此淡出非按钮区/拦截列表事件）
        self._hover_fade = False
        self._update_hover_fade()
        # 悬停渐隐当前透明度因子（1=全不透明；0.25=非按钮区鼠标悬停渐隐；由 Plugin 坐标轮询更新）
        self._hover_fade_factor = 1.0

        # 外围圆角半径（跟随主程序 widget_corner_radius 配置换算）
        self._widget_radius = 27.0
        self._update_widget_radius()

        # 绘图工具状态（特殊模式工具栏）：0=选择 1=笔 2=橡皮 3=形状
        self._active_tool = 0
        self._prev_tool = 0        # 进入形状工具前的工具（画完一条线自动回退到它）
        self._line_style = ""      # 形状线型 id（形状菜单选中；空=未选）
        # 笔工具：粗细(2/3/4.5/6px，支持半粗 4.5)与颜色（hex）；颜色空串=自动跟随模式（浅色黑/深色白）
        self._pen_width = 3.0
        self._pen_color = ""

    @Slot(int)
    def setActiveTool(self, tool):
        """设置当前绘图工具：0=选择 1=笔 2=橡皮 3=形状（形状菜单内部使用）。

        ⚠️ 切到**非形状工具**时同时清空形状选中态（`lineStyle`）：多步形状画到一半被改成
        笔/橡皮/选择打断后，形状菜单里那一项不该继续高亮（用户要求）；也不该留下
        “工具已不是形状但线型还留着”的中间态。
        """
        tool = int(tool)
        if tool in (0, 1, 2):
            self._prev_tool = tool   # 记住"上一个常规工具"，供形状线画完回退
        if tool != 3 and self._line_style:
            self._line_style = ""
            self.lineStyleChanged.emit()
        if tool != self._active_tool:
            self._active_tool = tool
            self.activeToolChanged.emit()

    @Slot(str)
    def setLineStyle(self, style):
        """形状菜单选中一种"画法"：线型或图形 id → 记住当前工具并切到"形状"工具
        （画完一个自动回退）。工具条上形状按钮的选中指示器由此点亮。
        """
        if (style not in _LINE_SHAPES and style not in _SHAPE_KINDS
                and style not in _SOLID_MENU_KINDS
                and style not in _AXIS_MENU_KINDS):
            return
        if self._active_tool in (0, 1, 2):
            self._prev_tool = self._active_tool
        if style != self._line_style:
            self._line_style = style
            self.lineStyleChanged.emit()
        if self._active_tool != 3:
            self._active_tool = 3
            self.activeToolChanged.emit()

    @Slot()
    def finishShape(self):
        """一条形状线画完（或手势取消）→ 工具回到进入形状工具前的那一个，
        并**清空线型选择**：下次打开线菜单时不应有任何线型处于"被选中"的高亮状态
        （每次绘制都要重新挑一种线型，形状工具此时也已退出，不会用空线型误画）。
        """
        tool_changed = False
        if self._active_tool == 3:
            self._active_tool = self._prev_tool if self._prev_tool in (0, 1, 2) else 1
            tool_changed = True
        if self._line_style:
            self._line_style = ""
            self.lineStyleChanged.emit()
        if tool_changed:
            self.activeToolChanged.emit()

    @Slot(float)
    def setPenWidth(self, width):
        """设置笔划粗细：2/3/4.5/6 px（4.5=半粗）"""
        width = float(width)
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

    @Property(str, notify=lineStyleChanged)
    def lineStyle(self):
        """当前形状线型 id（形状菜单高亮用）；空=未选过。"""
        return self._line_style

    @Property('QVariantList', constant=True)
    def lineStyleItems(self):
        """形状菜单"线"分类的条目 [{id, name}]（线型图案由 QML 自绘预览）。"""
        return [{"id": k, "name": _LINE_SHAPE_NAMES[k]} for k in _LINE_SHAPES]

    @Property('QVariantList', constant=True)
    def shapeItems(self):
        """形状菜单"图形"分类的条目 [{id, name}]（图形图标由 QML 自选）。"""
        return [{"id": k, "name": _SHAPE_KIND_NAMES[k]} for k in _SHAPE_KINDS]

    @Property('QVariantList', constant=True)
    def solidItems(self):
        """形状菜单"立体形状"分类的条目 [{id, name}]（图标由 QML 自绘）。

        每个立体图形的绘制引擎（形状引擎）由各自的子 agent 编写与管理，
        由 `_register_solid` 登记（本属性按 `_SOLID_MENU_KINDS` 顺序输出）。
        """
        return [{"id": k, "name": _SOLID_KIND_NAMES.get(k, k)}
                for k in _SOLID_MENU_KINDS]

    @Property('QVariantList', constant=True)
    def axisItems(self):
        """形状菜单"坐标系"分类的条目 [{id, name}]（**每行两列**，图标由 QML 自绘）。

        · planeaxes 平面直角坐标系（一步到位）；
        · spaceaxes 空间直角坐标系（两步：xy 平面 → z 轴）。
        """
        return [{"id": k, "name": _AXIS_KIND_NAMES[k]} for k in _AXIS_MENU_KINDS]

    @Property(float, notify=penWidthChanged)
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

    def _update_mini_mode(self):
        """跟随主程序 preferences.mini_mode：小组件是否进入迷你模式（QML 据此 0.7 缩放/自动隐藏）。"""
        try:
            configs = self.plugin._configs
            if configs:
                mini = bool(getattr(configs.preferences, 'mini_mode', False))
            else:
                mini = False
        except Exception:
            mini = False
        if mini != self._mini_mode:
            self._mini_mode = mini
            self.miniModeChanged.emit()

    def _update_hover_fade(self):
        """跟随主程序 interactions.hover_fade：悬停渐隐开关（QML 据此淡出非按钮区并拦截列表鼠标事件）。"""
        try:
            configs = self.plugin._configs
            if configs:
                hv = bool(getattr(configs.interactions, 'hover_fade', False))
            else:
                hv = False
        except Exception:
            hv = False
        if hv != self._hover_fade:
            self._hover_fade = hv
            self.hoverFadeChanged.emit()

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

        # 当前是否处于"上课"：以当前条目是否为课程判断，不能只看 current_status——
        # 主程序在课程临近结束时若下一节（活动/课程）即将开始会返回 preparation（预备），
        # 会误判为非上课，导致 nextLessonId（后课）在仍上着前一节课时也被高亮，
        # 且倒计时文本变成"秒后上课"而非"剩X秒"。
        self._current_state = 1 if (current and current.get("type") == "class") else 0
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

    def _check_auto_close(self, force_restart=False):
        """检查是否满足自动关闭特殊模式的条件（受"下课后自动关闭"设置控制）。

        设计：仅当特殊模式正打开、且发生"下课（进入课间 break）"的那次状态更新时
        才启动延迟计时；打开特殊模式时已是课间（无进入课间转换）不触发；
        计时中上课(class)/活动(activity)中止本轮自动关闭。
        force_restart=True：设置变化后调用，课间计时中以新延迟重启。
        """
        try:
            enabled = self.plugin.settings_backend.getBool("auto_close_after_class")
        except Exception:
            enabled = True
        if not enabled:
            # 开关关闭：不自动关闭
            self._in_auto_close_status = False
            self._auto_close_timer.stop()
            return
        if self._mode == "normal":
            # 特殊模式未打开：不计时、不自动关闭（也不更新 prev，避免污染下次进入的基准）
            self._in_auto_close_status = False
            self._auto_close_timer.stop()
            return
        current_status = self.plugin.api.runtime.current_status
        prev = self._prev_auto_close_status
        self._prev_auto_close_status = current_status
        if current_status == "break":
            if prev != "break":
                # 刚下课（进入课间）：启动延迟计时
                if not self._in_auto_close_status:
                    self._in_auto_close_status = True
                    self._auto_close_timer.start(self._get_auto_close_delay_ms())
            elif force_restart and self._in_auto_close_status:
                # 设置变化且正处于课间计时中：按新延迟重启
                self._auto_close_timer.start(self._get_auto_close_delay_ms())
        else:
            # 上课/活动/自由等：中止本轮自动关闭
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
                # 记录小组件锚点（无锚 → 居中），供 QML 缩放原点参考
                self._ui_anchor = "centercenter"
                x = (screen_width - ui_width) // 2
                y = 132
            else:
                vert, horz = parts[0].lower(), parts[1].lower()
                h_side = horz if horz in ("left", "right", "center") else "center"
                v_side = vert if vert in ("top", "bottom") else "center"
                self._ui_anchor = h_side + v_side

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
            # 自动关闭计时管理：无论进入/退出特殊模式都停止旧计时并复位状态；
            # 进入特殊模式时以"当前状态"为基准（若已是课间则不会误触发"下课计时"）。
            self._in_auto_close_status = False
            self._auto_close_timer.stop()
            if mode != "normal":
                try:
                    self._prev_auto_close_status = self.plugin.api.runtime.current_status
                except Exception:
                    self._prev_auto_close_status = None

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
    def enterHandboardMode(self):
        """进入"手写板模式"：仅交互智能平板顶部胶囊按钮触发，按设置进入黑板/白板。
        投影设备无此按钮（保留白板/熄屏双按钮），此处直接忽略。"""
        try:
            st = getattr(self.plugin, "settings_backend", None)
            if st is None or st.getString("device_type") != "interactive_panel":
                return
            action = st.getString("special_mode_action")
            if action == "whiteboard":
                self._set_mode("whiteboard")
            else:
                self._set_mode("blackboard")
        except Exception as e:
            plugin_logger.debug(f"进入手写板模式失败: {e}")

    @Slot()
    def openClassSwap(self):
        """打开主程序"换课"窗口（课程列表左侧换课按钮触发）。"""
        try:
            app = getattr(self.plugin.api, "_app", None)
            mgr = getattr(app, "window_manager", None) if app is not None else None
            if mgr is not None and hasattr(mgr, "openClassSwap"):
                mgr.openClassSwap()
            else:
                plugin_logger.debug("主程序无换课窗口管理接口(window_manager.openClassSwap)")
        except Exception as e:
            plugin_logger.debug(f"打开换课窗口失败: {e}")

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

    @Property(str, notify=positionChanged)
    def anchorPoint(self):
        """小组件锚点（如 lefttop/centerbottom/centercenter）：QML 据此选缩放原点。"""
        return self._ui_anchor

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

    @Property(bool, notify=miniModeChanged)
    def miniMode(self):
        """小组件迷你模式（主程序 preferences.mini_mode）：QML 据此做 0.7 缩放/自动隐藏（仅一般模式）"""
        return self._mini_mode

    @Property(bool, notify=hoverFadeChanged)
    def hoverFade(self):
        """主程序"悬停渐隐"开关（interactions.hover_fade）：QML 据此淡出非按钮区并拦截列表事件（仅一般模式）"""
        return self._hover_fade

    def set_hover_fade_factor(self, value):
        """设置悬停渐隐透明度因子（1=全不透明 / 0.25=非按钮区悬停渐隐），值变化才发通知。"""
        value = float(value)
        if abs(value - self._hover_fade_factor) > 1e-3:
            self._hover_fade_factor = value
            self.hoverFadeFactorChanged.emit()

    @Property(float, notify=hoverFadeFactorChanged)
    def hoverFadeFactor(self):
        """悬停渐隐透明度因子：QML LessonsDisplay root opacity 绑定（notify 刷新带动画渐变）"""
        return self._hover_fade_factor

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
        return self._plugin_meta.get("name", "LessonBoard")

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

    @Property(str, notify=settingsChanged)
    def deviceType(self):
        """设备类型（只读）：交互智能平板(interactive_panel)/投影设备或其他(projector)。
        随 settingsChanged 通知，QML 绑定可自动刷新（投影/平板界面差异用）。"""
        return self._config.get("device_type", DEFAULT_SETTINGS.get("device_type", "interactive_panel"))

    @Property(str, notify=settingsChanged)
    def specialModeAction(self):
        """手写板模式按钮进入的模式（只读）：blackboard(黑板)/whiteboard(白板)。
        随 settingsChanged 通知，QML 绑定可自动刷新按钮文字。"""
        return self._config.get("special_mode_action", DEFAULT_SETTINGS.get("special_mode_action", "blackboard"))

    @Property(bool, notify=settingsChanged)
    def hideInMiniMode(self):
        """"迷你模式时隐藏"开关（只读）：小组件进入迷你模式时自动隐藏灵动条（仅一般模式生效）。
        随 settingsChanged 通知，QML 绑定可自动刷新（透明度渐隐动画）。"""
        return bool(self._config.get("hide_in_mini_mode", DEFAULT_SETTINGS.get("hide_in_mini_mode", False)))

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
        # 主程序设置页注册的入口页相对路径（on_load 注册，on_unload 注销）
        self._settings_entry_path = None
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

        # 迷你模式自动隐藏：小组件迷你 + "迷你模式时隐藏"开启时，透明度淡出完成后
        # 真正隐藏主窗口（_mini_hidden 记录是否已因迷你隐藏），避免透明窗口拦截鼠标/右键
        self._mini_hidden = False
        self._mini_hide_timer = None

        # 悬停渐隐坐标轮询（hover_fade 生效时启动，按全局鼠标坐标判定渐隐）
        self._hover_timer = None
        # 悬停渐隐输入层：hover-fade 激活时主显示窗口整窗透明输入（点击穿透到后方），
        # 输入层小窗口仅按钮区 mask 承接按钮点击（无内容、透明）
        self._hover_input_engine = None
        self._hover_input_window = None
        self._hover_input_comp = None
        self._hover_input_enabled_flag = False
        self._hover_input_backend = None

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
        # 小组件迷你模式切换时刷新遮罩（迷你视觉缩放 0.7，遮罩须与实际显示面积一致）
        self.backend.miniModeChanged.connect(self._update_mask)
        # 小组件迷你模式变化时同步迷你自动隐藏（真正隐藏/恢复插件主窗口）
        self.backend.miniModeChanged.connect(self._sync_mini_auto_hide)
        # 迷你模式变化：同步悬停渐隐（迷你时停用 / 退出后重新启用按钮区 mask 与坐标轮询）
        self.backend.miniModeChanged.connect(self._sync_hover_fade)

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

        # 主程序设置页注册"插件设置"入口页（页内仅提供打开本插件设置对话框的入口卡片）
        try:
            ui = getattr(self.api, "ui", None)
            if ui is not None and hasattr(ui, "register_settings_page"):
                self._settings_entry_path = "qml/PluginSettingsEntry.qml"
                ui.register_settings_page(
                    qml_path=self._settings_entry_path,
                    title="LessonBoard",
                    icon="ic_fluent_book_open_20_regular",
                )
                plugin_logger.debug("已在主程序设置页注册插件设置入口")
        except Exception as e:
            plugin_logger.debug(f"注册主程序设置页入口失败: {e}")

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
            # 主程序小组件迷你模式配置变化时刷新（QML 0.7 缩放/自动隐藏）
            self.backend._update_mini_mode()
            # 主程序"悬停渐隐"开关变化时刷新（QML 淡出非按钮区/拦截列表事件）
            self.backend._update_hover_fade()
            # 悬停渐隐状态同步（开→按钮区 mask + 坐标轮询；关→恢复胶囊 mask）
            self._sync_hover_fade()
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
                    # 恢复显示后若悬停渐隐开启则重新启用（按钮区 mask + 坐标轮询）
                    self._sync_hover_fade()
        except Exception as e:
            plugin_logger.debug(f"同步贴边隐藏窗口失败: {e}")

    def _do_edge_hide(self):
        """延迟隐藏到期：胶囊已滑出屏幕后真正隐藏插件主窗口。"""
        try:
            if self.window and self._edge_hidden and self.window.isVisible():
                self.window.hide()
                plugin_logger.debug("贴边隐藏：已隐藏插件主窗口（胶囊滑出后）")
            self._sync_hover_fade()   # 窗口隐藏 → 停悬停渐隐轮询并复位因子
        except Exception as e:
            plugin_logger.debug(f"延迟隐藏窗口失败: {e}")

    def _should_mini_auto_hide(self):
        """迷你自动隐藏生效条件：一般模式 + 小组件迷你 + 设置"迷你模式时隐藏"开启。"""
        try:
            if not (self.backend and self.backend.mode == "normal" and self.backend.miniMode):
                return False
            return bool(self.settings_backend and self.settings_backend.getBool("hide_in_mini_mode"))
        except Exception:
            return False

    def _sync_mini_auto_hide(self):
        """小组件迷你自动隐藏同步：条件满足时延迟真正隐藏插件主窗口（等 QML 透明度
        淡出动画结束再 hide），条件解除时取消延迟并恢复显示。窗口彻底隐藏后不再
        拦截鼠标/右键，也不再更新 mask（性能）。仅在正常模式处理；贴边隐藏优先。"""
        try:
            if not self.window or not self.backend:
                return
            if self.backend.mode != "normal":
                return
            if self._edge_hidden:
                # 贴边隐藏已隐藏窗口：交给贴边流程管理（不叠加迷你状态）
                return
            should = self._should_mini_auto_hide()
            if should:
                if not self._mini_hidden and self.window.isVisible():
                    # 延迟隐藏：等 QML opacity 400ms 淡出动画结束（500ms 后）再真正隐藏
                    try:
                        if self._mini_hide_timer:
                            self._mini_hide_timer.stop()
                        self._mini_hide_timer = QTimer()
                        self._mini_hide_timer.setSingleShot(True)
                        self._mini_hide_timer.timeout.connect(self._do_mini_hide)
                        self._mini_hide_timer.start(500)
                    except Exception:
                        self._do_mini_hide()
            else:
                # 解除隐藏：取消待执行的延迟隐藏
                if self._mini_hide_timer:
                    try:
                        self._mini_hide_timer.stop()
                        self._mini_hide_timer.deleteLater()
                    except Exception:
                        pass
                    self._mini_hide_timer = None
                if self._mini_hidden:
                    self._mini_hidden = False
                    # 若主程序此刻仍贴边隐藏：把"已隐藏"登记转给贴边流程，不在此恢复显示
                    main_hide = False
                    try:
                        if self._configs:
                            main_hide = bool(self._configs.interactions.hide.state)
                    except Exception:
                        main_hide = False
                    if main_hide and not self.window.isVisible() and not self._edge_hidden:
                        self._edge_hidden = True
                        return
                    if not self.window.isVisible():
                        self.window.show()
                        # 恢复后确保 mask 应用到正常位置（若此期间被禁用）
                        self._enable_mask_and_update()
                        plugin_logger.debug("迷你自动隐藏解除：已恢复插件主窗口")
                    # 恢复显示后若悬停渐隐开启则重新启用（按钮区 mask + 坐标轮询）
                    self._sync_hover_fade()
        except Exception as e:
            plugin_logger.debug(f"同步迷你自动隐藏失败: {e}")

    def _do_mini_hide(self):
        """迷你自动隐藏延迟到期：透明度淡出完成后真正隐藏插件主窗口。"""
        try:
            self._mini_hide_timer = None
            if self.window and not self._edge_hidden and self._should_mini_auto_hide():
                self._mini_hidden = True
                if self.window.isVisible():
                    self.window.hide()
                    plugin_logger.debug("迷你自动隐藏：已彻底隐藏插件主窗口")
                self._sync_hover_fade()   # 窗口隐藏 → 停悬停渐隐轮询并复位因子
        except Exception as e:
            plugin_logger.debug(f"迷你自动隐藏失败: {e}")

    # ---------- 悬停渐隐（hover_fade，坐标 + 按钮区 mask 穿透方案）----------
    def _should_hover_fade_active(self):
        """悬停渐隐是否生效：主程序开关开 && 一般模式 && 窗口可见且未被贴边/迷你隐藏。
        迷你模式下同样生效（判定点经 _hover_to_source 反向 0.7 映射到源坐标）。"""
        try:
            if not (self.window and self.backend):
                return False
            if self.backend.mode != "normal":
                return False
            if not self.backend.hoverFade:
                return False
            if not self.window.isVisible():
                return False
            if self._edge_hidden or self._mini_hidden:
                return False
            return True
        except Exception:
            return False

    def _hover_to_source(self, lx, ly):
        """把窗口坐标点映射到"源坐标"（loader 布局几何）再判定。

        迷你模式胶囊视觉等比缩放 0.7（源宽放大 1/0.7、X 恒左缘、Y 依锚定边），鼠标视觉坐标
        须反向除以 0.7 才能与按钮源 rect / 胶囊源 bbox 比较；非迷你原样返回。"""
        try:
            loader = self.ui_loader
            if not (self.backend and self.backend.miniMode and loader):
                return (lx, ly)
            bx = float(loader.property("x"))
            by = float(loader.property("y"))
            w = float(loader.property("width"))
            h = float(loader.property("height"))
            k = 0.7
            vx = lx - bx
            vy = ly - by
            sx = vx / k
            ap = getattr(self.backend, "anchorPoint", "centercenter") or "centercenter"
            if ap.endswith("bottom"):
                sy = h - (h - vy) / k
            elif ap.endswith("top"):
                sy = vy / k
            else:
                oy = h / 2
                sy = oy + (vy - oy) / k
            return (bx + sx, by + sy)
        except Exception:
            return (lx, ly)

    def _hover_buttons_named(self):
        """当前可见顶部按钮列表 [(name, 窗口源 x, y, w, h)]（源布局坐标；迷你模式源宽已放大）。"""
        out = []
        try:
            if not (self.ui_loader and self.window):
                return out
            item = self.ui_loader.property("item")
            if not item:
                return out
            lx = float(self.ui_loader.property("x"))
            ly = float(self.ui_loader.property("y"))

            def push(name):
                btn = self.window.findChild(QObject, name)
                if btn is None and item is not None:
                    btn = item.findChild(QObject, name)
                if btn is None:
                    return
                try:
                    if not bool(btn.property("visible")):
                        return
                    pt = btn.mapToItem(item, QPointF(0, 0))
                    out.append((name, int(lx + pt.x()), int(ly + pt.y()),
                                int(btn.width()), int(btn.height())))
                except Exception:
                    pass

            push("topSwitchButton")
            device = "interactive_panel"
            try:
                if self.settings_backend:
                    device = self.settings_backend.getString("device_type")
            except Exception:
                pass
            if device == "interactive_panel":
                push("topHandboardButton")
            else:
                push("topButton1")
                push("topButton2")
        except Exception as e:
            plugin_logger.debug(f"读取悬停渐隐按钮区失败: {e}")
        return out

    def _hover_fade_button_rects(self):
        """按钮源 bbox 列表（透明度判定用，不含名字）。"""
        return [r[1:] for r in self._hover_buttons_named()]

    def _hover_fade_hit_button(self, sx, sy):
        """源坐标点命中的按钮名（None=非按钮）。"""
        for (name, bx, by, bw, bh) in self._hover_buttons_named():
            if bx <= sx < bx + bw and by <= sy < by + bh:
                return name
        return None

    def _hover_button_visual_rects(self):
        """按钮**视觉**屏幕坐标 rects [(name, gx, gy, gw, gh)]（含迷你 0.7 缩放与停靠边 origin），
        用于输入层窗口定位与 mask。"""
        out = []
        try:
            if not (self.ui_loader and self.window):
                return out
            item = self.ui_loader.property("item")
            if not item:
                return out
            lx = float(self.ui_loader.property("x"))
            ly = float(self.ui_loader.property("y"))
            lh = float(self.ui_loader.property("height"))
            mini = bool(self.backend and self.backend.miniMode)
            k = 0.7 if mini else 1.0
            ap = getattr(self.backend, "anchorPoint", "centercenter") or "centercenter"

            def fy(y):
                if ap.endswith("bottom"):
                    return lh - (lh - y) * k
                if ap.endswith("top"):
                    return y * k
                return lh / 2 + (y - lh / 2) * k

            for (name, bx, by, bw, bh) in self._hover_buttons_named():
                ix = bx - lx   # loader 内源坐标
                iy = by - ly
                vix = ix * k
                viy = fy(iy)
                g = self.window.mapToGlobal(QPoint(int(lx + vix), int(ly + viy)))
                out.append((name, g.x(), g.y(),
                            max(1, int(bw * k)), max(1, int(bh * k))))
        except Exception as e:
            plugin_logger.debug(f"计算悬停输入层按钮视觉区失败: {e}")
        return out

    def _hover_fade_factor_for_point(self, px, py, btn_rects, cap_rect):
        """坐标判定：按钮区→1（不渐隐）；胶囊内非按钮区→0.25（渐隐）；胶囊外→1（恢复）。"""
        for (bx, by, bw, bh) in btn_rects:
            if bx <= px < bx + bw and by <= py < by + bh:
                return 1.0
        if cap_rect:
            cx, cy, cw, ch = cap_rect
            if cx <= px < cx + cw and cy <= py < cy + ch:
                return 0.25
        return 1.0

    def _update_hover_fade_factor_now(self):
        """按当前全局鼠标坐标更新透明度因子（按钮区/胶囊外=1，非按钮区=0.25）。"""
        try:
            if not self._should_hover_fade_active():
                if self.backend and abs(self.backend.hoverFadeFactor - 1.0) > 1e-3:
                    self.backend.set_hover_fade_factor(1.0)
                return
            loader = self.ui_loader
            cap = (int(loader.property("x")), int(loader.property("y")),
                   int(loader.property("width")), int(loader.property("height")))
            local = self.window.mapFromGlobal(QCursor.pos())
            # 迷你模式：视觉坐标反向 0.7 映射到源坐标再与按钮源 rect / 胶囊源 bbox 判定
            src = self._hover_to_source(int(local.x()), int(local.y()))
            target = self._hover_fade_factor_for_point(
                int(src[0]), int(src[1]), self._hover_fade_button_rects(), cap)
            if abs(target - self.backend.hoverFadeFactor) > 1e-3:
                self.backend.set_hover_fade_factor(target)
        except Exception as e:
            plugin_logger.debug(f"更新悬停渐隐因子失败: {e}")

    def _ensure_hover_timer(self):
        """启动悬停渐隐坐标轮询（150ms，足够响应鼠标移动）。"""
        if self._hover_timer is None:
            self._hover_timer = QTimer()
            self._hover_timer.timeout.connect(self._hover_timer_tick)
        if not self._hover_timer.isActive():
            self._hover_timer.start(150)

    def _stop_hover_timer(self):
        if self._hover_timer is not None:
            self._hover_timer.stop()

    def _hover_timer_tick(self):
        try:
            if not self._should_hover_fade_active():
                # 状态已不满足（如窗口隐藏/退出一般模式）：收尾复位
                self._sync_hover_fade()
                return
            self._update_hover_fade_factor_now()
            # 迷你/位置变化时刷新输入层几何（跟随按钮带视觉位置）
            self._update_hover_input_geometry()
        except Exception as e:
            plugin_logger.debug(f"悬停渐隐轮询失败: {e}")

    def _sync_hover_fade(self):
        """悬停渐隐状态同步：生效时主显示窗口整窗透明输入（非按钮区点击穿透到后方窗口/桌面）、
        创建输入层承接按钮点击、启动坐标轮询；不生效时还原透明输入、销毁输入层、停轮询、因子复位 1。"""
        try:
            if not (self.window and self.backend):
                return
            if self._should_hover_fade_active():
                if not self._enable_hover_input():
                    return
                self._ensure_hover_timer()
                self._update_hover_fade_factor_now()
            else:
                self._disable_hover_input()
                self._stop_hover_timer()
                if abs(self.backend.hoverFadeFactor - 1.0) > 1e-3:
                    self.backend.set_hover_fade_factor(1.0)
                self._update_mask()          # 恢复常规 mask（胶囊/迷你视觉区等）
        except Exception as e:
            plugin_logger.debug(f"同步悬停渐隐失败: {e}")

    # ---------- 悬停渐隐：输入层（显示窗口整窗透明输入 + 独立输入层承接按钮）----------
    def _enable_hover_input(self):
        """hover-fade 生效：主显示窗口整窗对鼠标透明输入（Qt.WindowTransparentForInput → WS_EX_TRANSPARENT），
        点击穿透到后方窗口/桌面；创建输入层窗口承接按钮点击（mask 只按钮视觉区）。"""
        try:
            if not self.window:
                return False
            if not self._hover_input_enabled_flag:
                self.window.setFlag(Qt.WindowTransparentForInput, True)
                self._hover_input_enabled_flag = True
            if self._hover_input_engine is None:
                if self._hover_input_backend is None:
                    self._hover_input_backend = _HoverInputBackend(self)
                engine = QQmlEngine()
                engine.rootContext().setContextProperty("hoverInputBackend", self._hover_input_backend)
                qml_path = os.path.join(self.PATH, "qml", "HoverInputWindow.qml")
                comp = QQmlComponent(engine)
                comp.loadUrl(QUrl.fromLocalFile(qml_path))
                if comp.isError():
                    plugin_logger.error(f"悬停渐隐输入层加载失败: {comp.errorString()}")
                    engine.deleteLater()
                    return False
                win = comp.create()
                if win is None:
                    plugin_logger.error("悬停渐隐输入层创建失败")
                    engine.deleteLater()
                    return False
                self._hover_input_engine = engine
                self._hover_input_comp = comp
                self._hover_input_window = win
            self._update_hover_input_geometry()
            return True
        except Exception as e:
            plugin_logger.debug(f"启用悬停渐隐输入层失败: {e}")
            return False

    def _disable_hover_input(self):
        """hover-fade 失效：还原主显示窗口鼠标接收、销毁输入层。"""
        try:
            if self._hover_input_enabled_flag:
                if self.window:
                    self.window.setFlag(Qt.WindowTransparentForInput, False)
                self._hover_input_enabled_flag = False
            if self._hover_input_window:
                try:
                    self._hover_input_window.hide()
                    self._hover_input_window.deleteLater()
                except Exception:
                    pass
                self._hover_input_window = None
            if self._hover_input_engine:
                try:
                    self._hover_input_engine.deleteLater()
                except Exception:
                    pass
                self._hover_input_engine = None
            self._hover_input_comp = None
        except Exception as e:
            plugin_logger.debug(f"停用悬停渐隐输入层失败: {e}")

    def _update_hover_input_geometry(self):
        """按按钮视觉区域刷新输入层窗口位置/尺寸与 mask（迷你缩放实时跟随）。"""
        try:
            win = self._hover_input_window
            if not win:
                return
            rects = self._hover_button_visual_rects()
            if not rects:
                win.hide()
                return
            gx = min(r[1] for r in rects)
            gy = min(r[2] for r in rects)
            gx2 = max(r[1] + r[3] for r in rects)
            gy2 = max(r[2] + r[4] for r in rects)
            region = QRegion()
            for (_n, x, y, w, h) in rects:
                region = region.united(QRegion(x - gx, y - gy, w, h))
            cur = win.geometry()
            nw = gx2 - gx
            nh = gy2 - gy
            if (cur.x(), cur.y(), cur.width(), cur.height()) != (gx, gy, nw, nh):
                win.setGeometry(gx, gy, nw, nh)
            win.setMask(region)
            if not win.isVisible():
                win.show()
        except Exception as e:
            plugin_logger.debug(f"刷新悬停渐隐输入层几何失败: {e}")

    def _handle_hover_input_click(self, x, y, button):
        """输入层点击（由 _HoverInputBackend 转发）：解析命中按钮并触发对应动作（仅左键）。"""
        try:
            # QML 传来的 mouse.button 是整数（Qt.LeftButton == 1），勿与 flag 枚举直接比较
            if button != 1:
                return
            win = self._hover_input_window
            if not (win and self.window and self.backend):
                plugin_logger.debug("悬停输入层点击：缺少输入层/显示窗/后端")
                return
            pos = win.position()
            screen = QPoint(int(pos.x()) + int(x), int(pos.y()) + int(y))
            local = self.window.mapFromGlobal(screen)
            src = self._hover_to_source(int(local.x()), int(local.y()))
            name = self._hover_fade_hit_button(int(src[0]), int(src[1]))
            if name == "topSwitchButton":
                self.backend.openClassSwap()
            elif name == "topHandboardButton":
                self.backend.enterHandboardMode()
            elif name == "topButton1":
                self.backend.enterWhiteboard()
            elif name == "topButton2":
                self.backend.enterBlackboard()
        except Exception as e:
            plugin_logger.debug(f"悬停输入层点击处理失败: {e}")

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
        """插件设置变化（小组件图层/倒计时样式/自动关闭/笔触粗细等）：刷新图层状态，驱动 QML flags 绑定重新求值"""
        # "迷你模式时隐藏"开关变化：同步迷你自动隐藏（隐藏/恢复插件主窗口）
        self._sync_mini_auto_hide()
        if self.backend:
            self.backend._update_layer_state()
            # 倒计时样式变化：更新样式属性（QML 字号）并重新生成倒计时文本
            self.backend._update_countdown_style()
            self.backend._update_current_icon_and_remaining()
            # 自动关闭设置变化：重新检查（开关/延迟时间/单位变化立即生效；计时中按新延迟重启）
            self.backend._check_auto_close(force_restart=True)
        # 无压感设备笔触速度映射变化：实时更新已接线的白板后端（下一笔生效）
        if getattr(self, "_wb_backend", None) and self.settings_backend:
            try:
                self._wb_backend.set_pen_speed_map(
                    bool(self.settings_backend.getBool("pen_speed_pressure")),
                    self.settings_backend.getString("pen_speed_sensitivity"),
                )
            except Exception as e:
                plugin_logger.debug(f"更新笔触速度映射失败: {e}")

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
                # 兜底同步迷你模式（小组件切迷你若未触发 configChanged，宽度轮询也能感知）
                self.backend._update_mini_mode()
                # 兜底同步悬停渐隐开关（同上）
                self.backend._update_hover_fade()
                # 悬停渐隐状态同步（防 configChanged 未触发）
                self._sync_hover_fade()
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
            # 启动即迷你+自动隐藏开启：窗口显示后同步迷你隐藏（淡出后真正隐藏）
            self._sync_mini_auto_hide()
            # 启动即悬停渐隐开启：窗口显示后同步（按钮区 mask + 坐标轮询）
            self._sync_hover_fade()

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
        # 迷你自动隐藏生效：窗口将被/已被真正隐藏，跳过 mask 更新（性能）
        if self._should_mini_auto_hide():
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
            # 小组件迷你模式（一般模式）：胶囊视觉等比缩放 0.7，且源宽已放大 1/0.7 抵消
            # （视觉宽 = 小组件总宽）。遮罩须与实际显示面积一致：取源矩形按 scale 0.7、
            # X 恒以左缘为原点、Y 依小组件垂直停靠边（top/bottom/center）收缩后的矩形。
            if self.backend and self.backend.mode == "normal" and self.backend.miniMode:
                scale = 0.7
                vw = int(w * scale)
                vh = int(h * scale)
                vx = x                       # X origin 恒取左缘
                ap = getattr(self.backend, "anchorPoint", "centercenter") or "centercenter"
                if ap.endswith("bottom"):
                    vy = y + h - vh
                elif ap.endswith("top"):
                    vy = y
                else:
                    vy = y + (h - vh) // 2
                region = QRegion(vx, vy, vw, vh)
            else:
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

    def _finish_pending_figure(self):
        """工具被切换 / 形状菜单改选了别的形状时，若两阶段图形/多步多边形还没收尾 → 收尾提交。

        用户要求：焦点绘制完成后直接切工具（选择/笔/橡皮）或在形状菜单里选中其它形状，
        就按默认逻辑根据两焦点直接生成图形，并**进入新选中的工具的绘制模式**；
        **多边形随心画**同理：直接把还没连上的缺口闭合后提交。
        收尾时**不回退工具**（用户刚选的那个要保持），见 `finishFocusStage`。
        （改成非形状工具时，`LessonsBackend.setActiveTool` 已经顺手清空了 `lineStyle`，
        所以形状菜单不会再残留高亮。）
        """
        wb = self._wb_backend
        if wb is None:
            return
        try:
            wb.finishFocusStage()
        except Exception:
            plugin_logger.debug("两阶段图形收尾失败", exc_info=True)

    def _clear_shape_selection(self):
        """切页/增删页会打断正在绘制（`WhiteboardBackend.finishPendingDrawing`）→
        形状选中态一并清掉：被打断的形状不该继续在形状菜单里高亮（用户要求），
        工具顺手回退到进入形状工具前那一个（否则会是“形状工具激活但什么都没选”的死状态）。
        """
        try:
            if self.backend is not None and self.backend.activeTool == 3:
                self.backend.finishShape()
        except Exception:
            plugin_logger.debug("切页后清理形状选中态失败", exc_info=True)

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
                wb.set_pen_speed_map(
                    bool(self.settings_backend.getBool("pen_speed_pressure"))
                    if self.settings_backend else True,
                    self.settings_backend.getString("pen_speed_sensitivity")
                    if self.settings_backend else "standard",
                )
                wb.load_strokes(self._stroke_store.load_all())
                # 形状线画完一条 → 工具自动回到选择/笔/橡皮（工具条指示器随之切换）
                try:
                    wb.shapeFinished.connect(self.backend.finishShape)
                except Exception:
                    pass
                # 两阶段图形（椭圆/双曲线）第二阶段被"切换工具"或"改选形状"打断 →
                # 按默认探针把图形补出来并提交（**不回退工具**，见 finishFocusStage）
                # 注：在形状工具里改选另一种形状只发 lineStyleChanged（activeTool 不变）
                for _sig in (self.backend.activeToolChanged, self.backend.lineStyleChanged):
                    try:
                        _sig.connect(self._finish_pending_figure)
                    except Exception:
                        pass
                # 切页/增删页也会打断正在绘制 → 形状选中态（菜单高亮）一并清掉（用户要求）
                try:
                    wb.pageChanged.connect(self._clear_shape_selection)
                except Exception:
                    pass
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
                # 退出手写板模式前先收尾：正在画的多阶段/多步图形补完并落盘（用户要求，
                # 否则后端一销毁，这一笔就再也找不回来了）
                self._wb_backend.finishPendingDrawing()
            except Exception:
                plugin_logger.debug("退出模式前收尾失败", exc_info=True)
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
        # 模式切换：同步悬停渐隐（特殊模式停用、回一般模式重新启用按钮区 mask + 坐标轮询）
        self._sync_hover_fade()
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
            # 迷你自动隐藏状态同步（退出特殊模式后若小组件仍迷你+隐藏开关开启 → 重新隐藏）
            self._sync_mini_auto_hide()
        else:
            # 特殊模式（进入或白板↔熄屏切换）：先清零 mask 引用计数
            if self.backend:
                self.backend._mask_hide_refs = 0
                self.backend._anim_optimize_active = False
                self.backend._anim_optimize_timer.stop()
            # 迷你自动隐藏：特殊模式不缩放/不隐藏，进入即清理迷你隐藏状态
            # （下方会重新 show 主窗口作为专用窗口底层的全屏主窗口）
            if self._mini_hide_timer:
                try:
                    self._mini_hide_timer.stop()
                    self._mini_hide_timer.deleteLater()
                except Exception:
                    pass
                self._mini_hide_timer = None
            self._mini_hidden = False
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

    @Slot()
    def openSettingsDialog(self):
        """打开本插件设置对话框（主程序设置页入口卡片触发）。

        设置对话框是主 QML 引擎 FullScreenWindow 内 SettingsDialog 的子项，
        QML 侧 openDialog() 为 QML 函数（注册于 metaObject），可经 QMetaObject 调用。"""
        try:
            dlg = None
            if self.window is not None:
                dlg = self.window.findChild(QObject, "pluginSettingsDialog")
            if dlg is None:
                plugin_logger.debug("设置对话框未找到（窗口未就绪）")
                return
            # QueuedConnection：投递到对话框所在 GUI 线程再执行（跨线程安全）
            QMetaObject.invokeMethod(dlg, "openDialog", Qt.QueuedConnection)
        except Exception as e:
            plugin_logger.debug(f"打开设置对话框失败: {e}")

    def on_unload(self):
        # 先打印卸载消息再释放日志句柄（否则写不进文件）
        plugin_logger.info("今日课程插件卸载")
        # 注销主程序设置页入口（避免卸载后残留）
        try:
            ui = getattr(self.api, "ui", None)
            path = getattr(self, "_settings_entry_path", None)
            if ui is not None and path and hasattr(ui, "unregister_settings_page"):
                ui.unregister_settings_page(path)
        except Exception:
            pass
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
        if self._mini_hide_timer:
            try:
                self._mini_hide_timer.stop()
                self._mini_hide_timer.deleteLater()
            except Exception:
                pass
        if self._hover_timer is not None:
            try:
                self._hover_timer.stop()
                self._hover_timer.deleteLater()
                self._hover_timer = None
            except Exception:
                pass
        self._disable_hover_input()
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