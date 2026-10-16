# main.py
import os
import sys
import json
import logging
from datetime import datetime

# Moduli di processo
from processes.preparazione_postalizzazione.context import PreparazionePostalizzazioneContext
from processes.preparazione_postalizzazione import PreparazionePostalizzazioneEngineProcessor

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.manager import DefaultConnectionProvider
from processes.formazione_avviso.processor import FormazioneAvvisoEngineProcessor
from processes.formazione_avviso.context import FormazioneAvvisoContext

from config.loader import ConfigurationError
from core.batch_logger import BatchLogger

ELABORAZIONI_VALIDE = [
    "gestione_avvisi",
    "PDCFOAVV", # formazione_avviso
    "PDCPOAVV", #preparazione_postalizzazione
    "PDCFORUO", #formazione_ruoli
    "PDCFRCRE", #firma_ruoli
    "PDCINCRE"  #invio_ruoli_AdER
]


def print_timestamp(message: str) -> None:
    """Stampa un messaggio a console con timestamp leggibile."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def parse_date_param(date_str):
    """Parsa la data accettando formati YYYY-MM-DD, DD.MM.YYYY e DD/MM/YYYY."""
    if not date_str or not str(date_str).strip():
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(date_str).strip(), fmt).date()
        except ValueError:
            pass
    print(f"[WARN] Formato data non valido: '{date_str}'. Formati accettati: YYYY-MM-DD, DD.MM.YYYY, DD/MM/YYYY", file=sys.stderr)
    return None


def resolve_log_level(level_name=None, default: int = logging.INFO) -> int:
    """Mappa il nome stringa del livello di log alla costante logging."""
    if not level_name:
        return default
    mapping = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARN": logging.WARNING,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR
    }
    return mapping.get(str(level_name).strip().upper(), default)


def load_config_parameters(config_path: str) -> dict:
    """
    Estrae i parametri operativi, di logging e di soglia commit dal JSON.
    NOTA: Il tipo elaborazione NON è più letto dal file JSON, ma da riga comandi (sys.argv).
    """
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        batch_params = cfg.get("batch_parameters", {})
        logging_params = cfg.get("logging", {})

        size_commit = cfg.get("size_commit") or batch_params.get("size_commit") or 1000
        raw_data = cfg.get("data_formazione_avviso") or batch_params.get("data_formazione_avviso")
        parsed_data = parse_date_param(raw_data) if raw_data else None

        return {
            "data_formazione_avviso": parsed_data,
            "size_commit": int(size_commit),
            "log_dir": logging_params.get("log_dir"),
            "log_console": logging_params.get("log_console"),
            "log_file": logging_params.get("log_file")
        }
    except Exception as err:
        print(f"[WARN] Impossibile recuperare i parametri dal file JSON: {err}", file=sys.stderr)
        return {}


def format_elapsed_time(seconds: float) -> str:
    """Formatta la durata di esecuzione in secondi, minuti o ore."""
    if seconds < 60:
        return f"{seconds:.2f} secondi"
    elif seconds < 3600:
        minuti = int(seconds // 60)
        sec = seconds % 60
        return f"{minuti} minuti e {sec:.2f} secondi"
    else:
        ore = int(seconds // 3600)
        minuti = int((seconds % 3600) // 60)
        sec = seconds % 60
        return f"{ore} ore, {minuti} minuti e {sec:.2f} secondi"


def esegui_formazione_avviso(effective_sk_date, config_params, dry_run: bool = False):
    """Inizializza ed esegue il processore di formazione avviso."""
    context = FormazioneAvvisoContext(sk_data_elab=effective_sk_date)
    context.size_commit = config_params.get("size_commit", 1000)

    BatchLogger.info("ORCHESTRATORE", f"SK-DATA-ELAB operativo: {context.sk_data_elab}")
    BatchLogger.info("ORCHESTRATORE", f"Soglia COMMIT parziale configurata: {context.size_commit} record")

    worker = FormazioneAvvisoEngineProcessor(
        context=context,
        dry_run=dry_run
    )
    worker.size_commit = context.size_commit
    worker.run()


def esegui_preparazione_postalizzazione(effective_sk_date, config_params, dry_run: bool = False):
    """Inizializza ed esegue il processore di preparazione postalizzazione."""
    context = PreparazionePostalizzazioneContext(sk_data_elab=effective_sk_date)
    context.size_commit = config_params.get("size_commit", 1000)

    BatchLogger.info("ORCHESTRATORE", f"SK-DATA-ELAB operativo: {context.sk_data_elab}")
    BatchLogger.info("ORCHESTRATORE", f"Soglia COMMIT parziale configurata: {context.size_commit} record")

    worker = PreparazionePostalizzazioneEngineProcessor(
        context=context,
        dry_run=dry_run
    )
    worker.size_commit = context.size_commit
    worker.run()


def main():
    start_time = datetime.now()
    print_timestamp("Inizio elaborazione")

    # 1. Verifica presenza dell'argomento da riga di comando
    if len(sys.argv) < 2:
        print("[PARAMETRI] Errore: Numero insufficiente di parametri.", file=sys.stderr)
        print("Utilizzo: python main.py <operation>", file=sys.stderr)
        print(f"Operazioni ammesse: {', '.join(ELABORAZIONI_VALIDE)}", file=sys.stderr)
        sys.exit(1)

    # 2. Estrazione operazione ed eventuali parametri
    campi = sys.argv[1].split(';')
    operation = campi[0].strip()
    extra_param = campi[1].strip() if len(campi) > 1 else None

    # 3. Validazione
    if operation not in ELABORAZIONI_VALIDE:
        print(f"[VALIDAZIONE] Operazione '{operation}' non valida!", file=sys.stderr)
        print(f"Scegli tra: {', '.join(ELABORAZIONI_VALIDE)}", file=sys.stderr)
        sys.exit(1)

    # 4. Configurazione e lettura parametri JSON
    config_path = os.environ.get("EXTERNAL_DB_CONFIG_PATH") or r"C:\Users\maurizio.muzi\config\app_db_config.json"
    os.environ["EXTERNAL_DB_CONFIG_PATH"] = config_path

    config_params = load_config_parameters(config_path)

    log_dir = config_params.get("log_dir") or "logs"
    console_lvl = resolve_log_level(config_params.get("log_console"), logging.INFO)
    file_lvl = resolve_log_level(config_params.get("log_file"), logging.DEBUG)

    # 5. SETUP DEL LOGGER (È la PRIMA chiamata a BatchLogger in assoluto)
    BatchLogger.setup_logger(
        log_dir=log_dir,
        console_level=console_lvl,
        file_level=file_lvl,
        log_prefix=operation
    )

    # 6. Da qui in poi qualsiasi log viene scritto nel file <operation>_<timestamp>.txt
    BatchLogger.info("ORCHESTRATORE", f"Inizio elaborazione: {start_time}")
    BatchLogger.info("ORCHESTRATORE", f"Argomenti passati: {sys.argv}")
    BatchLogger.info("ORCHESTRATORE", f"Operazione: {operation}")
    if extra_param:
        BatchLogger.info("ORCHESTRATORE", f"Parametro extra: {extra_param}")

    effective_sk_date = config_params.get("data_formazione_avviso")
    BatchLogger.info("ORCHESTRATORE", f"Target di Elaborazione Selezionato: [{operation.upper()}]")

    exit_code = 0
    try:
        if operation == "PDCFOAVV":
            BatchLogger.info("Blocco FORMAZIONE-AVVISO", "Avvio fase di Formazione Avviso...")
            esegui_formazione_avviso(effective_sk_date, config_params)

        elif operation == "postalizzazione":
            BatchLogger.info("Blocco POSTALIZZAZIONE", "Avvio fase di Postalizzazione...")
            esegui_preparazione_postalizzazione(effective_sk_date, config_params)

        elif operation == "formazione_ruoli":
            BatchLogger.info("Blocco FORMAZIONE-RUOLI", "Avvio fase di Formazione Ruoli...")

        elif operation == "firma_ruoli":
            BatchLogger.info("Blocco FIRMA-RUOLI", "Avvio fase di Firma Ruoli...")

        elif operation == "invio_ruoli_AdER":
            BatchLogger.info("Blocco INVIO-ADER", "Avvio fase di Invio Ruoli ad Agenzia delle Entrate-Riscossione...")

        elif operation == "gestione_avvisi":
            BatchLogger.info("WORKFLOW-COMPLETO", "Esecuzione sequenziale di tutte le fasi batch...")

            BatchLogger.info("WORKFLOW-COMPLETO", ">> [1/5] Formazione Avviso")
            esegui_formazione_avviso(effective_sk_date, config_params)

            BatchLogger.info("WORKFLOW-COMPLETO", ">> [2/5] Postalizzazione")
            esegui_preparazione_postalizzazione(effective_sk_date, config_params)

            BatchLogger.info("WORKFLOW-COMPLETO", ">> [3/5] Formazione Ruoli")
            BatchLogger.info("WORKFLOW-COMPLETO", ">> [4/5] Firma Ruoli")
            BatchLogger.info("WORKFLOW-COMPLETO", ">> [5/5] Invio Ruoli AdER")

    except ConfigurationError as env_error:
        BatchLogger.error("ERR_ENVIRONMENT", str(env_error))
        exit_code = 2
    except Exception as general_error:
        BatchLogger.error("ERR_SYSTEM", str(general_error))
        exit_code = 1
    finally:
        DefaultConnectionProvider().close()

    # Timestamp di fine e calcolo tempo totale
    end_time = datetime.now()
    elapsed_time = (end_time - start_time).total_seconds()
    tempo_formattato = format_elapsed_time(elapsed_time)

    print_timestamp("Fine elaborazione")
    print(f"Tempo totale: {tempo_formattato}")
    BatchLogger.info("STATISTICHE", f"Tempo totale di esecuzione: {tempo_formattato}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()