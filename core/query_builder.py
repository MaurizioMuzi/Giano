# core/query_builder.py
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Dict, Any, List, Union
from config.schema_mapper import TableMap


class CompiledQuery:
    """Contenitore per statement SQL compilato e tuple di parametri associati."""
    def __init__(self, sql: str, params: tuple):
        self.sql = sql
        self.params = params


class Dialect(ABC):
    """Interfaccia astratta Enterprise per la scomposizione sintattica globale."""

    @abstractmethod
    def compile_select(self, table_name: str, fields: str, where: str, limit: int, no_lock: bool) -> str:
        pass

    @abstractmethod
    def compile_update(self, table_name: str, set_clause: str, where_clause: str) -> str:
        pass

    @abstractmethod
    def compile_update_joined(self, target_table: str, target_field: str, source_table: str, source_field: str, join_condition: str, filter_condition: str) -> str:
        pass

    @abstractmethod
    def compile_delete_joined(self, target_table: str, source_table: str, join_condition: str, filter_condition: str) -> str:
        pass

    @abstractmethod
    def format_value(self, value):
        pass


class DB2Dialect(Dialect):
    """Dialetto Enterprise specifico per IBM DB2 Mainframe."""

    def compile_select(self, table_name: str, fields: str, where: str, limit: int, no_lock: bool) -> str:
        sql = f"SELECT {fields} FROM {table_name}"
        if where:
            sql += f" WHERE {where}"
        if limit:
            sql += f" FETCH FIRST {limit} ROWS ONLY"
        if no_lock:
            sql += " WITH UR"
        return sql

    def compile_update(self, table_name: str, set_clause: str, where_clause: str) -> str:
        sql = f"UPDATE {table_name} SET {set_clause}"
        if where_clause:
            sql += f" WHERE {where_clause}"
        return sql

    def compile_update_joined(self, target_table: str, target_field: str, source_table: str, source_field: str, join_condition: str, filter_condition: str) -> str:
        where_clause = f" WHERE {filter_condition}" if filter_condition else ""
        sql = (f"UPDATE {target_table} SET {target_field} = (SELECT {source_field} FROM {source_table} WHERE {join_condition})"
               f" WHERE EXISTS (SELECT 1 FROM {source_table} WHERE {join_condition}{where_clause.replace('WHERE', 'AND')})")
        return sql

    def compile_delete_joined(self, target_table: str, source_table: str, join_condition: str, filter_condition: str) -> str:
        where_clause = f" AND {filter_condition}" if filter_condition else ""
        sql = f"DELETE FROM {target_table} WHERE EXISTS (SELECT 1 FROM {source_table} WHERE {join_condition}{where_clause})"
        return sql

    def format_value(self, value):
        """Formatta i valori nativi Python secondo lo standard ISO di DB2."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d-%H.%M.%S.%f')
        if isinstance(value, date):
            return value.strftime('%Y-%m-%d')
        return value


class SQLServerDialect(Dialect):
    """Dialetto Enterprise specifico per Microsoft SQL Server."""

    def compile_select(self, table_name: str, fields: str, where: str, limit: int, no_lock: bool) -> str:
        select_clause = f"SELECT TOP {limit}" if limit else "SELECT"
        lock_hint = " WITH (NOLOCK)" if no_lock else ""
        sql = f"{select_clause} {fields} FROM {table_name}{lock_hint}"
        if where:
            sql += f" WHERE {where}"
        return sql

    def compile_update(self, table_name: str, set_clause: str, where_clause: str) -> str:
        sql = f"UPDATE {table_name} SET {set_clause}"
        if where_clause:
            sql += f" WHERE {where_clause}"
        return sql

    def compile_update_joined(self, target_table: str, target_field: str, source_table: str, source_field: str, join_condition: str, filter_condition: str) -> str:
        where_clause = f" WHERE {filter_condition}" if filter_condition else ""
        sql = f"UPDATE t SET t.{target_field} = s.{source_field} FROM {target_table} t INNER JOIN {source_table} s ON {join_condition}{where_clause}"
        return sql

    def compile_delete_joined(self, target_table: str, source_table: str, join_condition: str, filter_condition: str) -> str:
        where_clause = f" WHERE {filter_condition}" if filter_condition else ""
        sql = f"DELETE t FROM {target_table} t INNER JOIN {source_table} s ON {join_condition}{where_clause}"
        return sql

    def format_value(self, value):
        """Formatta i valori nativi Python per SQL Server."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        if isinstance(value, date):
            return value.strftime('%Y-%m-%d')
        return value


class EntityModel:
    """Modello dati PRO esteso per operazioni massive, filtri scalari/insiemistici e UPDATE."""

    def __init__(self, table_map: TableMap, dialect: Dialect):
        self._map = table_map
        self._dialect = dialect
        self._selected_fields = []
        self._criteria = []
        self._params = []
        self._limit = None
        self._no_lock = False

    def select(self, *logical_columns: str):
        if logical_columns:
            self._selected_fields = [getattr(self._map, col) for col in logical_columns]
        return self

    def filter_by(self, logical_column: str, operator: str, value: Any):
        """
        Gestisce sia confronti scalari (=, <, >, <=, >=, <>) sia operatori di insieme (IN, NOT IN).
        """
        physical_col = getattr(self._map, logical_column)
        op_clean = operator.strip().upper()

        if op_clean in ("IN", "NOT IN") and isinstance(value, (list, tuple, set)):
            val_sequence = list(value)
            placeholders = ", ".join(["?" for _ in val_sequence])
            self._criteria.append(f"{physical_col} {op_clean} ({placeholders})")
            for item in val_sequence:
                self._params.append(self._dialect.format_value(item))
        else:
            self._criteria.append(f"{physical_col} {operator} ?")
            self._params.append(self._dialect.format_value(value))
        return self

    def with_uncommitted_read(self):
        self._no_lock = True
        return self

    def limit(self, max_rows: int):
        self._limit = max_rows
        return self

    def compile_select(self) -> CompiledQuery:
        fields_str = ", ".join(self._selected_fields) if self._selected_fields else "*"
        where_str = " AND ".join(self._criteria) if self._criteria else ""
        sql = self._dialect.compile_select(self._map.name, fields_str, where_str, self._limit, self._no_lock)
        return CompiledQuery(sql, tuple(self._params))

    def compile_update(self, set_values: Dict[str, Any]) -> CompiledQuery:
        """
        Compila l'istruzione UPDATE parametrica associando le clausole WHERE accumulate nel model.
        """
        set_fragments = []
        update_params = []

        for logical_col, val in set_values.items():
            physical_col = getattr(self._map, logical_col)
            set_fragments.append(f"{physical_col} = ?")
            update_params.append(self._dialect.format_value(val))

        set_clause = ", ".join(set_fragments)
        where_clause = " AND ".join(self._criteria) if self._criteria else ""
        total_params = tuple(update_params + self._params)

        sql = self._dialect.compile_update(self._map.name, set_clause, where_clause)
        return CompiledQuery(sql, total_params)