# processes/preparazione_postalizzazione/__init__.py
"""
Package dedicato alla reingegnerizzazione del programma COBOL batch PDCPOAVV.
"""

from .processor import PreparazionePostalizzazioneEngineProcessor

__all__ = ["PreparazionePostalizzazioneEngineProcessor"]