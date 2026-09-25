# core/base_process.py
from abc import ABC, abstractmethod
import sys
from database.manager import DefaultConnectionProvider
from core.query_builder import EntityModel, CompiledQuery, DB2Dialect, SQLServerDialect
from core.batch_logger import BatchLogger


class BaseProcessModel(ABC):
    def __init__(self, process_name: str, dry_run: bool = False):
        self.process_name = process_name
        self.dry_run = dry_run
        self.connection, self.provider = DefaultConnectionProvider().get_connection()

        if self.provider == "db2":
            self.dialect = DB2Dialect()
        elif self.provider == "sqlserver":
            self.dialect = SQLServerDialect()
        else:
            raise NotImplementedError(f"Driver {self.provider} non supportato.")

    def repository(self, logical_table_key: str) -> "GenericRepository":
        from core.generic_repository import GenericRepository
        return GenericRepository(self, logical_table_key)

    def get_table_map(self, logical_table_key: str):
        return DefaultConnectionProvider().get_table_map(logical_table_key)

    def dataset(self, logical_table_key: str) -> EntityModel:
        table_map = self.get_table_map(logical_table_key)
        return EntityModel(table_map, self.dialect)

    def join_dataset(self, left_table_key: str, right_table_key: str, alias_self: str = "A", alias_target: str = "B") -> EntityModel:
        left_map = self.get_table_map(left_table_key)
        right_map = self.get_table_map(right_table_key)
        return EntityModel(left_map, self.dialect).join(right_map, alias_self=alias_self, alias_target=alias_target)

    def fetch(self, compiled_query: CompiledQuery, depth: int = 2) -> list:
        if not isinstance(compiled_query, CompiledQuery):
            raise TypeError("Richiesto oggetto CompiledQuery.")

        BatchLogger.debug("DB-SELECT", f"SQL: {compiled_query.sql}", depth=depth)
        BatchLogger.debug("PARAMS", str(compiled_query.params), depth=depth + 1)

        rows = []
        if self.provider == "sqlserver":
            cursor = self.connection.cursor()
            try:
                cursor.execute(compiled_query.sql, compiled_query.params)
                columns = [column[0] for column in cursor.description]
                rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            finally:
                cursor.close()

        elif self.provider == "db2":
            import ibm_db
            stmt = ibm_db.prepare(self.connection, compiled_query.sql)
            if not ibm_db.execute(stmt, compiled_query.params):
                err_msg = ibm_db.stmt_errormsg()
                BatchLogger.error("DB-ERROR", f"Errore DB2 SELECT: {err_msg}", depth=depth + 1, is_last=True)
                raise RuntimeError(f"Errore DB2: {err_msg}")
            raw_row = ibm_db.fetch_assoc(stmt)
            while raw_row:
                rows.append(raw_row)
                raw_row = ibm_db.fetch_assoc(stmt)

        BatchLogger.debug("RESULT", f"Estratte {len(rows)} riga/righe", depth=depth + 1, is_last=True)
        return rows

    def cursor_stream(self, compiled_query: CompiledQuery, buffer_size: int = 1000, depth: int = 2):
        BatchLogger.debug("DB-CURSOR-OPEN", f"SQL: {compiled_query.sql}", depth=depth)
        BatchLogger.debug("PARAMS", str(compiled_query.params), depth=depth + 1)

        totale_letti = 0
        if self.provider == "sqlserver":
            cursor = self.connection.cursor()
            try:
                cursor.execute(compiled_query.sql, compiled_query.params)
                while True:
                    rows = cursor.fetchmany(buffer_size)
                    if not rows:
                        break
                    totale_letti += len(rows)
                    columns = [column[0] for column in cursor.description]
                    yield [dict(zip(columns, row)) for row in rows]
            finally:
                cursor.close()
                BatchLogger.debug("RESULT", f"Cursore chiuso. Record processati: {totale_letti}", depth=depth + 1, is_last=True)

        elif self.provider == "db2":
            import ibm_db
            stmt = ibm_db.prepare(self.connection, compiled_query.sql)
            if not ibm_db.execute(stmt, compiled_query.params):
                err_msg = ibm_db.stmt_errormsg()
                BatchLogger.error("DB-ERROR", f"Errore apertura cursore DB2: {err_msg}", depth=depth + 1, is_last=True)
                raise RuntimeError(f"Errore Cursore DB2: {err_msg}")

            try:
                chunk = []
                raw_row = ibm_db.fetch_assoc(stmt)
                while raw_row:
                    totale_letti += 1
                    chunk.append(raw_row)
                    if len(chunk) >= buffer_size:
                        yield chunk
                        chunk = []
                    raw_row = ibm_db.fetch_assoc(stmt)
                if chunk:
                    yield chunk
            finally:
                ibm_db.free_result(stmt)
                ibm_db.free_stmt(stmt)
                BatchLogger.debug("RESULT", f"Cursore DB2 chiuso. Record totali letti nello stream: {totale_letti}", depth=depth + 1, is_last=True)

    def simulate_mutation(self, compiled_query: CompiledQuery, depth: int = 2) -> int:
        BatchLogger.warn("DRY-RUN", "Simulazione mutazione: nessuna scrittura su DB2", depth=depth)
        BatchLogger.debug("DB-MUTATION", f"SQL: {compiled_query.sql}", depth=depth + 1)
        BatchLogger.debug("PARAMS", str(compiled_query.params), depth=depth + 2)
        BatchLogger.debug("RESULT", "Simulati: 1 record impattato", depth=depth + 2, is_last=True)
        return 1

    def execute_real_mutation(self, compiled_query: CompiledQuery, depth: int = 2) -> int:
        BatchLogger.debug("DB-MUTATION", f"[{self.provider.upper()}] SQL: {compiled_query.sql}", depth=depth)
        BatchLogger.debug("PARAMS", str(compiled_query.params), depth=depth + 1)

        affected = 0
        if self.provider == "db2":
            import ibm_db
            stmt = ibm_db.prepare(self.connection, compiled_query.sql)
            if not ibm_db.execute(stmt, compiled_query.params):
                err_msg = ibm_db.stmt_errormsg()
                BatchLogger.error("DB-ERROR", f"Errore mutazione DB2: {err_msg}", depth=depth + 1, is_last=True)
                raise RuntimeError(f"Errore UPDATE/DELETE DB2: {err_msg}")
            affected = ibm_db.num_rows(stmt)

        elif self.provider == "sqlserver":
            cursor = self.connection.cursor()
            try:
                cursor.execute(compiled_query.sql, compiled_query.params)
                affected = cursor.rowcount
            finally:
                cursor.close()

        BatchLogger.debug("RESULT", f"Righe impattate: {affected}", depth=depth + 1, is_last=True)
        return affected

    def execute_mutation(self, compiled_query: CompiledQuery, depth: int = 2) -> int:
        if self.dry_run and self.provider == "db2":
            return self.simulate_mutation(compiled_query, depth=depth)
        return self.execute_real_mutation(compiled_query, depth=depth)

    def execute_bulk_insert(self, logical_table_key: str, data_list: list, force_simulate: bool = False, depth: int = 2) -> int:
        if not data_list:
            return 0
        table_map = self.get_table_map(logical_table_key)

        logical_columns = list(data_list[0].keys())
        physical_columns = [getattr(table_map, col) for col in logical_columns]
        placeholders = ", ".join(["?" for _ in logical_columns])

        sql = f"INSERT INTO {table_map.name} ({', '.join(physical_columns)}) VALUES ({placeholders})"

        tuple_batch = []
        for row in data_list:
            tuple_batch.append(tuple(self.dialect.format_value(row.get(col)) for col in logical_columns))

        BatchLogger.debug("DB-BULK-INSERT", f"Target: {table_map.name} | Batch size: {len(tuple_batch)}", depth=depth)
        BatchLogger.debug("SQL", sql, depth=depth + 1)

        if (self.dry_run or force_simulate) and self.provider == "db2":
            BatchLogger.warn("DRY-RUN", "Simulazione Bulk Insert su DB2 (nessuna scrittura fisica)", depth=depth + 1, is_last=True)
            return len(tuple_batch)

        if self.provider == "db2":
            import ibm_db
            stmt = ibm_db.prepare(self.connection, sql)
            count = 0
            for item in tuple_batch:
                if not ibm_db.execute(stmt, item):
                    err_msg = ibm_db.stmt_errormsg()
                    BatchLogger.error("DB-ERROR", f"Errore Bulk DB2: {err_msg}", depth=depth + 1, is_last=True)
                    raise RuntimeError(f"Errore Bulk DB2: {err_msg}")
                count += 1
            BatchLogger.debug("RESULT", f"Bulk insert completato. Righe inserite: {count}", depth=depth + 1, is_last=True)
            return count

        elif self.provider == "sqlserver":
            cursor = self.connection.cursor()
            try:
                cursor.executemany(sql, tuple_batch)
                BatchLogger.debug("RESULT", f"Bulk insert completato. Righe inserite: {cursor.rowcount}", depth=depth + 1, is_last=True)
                return cursor.rowcount
            finally:
                cursor.close()

    def run(self):
        try:
            self._execute_business_logic()

            if self.provider == "sqlserver":
                self.connection.commit()
                BatchLogger.info("TRANSACTION", "COMMIT consolidato con successo su SQL Server.", depth=0)
            elif self.provider == "db2":
                if not self.dry_run:
                    import ibm_db
                    ibm_db.commit(self.connection)
                    BatchLogger.info("TRANSACTION", "COMMIT reale consolidato con successo su DB2.", depth=0)
                else:
                    BatchLogger.warn("TRANSACTION", "Modalità DRY-RUN attiva: nessun commit inviato a DB2.", depth=0)

        except Exception as e:
            if self.provider == "sqlserver":
                self.connection.rollback()
                BatchLogger.error("TRANSACTION", "ROLLBACK eseguito su SQL Server a seguito di errore.", depth=0)
            elif self.provider == "db2":
                import ibm_db
                ibm_db.rollback(self.connection)
                BatchLogger.error("TRANSACTION", "ROLLBACK eseguito su DB2 a seguito di errore.", depth=0)
            raise e

    def commit(self):
        """Esegue il commit esplicito della transazione corrente in base al provider."""
        if self.provider == "sqlserver":
            self.connection.commit()
            BatchLogger.info("TRANSACTION", "COMMIT parziale consolidato su SQL Server.", depth=1)
        elif self.provider == "db2":
            if not self.dry_run:
                import ibm_db
                ibm_db.commit(self.connection)
                BatchLogger.info("TRANSACTION", "COMMIT parziale consolidato su DB2.", depth=1)

    def rollback(self):
        """Esegue il rollback della transazione corrente in base al provider."""
        if self.provider == "sqlserver":
            self.connection.rollback()
            BatchLogger.error("TRANSACTION", "ROLLBACK parziale eseguito su SQL Server.", depth=1)
        elif self.provider == "db2":
            import ibm_db
            ibm_db.rollback(self.connection)
            BatchLogger.error("TRANSACTION", "ROLLBACK parziale eseguito su DB2.", depth=1)

    @abstractmethod
    def _execute_business_logic(self):
        pass