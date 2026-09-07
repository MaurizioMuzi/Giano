# core/base_process.py
from abc import ABC, abstractmethod
import sys
from database.manager import DefaultConnectionProvider
from core.query_builder import EntityModel, CompiledQuery, DB2Dialect, SQLServerDialect


class BaseProcessModel(ABC):
    def __init__(self, process_name: str):
        self.process_name = process_name
        self.connection, self.provider = DefaultConnectionProvider().get_connection()

        if self.provider == "db2":
            self.dialect = DB2Dialect()
        elif self.provider == "sqlserver":
            self.dialect = SQLServerDialect()
        else:
            raise NotImplementedError(f"Driver {self.provider} non supportato.")

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

    def execute_mutation(self, compiled_query: CompiledQuery) -> int:
        """Esegue UPDATE/DELETE reali su SQL Server e LOGGA unicamente su DB2 Mainframe."""
        if self.provider == "db2":
            print(f"   [LOG MAINFRAME - NO_WRITE] Rilevato canale DB2. Bloccata mutazione fisica.")
            print(f"   >> SQL MUTATION COMPILATO: {compiled_query.sql}")
            print(f"   >> PARAMETRI ASSOCIAZIONI: {compiled_query.params}")
            return 1  # Simula il successo dell'operazione ex-COBOL senza toccare il DB

        elif self.provider == "sqlserver":
            print(f"   >> [EXEC_REAL_MUTATION] SQL: {compiled_query.sql}")
            cursor = self.connection.cursor()
            try:
                cursor.execute(compiled_query.sql, compiled_query.params)
                return cursor.rowcount
            finally:
                cursor.close()

    def execute_bulk_insert(self, logical_table_key: str, data_list: list) -> int:
        """Esegue l'inserimento massivo reale su SQL Server e LOGGA unicamente su DB2."""
        if not data_list: return 0
        table_map = self.get_table_map(logical_table_key)

        logical_columns = list(data_list[0].keys())
        physical_columns = [getattr(table_map, col) for col in logical_columns]
        placeholders = ", ".join(["?" for _ in logical_columns])

        sql = f"INSERT INTO {table_map.name} ({', '.join(physical_columns)}) VALUES ({placeholders})"

        # Formattazione e preparazione dei pacchetti dati tramite Dialetto
        tuple_batch = []
        for row in data_list:
            tuple_batch.append(tuple(self.dialect.format_value(row.get(col)) for col in logical_columns))

        # INTERCETTAZIONE DI SICUREZZA PER DB2 - PRIMA DEL CORRUTTIBILE EXECUTE DEL DRIVER CLI
        if self.provider == "db2":
            print(f"   [LOG MAINFRAME - NO_WRITE] Rilevato canale DB2. Intercettata ed Evitata Scrittura Bulk.")
            print(f"   >> SQL BULK TARGET: {sql}")
            print(f"   >> MATRICE BUFFER CODA: {len(tuple_batch)} record normalizzati pronti nel tracciato.")
            print(f"   >> ESEMPIO TUPLA RECORD STRUTTURATO: {tuple_batch[0]}")
            return len(tuple_batch) # Simula l'avvenuto inserimento di tutti i record batch

        elif self.provider == "sqlserver":
            print(f"   >> [EXEC_REAL_BULK_INSERT] Tabella: {table_map.name} - Righe: {len(tuple_batch)}")
            cursor = self.connection.cursor()
            try:
                cursor.executemany(sql, tuple_batch)
                return cursor.rowcount
            finally:
                cursor.close()

    def run(self):
        try:
            self._execute_business_logic()
            if self.provider == "sqlserver":
                self.connection.commit()
                print("   >> [TRANSACTION] COMMIT reale eseguito su SQL Server.")
        except Exception as e:
            if self.provider == "sqlserver":
                self.connection.rollback()
                print("   >> [TRANSACTION] ROLLBACK eseguito su SQL Server.")
            raise e

    @abstractmethod
    def _execute_business_logic(self):
        pass