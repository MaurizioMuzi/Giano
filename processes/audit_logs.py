# processes/audit_logs.py
from datetime import date, datetime
from core.base_process import BaseProcessModel
from core.query_builder import CompiledQuery


class AuditLogsProcessor(BaseProcessModel):
    """
    Script Applicativo Enterprise V3 PRO.
    Risolve le mappe sfruttando le primitive ereditate dalla classe base astratta,
    prevenendo errori di mancata risoluzione dei Name/Attribute.
    """

    def __init__(self):
        super().__init__(process_name="Reingegnerizzazione_Cobol_Massivi_PRO")

    def _execute_business_logic(self):
        # Risoluzione ereditata nativamente dalla classe base
        agenda_map = self.get_table_map("agenda_lavori")
        flussi_map = self.get_table_map("flussi_telematici")

        print("\n--- SCENARIO 1: STRUTTURA CURSORE SEQUENZIALE MASSIVO (MIMIC COBOL) ---")
        query_stream = (self.dataset("agenda_lavori")
                        .select("sede", "zona")
                        .with_uncommitted_read()  # Genera WITH UR su DB2 o (NOLOCK) su SQL Server
                        .compile_select())

        # Consuma il cursore a blocchi di 2000 alla volta, preservando la memoria
        for chunk in self.cursor_stream(query_stream, buffer_size=2000):
            print(f"   [CURSORE APERTO] Estratto blocco di {len(chunk)} record.")
            break  # Interrompiamo subito l'esempio per il test di convalidazione

        print("\n--- SCENARIO 2: INSERT MASSIVA AD ALTE PRESTAZIONI (BULK INSERT) ---")
        # COMPILAZIONE COMPLETA DELLE CHIAVI LOGICHE COMPRESO IL TIMESTAMP DI CREAZIONE (tmp_cre)
        dataset_nuovi_flussi = [
            {
                "ambito": 10,
                "tipo_flusso": "AA",
                "anno_flusso": 2026,
                "num_flusso": "F_1",
                "data_rif": date(2026, 1, 1),
                "data_cre": date(2026, 1, 1),
                "rel_soft": "V1.0",
                "flg_euro": "E",
                "flg_ric": "N",
                "anno_rif_invio": 2026,
                "num_file_invio": 1,
                "tmp_cre": datetime(2026, 7, 7, 12, 0, 0), # Risolve l'errore SQL0407N sulla colonna HCREFIL
                "tot_r5a": 0, "tot_r5b": 0, "tot_r7a": 0, "tot_r7b": 0, "tot_r7c": 0,
                "tot_r7d": 0, "tot_r7e": 0, "tot_r7f": 0, "tot_r7g": 0, "tot_r5z": 0,
                "tot_rec": 0, "tot_imposta": 0.0, "tot_sanzioni": 0.0, "tot_interessi": 0.0,
                "tot_altro": 0.0, "tot_aggio_ant": 0.0, "tot_aggio": 0.0, "tot_arrot": 0.0,
                "tot_carico": 0.0, "tot_r7l": 0
            },
            {
                "ambito": 10,
                "tipo_flusso": "BB",
                "anno_flusso": 2026,
                "num_flusso": "F_2",
                "data_rif": date(2026, 1, 2),
                "data_cre": date(2026, 1, 2),
                "rel_soft": "V1.0",
                "flg_euro": "E",
                "flg_ric": "N",
                "anno_rif_invio": 2026,
                "num_file_invio": 2,
                "tmp_cre": datetime(2026, 7, 7, 12, 0, 0), # Risolve l'errore SQL0407N sulla colonna HCREFIL
                "tot_r5a": 0, "tot_r5b": 0, "tot_r7a": 0, "tot_r7b": 0, "tot_r7c": 0,
                "tot_r7d": 0, "tot_r7e": 0, "tot_r7f": 0, "tot_r7g": 0, "tot_r5z": 0,
                "tot_rec": 0, "tot_imposta": 0.0, "tot_sanzioni": 0.0, "tot_interessi": 0.0,
                "tot_altro": 0.0, "tot_aggio_ant": 0.0, "tot_aggio": 0.0, "tot_arrot": 0.0,
                "tot_carico": 0.0, "tot_r7l": 0
            }
        ]
        inseriti = self.execute_bulk_insert("flussi_telematici", dataset_nuovi_flussi)
        print(f"   [BULK] Scrittura massiva completata. Record inseriti: {inseriti}")

        print("\n--- SCENARIO 3: UPDATE MASSIVO CON JOIN TRA TABELLE (CORRELATO) ---")
        join_cond = f"s.{flussi_map.ambito} = t.{agenda_map.sede}"
        filter_cond = f"t.{agenda_map.zona} = 'NORD'"

        sql_update = self.dialect.compile_update_joined(
            target_table=agenda_map.name,
            target_field=agenda_map.areaCom,
            source_table=flussi_map.name,
            source_field=flussi_map.tipo_flusso,
            join_condition=join_cond,
            filter_condition=filter_cond
        )

        modificati = self.execute_mutation(CompiledQuery(sql_update, ()))
        print(f"   [UPDATE MASSIVA] Righe aggiornate dall'unione dialettale: {modificati}")

        print("\n--- SCENARIO 4: DELETE MASSIVO ASSOCIATO CON JOIN ---")
        sql_delete = self.dialect.compile_delete_joined(
            target_table=agenda_map.name,
            source_table=flussi_map.name,
            join_condition=f"s.{flussi_map.ambito} = t.{agenda_map.sede}",
            filter_condition=f"t.{agenda_map.zona} = 'SUD'"
        )

        eliminati = self.execute_mutation(CompiledQuery(sql_delete, ()))
        print(f"   [DELETE MASSIVA] Righe rimosse dall'unione dialettale: {eliminati}")