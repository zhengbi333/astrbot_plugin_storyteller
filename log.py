"""插件运行时日志：AstrBot 日志面板 + 文件（滚动保留）+ 内存环形（按模块，供面板实时展示）。

所有模块通过 from .log import get_logger 获取带中文模块名的日志器；get_logger 返回的
日志器会自动为消息补上「【为你续写的故事】【模块名】」前缀，并写入：
1. AstrBot 日志面板（沿 logging 链传播，EnricherFilter 补齐 AstrBot 期望的字段）；
2. 插件数据目录 storyteller.log（滚动保留，最多 2 MiB × 3）；
3. 内存环形缓冲（按模块归类，最多 300 条，由面板「各模块日志展示」API 读取）。

注意：插件日志会沿 logger 链传播到 AstrBot 的日志 handler，而挂载在 AstrBot
自身 logger 上的字段注入 filter 不会作用于插件记录，因此必须由本模块自行补齐
plugin_tag / short_levelname 等字段，否则 AstrBot 日志格式化会报错
（Formatting field not found in record: 'plugin_tag'）。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_NAME = "astrbot.plugin_storyteller"
_LOG_FILE = "storyteller.log"
_MAX_BYTES = 2 * 1024 * 1024
_BACKUPS = 3

# 内存环形日志（AstrBot 面板的「各模块日志展示」数据源）
_MEM_LIMIT = 300
_mem_lock = threading.Lock()
_mem: deque = deque(maxlen=_MEM_LIMIT)

_LEVEL_TAG = {
    "DEBUG": "DBUG",
    "INFO": "INFO",
    "WARNING": "WARN",
    "ERROR": "ERRO",
    "CRITICAL": "CRIT",
}

_LEVEL_ANSI = {
    "DEBUG": "\x1b[1;34m",
    "INFO": "\x1b[1;36m",
    "WARNING": "\x1b[1;33m",
    "ERROR": "\x1b[31m",
    "CRITICAL": "\x1b[1;31m",
}


def _fmt_time() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def memory_logs(module: str | None = None, limit: int = 120) -> list[dict]:
    """按中文模块名读取内存日志（module 为空返回全部；最新在前）。"""
    with _mem_lock:
        rows = list(_mem)
    if module:
        rows = [r for r in rows if r.get("module") == module]
    try:
        count = max(1, min(500, int(limit)))
    except (TypeError, ValueError):
        count = 120
    return rows[-count:][::-1]


class _EnricherFilter(logging.Filter):
    """为日志记录注入 AstrBot 日志体系期望的格式化字段。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.plugin_tag = "【为你续写的故事】"
        record.short_levelname = _LEVEL_TAG.get(
            record.levelname, record.levelname[:4].upper()
        )
        record.astrbot_version_tag = ""
        record.source_file = (
            os.path.basename(os.path.dirname(record.pathname)) + "." +
            os.path.basename(record.pathname).replace(".py", "")
        )
        record.source_line = record.lineno
        record.is_trace = False
        record.ansi_prefix = _LEVEL_ANSI.get(record.levelname, "\x1b[0m")
        record.ansi_reset = "\x1b[0m"
        return True


class _MemoryHandler(logging.Handler):
    """把日志行写入内存环形缓冲（面板实时展示的数据源）。

    模块日志器会通过 extra 提供 story_message（原始文本，不含前缀），
    供各模块页日志面板展示；默认 logger 无该字段时回退 record.getMessage()。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = str(getattr(record, "story_message", "") or "")
            if not message:
                message = record.getMessage()
            module = str(getattr(record, "story_module", "") or "")
            with _mem_lock:
                _mem.append(
                    {
                        "time": _fmt_time(),
                        "level": record.levelname,
                        "module": module,
                        "message": message,
                    }
                )
        except Exception:
            pass


logger = logging.getLogger(_LOG_NAME)
logger.setLevel(logging.INFO)
logger.addFilter(_EnricherFilter())
logger.addHandler(_MemoryHandler())

_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)


def setup(data_dir: Path) -> None:
    """在插件数据目录挂载文件 handler（幂等，可重复调用）。"""
    if any(
        isinstance(handler, RotatingFileHandler) for handler in logger.handlers
    ):
        return
    try:
        directory = Path(data_dir)
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            directory / _LOG_FILE,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUPS,
            encoding="utf-8",
        )
        handler.setFormatter(_formatter)
        logger.addHandler(handler)
    except Exception:
        pass


class ModuleLogger:
    """带中文模块名的模块日志器：消息自动带「【为你续写的故事】【模块名】」前缀。"""

    def __init__(self, cn_name: str):
        self._cn = cn_name or ""

    def _emit(self, level: int, msg: str, *args, **kwargs) -> None:
        try:
            text = msg % args if args else msg
            # AStrBot 面板消息：plugin_tag（【为你续写的故事】）+ 模块名前缀 + 原始文本
            full = f"【为你续写的故事】【{self._cn}】 {text}"
            record = logger.makeRecord(
                logger.name, level, __file__, 1, full, None, None, None,
                extra={"story_module": self._cn, "story_message": text},
            )
            logger.handle(record)
        except Exception:
            # 日志系统自身故障不允许向外抛（不阻塞业务）
            try:
                with _mem_lock:
                    _mem.append(
                        {
                            "time": _fmt_time(),
                            "level": "ERROR",
                            "module": self._cn,
                            "message": "插件日志系统自身异常: " + str(msg),
                        }
                    )
            except Exception:
                pass

    def info(self, msg: str, *args, **kwargs) -> None:
        self._emit(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        self._emit(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        self._emit(logging.ERROR, msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs) -> None:
        self._emit(logging.DEBUG, msg, *args, **kwargs)


def get_logger(cn_name: str) -> ModuleLogger:
    """获取一个带中文模块名的日志器（如 get_logger("防抖")）。"""
    return ModuleLogger(cn_name)