# core/base_process.py
from abc import ABC, abstractmethod
import sys
from database.manager import DefaultConnectionProvider
from core.query_builder import EntityModel, CompiledQuery, DB2Dialect, SQLServerDialect


class BaseProcessModel(ABC):
    def __init__(self, process_name: str, dry_run: bool = False):
        """
        Inizializza il processor.

        :param process_name: Identificativo del processo batch
        :param dry_run: Se True, blocca le mutazioni fisiche su DB2 e si limita a loggare
        """
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
        """Restituisce l'istanza TableMap risolta dal provider centrale."""
        return DefaultConnectionProvider().get_table_map(logical_table_key)

    def dataset(self, logical_table_key: str) -> EntityModel:
        table_map = self.get_table_map(logical_table_key)
        return EntityModel(table_map, self.dialect)

    def fetch(self, compiled_query: CompiledQuery) -> list:
        if not isinstance(compiled_query, CompiledQuery):
            raise TypeError("Richiesto oggetto CompiledQuery.")

        print(f"   >> [EXEC_SELECT] SQL: {compiled_query.sql}")
        if self.provider == "sqlserver":
            cursor = self.connection.cursor()
            try:
                cursor.execute(compiled_query.sql, compiled_query.params)
                columns = [column[0] for column in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
            finally:
                cursor.close()

        elif self.provider == "db2":
            import ibm_db
            stmt = ibm_db.prepare(self.connection, compiled_query.sql)
            if not ibm_db.execute(stmt, compiled_query.params):
                raise RuntimeError(f"Errore DB2: {ibm_db.stmt_errormsg()}")
            rows = []
            raw_row = ibm_db.fetch_assoc(stmt)
            while raw_row:
                rows.append(raw_row)
                raw_row = ibm_db.fetch_assoc(stmt)
            return rows

    def cursor_stream(self, compiled_query: CompiledQuery, buffer_size: int = 1000):
        print(f"   >> [STREAM_CURSOR_OPEN] SQL: {compiled_query.sql}")

        if self.provider == "sqlserver":
            cursor = self.connection.cursor()
            cursor.execute(compiled_query.sql, compiled_query.params)
            while True:
                rows = cursor.fetchmany(buffer_size)
                if not rows: break
                columns = [column[0] for column in cursor.description]
                yield [dict(zip(columns, row)) for row in rows]
            cursor.close()

        elif self.provider == "db2":
            import ibm_db
            stmt = ibm_db.prepare(self.connection, compiled_query.sql)
            if not ibm_db.execute(stmt, compiled_query.params):
                raise RuntimeError(f"Errore Cursore DB2: {ibm_db.stmt_errormsg()}")

            chunk = []
            raw_row = ibm_db.fetch_assoc(stmt)
            while raw_row:
                chunk.append(raw_row)
                if len(chunk) >= buffer_size:
                    yield chunk
                    chunk = []
                raw_row = ibm_db.fetch_assoc(stmt)
            if chunk:
                yield chunk

    def simulate_mutation(self, compiled_query: CompiledQuery) -> int:
        """
        MODALITÀ SIMULATA (DRY-RUN):
        Logga l'istruzione ed evita qualsiasi scrittura su DB2 Mainframe.
        """
        print(f"   [LOG MAINFRAME - SIMULATE_ONLY] Blocco mutazione fisica richiesto.")
        print(f"   >> SQL MUTATION COMPILATO: {compiled_query.sql}")
        print(f"   >> PARAMETRI ASSOCIAZIONI: {compiled_query.params}")
        return 1

    def execute_real_mutation(self, compiled_query: CompiledQuery) -> int:
        """
        MODALITÀ REALE (WRITE-ENABLED):
        Esegue fisicamente l'UPDATE o DELETE sia su DB2 che su SQL Server.
        """
        print(f"   >> [EXEC_REAL_MUTATION] [{self.provider.upper()}] SQL: {compiled_query.sql}")
        print(f"   >> PARAMETRI: {compiled_query.params}")

        if self.provider == "db2":
            import ibm_db
            stmt = ibm_db.prepare(self.connection, compiled_query.sql)
            if not ibm_db.execute(stmt, compiled_query.params):
                raise RuntimeError(f"Errore UPDATE/DELETE DB2: {ibm_db.stmt_errormsg()}")
            return ibm_db.num_rows(stmt)

        elif self.provider == "sqlserver":
            cursor = self.connection.cursor()
            try:
                cursor.execute(compiled_query.sql, compiled_query.params)
                return cursor.rowcount
            finally:
                cursor.close()

    def execute_mutation(self, compiled_query: CompiledQuery) -> int:
        """
        Dispatcher unificato:
        Se self.dry_run è True (o se esplicitamente impostato), simula su DB2.
        Altrimenti esegue la mutazione reale su entrambi i database.
        """
        if self.dry_run and self.provider == "db2":
            return self.simulate_mutation(compiled_query)
        return self.execute_real_mutation(compiled_query)

    def execute_bulk_insert(self, logical_table_key: str, data_list: list, force_simulate: bool = False) -> int:
        """Esegue bulk insert reale o simulato in base alla configurazione."""
        if not data_list: return 0
        table_map = self.get_table_map(logical_table_key)

        logical_columns = list(data_list[0].keys())
        physical_columns = [getattr(table_map, col) for col in logical_columns]
        placeholders = ", ".join(["?" for _ in logical_columns])

        sql = f"INSERT INTO {table_map.name} ({', '.join(physical_columns)}) VALUES ({placeholders})"

        tuple_batch = []
        for row in data_list:
            tuple_batch.append(tuple(self.dialect.format_value(row.get(col)) for col in logical_columns))

        if (self.dry_run or force_simulate) and self.provider == "db2":
            print(f"   [LOG MAINFRAME - NO_WRITE] Simulazione bulk insert DB2.")
            print(f"   >> SQL BULK TARGET: {sql}")
            print(f"   >> RECORD BUFFER: {len(tuple_batch)}")
            return len(tuple_batch)

        if self.provider == "db2":
            import ibm_db
            stmt = ibm_db.prepare(self.connection, sql)
            count = 0
            for item in tuple_batch:
                if not ibm_db.execute(stmt, item):
                    raise RuntimeError(f"Errore Bulk DB2: {ibm_db.stmt_errormsg()}")
                count += 1
            return count

        elif self.provider == "sqlserver":
            print(f"   >> [EXEC_REAL_BULK_INSERT] Tabella: {table_map.name} - Righe: {len(tuple_batch)}")
            cursor = self.connection.cursor()
            try:
                cursor.executemany(sql, tuple_batch)
                return cursor.rowcount
            finally:
                cursor.close()

    def run(self):
        """Esecuzione orchestrata con gestione atomica del COMMIT / ROLLBACK su entrambi i DB."""
        try:
            self._execute_business_logic()

            if self.provider == "sqlserver":
                self.connection.commit()
                print("   >> [TRANSACTION] COMMIT reale eseguito su SQL Server.")
            elif self.provider == "db2":
                if not self.dry_run:
                    import ibm_db
                    ibm_db.commit(self.connection)
                    print("   >> [TRANSACTION] COMMIT reale eseguito su DB2.")
                else:
                    print("   >> [TRANSACTION] Modalità DRY-RUN attiva: nessun commit inviato a DB2.")

        except Exception as e:
            if self.provider == "sqlserver":
                self.connection.rollback()
                print("   >> [TRANSACTION] ROLLBACK eseguito su SQL Server.")
            elif self.provider == "db2":
                import ibm_db
                ibm_db.rollback(self.connection)
                print("   >> [TRANSACTION] ROLLBACK eseguito su DB2.")
            raise e

    @abstractmethod
    def _execute_business_logic(self):
        pass