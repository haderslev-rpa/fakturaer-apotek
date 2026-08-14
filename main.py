import asyncio
import logging
import os
import sys
from pprint import pprint

from konfiguration import (
    AFDELING,
    APOTEK_EAN,
    LEVERANDOER_SOEGESTRENG,
    PRISME_CREDENTIAL,
    QUEUE_ID,
    configure_logging,
)


# ------------------------------------------------------------
# 🧠 PROCESS-KODE (ÉT ITEM)
# ------------------------------------------------------------
from behandel import behandel_page


# ------------------------------------------------------------
# 🧠 AUTOMATION SERVER
# ------------------------------------------------------------
from automation_server_client import (
    AutomationServer,
    Workqueue,
    WorkItemError,
    WorkItemStatus,
)

from q_haderslev_vbo.automation_server.ats_update_item_data import (
    update_item_data,
)

from q_haderslev_vbo.automation_server.ats_is_item_in_queue import (
    is_item_in_queue,
)


# ------------------------------------------------------------
# 🧠 PRISME 365 API
# ------------------------------------------------------------
from q_prisme365_api.api_client import (
    initialiser_prisme,
)

from q_prisme365_api.functionality.fakturaer import (
    search_fakturaer,
)

# ------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------
configure_logging()

# ------------------------------------------------------------
# HJÆLPEFUNKTIONER
# ------------------------------------------------------------
def first_value(
    data: dict,
    *field_names: str,
):
    """
    Returnerer første udfyldte feltværdi.

    Prisme API kan bruge forskellige feltnavne,
    afhængigt af hvilket endpoint der svarer.
    """

    for field_name in field_names:
        value = data.get(
            field_name
        )

        if value not in (
            None,
            "",
        ):
            return value

    return None


def first_text(
    data: dict,
    *field_names: str,
) -> str:
    """
    Returnerer første udfyldte tekstværdi.
    """

    value = first_value(
        data,
        *field_names,
    )

    if value is None:
        return ""

    return str(
        value
    ).strip()


# ------------------------------------------------------------
# QUEUE-MODE (PRODUCER)
# ------------------------------------------------------------
async def populate_queue(
    workqueue: Workqueue,
    debug: bool,
):
    """
    Henter relevante apoteksfakturaer fra Prisme
    og tilføjer dem til køen.

    En faktura bliver kun tilføjet, når:

    1. EAN er 5798005223924.
    2. Leverandørnavnet indeholder "apotek".
    3. Fakturaen ikke allerede findes i køen.

    Fakturadetaljer hentes for at få EAN.

    Dokumenter og OIOUBL hentes ikke her.
    Dokumenterne hentes først i behandel.py.
    """

    logger = logging.getLogger(__name__)

    logger.info(
        f"Populate queue mode started "
        f"(debug={debug})"
    )

    # ==========================================================
    # INITIALISÉR PRISME
    # ==========================================================
    initialiser_prisme(
        PRISME_CREDENTIAL
    )



    # --------------------------------------------------------
    # HENT FAKTURAER FRA PRISME
    #
    # Detaljer skal hentes, fordi EAN først
    # bliver udfyldt fra fakturadetaljerne.
    #
    # Dokumenter hentes ikke i queue-delen.
    # --------------------------------------------------------
    
    fakturaer = search_fakturaer(
        afdeling=AFDELING,
        hent_detaljer=True,
        hent_dokumenter=False,
    )

    if not isinstance(
        fakturaer,
        list,
    ):
        raise TypeError(
            "search_fakturaer skal returnere "
            "en liste."
        )

    logger.info(
        "Antal fakturaer fundet i Prisme: %s",
        len(fakturaer),
    )

    antal_tilfoejet = 0
    antal_forkert_ean = 0
    antal_ikke_apotek = 0
    antal_findes_i_koe = 0
    antal_ugyldige = 0

    # --------------------------------------------------------
    # LOOP FAKTURAER
    # --------------------------------------------------------
    for faktura in fakturaer:

        if not isinstance(
            faktura,
            dict,
        ):
            antal_ugyldige += 1

            logger.warning(
                "Springer faktura over, fordi "
                "resultatet ikke er en dictionary."
            )
            continue

        # ----------------------------------------------------
        # HENT OPLYSNINGER FRA PRISME-RESULTATET
        # ----------------------------------------------------
        header_reference = str(
            faktura.get(
                "HeaderReference",
                "",
            )
            or ""
        ).strip()

        fakturanr = str(
            faktura.get(
                "Fakturanr",
                "",
            )
            or ""
        ).strip()

        leverandoernavn = str(
            faktura.get(
                "Leverandørnavn",
                "",
            )
            or ""
        ).strip()

        ean = str(
            faktura.get(
                "EAN",
                "",
            )
            or ""
        ).strip()

        # ----------------------------------------------------
        # KONTROLLÉR OBLIGATORISKE FELTER
        # ----------------------------------------------------
        if not header_reference:
            antal_ugyldige += 1

            logger.warning(
                "Springer faktura over, fordi "
                "HeaderReference mangler."
            )
            continue

        if not fakturanr:
            antal_ugyldige += 1

            logger.warning(
                "Springer faktura over, fordi "
                "Fakturanr mangler. "
                "HeaderReference: %s.",
                header_reference,
            )
            continue

        if not leverandoernavn:
            antal_ugyldige += 1

            logger.warning(
                "Springer faktura over, fordi "
                "Leverandørnavn mangler. "
                "HeaderReference: %s. "
                "Fakturanr: %s.",
                header_reference,
                fakturanr,
            )
            continue

        # ----------------------------------------------------
        # KONTROLLÉR EAN
        # ----------------------------------------------------
        if ean != APOTEK_EAN:
            antal_forkert_ean += 1
            continue

        # ----------------------------------------------------
        # KONTROLLÉR LEVERANDØRNAVN
        # ----------------------------------------------------
        if (
            LEVERANDOER_SOEGESTRENG.casefold()
            not in leverandoernavn.casefold()
        ):
            antal_ikke_apotek += 1
            continue

        # ----------------------------------------------------
        # BYG ITEM-REFERENCE
        # ----------------------------------------------------
        item_reference = (
            f"{header_reference} | "
            f"{fakturanr} | "
            f"{leverandoernavn}"
        )

        # ----------------------------------------------------
        # KONTROLLÉR OM ITEM ALLEREDE FINDES
        # ----------------------------------------------------
        if is_item_in_queue(
            queue_id=QUEUE_ID,
            item_reference=item_reference,
            new=True,
            in_progress=True,
            completed=True,
            failed=True,
            pending_user_action=True,
            updated_at=False,
        ):
            antal_findes_i_koe += 1

            logger.info(
                "Springer over: Item med reference "
                "'%s' findes allerede i køen.",
                item_reference,
            )
            continue

        # ----------------------------------------------------
        # OPBYG ITEM.DATA
        # ----------------------------------------------------
        data_json = {}

        update_item_data(
            data_json,
            box_updates={
                "header_reference": (
                    header_reference
                ),
                "fakturanr": (
                    fakturanr
                ),
                "leverandoernavn": (
                    leverandoernavn
                ),
                "ean": ean,
                "afdeling": (
                    AFDELING
                ),
            },
            update=False,
        )

        # ----------------------------------------------------
        # TILFØJ ITEM TIL KØEN
        # ----------------------------------------------------
        workqueue.add_item(
            data=data_json,
            reference=item_reference,
        )

        antal_tilfoejet += 1

        logger.info(
            "Item med reference '%s' "
            "er tilføjet til køen.",
            item_reference,
        )

    # --------------------------------------------------------
    # OPSUMMERING
    # --------------------------------------------------------
    logger.info(
        "Populate queue mode completed. "
        "Fundet i Prisme: %s. "
        "Tilføjet: %s. "
        "Forkert EAN: %s. "
        "Leverandør uden 'apotek': %s. "
        "Findes allerede i køen: %s. "
        "Ugyldige fakturaer: %s.",
        len(fakturaer),
        antal_tilfoejet,
        antal_forkert_ean,
        antal_ikke_apotek,
        antal_findes_i_koe,
        antal_ugyldige,
    )

# ------------------------------------------------------------
# PROCESS-MODE (WORKER)
# ------------------------------------------------------------
async def process_workqueue(
    workqueue: Workqueue,
    debug: bool,
):
    logger = logging.getLogger(__name__)

    logger.info(
        f"Process workqueue mode started "
        f"(debug={debug})"
    )

    for item in workqueue:

        with item:
            data = item.data

            try:
                print(
                    "==================================== "
                    "NEXT ITEM "
                    "===================================="
                )

                pprint(data)

                # --------------------------------------------------
                # PROCESS-KODE
                # --------------------------------------------------
                resultat = await behandel_page(
                    item=item
                )

                # Genindlæs itemdata efter behandlingen.
                data = item.data

                # --------------------------------------------------
                # STATUS SÆTTES KUN HER TIL SIDST
                # --------------------------------------------------
                if resultat:
                    status = resultat.get(
                        "status",
                        "Completed",
                    )

                    status_code = resultat.get(
                        "status_code",
                        "Færdig",
                    )

                else:
                    status = "Completed"
                    status_code = "Færdig"

                update_item_data(
                    data,
                    item=item,
                    status=status,
                    status_code=status_code,
                    state="Completed",
                )

                item.update(data)

                item.complete(status)

                logger.info(
                    "Item %s afsluttet med "
                    "status '%s' og statuskode '%s'.",
                    item.reference,
                    status,
                    status_code,
                )

            except WorkItemError as error:
                # =================================================
                # SOFT ERROR
                # =================================================
                logger.error(
                    "WorkItemError for item %s: %s",
                    item.reference,
                    error,
                )

                item.fail(
                    str(error)
                )

                raise

# ------------------------------------------------------------
# MAIN ENTRY POINT
# ------------------------------------------------------------
if __name__ == "__main__":

    # CLI flags (runtime-parametre)
    DEBUG = "--debug" in sys.argv
    QUEUE_MODE = "--queue" in sys.argv

    ats = AutomationServer.from_environment()
    workqueue = ats.workqueue()

    # --------------------------------------------------------
    # QUEUE-MODE
    # --------------------------------------------------------
    if QUEUE_MODE:
        # ----------------------------------------------------
        # VIGTIGT:
        # Denne linje CLEARSER alle NEW items i køen.
        #
        # Hvis du ALDRIG vil slette eksisterende NEW items:
        # Fjern eller kommentér linjen ud.
        # ----------------------------------------------------

        #workqueue.clear_workqueue(
        #    WorkItemStatus.NEW
        #)

        asyncio.run(
            populate_queue(
                workqueue,
                debug=DEBUG,
            )
        )

        sys.exit(0)

    # --------------------------------------------------------
    # PROCESS-MODE
    # --------------------------------------------------------
    asyncio.run(
        process_workqueue(
            workqueue,
            debug=DEBUG,
        )
    )