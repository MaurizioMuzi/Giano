# core/file_writer.py
from pathlib import Path
from core.record_formatter import RecordFormatter


class FileWriter:
    def __init__(self, formatter: RecordFormatter, encoding: str = "cp1252", line_ending: str = "\r\n"):
        self.formatter = formatter
        self.encoding = encoding
        self.line_ending = line_ending
        self._file = None
        self.total_records = 0
        self.counts: dict[str, int] = {}

    @property
    def is_open(self) -> bool:
        return self._file is not None and not self._file.closed

    def open(self, file_path: str | Path) -> None:
        if self.is_open:
            self.close()
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "w", encoding=self.encoding, newline="")
        self.total_records = 0
        self.counts.clear()

    def write(self, rec_type: str, data: dict) -> None:
        if not self.is_open:
            raise RuntimeError("File non aperto: chiamare writer.open() prima di write().")
        line = self.formatter.format(rec_type, data)
        self._file.write(line + self.line_ending)
        self.total_records += 1
        self.counts[rec_type] = self.counts.get(rec_type, 0) + 1

    def close(self) -> None:
        if self.is_open:
            self._file.close()
        self._file = None