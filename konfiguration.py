"""
Fælles konfiguration for Fakturaer - Apotek.

Filen indeholder kun fælles opsætning og
faste værdier.

Proceslogik skal fortsat ligge i:
    main.py
    behandel.py
"""

from __future__ import annotations

import logging


# ==========================================================
# PRISME
# ==========================================================

PRISME_CREDENTIAL = "API_PRISME365_2"

PRISME_DOMAIN_SUFFIX = "prisme-365.dk"


# ==========================================================
# AUTOMATION SERVER
# ==========================================================

QUEUE_ID = 10


# ==========================================================
# FAKTURAUDVÆLGELSE
# ==========================================================

AFDELING = "180504090000"

APOTEK_EAN = "5798005223924"

LEVERANDOER_SOEGESTRENG = "apotek"


# ==========================================================
# KONTERING
# ==========================================================

KONTOSTRENG = (
    "180123000000-548671008-10040-40-"
)

STANDARD_ENHED = "STK"

MAX_KONTERINGSLINJER = 2000

CPR_NUMRE_VALIDERET_TIL_KONTERING = True

UDFOER_KONTERING = True


# ==========================================================
# DATAFORDELEREN
# ==========================================================

# False:
# Datafordeleren kaldes ikke.
#
# True:
# Hvert CPR slås op i Datafordeleren.
ENABLE_DATAFORDELEREN = False


# ==========================================================
# LEVERANDØRSPECIFIK DATOREGEL
# ==========================================================

# Apopro bruger måneden før fakturadatoen.
APOPRO_LEVERANDOERNAVN = (
    "Apopro Online Apotek"
)

APOPRO_MAANEDSFORSKYDNING = -1

POSTERINGSTEKST_DATOFORMAT = "%m-%Y"

POSTERINGSTEKST_SEPARATOR = " - "


# ==========================================================
# MANUELLE FAKTURABESKRIVELSER
# ==========================================================

MANUEL_BESKRIVELSE_OIOUBL = (
    "Robot: OIOUBL-dokumentet kunne ikke "
    "identificeres entydigt. Fakturaen skal "
    "vurderes manuelt."
)

MANUEL_BESKRIVELSE_DOKUMENTSTI = (
    "Robot: Dokumentstien til OIOUBL mangler. "
    "Fakturaen skal vurderes manuelt."
)

MANUEL_BESKRIVELSE_INGEN_CPR = (
    "Robot: Intet CPR fundet på en eller flere "
    "fakturalinjer. Fakturaen skal vurderes "
    "manuelt."
)

MANUEL_BESKRIVELSE_FLERE_CPR = (
    "Robot: En eller flere fakturalinjer har "
    "flere CPR-numre. Fakturaen skal vurderes "
    "manuelt."
)

MANUEL_BESKRIVELSE_UGYLDIGT_CPR = (
    "Robot: Et eller flere CPR-numre findes "
    "ikke i Datafordeleren. Fakturaen skal "
    "vurderes manuelt."
)

MANUEL_BESKRIVELSE_FOR_MANGE_LINJER = (
    "Robot: Fakturaen har for mange "
    "konteringslinjer til automatisk behandling."
)


# ==========================================================
# STATUSKODER TIL MAIN.PY
# ==========================================================

STATUS_MANUEL = "Manuel behandling"

STATUS_CODE_MANUEL_OIOUBL = (
    "MANUAL_OIOUBL"
)

STATUS_CODE_MANUEL_DOKUMENTSTI = (
    "MANUAL_DOCUMENT_PATH"
)

STATUS_CODE_MANUEL_INGEN_CPR = (
    "MANUAL_NO_CPR"
)

STATUS_CODE_MANUEL_FLERE_CPR = (
    "MANUAL_MULTIPLE_CPR"
)

STATUS_CODE_MANUEL_FOR_MANGE_LINJER = (
    "MANUAL_TOO_MANY_LINES"
)

STATUS_CODE_MANUEL_UGYLDIGT_CPR = (
    "MANUAL_INVALID_CPR"
)


# ==========================================================
# LOGGING
# ==========================================================

LOG_LEVEL = logging.INFO

LOG_FORMAT = (
    "%(asctime)s "
    "[%(levelname)s] "
    "%(name)s: "
    "%(message)s"
)

# Egne loggere, som fortsat må vise INFO.
INFO_LOGGERS = (
    "__main__",
    "behandel",
)

# Eksterne biblioteker viser kun
# WARNING, ERROR og CRITICAL.
WARNING_LOGGERS = (
    "httpx",
    "httpcore",
    "urllib3",
    "requests",
    "automation_server_client",
    "q_prisme365_api",
    "q_datafordeleren_api",
    "q_oioubl_faktura_parser",
    "smbprotocol",
    "smbclient",
    "spnego",
    "debugpy",
)


def configure_logging() -> None:
    """
    Konfigurerer fælles logging.

    Proceslogs vises på INFO-niveau.
    Teknisk biblioteksstøj vises først
    fra WARNING-niveau.
    """

    logging.basicConfig(
        level=LOG_LEVEL,
        format=LOG_FORMAT,
    )

    for logger_name in INFO_LOGGERS:
        logging.getLogger(
            logger_name
        ).setLevel(
            logging.INFO
        )

    for logger_name in WARNING_LOGGERS:
        logging.getLogger(
            logger_name
        ).setLevel(
            logging.WARNING
        )