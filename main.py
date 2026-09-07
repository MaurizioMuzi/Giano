# main.py
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.manager import DefaultConnectionProvider
from processes.audit_logs import AuditLogsProcessor
# INTEGRAZIONE PRO: Importazione del nuovo modulo applicativo ex-COBOL
from processes.migration_tables import Migrationprocessor
from config.loader import ConfigurationError


def main():
    print("======================================================================")
    print("         INIZIALIZZAZIONE RUNTIME ENGINE INDUSTRIAL_PROCESSOR (PRO)   ")
    print("======================================================================\n")

    os.environ["EXTERNAL_DB_CONFIG_PATH"] = r"C:\Users\mmuzi\config\app_db_config.json"

    try:
        # Il costruttore del worker attiverà automaticamente il provider impostato nel JSON
        relational_worker = AuditLogsProcessor()

        print(f"[ORCHESTRATORE] Database rilevato da configurazione: {relational_worker.provider.upper()}")
        print("[ORCHESTRATORE] Avvio esecuzione Task Relazionali...")

        # 1. Esecuzione del processo di Audit standard
        relational_worker.run()

        # ---------------------------------------------------------------------
        # INTEGRAZIONE PRO: NUOVO MODULO APPLICATIVO EX-COBOL (MOMENTANEAMENTE COMMENTATO)
        # ---------------------------------------------------------------------
        print("\n[ORCHESTRATORE] Avvio esecuzione Task Migrazione Db2-SqlServer...")
        provvigioni_worker = Migrationprocessor()
        provvigioni_worker.run()
        # ---------------------------------------------------------------------

    except ConfigurationError as env_error:
        print(f"[ERR_ENVIRONMENT] Blocco critico di configurazione: {env_error}", file=sys.stderr)
    except Exception as general_error:
        print(f"[ERR_SYSTEM] Errore imprevisto nell'architettura: {general_error}", file=sys.stderr)
    finally:
        # Il provider chiude in sicurezza i canali attivi indipendentemente da quale worker ha girato
        DefaultConnectionProvider().close()
        print("[ORCHESTRATORE] Shutdown del sistema e rilascio socket completato.")


if __name__ == "__main__":
    main()