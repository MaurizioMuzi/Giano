# core/query_builder.py
import json
import os
import re
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Dict, Any, List, Union, Optional
from config.schema_mapper import TableMap

# Risale da core/ alla radice del progetto e punta a config/sql/template_sql.json
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_FILE_PATH = os.path.join(BASE_DIR, "config", "sql", "template_sql.json")


def _load_sql_catalog(path: str) -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Configurazione template SQL assente: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


SQL_CATALOG = _load_sql_catalog(TEMPLATES_FILE_PATH)
COMMON_SQL = SQL_CATALOG.get("common_fragments", {})


class CompiledQuery:
    """Contenitore per statement SQL compilato e tuple di parametri associati."""

    def __init__(self, sql: str, params: tuple):
        self.sql = sql
        self.params = params

    @property
    def debug_sql(self) -> str:
        """
        Restituisce la query SQL con i valori reali sostituiti ai segnaposti '?',
        formattata per il copia-incolla immediato in qualsiasi client SQL.
        """
        if not self.params:
            return self.sql

        formatted_vals = []
        for p in self.params:
            if p is None:
                formatted_vals.append("NULL")
            elif isinstance(p, (int, float, Decimal)):
                formatted_vals.append(str(p))
            elif isinstance(p, datetime):
                # Formato compatibile DB2 / SQL Server
                formatted_vals.append(f"'{p.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}'")
            elif isinstance(p, date):
                formatted_vals.append(f"'{p.strftime('%Y-%m-%d')}'")
            elif isinstance(p, bool):
                formatted_vals.append("1" if p else "0")
            else:
                # Stringhe e altri tipi: raddoppia eventuali apici singoli
                val_escaped = str(p).replace("'", "''")
                formatted_vals.append(f"'{val_escaped}'")

        # Sostituzione ordinata dei singoli '?' con i rispettivi valori letterali
        query_parts = self.sql.split("?")
        if len(query_parts) - 1 != len(formatted_vals):
            # Fallback di sicurezza in caso di mismatch
            return f"-- [PARAM MISMATCH] params={self.params}\n{self.sql}"

        reconstructed = []
        for i, part in enumerate(query_parts[:-1]):
            reconstructed.append(part)
            reconstructed.append(formatted_vals[i])
        reconstructed.append(query_parts[-1])

        return "".join(reconstructed)

    def __str__(self) -> str:
        return self.debug_sql


class Dialect(ABC):
    """Interfaccia astratta Enterprise configurata su modelli esterni JSON."""

    def __init__(self, dialect_key: str):
        self.config = SQL_CATALOG.get("dialects", {}).get(dialect_key, {})

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
    def compile_delete(self, table_name: str, where_clause: str) -> str:
        pass

    @abstractmethod
    def compile_delete_joined(self, target_table: str, source_table: str, join_condition: str,
                              filter_condition: str) -> str:
        pass

    def get_function_template(self, func_name: str) -> str:
        return self.config.get("functions", {}).get(func_name, "")

    def format_value(self, value):
        if value is None:
            return None

        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d-%H.%M.%S.%f')
        if isinstance(value, date):
            return value.strftime('%Y-%m-%d')

        if isinstance(value, str):
            val_clean = value.strip()
            if val_clean in ("0001-01-01-00.00.00.000000", "0001-01-01 00:00:00.000000"):
                return "0001-01-01-00.00.00.000000"
            if val_clean == "0001-01-01":
                return "0001-01-01"
            return value

        return value


class DB2Dialect(Dialect):
    """Dialetto Enterprise per IBM DB2 Mainframe configurato su catalogo JSON."""

    def __init__(self):
        super().__init__("DB2")

    def compile_select(self, table_name: str, fields: str, where: str, limit: int, no_lock: bool,
                       is_distinct: bool = False, order_by: str = "", group_by: str = "", having: str = "") -> str:
        cfg = self.config["select"]
        distinct_kw = cfg["distinct_keyword"] if is_distinct else ""
        sql = cfg["statement"].format(distinct=distinct_kw, fields=fields, table=table_name)

        if where:
            sql += f" " + cfg["where"].format(condition=where)
        if group_by:
            sql += f" " + cfg["group_by"].format(columns=group_by)
        if having:
            sql += f" " + cfg["having"].format(condition=having)
        if order_by:
            sql += f" " + cfg["order_by"].format(columns=order_by)
        if limit:
            sql += f" " + cfg["limit"].format(limit=limit)
        if no_lock:
            sql += f" " + cfg["isolation_ur"]
        return sql

    def compile_join(self, table_a: str, alias_a: str, table_b: str, alias_b: str,
                     fields: str, on_clause: str, where_clause: str,
                     limit: int, no_lock: bool, is_distinct: bool = False, order_by: str = "",
                     group_by: str = "", having: str = "") -> str:
        cfg = self.config["join"]
        is_count = fields.strip().upper() == "COUNT(*)"
        distinct_kw = cfg["distinct_keyword"] if (is_distinct and not is_count) else ""

        sql = cfg["statement"].format(
            distinct=distinct_kw,
            fields=fields,
            table_a=table_a,
            alias_a=alias_a,
            table_b=table_b,
            alias_b=alias_b,
            on_clause=on_clause
        )
        if where_clause:
            sql += f" " + cfg["where"].format(condition=where_clause)
        if group_by:
            sql += f" " + cfg["group_by"].format(columns=group_by)
        if having:
            sql += f" " + cfg["having"].format(condition=having)
        if order_by and not is_count:
            sql += f" " + cfg["order_by"].format(columns=order_by)
        if limit and not is_count:
            sql += f" " + cfg["limit"].format(limit=limit)
        if no_lock:
            sql += f" " + cfg["isolation_ur"]
        return sql

    def compile_subquery_count(self, inner_sql: str, alias: str, no_lock: bool) -> str:
        clean_inner = inner_sql.replace(" WITH UR FOR FETCH ONLY", "").replace(" WITH UR", "").strip()
        lock_clause = f" {self.config['select']['isolation_ur']}" if no_lock else ""
        return self.config["subquery_count"]["statement"].format(
            inner_sql=clean_inner,
            alias=alias,
            isolation=lock_clause
        )

    def compile_update(self, table_name: str, set_clause: str, where_clause: str) -> str:
        cfg = self.config["update"]
        sql = cfg["statement"].format(table=table_name, set_clause=set_clause)
        if where_clause:
            sql += f" " + cfg["where"].format(condition=where_clause)
        return sql

    def compile_update_joined(self, target_table: str, target_field: str, source_table: str, source_field: str,
                              join_condition: str, filter_condition: str) -> str:
        where_filter = f" AND {filter_condition}" if filter_condition else ""
        return self.config["update_joined"]["statement"].format(
            target_table=target_table,
            target_field=target_field,
            source_table=source_table,
            source_field=source_field,
            join_condition=join_condition,
            filter_condition=where_filter
        )

    def compile_delete(self, table_name: str, where_clause: str) -> str:
        cfg = self.config["delete"]
        sql = cfg["statement"].format(table=table_name)
        if where_clause:
            sql += f" " + cfg["where"].format(condition=where_clause)
        return sql

    def compile_delete_joined(self, target_table: str, source_table: str, join_condition: str,
                              filter_condition: str) -> str:
        where_filter = f" AND {filter_condition}" if filter_condition else ""
        return self.config["delete_joined"]["statement"].format(
            target_table=target_table,
            source_table=source_table,
            join_condition=join_condition,
            filter_condition=where_filter
        )

    def format_value(self, value):
        if value is None:
            return None
        if isinstance(value, str):
            val_clean = value.strip()
            if val_clean in ("0001-01-01-00.00.00.000000", "0001-01-01 00:00:00.000000"):
                return datetime(1, 1, 1, 0, 0, 0)
            if val_clean == "0001-01-01":
                return date(1, 1, 1)
            return value

        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return value
        return value


class SQLServerDialect(Dialect):
    """Dialetto Enterprise per Microsoft SQL Server configurato su catalogo JSON."""

    def __init__(self):
        super().__init__("SQLSERVER")

    def compile_select(self, table_name: str, fields: str, where: str, limit: int, no_lock: bool,
                       is_distinct: bool = False, order_by: str = "", group_by: str = "", having: str = "") -> str:
        cfg = self.config["select"]
        distinct_kw = cfg["distinct_keyword"] if is_distinct else ""
        limit_kw = cfg["limit"].format(limit=limit) if limit else ""
        lock_kw = cfg["lock_hint"] if no_lock else ""

        sql = cfg["statement"].format(
            distinct=distinct_kw,
            limit=limit_kw,
            fields=fields,
            table=table_name,
            lock_hint=lock_kw
        )
        if where:
            sql += f" " + cfg["where"].format(condition=where)
        if group_by:
            sql += f" " + cfg["group_by"].format(columns=group_by)
        if having:
            sql += f" " + cfg["having"].format(condition=having)
        if order_by:
            sql += f" " + cfg["order_by"].format(columns=order_by)
        return sql

    def compile_join(self, table_a: str, alias_a: str, table_b: str, alias_b: str,
                     fields: str, on_clause: str, where_clause: str,
                     limit: int, no_lock: bool, is_distinct: bool = False, order_by: str = "",
                     group_by: str = "", having: str = "") -> str:
        cfg = self.config["join"]
        is_count = fields.strip().upper() == "COUNT(*)"
        distinct_kw = ""
        limit_kw = ""
        if not is_count:
            if is_distinct:
                distinct_kw = cfg["distinct_keyword"]
            if limit:
                limit_kw = cfg["limit"].format(limit=limit)

        lock_kw = cfg["lock_hint"] if no_lock else ""

        sql = cfg["statement"].format(
            distinct=distinct_kw,
            limit=limit_kw,
            fields=fields,
            table_a=table_a,
            alias_a=alias_a,
            lock_a=lock_kw,
            table_b=table_b,
            alias_b=alias_b,
            lock_b=lock_kw,
            on_clause=on_clause
        )
        if where_clause:
            sql += f" " + cfg["where"].format(condition=where_clause)
        if group_by:
            sql += f" " + cfg["group_by"].format(columns=group_by)
        if having:
            sql += f" " + cfg["having"].format(condition=having)
        if order_by and not is_count:
            sql += f" " + cfg["order_by"].format(columns=order_by)
        return sql

    def compile_subquery_count(self, inner_sql: str, alias: str, no_lock: bool) -> str:
        return self.config["subquery_count"]["statement"].format(inner_sql=inner_sql, alias=alias)

    def compile_update(self, table_name: str, set_clause: str, where_clause: str) -> str:
        cfg = self.config["update"]
        sql = cfg["statement"].format(table=table_name, set_clause=set_clause)
        if where_clause:
            sql += f" " + cfg["where"].format(condition=where_clause)
        return sql

    def compile_update_joined(self, target_table: str, target_field: str, source_table: str, source_field: str,
                              join_condition: str, filter_condition: str) -> str:
        where_clause = f" WHERE {filter_condition}" if filter_condition else ""
        return self.config["update_joined"]["statement"].format(
            target_table=target_table,
            target_field=target_field,
            source_table=source_table,
            source_field=source_field,
            join_condition=join_condition,
            filter_condition=where_clause
        )

    def compile_delete(self, table_name: str, where_clause: str) -> str:
        cfg = self.config["delete"]
        sql = cfg["statement"].format(table=table_name)
        if where_clause:
            sql += f" " + cfg["where"].format(condition=where_clause)
        return sql

    def compile_delete_joined(self, target_table: str, source_table: str, join_condition: str,
                              filter_condition: str) -> str:
        where_clause = f" WHERE {filter_condition}" if filter_condition else ""
        return self.config["delete_joined"]["statement"].format(
            target_table=target_table,
            source_table=source_table,
            join_condition=join_condition,
            filter_condition=where_clause
        )

    def format_value(self, value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        if isinstance(value, date):
            return value.strftime('%Y-%m-%d')
        return value


class ExpressionBuilder:
    """Costruttore astratto di espressioni scalari (funzioni, concatenazioni, conversioni) basato su JSON."""

    def __init__(self, model: "EntityModel"):
        self._model = model
        self._dialect = model._dialect

    def _resolve(self, item: Any) -> str:
        if isinstance(item, ExpressionBuilder):
            return item.compile()
        if isinstance(item, str):
            # Se è una colonna logica presente nella TableMap
            if hasattr(self._model._map, item):
                phys = getattr(self._model._map, item)
                return f"{self._model._alias_self}.{phys}" if self._model._joined_map else phys
            if self._model._joined_map and hasattr(self._model._joined_map, item):
                phys = getattr(self._model._joined_map, item)
                return f"{self._model._alias_joined}.{phys}"
            # Altrimenti è un letterale stringa gestito tramite JSON
            return COMMON_SQL["expressions"]["literal_string"].format(value=item)
        return str(item)

    def concat(self, *items: Any) -> "ExpressionBuilder":
        """Concatena più elementi in sequenza secondo il template di dialetto."""
        template = self._dialect.get_function_template("concat")
        if not template:
            raise NotImplementedError(f"Operazione concat non supportata dal dialetto {self._dialect}")

        current = self._resolve(items[0])
        for next_item in items[1:]:
            current = template.format(left=current, right=self._resolve(next_item))

        builder = ExpressionBuilder(self._model)
        builder._compiled = current
        return builder

    def rtrim(self, column_logical: str) -> "ExpressionBuilder":
        template = self._dialect.get_function_template("rtrim")
        col_res = self._resolve(column_logical)
        builder = ExpressionBuilder(self._model)
        builder._compiled = template.format(column=col_res)
        return builder

    def strip_leading_zero(self, column_logical: str) -> "ExpressionBuilder":
        template = self._dialect.get_function_template("strip_leading_zero")
        col_res = self._resolve(column_logical)
        builder = ExpressionBuilder(self._model)
        builder._compiled = template.format(column=col_res)
        return builder

    def char(self, column_logical: str) -> "ExpressionBuilder":
        template = self._dialect.get_function_template("char")
        col_res = self._resolve(column_logical)
        builder = ExpressionBuilder(self._model)
        builder._compiled = template.format(column=col_res)
        return builder

    def compile(self) -> str:
        return getattr(self, "_compiled", "")


class CaseConditionBuilder:
    """Builder per la condizione WHEN (ad es. column > value) senza frammenti SQL grezzi."""

    def __init__(self, model: "EntityModel", logical_col: str, operator: str, value: Any):
        self._model = model
        self.logical_col = logical_col
        self.operator = operator
        self.value = value

    def compile(self) -> str:
        phys = getattr(self._model._map, self.logical_col, self.logical_col)
        col_target = f"{self._model._alias_self}.{phys}" if self._model._joined_map else phys

        if isinstance(self.value, str):
            val_formatted = COMMON_SQL["expressions"]["literal_string"].format(value=self.value)
        else:
            val_formatted = str(self.value)

        return f"{col_target} {self.operator} {val_formatted}"


class CaseBuilder:
    """Builder fluido e sicuro per espressioni CASE WHEN, completamente separato da SQL inline."""

    def __init__(self, parent_model: "EntityModel"):
        self._model = parent_model
        self._branches: List[str] = []
        self._else_clause: Optional[str] = None
        self._alias: Optional[str] = None

    def when(self, logical_col: str, operator: str, comp_value: Any, then_expression: Union[str, ExpressionBuilder]):
        condition = CaseConditionBuilder(self._model, logical_col, operator, comp_value).compile()
        then_sql = then_expression.compile() if isinstance(then_expression,
                                                           ExpressionBuilder) else self._model.expr()._resolve(
            then_expression)

        branch = COMMON_SQL["expressions"]["case_when"].format(
            condition=condition,
            result=then_sql
        )
        self._branches.append(branch)
        return self

    def else_(self, else_expression: Union[str, ExpressionBuilder]):
        else_sql = else_expression.compile() if isinstance(else_expression,
                                                           ExpressionBuilder) else self._model.expr()._resolve(
            else_expression)
        self._else_clause = COMMON_SQL["expressions"]["case_else"].format(result=else_sql)
        return self

    def as_(self, alias: str):
        self._alias = alias
        return self

    def compile(self) -> str:
        branches_str = " ".join(self._branches)
        else_str = self._else_clause or ""
        raw_case = COMMON_SQL["expressions"]["case_statement"].format(
            branches=branches_str,
            else_clause=else_str
        ).strip()

        if self._alias:
            return COMMON_SQL["expressions"]["column_alias"].format(
                expression=raw_case,
                alias=self._alias
            )
        return raw_case

    def end(self) -> "EntityModel":
        self._model.select_raw(self.compile())
        return self._model


class ExistsSubquery:
    """Builder fluido per la compilazione di sottoquery correlate leggendo i modelli da JSON."""

    def __init__(self, target_table_map: TableMap, alias: str, dialect: Dialect, parent_alias: Optional[str] = "A"):
        self._map = target_table_map
        self._alias = alias
        self._dialect = dialect
        self._parent_alias = parent_alias
        self._criteria: List[str] = []
        self._params: List[Any] = []

    def correlate(self, sub_logical_col: str, parent_logical_col: str, parent_table_map: TableMap, operator: str = "="):
        phys_sub = getattr(self._map, sub_logical_col)
        phys_parent = getattr(parent_table_map, parent_logical_col)
        p_prefix = f"{self._parent_alias}." if self._parent_alias else ""

        clause = COMMON_SQL["predicates"]["correlation"].format(
            alias_sub=self._alias,
            col_sub=phys_sub,
            operator=operator,
            parent_prefix=p_prefix,
            col_parent=phys_parent
        )
        self._criteria.append(clause)
        return self

    def correlate_mismatch(self, *logical_cols: str, parent_table_map: TableMap, operator: str = "<>"):
        if not logical_cols:
            return self

        p_prefix = f"{self._parent_alias}." if self._parent_alias else ""
        mismatch_clauses = []
        for col in logical_cols:
            phys_sub = getattr(self._map, col)
            phys_parent = getattr(parent_table_map, col)
            clause = COMMON_SQL["predicates"]["correlation"].format(
                alias_sub=self._alias,
                col_sub=phys_sub,
                operator=operator,
                parent_prefix=p_prefix,
                col_parent=phys_parent
            )
            mismatch_clauses.append(clause)

        combined = " OR ".join(mismatch_clauses)
        self._criteria.append(f"({combined})")
        return self

    def filter_by(self, logical_col: str, operator: str, value: Any):
        phys = getattr(self._map, logical_col)
        col_ref = f"{self._alias}.{phys}"
        op_clean = operator.strip().upper()

        if op_clean in ("IN", "NOT IN") and isinstance(value, (list, tuple, set)):
            val_sequence = list(value)
            placeholders = ", ".join(["?" for _ in val_sequence])
            clause = COMMON_SQL["predicates"]["in_sequence"].format(
                column=col_ref,
                operator=op_clean,
                placeholders=placeholders
            )
            self._criteria.append(clause)
            for item in val_sequence:
                self._params.append(self._dialect.format_value(item))
        else:
            clause = COMMON_SQL["predicates"]["comparison"].format(
                column=col_ref,
                operator=operator
            )
            self._criteria.append(clause)
            self._params.append(self._dialect.format_value(value))
        return self

    def compile(self) -> tuple[str, list]:
        where_str = f" WHERE {' AND '.join(self._criteria)}" if self._criteria else ""
        sql = COMMON_SQL["exists"]["statement"].format(
            table=self._map.name,
            alias=self._alias,
            where_clause=where_str
        )
        return sql, self._params


class EntityModel:
    """Modello dati fluido orientato a TableMap, disaccoppiato tramite il catalogo JSON."""

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

    def expr(self) -> ExpressionBuilder:
        """Inizializza un builder di espressioni scalari collegate alla tabella e al dialetto."""
        return ExpressionBuilder(self)

    def case(self) -> CaseBuilder:
        """Inizia la composizione fluida e sicura di un costrutto CASE WHEN."""
        return CaseBuilder(self)

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
        clause = COMMON_SQL["predicates"]["equality_join"].format(
            alias_a=self._alias_self,
            col_a=phys_a,
            alias_b=self._alias_joined,
            col_b=phys_b
        )
        self._join_conditions.append(clause)
        return self

    def _resolve_column_expression(self, expr: str, table_map: TableMap, table_alias: Optional[str]) -> str:
        expr_clean = expr.strip()

        if ":" in expr_clean:
            func, logical_col = expr_clean.split(":", 1)
            func = func.strip().upper()
            logical_col = logical_col.strip()
            phys = getattr(table_map, logical_col)
            col_target = f"{table_alias}.{phys}" if table_alias else phys
            return COMMON_SQL["expressions"]["function_alias"].format(
                function=func,
                column=col_target,
                alias=phys
            )

        match = re.match(r"^([a-zA-Z0-9_]+)\s*\(\s*([a-zA-Z0-9_]+)\s*\)$", expr_clean)
        if match:
            func = match.group(1).upper()
            logical_col = match.group(2)
            if hasattr(table_map, logical_col):
                phys = getattr(table_map, logical_col)
                col_target = f"{table_alias}.{phys}" if table_alias else phys
                return COMMON_SQL["expressions"]["function_alias"].format(
                    function=func,
                    column=col_target,
                    alias=phys
                )

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

    def _resolve_order_field(self, col_expr: str, table_map: TableMap, table_alias: Optional[str],
                             default_desc: bool = False) -> str:
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
        if direction == "DESC":
            return COMMON_SQL["expressions"]["order_item"].format(column=target, direction=direction)
        return target

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
            self._order_by_fields.append(
                self._resolve_order_field(col, self._joined_map, self._alias_joined, default_desc=True))
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
            clause = COMMON_SQL["predicates"]["in_sequence"].format(
                column=col_ref,
                operator=op_clean,
                placeholders=placeholders
            )
            self._criteria.append(clause)
            for item in val_sequence:
                self._params.append(self._dialect.format_value(item))
        else:
            clause = COMMON_SQL["predicates"]["comparison"].format(
                column=col_ref,
                operator=operator
            )
            self._criteria.append(clause)
            self._params.append(self._dialect.format_value(value))

    def exists(self, target_table_map: TableMap, alias: str = "B") -> ExistsSubquery:
        parent_alias = self._alias_self if self._joined_map else None
        return ExistsSubquery(target_table_map, alias, self._dialect, parent_alias=parent_alias)

    def where_exists(self, subquery: ExistsSubquery):
        sql, sub_params = subquery.compile()
        self._criteria.append(sql)
        self._params.extend(sub_params)
        return self

    def where_not_exists(self, subquery: ExistsSubquery):
        sql, sub_params = subquery.compile()
        negated_sql = COMMON_SQL["exists"]["not_prefix"].format(expression=sql)
        self._criteria.append(negated_sql)
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
            assignment = COMMON_SQL["predicates"]["assignment"].format(column=physical_col)
            set_fragments.append(assignment)
            update_params.append(self._dialect.format_value(val))

        set_clause = ", ".join(set_fragments)
        where_clause = " AND ".join(self._criteria) if self._criteria else ""
        total_params = tuple(update_params + self._params)

        sql = self._dialect.compile_update(self._map.name, set_clause, where_clause)
        return CompiledQuery(sql, total_params)

    def compile_delete(self) -> CompiledQuery:
        where_clause = " AND ".join(self._criteria) if self._criteria else ""
        sql = self._dialect.compile_delete(self._map.name, where_clause)
        return CompiledQuery(sql, tuple(self._params))

    def compile_delete_joined(self) -> CompiledQuery:
        if not self._joined_map:
            raise ValueError("Nessuna tabella configurata con .join() per compile_delete_joined()")

        join_condition = " AND ".join(self._join_conditions)
        filter_condition = " AND ".join(self._criteria) if self._criteria else ""

        sql = self._dialect.compile_delete_joined(
            target_table=self._map.name,
            source_table=self._joined_map.name,
            join_condition=join_condition,
            filter_condition=filter_condition
        )
        return CompiledQuery(sql, tuple(self._params))

    def compile_insert(self, data: Dict[str, Any]) -> CompiledQuery:
        phys_cols = []
        placeholders = []
        insert_params = []

        for logical_col, val in data.items():
            physical_col = getattr(self._map, logical_col, logical_col)
            phys_cols.append(physical_col)
            placeholders.append("?")
            insert_params.append(self._dialect.format_value(val))

        sql = COMMON_SQL["insert"]["statement"].format(
            table=self._map.name,
            columns=", ".join(phys_cols),
            placeholders=", ".join(placeholders)
        )
        return CompiledQuery(sql, tuple(insert_params))