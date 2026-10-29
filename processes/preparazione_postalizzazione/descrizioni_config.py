# processes/pdcpoavv_preparazione_postalizzazione/descrizioni_config.py
from dataclasses import dataclass, field
from typing import Optional

K3_AP_IT = "PROT. "
K3_AP_TD = "PROT. "

@dataclass
class DescrPartConfig:
# Costanti utilizzate per le descrzioni degli avvisi omissione
    k1_omg1: Optional[str]
    k2_omg3: Optional[str]
    kf_omg3: Optional[str]
    k3_omg3: Optional[str]
    k4_omg5: Optional[str]
    k5_omg5: Optional[str]
    k5_omg6: Optional[str]
    ka_omg7: Optional[str]
    k6_omg7: Optional[str]
    k7_omg7: Optional[str]
    k8_omg8: Optional[str]
    k9_omgp: Optional[str]
    ka_omgp: Optional[str]
    kb_omge: Optional[str]
#costanti per gestione domestici
    k1_omdm: Optional[str]
    k2_omdm: Optional[str]
    k3_omdm: Optional[str]
    k1_omredec: Optional[str]

# Costanti utilizzate per le descrzioni degli avvisi da verbale ispettivo
    k1_ac: Optional[str]
    k1_ac_vb: Optional[str]
    k2_ac: Optional[str]
    k3_ac: Optional[str]
    k3_ac_vb: Optional[str]
    k4_ac: Optional[str]
    k5_ac: Optional[str]
    k8_ac: Optional[str]
    k6_ac: Optional[str]
    k6_ac1: Optional[str]

    k3_ap: Optional[str]

# AVVISI OMISSIONE
TDS_OM = DescrPartConfig(
    k1_omg1="BEITRAGSUNTERLASSUNG ",
    k2_omg3="PROZENTBEITRAG ÜBER DEM MINDESTBEITRAG AUSGESTELLT ",
    kf_omg3="AUSGABE FIXBEITRÄGE ",
    k3_omg3=" RATE NR. ",
    k4_omg5="AUSGABE ",
    k5_omg5=" TRIMESTER ",
    k5_omg6=" RATE ",
    ka_omg7="EMENS ",
    k6_omg7="BEZUGSZEIT MONAT/JAHR ",
    k7_omg7=" AMTSSTELLE ",
    k8_omg8="BEZUGSJAHR JAHR ",
    k9_omgp="MATRIKEL ",
    ka_omgp=" JAHR ",
    kb_omge="AUSSTEHENDE MELDUNG",
    k1_omdm="BEITRAGSREGELUNG NR. ",
    k2_omdm=" BEZUGS-TRIMESTER/JAHR ",
    k3_omdm="/",
    k1_omredec="40%-VORAUSZAHLUNG LOHNAUSGLEICH (CIGO, CIGD, ASO)",
    k3_ap=K3_AP_TD
)

IT_OM = DescrPartConfig(
    k1_omg1="INADEMPIENZA ",
    k2_omg3="CONTRIBUTO PERCENTUALE OLTRE IL MINIMALE EMISSIONE ",
    kf_omg3="CONTRIBUTO FISSO EMISSIONE ",
    k3_omg3=" RATA N. ",
    k4_omg5="EMISSIONE ",
    k5_omg5=" TRIM. ",
    k5_omg6=" RATA ",
    ka_omg7="EMENS ",
    k6_omg7="COMPETENZA MESE/ANNO ",
    k7_omg7=" SEDE ",
    k8_omg8="COMPETENZA ANNO ",
    k9_omgp="MATRICOLA ",
    ka_omgp=" ANNO ",
    kb_omge="DENUNCIA INSOLUTA",
    k1_omdm="REGOLARIZZAZIONE N. ",
    k2_omdm=" COMPETENZA TRIMESTRE/ANNO ",
    k3_omdm="/",
    k3_ap=K3_AP_IT
)

# AVVISI VERBALE ISPETTIVO
TDS_AC = DescrPartConfig(
    k1_ac="ERHEBUNGSPROTOKOLL",
    k1_ac_vb= "INSPEKTIONSPROTOKOLL",
    k2_ac="ZUGESTELLT AM ",
    k3_ac=" PROT. ",
    k3_ac_vb="INSPEKTIONSPROTOKOLL PROT.NR. ",
    k4_ac=" VOM "
)

IT_AC = DescrPartConfig(
    k1_ac="VERBALE ISPETTIVO",
    k2_ac=" NOTIFICATO IL ",
    k3_ac="VERBALE ISPETTIVO PROT. ",
    k4_ac=" DEL ",
    k5_ac="NOTIFICATO IL ",
    k8_ac="'NOTIFICATA IL ",
    k6_ac=" NIU ",
    k6_ac1="DEL "
)


