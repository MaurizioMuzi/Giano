# processes/preparazione_postalizzazione/step_elabora_avviso.py
from datetime import date

from core.batch_logger import BatchLogger
from .context import PreparazionePostalizzazioneContext
from .step_curt_14 import DettaglioCurt14
from .step_ciclo_curt_01 import DettaglioCicloCurt01

class DettaglioElaboraAvviso:
    """
    Se l'avviso non è stato scartato per sede o per importo o per RAV,
    si procede alla scrittura sulle tabelle di postalizzazione
    """

    def __init__(self, engine):
        self.engine = engine
        self.step_curt_14 = DettaglioCurt14(engine)
        self.step_ciclo_curt_01 = DettaglioCicloCurt01(engine)

        self.record_avv12 = {}

    def execute_dettaglio(self, ctx: PreparazionePostalizzazioneContext, depth: int = 1) -> None:
        BatchLogger.info("CURSORE-CURT01", "Estrazione delle partite su ADCFRT01", depth=1)
        t01_map = self.engine.get_table_map("ADCFRT01")

        # Equivalente di OPEN-CURT01 + FETCH-CURT01: CURSORE DI ESTRAZIONE DELLE PARTITE SU ADCFRT01
        query = (
            self.engine.dataset("ADCFRT01")
            .select("gestione", "codiceAtto", "codiceFiscale", "sede", "zona",
                    "codCentro", "partitaIva", "dataInf", "dataNot", "codDipendente", "dataRifCon",
                    "codAzienda", "descrizioneAtto", "annoEmissione", "numEmissione", "numInail", "codSegnalazione",
                    "flgDecadenza", "meseInizioPeriodo", "meseFinePeriodo", "dataFallimento", "numSogg", "numRate",
                    "statoAttivita", "codEsattoria", "flgValFiscale", "annoRifRuolo", "numRuolo", "flgEuro", "codEsattoriaDel",
                    "annoCarico", "numCarico", "numChkCarico", "dataTransizioneStato", "flgIscrizione", "flgCessione", "codCausale",
                    "codFasAmm", "statoAzienda", "dataStatoAzienda", "descrizioneAttoBi", "timestampInsStato", "timestampVarStato",
                    "tipoAvviso", "annoAvviso", "progAvviso", "numPartitaAvviso", "numEspAvviso", "periodo", "periodoBi", "sedeOrigine",
                    "flgSanzioni", "flgCessioneRuolo", "flgRateizzazione", "codEsattoriaAvviso", "codiceErrore", "flgSanzioniAdr")
            .filter_by("codEsattoria", "=", ctx.cesa)
            .filter_by("annoCarico", "=", ctx.annoCartella)
            .filter_by("numCarico", "=", ctx.numeroCartella)
            .filter_by("numChkCarico", "=", ctx.chkCartella)
            .order_by("numEspAvviso")
            .with_uncommitted_read()
            .limit(1) #da verificare che sia solo un record
            .compile_select()
        )
        rows_t01 = self.engine.fetch(query, depth=1)

        if rows_t01:
            row_t01 = t01_map.normalize(rows_t01[0])

            ctx.ws_cges = row_t01.get("gestione")
            ctx.cseg = row_t01.get("codSegnalazione")
            ctx.catt = row_t01.get("codiceAtto")
            ctx.nesp = row_t01.get("numEspAvviso")
            ctx.tipoavv = row_t01.get("tipoAvviso")
            ctx.sattbi = row_t01.get("descrizioneAttoBi")
            ctx.satt = row_t01.get("descrizioneAtto")
            ctx.sede = row_t01.get("sedeOrigine")

        else:
            BatchLogger.error("SELECT-ADCFRT01", f"Nessun record attivo su ADCFRT01", depth=1, is_last=True)
            ctx.indic_errore = "X"
            return

        # SELECT su ADCFRT14: estrazione dati intestatario dell'avviso addebito
        t14_map = self.engine.get_table_map("ADCFRT14")

        query_t14 = (
            self.engine.dataset("ADCFRT14")
            .select("gestione", "codiceAtto", "partitaIva", "codiceFiscale", "cognome",
                    "nome", "sesso", "dataNascita", "comuneNascita", "provinciaNascita", "indirizzo",
                    "numeroCivico", "letteraCivico", "numeroChilometro", "cap","localita", "siglaProvincia",
                    "comuneDomicilio", "indAnagrafeTrib", "capAnagrafeTrib", "siglaProvAnagrafeTrib", "locAnagrafeTrib"
                    "comuneAnagrafeTrib", "dataValidDoc", "pec"
                    )
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("codiceAtto", "=", ctx.catt)
            .filter_by("codiceAnag", "=", "I")
            .compile_select()
        )
        rows_t14 = self.engine.fetch(query_t14, depth=depth)

        if rows_t14:
            row_t14 = t14_map.normalize(rows_t14[0])
        else:
            BatchLogger.error("SELECT-ADCFRT14", f"Nessun intestatario trovato su ADCFRT14 con CGES= {ctx.ws_cges} e CATT = {ctx.catt}",
                              depth=1, is_last=True)
            ctx.indic_errore = "X"
            return


        self._valorizza_t12(ctx, rowt01 = row_t01, rowt14 = row_t14, depth=depth+1)
        self._ctrl_sedi_chiuse(ctx, depth=depth+1)
        self._inserisci_t12(ctx, depth=depth+1)

        # Apertura cursore su ADCFRT14 per estrazione delle occorrenze con CANA = 'IP'
        # inserimento delle stesse su ADCAVV22
        self.step_curt_14.execute_dettaglio(ctx, rowt01 = row_t01, depth=depth)

        # Apertura cursore su ADCFRT01 per elaborazione partite che confluiscono in un unico avviso
        tot_t01 = len(rows_t01)

        for idx, row_t01 in enumerate(rows_t01, start=1):
            is_last = (idx == tot_t01)

            BatchLogger.info(
                "PARTITE-ESTRATTE-ADCFRT01",
                f"[{idx}/{tot_t01}]",
                depth=depth + 1,
                is_last=False
            )

            self.step_ciclo_curt_01.execute_dettaglio(
                ctx=ctx,
                row=row_t01,
                depth=depth + 1,
                is_last=is_last
            )

    def _valorizza_t12(self, ctx: PreparazionePostalizzazioneContext, rowt01, rowt14, is_last: bool = False,
                                 depth: int = 2) -> None:
        BatchLogger.info("VALORIZZAZIONE-ADCAVV12", "Valorizzazione dati ADCAVV12 prima di procedere con l'inserimento", depth=depth)

        # Valorizzazione del campo PRGCENS (Progressivo di Censimento)
        prgcens_no_bolzano = {
            '1': 1, '3': 2, '4': 3, '5': 4, '6': 5, '7': 6, '8': 7,
            'G': 17, 'H': 17, 'I': 19, 'E': 21, 'F': 21,
            'C': 23, 'L': 25, 'M': 8, 'D': 27,
        }

        prgcens_bolzano = {
            '1': 9, '3': 10, '4': 11, '5': 12, '6': 13, '7': 14, '8': 15,
            'G': 18, 'H': 18, 'I': 20, 'E': 22, 'F': 22,
            'C': 24, 'L': 26, 'M': 16, 'D': 28,
        }

        mappa = prgcens_bolzano if ctx.cesa == 21 else prgcens_no_bolzano

        if ctx.ws_cges in mappa:
                ctx.prgcens = mappa[ctx.ws_cges]

        # Valorizzazione dei campi per la tabella AVV12

        idavv = (ctx.idAvviso or "").ljust(20)  # IDAVV OF CDCFRT03

        # MOVE IDAVV OF CDCFRT03 TO IDAVV OF CDCAVV12
        ctx.ws_cesaavv = int(idavv[0:3].strip() or 0)
        ctx.ws_annoavv = int(idavv[3:7].strip() or 0)
        ctx.ws_numavv = int(idavv[7:15].strip() or 0)
        ctx.ws_nck = "00"
        ctx.ws_sol = idavv[17:20]

        val_sede = [
                    str(ctx.current_sede or "").strip(),
                    str(ctx.current_zona or "").strip()
                    ]
        ws_sede = "".join(val_sede)[:4]

        ctx.ws_cazi = (rowt01.get("codAzienda") or "").ljust(10)
        if ctx.ws_cges == 'L':
            # CAZI(1:6) -> CODMAT(1:6), '/' -> CODMAT(7:1), CAZI(7:4) -> CODMAT(8:3)
            codiceMatricola = ctx.ws_cazi[0:6] + "/" + ctx.ws_cazi[6:9]
        else:
            codiceMatricola = ctx.ws_cazi
        # BatchLogger.info("CODICE-MATRICOLA-CDCAVV12",
        #                  f"CODMAT = {ctx.avv12['codMatricola']}",
        #                  depth=depth,
        #                  is_last=is_last)

        cfis = str(rowt14.get("codiceFiscale") or "")
        scog = str(rowt14.get("cognome") or "")
        snom = str(rowt14.get("nome") or "")
        cses = str(rowt14.get("sesso") or "")

        if cfis[11:16].strip():
            cognome = scog[0:25]
            nome = snom[0:20]
            sesso = cses
            denominazioneAzienda = " "
        else:
            cognome = " "
            nome = " "
            sesso = " "
            denominazioneAzienda = scog

        if rowt01.get("flgValFiscale") in ['0', '1']:
            indirizzoDest = rowt14.get("indAnagrafeTrib")
            capDest = rowt14.get("capAnagrafeTrib")
            provDest = rowt14.get("siglaProvAnagrafeTrib")
            comuneDest = rowt14.get("locAnagrafeTrib")
            flagInd = " "
            codComuneDest = rowt14.get("comuneAnagrafeTrib")
            indDest = " "
            numCivDest = " "
            letCivDest = " "
            numKmDest = 0
        else:
            # Caso di indirizzo forzato dalla gestione, si selezionano i dati dell'indirizzo
            # formattati nel campo ws_sind_dest
            BatchLogger.debug(
                "VALORIZZA-IND-DAGEST",
                f"Indirizzo forzato dalla gestione",
                depth=depth
            )
            t14_ind = self.engine.get_table_map("ADCFRT14")

            query_t14_ind = (
                self.engine.dataset("ADCFRT14")
                .select("gestione", "codiceAtto", "partitaIva", "codiceFiscale", "cognome",
                        "nome", "sesso", "dataNascita", "comuneNascita", "provinciaNascita", "indirizzo",
                        "numeroCivico", "letteraCivico", "numeroChilometro", "cap", "localita", "siglaProvincia",
                        "comuneDomicilio", "indAnagrafeTrib", "capAnagrafeTrib", "siglaProvAnagrafeTrib",
                        "locAnagrafeTrib"
                        "comuneAnagrafeTrib", "dataValidDoc", "pec"
                        )
                .filter_by("gestione", "=", ctx.ws_cges)
                .filter_by("codiceAtto", "=", ctx.catt)
                .filter_by("codiceAnag", "=", "I")
                .compile_select()
            )
            rows_t14_ind = self.engine.fetch(query_t14_ind, depth=depth)


            if not rows_t14_ind:
                BatchLogger.error("SELECT-ADCFRT14-IND",
                                  f"Nessun indirizzo trovato su ADCFRT14 con CGES= {ctx.ws_cges} e CATT = {ctx.catt}",
                                  depth=1, is_last=True)
                ctx.indic_errore = "X"
                return

            ws_sind_dest = t14_ind.normalize(rows_t14_ind[0])

            #self._valorizza_ind_dagest(ctx, row = rowt01, depth= depth)
            indirizzoDest = ws_sind_dest
            capDest = rowt14.get("capAnagrafeTrib")
            provDest = rowt14.get("siglaProvAnagrafeTrib")
            comuneDest = rowt14.get("locAnagrafeTrib")
            codComuneDest = rowt14.get("comuneAnagrafeTrib")
            indDest = rowt14.get("indirizzo")
            numCivDest = rowt14.get("numeroCivico")
            letCivDest = rowt14.get("letteraCivico")
            numKmDest = rowt14.get("numeroChilometro")
            flagInd = '1'

        # Calcolo CIN-RAV per inserirlo nel campo del codiceRav della tabella AVV12
        self._calcola_cin_rav(ctx, depth)

        if ctx.ws_cges in ['E','F']:
            dataNotificaDeb = rowt01.get("dataNot")
            dataDiffida = rowt01.get("dataStatoAzienda")
        elif ctx.ws_cges in['L', 'D'] :
            dataNotificaDeb = rowt01.get("dataNot")
            dataDiffida = "0001-01-01-00.00.00.000000"
        else:
            dataNotificaDeb = "0001-01-01-00.00.00.000000"
            dataDiffida = "0001-01-01-00.00.00.000000"

        if ctx.ws_cges in ['G','H']:
            nomeProc = ctx.nomedir
            cognomeProc = ctx.cogndir
        else:
            nomeProc = " "
            cognomeProc = " "

        piu = ""
        if (
                ctx.tipoavv == "M"
                and ctx.ws_cges == "E"
                and ctx.nesp == 1
        ):
            piu = (rowt01.get("codEsattoriaAvviso") or "")[:28].strip()


        # Mappatura esclusiva sui nomi logici definiti in ADCAVV12.json
        self.record_avv12 = {
            "codiceAvviso": ctx.ws_codavv,
            "prgCens": ctx.prgcens,
            "numElab": ctx.ws_num_elab,
            "dcon": ctx.dcon,
            "identificativoAvviso": ctx.idAvviso,
            "flgRateizzazione": rowt01.get("flgRateizzazione"),
            "sedeMittente": ws_sede,
            "gestione": ctx.ws_cges,
            "codConcessione": rowt01.get("codEsattoria"),
            "codMatricola": codiceMatricola,
            "dataLettera" : ctx.dinifor,
            "dataCreLettera" : date.today().strftime("%d/%m/%Y"),
            "statoLettera" : '1',
            "nomeDirSede" : ctx.nomedir,
            "cognomeDirSede" : ctx.cogndir,
            "sedeInps" : ctx.sede,
            "provSedeInps" : ctx.pr,
            "indirizzoSedeInps": ctx.indir_sedi,
            "capSedeInps": ctx.cap_sedi,
            "codFiscaleDestLettera": rowt14.get("codiceFiscale"),
            "tipoDest": 'I',
            "cognomeDest" : cognome,
            "nomeDest" : nome,
            "sessoDest" : sesso,
            "denomAziendaDest" : denominazioneAzienda,
            "indirizzoDest": indirizzoDest,
            "capDest": capDest,
            "provinciaDest": provDest,
            "comuneDest": comuneDest,
            "codComuneDest": codComuneDest,
            "indDest": indDest,
            "numCivDest": numCivDest,
            "letCivDest": letCivDest,
            "numKmDest": numKmDest,
            "flgInd": flagInd,
            "impAvviso" : ctx.impAvvisoRav,
            "impTributo" : ctx.impCaricoCartella,
            "impRiscossione" : ctx.impAggio,
            "periodo": rowt01.get("periodo"),
            "periodobi": rowt01.get("periodobi"),
            "codLett": " ",
            "codErr": 0,
            "codLot": 0,
            "statoInvioEQ" : '0',
            "timestampVarLet": "0001-01-01-00.00.00.000000",
            "codBoll" : 'TD247',
            "pec" : rowt14.get("pec"),
            "codRav" : ctx.rav_17,
            "timestampVarEQS": "0001-01-01-00.00.00.000000",
            "numRiposta" : 0,
            "cdipInd" : " ",
            "dataInd": "0001-01-01-00.00.00.000000",
            "sedeInd" : " ",
            "dataNotificaDeb": dataNotificaDeb,
            "dataDiffida" : dataDiffida,
            "comuneSede" : ctx.comune_sedi,
            "nomeProc" : nomeProc,
            "cognomeProc" : cognomeProc,
            "piu" : piu
        }

    def _calcola_cin_rav(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> None:
        BatchLogger.debug(
            "CALCOLA-CIN-RAV",
            f"Valorizzazione di WS-CABI, WS-CIN1, WS-CIN2",
            depth=depth
        )

        abi_rav = int(ctx.ws_cabi)
        prg_rav = int(ctx.ws_ciderav)
        imp_rav = int(ctx.impAvvisoRav)

        abi_rav1 = 8 if abi_rav < 10000 else 9
        abi_rav = abi_rav1 * 10000 + abi_rav % 10000 # ABIRAV1 e' la prima cifra di ABIRAV (REDEFINES): la MOVE modifica ABIRAV

        # COMPUTE WS-SOMMA = ABIRAV + PRGRAV + IMPRAV  (WS-SOMMA e' PIC 9(11))
        somma = (abi_rav + prg_rav + imp_rav) % 10 ** 11
        cifre = [int(c) for c in f"{somma:011d}"]  # WS-BYTE(1..11)

        # Calcolo di CIN1: posizioni dispari raddoppiate (cifre del doppio sommate), pari sommate
        somma_2 = 0
        for pos, cifra in enumerate(cifre, start=1):
            if pos % 2 == 1:
                doppio = cifra * 2  # WS-CALC
                somma_2 = (somma_2 + doppio // 10 + doppio % 10) % 100  # + WS-CA01 + WS-CA02
            else:
                somma_2 = (somma_2 + cifra) % 100

        s202 = somma_2 % 10  # WS-S202 (ultima cifra)
        cin1 = 0 if s202 == 0 else 10 - s202

        # PRIMI-15 = ABICORAV(5) + PROCORAV(9) + CIN1(1)
        abicorav = abi_rav  # MOVE ABIRAV TO ABICORAV
        procorav = prg_rav % 10 ** 9  # MOVE PRGRAV TO PROCORAV (PIC 9(9))
        primi_15 = int(f"{abicorav:05d}{procorav:09d}{cin1:d}")

        # DIVIDE PRIMI-15 BY 93 GIVING WS-RISULTATO REMAINDER CIN2
        cin2 = primi_15 % 93

        ctx.ws_cabi = abi_rav
        ctx.ws_cin1 = cin1
        ctx.ws_cin2 = cin2

        BatchLogger.debug(
            "CODICE-RAV",
            f"ABI={abi_rav} PROGR={prg_rav} CIN1={cin1} CIN2={cin2}",
            depth=depth
        )
    def _ctrl_sedi_chiuse(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> None:
        BatchLogger.info("CTRL-SEDI-CHIUSE", "Controllo le sedi chiuse (AGESEDI)", depth=1)

        t_agesedi_map = self.engine.get_table_map("AGESEDI")

        ws_sszz = self.record_avv12["sedeMittente"]

        # Select su AGESEDI
        query_sedi = (
            self.engine.dataset("AGESEDI")
            .select("flagatt")
            .filter_by("sszz", "=", ws_sszz)
            .compile_select()
        )
        rows_agesedi = self.engine.fetch(query_sedi, depth=1)

        if not rows_agesedi:
            BatchLogger.error("SELECT-AGESEDI", f"Sede inesistente in AGESEDI", depth=1, is_last=True)
            ctx.indic_errore = "X"
            return

        row_agesedi = t_agesedi_map.normalize(rows_agesedi[0])

        if row_agesedi.get("flagatt") == '3':
            if ws_sszz == '7005':
                self.record_avv12["sedeInd"] = '7000'
            elif ws_sszz == '5103':
                self.record_avv12["sedeInd"] = '5105'
            elif ws_sszz == '4892':
                self.record_avv12["sedeInd"] = '4894'
            else:
                ctx.indic_errore = "X"
                BatchLogger.error("SEGNALAZIONE", f"Manca sede alternativa a sede chiusa, SEDE = {ws_sszz}", depth=depth+1, is_last=True)
                #TORNA-ERRORE: EXEC SQL ROLLBACK
        else:
            self.record_avv12["sedeInd"] = ws_sszz

    def _inserisci_t12(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> None:
        """
        Inserisce il record nella tabella ADCAVV12
        utilizzando i campi logici esatti definiti in VALORIZZA-T12.
        """
        BatchLogger.info(
            "INSERT-T12",
            f"Inserimento avviso in ADCAVV12 (Codice avviso: {ctx.ws_codavv})",
            depth=depth
        )

        ins_tavv12 = self.engine.dataset("ADCAVV12").compile_insert(self.record_avv12)

        try:
            righe = self.engine.execute_mutation(ins_tavv12, depth=depth)
            BatchLogger.debug(
                "INSERISCI-ADCAVV12",
                f"Testata ADCAVV12 inserita per avviso {ctx.ws_codavv} (Righe: {righe})",
                depth=depth
            )
        except:
            ctx.indic_errore = "X"
            BatchLogger.error(
                "INSERT-ADCAVV12E",
                f"Fallito inserimento avviso in ADCAVV12 (Codice avviso: {ctx.ws_codavv})",
                depth=2, is_last=True
            )
            raise