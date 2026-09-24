# core/batch_logger.py
import logging
import os
from datetime import datetime
from typing import Optional


class TreeFormatter(logging.Formatter):
    """Formatta i messaggi garantendo l'allineamento a colonna fissa su ogni livello."""

    def format(self, record: logging.LogRecord) -> str:
        branch_str = getattr(record, "branch_str", "")
        tag_str = getattr(record, "tag_str", "GENERAL")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        # Allineamento a 7 caratteri: gestisce perfettamente WARNING (7 crt) e allinea DEBUG, INFO, ERROR
        level_str = f"{record.levelname:<7}"

        # Se è una linea separatrice pulita
        if tag_str == "---":
            return f"[{timestamp}] [{level_str}] {branch_str}------------------------------------------------------------"

        return f"[{timestamp}] [{level_str}] {branch_str}[{tag_str:<14}] {record.getMessage()}"


class BatchLogger:
    """Gestore unificato con livelli indipendenti tra Console e File .txt."""
    _logger: Optional[logging.Logger] = None

    @classmethod
    def setup_logger(
            cls,
            log_dir: str = "logs",
            file_level: int = logging.DEBUG,
            console_level: int = logging.INFO,
            log_prefix: str = "BATCH"
    ) -> None:
        if cls._logger is not None:
            return

        cls._logger = logging.getLogger("BatchProcessLogger")
        cls._logger.setLevel(logging.DEBUG)
        cls._logger.propagate = False

        formatter = TreeFormatter()

        # 1. Handler Console
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)
        console_handler.setFormatter(formatter)
        cls._logger.addHandler(console_handler)

        # 2. Handler File .txt con prefisso dinamico
        os.makedirs(log_dir, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_prefix = str(log_prefix).strip()
        log_file_path = os.path.join(log_dir, f"{clean_prefix}_{date_str}.txt")

        file_handler = logging.FileHandler(log_file_path, mode="a", encoding="utf-8")
        file_handler.setLevel(file_level)
        file_handler.setFormatter(formatter)
        cls._logger.addHandler(file_handler)

        cls.banner(f"SESSIONE DI LOG AVVIATA -> File: {log_file_path}")

    @classmethod
    def _emit(cls, level: int, tag: str, msg: str, depth: int = 0, is_last: bool = False) -> None:
        if cls._logger is None:
            cls.setup_logger()

        branch = "└── " if is_last else "├── "
        prefix = branch if depth == 0 else ("│   " * depth + branch)

        extra = {
            "branch_str": prefix,
            "tag_str": tag
        }
        cls._logger.log(level, msg, extra=extra)

    @classmethod
    def debug(cls, tag: str, msg: str, depth: int = 0, is_last: bool = False) -> None:
        cls._emit(logging.DEBUG, tag, msg, depth, is_last)

    @classmethod
    def info(cls, tag: str, msg: str, depth: int = 0, is_last: bool = False) -> None:
        cls._emit(logging.INFO, tag, msg, depth, is_last)

    @classmethod
    def warn(cls, tag: str, msg: str, depth: int = 0, is_last: bool = False) -> None:
        cls._emit(logging.WARNING, tag, msg, depth, is_last)

    @classmethod
    def error(cls, tag: str, msg: str, depth: int = 0, is_last: bool = False) -> None:
        cls._emit(logging.ERROR, tag, msg, depth, is_last)

    @classmethod
    def banner(cls, title: str) -> None:
        if cls._logger is None:
            cls.setup_logger()
        sep = "=" * 115
        print(
            f"\n{sep}\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] [INFO   ] [PROCESS-ORCH   ] {title}\n{sep}\n")

    @classmethod
    def separator(cls, depth: int = 0) -> None:
        if cls._logger is None:
            cls.setup_logger()
        prefix = ("│   " * depth) if depth > 0 else ""
        cls._logger.info("", extra={"branch_str": prefix, "tag_str": "---"})