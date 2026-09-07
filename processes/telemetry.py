# processes/telemetry.py
from core.base_process import BaseProcessModel


class TelemetryProcessor(BaseProcessModel):
    """
    Processo focalizzato sull'analisi dei flussi JSON provenienti dai sensori IoT.
    Sfrutta le API documentali native di MongoDB.
    """

    def __init__(self):
        super().__init__(process_name="Analisi_Telemetria_NoSQL")

    def _execute_business_logic(self):
        if self.db_manager.provider != "mongodb":
            raise TypeError(f"Il database attivo '{self.db_manager.provider}' non supporta l'algebra documentale BSON.")

        # Connessione interpretata correttamente come oggetto Database di pymongo
        db = self.connection
        collection = db["iot_telemetry"]

        # Interrogazione nativa NoSQL
        cursor = collection.find({"status": "critical"}).limit(3)

        print("[TELEMETRY_WORKER] Analisi record critici estratti da MongoDB:")
        counter = 0
        for doc in cursor:
            counter += 1
            print(f"  -> Document ID: {doc.get('_id')} | Sensore: {doc.get('sensor_type')}")
        print(f"[TELEMETRY_WORKER] Task completato. Documenti processati: {counter}")