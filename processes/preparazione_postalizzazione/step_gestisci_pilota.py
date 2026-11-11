# processes/preparazione_postalizzazione/step_gestisci_pilota.py
from core.batch_logger import BatchLogger
from typing import List, Any, Optional
from .context import PreparazionePostalizzazioneContext

# Progressivi di censimento (es. per la gestione 1 - aziende, per la gestione 2 - artigiani, ...)
CATEGORIE_GESTIONE = {
    1:  "Gestione Aziende con lavoratori dipendenti",
    2:  "Gestione Artigiani",
    3:  "Gestione Commercianti",
    4:  "Gestione Agricola - Datori di lavoro",
    5:  "Gestione Agricola - Lavoratori Autonomi ed Associati",
    6:  "Gestione Separata: Committenti/Associati",
    7:  "Gestione Separata: Liberi Professionisti",
    8:  "Gestione Pescatori Autonomi - Gestione Redec",
    9:  "Gestione Aziende con lavoratori dipendenti - DE",
    10:  "Gestione Artigiani - DE",
    11:  "Gestione Commercianti - DE",
    12:  "Gestione Agricola - Datori di lavoro - DE",
    13:  "Gestione Agricola - Lavoratori Autonomi ed Associati - DE",
    14:  "Gestione Separata: Committenti/Associati - DE",
    15:  "Gestione Separata: Liberi Professionisti - DE",
    16:  "Gestione Pescatori Autonomi - Gestione Redec - DE",
    17:  "Gestione Ex-Enpals Lavoratori dello spettacolo - Sportivi Professionisti",
    18:  "Gestione Ex-Enpals Lavoratori dello spettacolo - Sportivi Professionisti - DE",
    19:  "Gestione Dipendenti Pubblici",
    20:  "Gestione Dipendenti Pubblici - DE",
    21:  "Indebiti da Prestazioni a sostegno del Reddito - Indebiti da Pensioni",
    22:  "Indebiti da Prestazioni a sostegno del Reddito - Indebiti da Pensioni - DE",
    23:  "Gestione Lavoratori Domestici",
    24:  "Gestione Lavoratori Domestici - DE",
    25:  "Gestione Spese Legali",
    26:  "Gestione Spese Legali - DE",
    27:  "Gestione VMC",
    28:  "Gestione VMC - DE"
}

class GestiscePilota:
    def __init__(self, engine):
        self.engine = engine

    def execute(self, ctx: PreparazionePostalizzazioneContext, depth:int=1) -> None:
        BatchLogger.info("ACCEDI-PILOTA", "Verifica ultima elaborazione (ADCAVV11)", depth=depth)
        tavv11_map = self.engine.get_table_map("ADCAVV11")

        try:
            # CURSORE 11: estrazione del record con NUMELAB più alto (ultima elaborazione)
            rows = self._db_fetch_t11(depth = depth + 1)
            if not rows:
            # Rif. COBOL: IF PILOTA-KO -> TABELLA PILOTA VUOTA
                BatchLogger.error(
                    "PILOTA-KO",
                    "SEGNALAZIONE: POSTALIZZAZIONE NON CONSENTITA - TABELLA PILOTA VUOTA",
                    depth=depth+1, is_last=True
                )
                raise RuntimeError("[COBOL_EXCEPTION] POSTALIZZAZIONE NON CONSENTITA: TABELLA PILOTA VUOTA")

            row = tavv11_map.normalize(rows[0])
            ctx.ws_num_elab = row.get["numelab"]

            if ctx.fstfor == "3":
                '''
                NUMELAB si incrementa solo se FSTFOR (pre-update) era '3' -> nuovo giro di elaborazione
                Se non è un nuovo giro ('3'), NUMELAB resta quello estratto
                '''
                ctx.ws_num_elab += 1

                BatchLogger.debug(
                    "NUMELAB-CALCOLATO",
                    f"NUMELAB ={ctx.ws_num_elab} | FSTFOR ={ctx.fstfor} ",
                    depth=1
                )
                # Inserimento di un record in ADCAVV11 per ognuno dei progressivi censimento
                BatchLogger.info(
                    "INSERT-PILOTA",
                    f"Avvio inserimento per {len(CATEGORIE_GESTIONE)} categorie | NUMELAB={ctx.ws_num_elab}",
                    depth=1
                )
                for prgcens in CATEGORIE_GESTIONE:
                    self._db_insert_t11(ctx, prgcens, depth=depth+1)

                BatchLogger.info(
                    "INSERT-PILOTA-COMPLETATO",
                    f"Inserite {len(CATEGORIE_GESTIONE)} righe in ADCAVV11 (NUMELAB={ctx.ws_num_elab})",
                    depth=depth+1
                )
                BatchLogger.separator(depth=0)
        except Exception as err:
            BatchLogger.error(
                "ACCEDI-PILOTA",
                f"Errore critico durante la gestione su ADCAVV11: {err}",
                depth=0
            )
            ctx.indic_errore = "X"
            try:
                self.engine.rollback()
                BatchLogger.warn("ACCEDI-PILOTAI", "Rollback transazionale eseguito a fronte del fallimento", depth=0)
            except Exception as rollback_err:
                BatchLogger.error("ACCEDI-PILOTA", f"Fallito il rollback: {rollback_err}", depth=0)
            raise

    # =========================================================================
    # ACCESSI AL DATABASE (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_fetch_t11(self, depth: int) -> Optional[List[Any]]:
        """Accesso atomico DB: recupera il record da elaborare da ADCAVV11."""
        query = (
            self.engine.dataset("ADCAVV11")
            .select("prgcens", "numelab", "dcon", "dinifor", "dfinfor", "cstacom", "cstaavv", "tms_finform",
                    "tms_finlot", "tms_inveq")
            .order_by_desc("numelab")
            .limit(1)
            .with_uncommitted_read()
            .compile_select()
        )
        try:
            return self.engine.fetch(query, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-T11-ERR",
                f"Errore DB durante la SELECT su ADCAVV11: {err}",
                depth=depth
            )
            return []


    def _db_insert_t11(self, ctx,prgcens: int, depth: int) -> int:
        """Rif. COBOL: INSERT-PILOTA-1 .. INSERT-PILOTA-30 (PRGCENS diverso)"""
        ins_avv11 = self.engine.dataset("ADCAVV11").compile_insert({
            "prgcens": prgcens,
            "numelab": ctx.ws_num_elab, #NUMELAB incrementato
            "dcon": ctx.dcon,
            "dinifor": ctx.dinifor,
            "dfinfor": ctx.dfinfor,
            "cstacom": "0",
            "cstaavv": "0",
            "tms_finform": "0001-01-01-00.00.00.000000",
            "tms_finlot": "0001-01-01-00.00.00.000000",
            "tms_inveq": "0001-01-01-00.00.00.000000"
        })

        try:
            righe = self.engine.execute_mutation(ins_avv11, depth=depth)

            BatchLogger.debug(  # <-- log di dettaglio, uno per ogni chiamata
                "INSERT-ADCAVV11",
                f"Inserita riga PRGCENS={prgcens} ({CATEGORIE_GESTIONE[prgcens]}) NUMELAB={ctx.ws_num_elab}. Righe: {righe}",
                depth=depth
            )
            return righe
        except Exception as err:
            BatchLogger.error(
                "INSERT-ADCAVV11",
                f"Fallito inserimento PRGCENS={prgcens} ({CATEGORIE_GESTIONE[prgcens]}) NUMELAB={ctx.ws_num_elab}: {err}",
                depth=depth)
            raise
