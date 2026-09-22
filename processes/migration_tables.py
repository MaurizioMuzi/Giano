# processes/migration_tables.py
import sys
import json
import os
from core.base_process import BaseProcessModel
from config.schema_mapper import SchemaMapper
from config.loader import ConfigLoader


class Migrationprocessor(BaseProcessModel):
    """
    Worker industriale dedicato alla migrazione fisica dei flussi telematici.
    Estrae da IBM DB2 e scrive in modalità Batch su SQL Server (FlussiTelematici),
    utilizzando il file di mappatura logica 'ADCTET11.json'[cite: 19].
    """

    def __init__(self):
        super().__init__(process_name="Migrazione_Massiva_ADCTET11_To_SQLServer")

        # Inizializzazione delle due connessioni distinte tramite il connettore centrale
        self.source_conn, self.provider_source = self._connect_explicit("db2_legacy")
        self.target_conn, self.provider_target = self._connect_explicit("sqlserver_prod")

    def _connect_explicit(self, connection_alias: str) -> tuple:
        """Apre un canale di rete esplicito basandosi sugli alias del file di configurazione."""
        config_path = os.environ.get("EXTERNAL_DB_CONFIG_PATH")
        with open(config_path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
            db_config = payload["connections"][connection_alias]

        provider = db_config.get("provider")

        if provider == "db2":
            import ibm_db
            conn_str = (f"DATABASE={db_config['database']};HOSTNAME={db_config['hostname']};"
                        f"PORT={db_config['port']};PROTOCOL=TCPIP;UID={db_config['username']};"
                        f"PWD={db_config['password']};")
            return ibm_db.pconnect(conn_str, "", ""), provider

        elif provider == "sqlserver":
            import pyodbc
            conn_str = (f"DRIVER={{{db_config['driver']}}};SERVER={db_config['server']};"
                        f"DATABASE={db_config['database']};UID={db_config['username']};"
                        f"PWD={db_config['password']};Encrypt=yes;TrustServerCertificate=yes;")
            return pyodbc.connect(conn_str), provider

        else:
            raise NotImplementedError(f"Provider '{provider}' non supportato.")

    def _execute_business_logic(self):
        import ibm_db

        # Caricamento delle mappe per la tabella ADCTET11
        meta_source = SchemaMapper.get_map("ADCTET11", self.provider_source)
        meta_target = SchemaMapper.get_map("ADCTET11", self.provider_target)

        logical_columns = list(meta_source._columns.keys())

        # Composizione SQL per DB2
        db2_physical_cols = [meta_source._columns[col] for col in logical_columns]
        db2_query = f"SELECT {', '.join(db2_physical_cols)} FROM {meta_source.name}"

        # Composizione SQL per SQL Server
        sql_physical_cols = [meta_target._columns[col] for col in logical_columns]
        placeholders = ", ".join(["?" for _ in logical_columns])
        sql_insert_query = f"INSERT INTO {meta_target.name} ({', '.join(sql_physical_cols)}) VALUES ({placeholders})"

        print(f"   [MIGRATION] Query di estrazione generata (DB2):\n               {db2_query}\n")
        print(f"   [MIGRATION] Query di inserimento generata (SQL Server):\n               {sql_insert_query}\n")

        # Innesco dei canali di streaming nativi
        stmt_source = ibm_db.exec_immediate(self.source_conn, db2_query)
        target_cursor = self.target_conn.cursor()

        BATCH_SIZE = 5000
        batch_data = []
        total_migrated = 0

        print("   [MIGRATION] Inizio streaming dei dati dal Mainframe...")

        raw_row = ibm_db.fetch_assoc(stmt_source)

        while raw_row:
            # Normalizzazione basata sullo schema 'ADCTET11.json'
            logical_row = meta_source.normalize(raw_row)

            row_tuple = tuple(logical_row.get(col) for col in logical_columns)
            batch_data.append(row_tuple)

            if len(batch_data) >= BATCH_SIZE:
                target_cursor.executemany(sql_insert_query, batch_data)
                self.target_conn.commit()
                total_migrated += len(batch_data)
                print(f"               [BATCH] Trasmessi con successo {total_migrated} record...")
                batch_data.clear()

            raw_row = ibm_db.fetch_assoc(stmt_source)

        if batch_data:
            target_cursor.executemany(sql_insert_query, batch_data)
            self.target_conn.commit()
            total_migrated += len(batch_data)
            batch_data.clear()

        print(f"\n   [MIGRATION] Operazione conclusa. Tabella copiata con successo!")
        print(f"   [MIGRATION] Totale record scritti nella tabella {meta_target.name}: {total_migrated}")

        target_cursor.close()


if __name__ == "__main__":
    os.environ["EXTERNAL_DB_CONFIG_PATH"] = r"C:\Users\maurizio.muzi\config\app_db_config.json"

    migration_worker = Migrationprocessor()
    migration_worker.run()