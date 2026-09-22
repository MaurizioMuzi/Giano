# core/query_builder.py
import re
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Dict, Any, List, Union, Optional
from config.schema_mapper import TableMap


class CompiledQuery:
    """Contenitore per statement SQL compilato e tuple di parametri associati."""

    def __init__(self, sql: str, params: tuple):
        self.sql = sql
        self.params = params


class Dialect(ABC):
    """Interfaccia astratta Enterprise per la scomposizione sintattica globale."""

    @abstractmethod
    def compile_select(self, table_name: str, fields: str, where: str, limit: int, no_lock: bool,
                       is_distinct: bool = False, order_by: str = "", group_by: str = "", having: str = "") -> str:
        pass

    @abstractmethod
    def compile_join(self, table_a: str, alias_a: str, table_b: str, alias_b: str,
                     fields: str, on_clause: str, where_clause: str,
                     limit: int, no_lock: bool, is_distinct: bool = False, order_by: str = "",
                     group_by: str = "", having: str = "") -> str:
        pass

    @abstractmethod
    def compile_subquery_count(self, inner_sql: str, alias: str, no_lock: bool) -> str:
        pass

    @abstractmethod
    def compile_update(self, table_name: str, set_clause: str, where_clause: str) -> str:
        pass

    @abstractmethod
    def compile_update_joined(self, target_table: str, target_field: str, source_table: str, source_field: str,
                              join_condition: str, filter_condition: str) -> str:
        pass

    @abstractmethod
    def compile_delete_joined(self, target_table: str, source_table: str, join_condition: str,
                              filter_condition: str) -> str:
        pass

    @abstractmethod
    def format_value(self, value):
        pass


class DB2Dialect(Dialect):
    """Dialetto Enterprise specifico per IBM DB2 Mainframe."""

    def compile_select(self, table_name: str, fields: str, where: str, limit: int, no_lock: bool,
                       is_distinct: bool = False, order_by: str = "", group_by: str = "", having: str = "") -> str:
        distinct_kw = "DISTINCT " if is_distinct else ""
        sql = f"SELECT {distinct_kw}{fields} FROM {table_name}"
        if where:
            sql += f" WHERE {where}"
        if group_by:
            sql += f" GROUP BY {group_by}"
        if having:
            sql += f" HAVING {having}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit:
            sql += f" FETCH FIRST {limit} ROWS ONLY"
        if no_lock:
            sql += " WITH UR"
        return sql

    def compile_join(self, table_a: str, alias_a: str, table_b: str, alias_b: str,
                     fields: str, on_clause: str, where_clause: str,
                     limit: int, no_lock: bool, is_distinct: bool = False, order_by: str = "",
                     group_by: str = "", having: str = "") -> str:
        is_count = fields.strip().upper() == "COUNT(*)"
        distinct_kw = "DISTINCT " if (is_distinct and not is_count) else ""
        sql = f"SELECT {distinct_kw}{fields} FROM {table_a} {alias_a} INNER JOIN {table_b} {alias_b} ON {on_clause}"
        if where_clause:
            sql += f" WHERE {where_clause}"
        if group_by:
            sql += f" GROUP BY {group_by}"
        if having:
            sql += f" HAVING {having}"
        if order_by and not is_count:
            sql += f" ORDER BY {order_by}"
        if limit and not is_count:
            sql += f" FETCH FIRST {limit} ROWS ONLY"
        if no_lock:
            sql += " WITH UR FOR FETCH ONLY"
        return sql

    def compile_subquery_count(self, inner_sql: str, alias: str, no_lock: bool) -> str:
        clean_inner = inner_sql.replace(" WITH UR FOR FETCH ONLY", "").replace(" WITH UR", "").strip()
        lock_clause = " WITH UR" if no_lock else ""
        return f"SELECT COUNT(*) FROM ({clean_inner}) {alias}{lock_clause}"

    def compile_update(self, table_name: str, set_clause: str, where_clause: str) -> str:
        sql = f"UPDATE {table_name} SET {set_clause}"
        if where_clause:
            sql += f" WHERE {where_clause}"
        return sql

    def compile_update_joined(self, target_table: str, target_field: str, source_table: str, source_field: str,
                              join_condition: str, filter_condition: str) -> str:
        where_clause = f" WHERE {filter_condition}" if filter_condition else ""
        sql = (
            f"UPDATE {target_table} SET {target_field} = (SELECT {source_field} FROM {source_table} WHERE {join_condition})"
            f" WHERE EXISTS (SELECT 1 FROM {source_table} WHERE {join_condition}{where_clause.replace('WHERE', 'AND')})")
        return sql

    def compile_delete_joined(self, target_table: str, source_table: str, join_condition: str,
                              filter_condition: str) -> str:
        where_clause = f" AND {filter_condition}" if filter_condition else ""
        sql = f"DELETE FROM {target_table} WHERE EXISTS (SELECT 1 FROM {source_table} WHERE {join_condition}{where_clause})"
        return sql

    def format_value(self, value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d-%H.%M.%S.%f')
        if isinstance(value, date):
            return value.strftime('%Y-%m-%d')
        return value


class SQLServerDialect(Dialect):
    """Dialetto Enterprise specifico per Microsoft SQL Server."""

    def compile_select(self, table_name: str, fields: str, where: str, limit: int, no_lock: bool,
                       is_distinct: bool = False, order_by: str = "", group_by: str = "", having: str = "") -> str:
        select_clause = "SELECT"
        if is_distinct:
            select_clause += " DISTINCT"
        if limit:
            select_clause += f" TOP {limit}"
        lock_hint = " WITH (NOLOCK)" if no_lock else ""
        sql = f"{select_clause} {fields} FROM {table_name}{lock_hint}"
        if where:
            sql += f" WHERE {where}"
        if group_by:
            sql += f" GROUP BY {group_by}"
        if having:
            sql += f" HAVING {having}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        return sql

    def compile_join(self, table_a: str, alias_a: str, table_b: str, alias_b: str,
                     fields: str, on_clause: str, where_clause: str,
                     limit: int, no_lock: bool, is_distinct: bool = False, order_by: str = "",
                     group_by: str = "", having: str = "") -> str:
        is_count = fields.strip().upper() == "COUNT(*)"
        select_clause = "SELECT"
        if not is_count:
            if is_distinct:
                select_clause += " DISTINCT"
            if limit:
                select_clause += f" TOP {limit}"

        lock_a = " WITH (NOLOCK)" if no_lock else ""
        lock_b = " WITH (NOLOCK)" if no_lock else ""
        sql = f"{select_clause} {fields} FROM {table_a} {alias_a}{lock_a} INNER JOIN {table_b} {alias_b}{lock_b} ON {on_clause}"
        if where_clause:
            sql += f" WHERE {where_clause}"
        if group_by:
            sql += f" GROUP BY {group_by}"
        if having:
            sql += f" HAVING {having}"
        if order_by and not is_count:
            sql += f" ORDER BY {order_by}"
        return sql

    def compile_subquery_count(self, inner_sql: str, alias: str, no_lock: bool) -> str:
        return f"SELECT COUNT(*) FROM ({inner_sql}) AS {alias}"

    def compile_update(self, table_name: str, set_clause: str, where_clause: str) -> str:
        sql = f"UPDATE {table_name} SET {set_clause}"
        if where_clause:
            sql += f" WHERE {where_clause}"
        return sql

    def compile_update_joined(self, target_table: str, target_field: str, source_table: str, source_field: str,
                              join_condition: str, filter_condition: str) -> str:
        where_clause = f" WHERE {filter_condition}" if filter_condition else ""
        sql = f"UPDATE t SET t.{target_field} = s.{source_field} FROM {target_table} t INNER JOIN {source_table} s ON {join_condition}{where_clause}"
        return sql

    def compile_delete_joined(self, target_table: str, source_table: str, join_condition: str,
                              filter_condition: str) -> str:
        where_clause = f" WHERE {filter_condition}" if filter_condition else ""
        sql = f"DELETE t FROM {target_table} t INNER JOIN {source_table} s ON {join_condition}{where_clause}"
        return sql

    def format_value(self, value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        if isinstance(value, date):
            return value.strftime('%Y-%m-%d')
        return value


class ExistsSubquery:
    """Builder fluido per la compilazione di sottoquery correlate: EXISTS (SELECT 1 FROM ...)."""

    def __init__(self, target_table_map: TableMap, alias: str, dialect: Dialect, parent_alias: Optional[str] = "A"):
        self._map = target_table_map
        self._alias = alias
        self._dialect = dialect
        self._parent_alias = parent_alias
        self._criteria: List[str] = []
        self._params: List[Any] = []

    def correlate(self, sub_logical_col: str, parent_logical_col: str, parent_table_map: TableMap, operator: str = "="):
        """Correlazione scalare tra sottoquery e tabella esterna: alias_sub.COL = alias_parent.COL."""
        phys_sub = getattr(self._map, sub_logical_col)
        phys_parent = getattr(parent_table_map, parent_logical_col)
        p_prefix = f"{self._parent_alias}." if self._parent_alias else ""
        self._criteria.append(f"{self._alias}.{phys_sub} {operator} {p_prefix}{phys_parent}")
        return self

    def correlate_mismatch(self, *logical_cols: str, parent_table_map: TableMap, operator: str = "<>"):
        """
        Risolve dinamicamente una disgiunzione (OR) di disuguaglianza tra colonne correlate.
        Genera ad es.: (B.CGES <> A.CGES OR B.CSED <> A.CSED OR B.ANNOAVV <> A.ANNOAVV ...)
        """
        if not logical_cols:
            return self

        p_prefix = f"{self._parent_alias}." if self._parent_alias else ""
        mismatch_clauses = []
        for col in logical_cols:
            phys_sub = getattr(self._map, col)
            phys_parent = getattr(parent_table_map, col)
            mismatch_clauses.append(f"{self._alias}.{phys_sub} {operator} {p_prefix}{phys_parent}")

        combined = " OR ".join(mismatch_clauses)
        self._criteria.append(f"({combined})")
        return self

    def filter_by(self, logical_col: str, operator: str, value: Any):
        """Filtro scalare o insiemistico con parametri posizionali sicuri."""
        phys = getattr(self._map, logical_col)
        col_ref = f"{self._alias}.{phys}"
        op_clean = operator.strip().upper()

        if op_clean in ("IN", "NOT IN") and isinstance(value, (list, tuple, set)):
            val_sequence = list(value)
            placeholders = ", ".join(["?" for _ in val_sequence])
            self._criteria.append(f"{col_ref} {op_clean} ({placeholders})")
            for item in val_sequence:
                self._params.append(self._dialect.format_value(item))
        else:
            self._criteria.append(f"{col_ref} {operator} ?")
            self._params.append(self._dialect.format_value(value))
        return self

    def compile(self) -> tuple[str, list]:
        """Restituisce la clausola 'EXISTS (SELECT 1 FROM TAB B WHERE ...)' e i relativi parametri."""
        where_str = f" WHERE {' AND '.join(self._criteria)}" if self._criteria else ""
        sql = f"EXISTS (SELECT 1 FROM {self._map.name} {self._alias}{where_str})"
        return sql, self._params


class EntityModel:
    """Modello dati PRO esteso per operazioni massive, aggregazioni, ordinamenti DESC, funzioni scalari ed EXISTS."""

    def __init__(self, table_map: TableMap, dialect: Dialect):
        self._map = table_map
        self._dialect = dialect
        self._selected_fields: List[str] = []
        self._criteria: List[str] = []
        self._params: List[Any] = []
        self._order_by_fields: List[str] = []
        self._group_by_fields: List[str] = []
        self._having_clause: str = ""
        self._subquery_count_alias: Optional[str] = None
        self._limit = None
        self._no_lock = False
        self._is_count = False
        self._is_distinct = False

        self._joined_map: TableMap = None
        self._alias_self: str = "A"
        self._alias_joined: str = "B"
        self._join_conditions: List[str] = []

    def count(self):
        self._is_count = True
        return self

    def count_subquery(self, alias: str = "TAB1"):
        self._subquery_count_alias = alias
        return self

    def distinct(self):
        self._is_distinct = True
        return self

    def join(self, target_table_map: TableMap, alias_self: str = "A", alias_target: str = "B"):
        self._joined_map = target_table_map
        self._alias_self = alias_self
        self._alias_joined = alias_target
        return self

    def on(self, col_left_logical: str, col_right_logical: str):
        if not self._joined_map:
            raise ValueError("Chiamare .join(table_map) prima di specificare clausole .on()")
        phys_a = getattr(self._map, col_left_logical)
        phys_b = getattr(self._joined_map, col_right_logical)
        self._join_conditions.append(f"{self._alias_self}.{phys_a} = {self._alias_joined}.{phys_b}")
        return self

    def _resolve_column_expression(self, expr: str, table_map: TableMap, table_alias: Optional[str]) -> str:
        expr_clean = expr.strip()

        if ":" in expr_clean:
            func, logical_col = expr_clean.split(":", 1)
            func = func.strip().upper()
            logical_col = logical_col.strip()
            phys = getattr(table_map, logical_col)
            col_target = f"{table_alias}.{phys}" if table_alias else phys
            return f"{func}({col_target}) AS {phys}"

        match = re.match(r"^([a-zA-Z0-9_]+)\s*\(\s*([a-zA-Z0-9_]+)\s*\)$", expr_clean)
        if match:
            func = match.group(1).upper()
            logical_col = match.group(2)
            if hasattr(table_map, logical_col):
                phys = getattr(table_map, logical_col)
                col_target = f"{table_alias}.{phys}" if table_alias else phys
                return f"{func}({col_target}) AS {phys}"

        phys = getattr(table_map, expr_clean)
        return f"{table_alias}.{phys}" if table_alias else phys

    def select(self, *logical_columns: str):
        alias = self._alias_self if self._joined_map else None
        for col in logical_columns:
            self._selected_fields.append(self._resolve_column_expression(col, self._map, alias))
        return self

    def select_joined(self, *logical_columns: str):
        if not self._joined_map:
            raise ValueError("Nessuna tabella agganciata in JOIN per select_joined()")
        for col in logical_columns:
            self._selected_fields.append(self._resolve_column_expression(col, self._joined_map, self._alias_joined))
        return self

    def select_raw(self, raw_expression: str):
        self._selected_fields.append(raw_expression)
        return self

    def _resolve_order_field(self, col_expr: str, table_map: TableMap, table_alias: Optional[str], default_desc: bool = False) -> str:
        col_clean = col_expr.strip()
        direction = "DESC" if default_desc else "ASC"

        if col_clean.startswith("-"):
            direction = "DESC"
            col_clean = col_clean[1:].strip()
        elif col_clean.upper().endswith(" DESC"):
            direction = "DESC"
            col_clean = col_clean[:-5].strip()
        elif col_clean.upper().endswith(" ASC"):
            direction = "ASC"
            col_clean = col_clean[:-4].strip()

        phys = getattr(table_map, col_clean)
        target = f"{table_alias}.{phys}" if table_alias else phys
        return f"{target} {direction}" if direction == "DESC" else target

    def order_by(self, *logical_columns: str):
        alias = self._alias_self if self._joined_map else None
        for col in logical_columns:
            self._order_by_fields.append(self._resolve_order_field(col, self._map, alias))
        return self

    def order_by_desc(self, *logical_columns: str):
        alias = self._alias_self if self._joined_map else None
        for col in logical_columns:
            self._order_by_fields.append(self._resolve_order_field(col, self._map, alias, default_desc=True))
        return self

    def order_by_joined(self, *logical_columns: str):
        if not self._joined_map:
            raise ValueError("Nessuna tabella agganciata in JOIN per order_by_joined()")
        for col in logical_columns:
            self._order_by_fields.append(self._resolve_order_field(col, self._joined_map, self._alias_joined))
        return self

    def order_by_joined_desc(self, *logical_columns: str):
        if not self._joined_map:
            raise ValueError("Nessuna tabella agganciata in JOIN per order_by_joined_desc()")
        for col in logical_columns:
            self._order_by_fields.append(self._resolve_order_field(col, self._joined_map, self._alias_joined, default_desc=True))
        return self

    def group_by(self, *logical_columns: str):
        for col in logical_columns:
            phys = getattr(self._map, col)
            self._group_by_fields.append(f"{self._alias_self}.{phys}" if self._joined_map else phys)
        return self

    def group_by_joined(self, *logical_columns: str):
        if not self._joined_map:
            raise ValueError("Nessuna tabella agganciata in JOIN per group_by_joined()")
        for col in logical_columns:
            phys = getattr(self._joined_map, col)
            self._group_by_fields.append(f"{self._alias_joined}.{phys}")
        return self

    def having_raw(self, having_expression: str):
        self._having_clause = having_expression
        return self

    def filter_by(self, logical_column: str, operator: str, value: Any):
        physical_col = getattr(self._map, logical_column)
        col_ref = f"{self._alias_self}.{physical_col}" if self._joined_map else physical_col
        self._apply_filter(col_ref, operator, value)
        return self

    def filter_by_joined(self, logical_column: str, operator: str, value: Any):
        if not self._joined_map:
            raise ValueError("Nessuna tabella agganciata in JOIN per filter_by_joined()")
        physical_col = getattr(self._joined_map, logical_column)
        col_ref = f"{self._alias_joined}.{physical_col}"
        self._apply_filter(col_ref, operator, value)
        return self

    def _apply_filter(self, col_ref: str, operator: str, value: Any):
        op_clean = operator.strip().upper()
        if op_clean in ("IN", "NOT IN") and isinstance(value, (list, tuple, set)):
            val_sequence = list(value)
            placeholders = ", ".join(["?" for _ in val_sequence])
            self._criteria.append(f"{col_ref} {op_clean} ({placeholders})")
            for item in val_sequence:
                self._params.append(self._dialect.format_value(item))
        else:
            self._criteria.append(f"{col_ref} {operator} ?")
            self._params.append(self._dialect.format_value(value))

    def exists(self, target_table_map: TableMap, alias: str = "B") -> ExistsSubquery:
        """Crea una sottoquery EXISTS per la tabella specificata."""
        parent_alias = self._alias_self if self._joined_map else None
        return ExistsSubquery(target_table_map, alias, self._dialect, parent_alias=parent_alias)

    def where_exists(self, subquery: ExistsSubquery):
        """Aggancia la sottoquery con condizione WHERE EXISTS (...) e ne accumula i parametri."""
        sql, sub_params = subquery.compile()
        self._criteria.append(sql)
        self._params.extend(sub_params)
        return self

    def where_not_exists(self, subquery: ExistsSubquery):
        """Aggancia la sottoquery con condizione WHERE NOT EXISTS (...) e ne accumula i parametri."""
        sql, sub_params = subquery.compile()
        self._criteria.append(f"NOT {sql}")
        self._params.extend(sub_params)
        return self

    def with_uncommitted_read(self):
        self._no_lock = True
        return self

    def limit(self, max_rows: int):
        self._limit = max_rows
        return self

    def compile_select(self) -> CompiledQuery:
        if self._is_count:
            fields_str = "COUNT(*)"
        else:
            fields_str = ", ".join(self._selected_fields) if self._selected_fields else "*"

        where_str = " AND ".join(self._criteria) if self._criteria else ""
        order_str = ", ".join(self._order_by_fields) if self._order_by_fields else ""
        group_str = ", ".join(self._group_by_fields) if self._group_by_fields else ""

        if self._joined_map:
            on_str = " AND ".join(self._join_conditions)
            sql = self._dialect.compile_join(
                table_a=self._map.name,
                alias_a=self._alias_self,
                table_b=self._joined_map.name,
                alias_b=self._alias_joined,
                fields=fields_str,
                on_clause=on_str,
                where_clause=where_str,
                limit=self._limit,
                no_lock=self._no_lock,
                is_distinct=self._is_distinct,
                order_by=order_str,
                group_by=group_str,
                having=self._having_clause
            )
        else:
            sql = self._dialect.compile_select(
                table_name=self._map.name,
                fields=fields_str,
                where=where_str,
                limit=self._limit,
                no_lock=self._no_lock,
                is_distinct=self._is_distinct,
                order_by=order_str,
                group_by=group_str,
                having=self._having_clause
            )

        if self._subquery_count_alias:
            sql = self._dialect.compile_subquery_count(
                inner_sql=sql,
                alias=self._subquery_count_alias,
                no_lock=self._no_lock
            )

        return CompiledQuery(sql, tuple(self._params))

    def compile_update(self, set_values: Dict[str, Any]) -> CompiledQuery:
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