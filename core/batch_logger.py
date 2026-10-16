# core/batch_logger.py
import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any

# Livelli numerici:
# DEBUG (10) < INFO (20) < TRANSITION (22) < METRICS (25) < WARNING (30) < ERROR (40)
# Essendo > INFO, compaiono SEMPRE se il livello attivo è INFO o DEBUG.
LEVEL_TRANSITION = 22
LEVEL_METRICS = 25

logging.addLevelName(LEVEL_TRANSITION, "TRANSIT")
logging.addLevelName(LEVEL_METRICS, "METRICS")


class TreeFormatter(logging.Formatter):
    """Formatta i messaggi garantendo l'allineamento a colonna fissa su ogni livello."""

    def format(self, record: logging.LogRecord) -> str:
        branch_str = getattr(record, "branch_str", "")
        tag_str = getattr(record, "tag_str", "GENERAL")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        # Allineamento a 8 caratteri per includere 'TRANSIT', 'METRICS', 'WARNING', ecc.
        level_str = f"{record.levelname:<8}"

        # Separatore visivo dell'albero
        if tag_str == "---":
            return f"[{timestamp}] [{level_str}] {branch_str}------------------------------------------------------------------------"

        return f"[{timestamp}] [{level_str}] {branch_str}[{tag_str:<14}] {record.getMessage()}"


class BatchLogger:
    """Gestore unificato con livelli indipendenti tra Console e File .txt."""
    _logger: Optional[logging.Logger] = None

    # Esposizione pubblica dei livelli
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    TRANSITION = LEVEL_TRANSITION
    METRICS = LEVEL_METRICS
    WARNING = logging.WARNING
    ERROR = logging.ERROR

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
        # Il logger radice cattura dal livello più basso (DEBUG), lasciando ai singoli handler il filtraggio
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
    def transition(cls, tag: str, msg: str, depth: int = 0, is_last: bool = False) -> None:
        """Livello TRANSIT (22): visibile se la soglia è DEBUG, INFO o TRANSITION."""
        cls._emit(LEVEL_TRANSITION, tag, msg, depth, is_last)

    @classmethod
    def metrics(cls, tag: str, msg: str, depth: int = 0, is_last: bool = False) -> None:
        """Livello METRICS (25): visibile se la soglia è DEBUG, INFO, TRANSITION o METRICS."""
        cls._emit(LEVEL_METRICS, tag, msg, depth, is_last)

    @classmethod
    def warn(cls, tag: str, msg: str, depth: int = 0, is_last: bool = False) -> None:
        cls._emit(logging.WARNING, tag, msg, depth, is_last)

    @classmethod
    def error(cls, tag: str, msg: str, depth: int = 0, is_last: bool = False) -> None:
        cls._emit(logging.ERROR, tag, msg, depth, is_last)

    # --- Metodi Helper di comodo ---

    @classmethod
    def log_table_counters(cls, table: str, counts: Dict[str, Any], depth: int = 0, is_last: bool = False) -> None:
        """Stampa i contatori aggregati per T01, T10, T14, T03 al livello METRICS."""
        formatted = " | ".join(f"{k}: {v}" for k, v in counts.items())
        cls.metrics(table, f"CONTATORI -> {formatted}", depth=depth, is_last=is_last)

    @classmethod
    def log_state_change(cls, table: str, from_state: str, to_state: str, count: int, depth: int = 0, is_last: bool = False) -> None:
        """Traccia il numero di record che transitano di stato al livello TRANSIT."""
        cls.transition(table, f"CAMBIO STATO [{from_state} -> {to_state}]: {count} record", depth=depth, is_last=is_last)

    @classmethod
    def banner(cls, title: str) -> None:
        if cls._logger is None:
            cls.setup_logger()
        sep = "=" * 115
        print(
            f"\n{sep}\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] [INFO    ] [PROCESS-ORCH   ] {title}\n{sep}\n")

    @classmethod
    def separator(cls, depth: int = 0) -> None:
        if cls._logger is None:
            cls.setup_logger()
        prefix = ("│   " * depth) if depth > 0 else ""
        cls._logger.info("", extra={"branch_str": prefix, "tag_str": "---"})