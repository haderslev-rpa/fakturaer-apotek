"""
Fakturaer - Apotek.

Behandler ét ATS-item ad gangen.

Procesforløb:
1. Hent faktura og dokumenter fra Prisme.
2. Find og læs OIOUBL-dokumentet.
3. Læs CPR fra parserens fakturalinjer.
4. Validér eventuelt CPR via Datafordeleren.
5. Byg konteringslinjer.
6. Konter fakturaen.
7. Godkendelse er klargjort, men deaktiveret.

STATUS:
- Status sættes ikke i denne fil.
- Manuel behandling returnerer status til main.py.
- Normal behandling returnerer None.
- main.py sætter status helt til sidst.

STATES:
- States gemmes løbende som sporbarhed.
- States kontrolleres ikke før procestrinnene.
- De deaktiverede kontroller står kommenteret.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from decimal import InvalidOperation
from typing import Any

from q_datafordeleren_api.functionality.datafordeler_use import (
    get_aktuel_navn_og_adresse,
)

from q_oioubl_faktura_parser.functionality.parser import (
    OIOUBLParser,
)

from q_prisme365_api.api_client import (
    initialiser_prisme,
)

from q_prisme365_api.functionality.fakturaer import (
    approve_faktura,
    search_fakturaer,
    update_faktura_beskrivelse,
)

from q_prisme365_api.functionality.faktura_kontering import (
    konter_faktura,
)

from konfiguration import (
    AFDELING,
    APOPRO_LEVERANDOERNAVN,
    APOPRO_MAANEDSFORSKYDNING,
    CPR_NUMRE_VALIDERET_TIL_KONTERING,
    ENABLE_DATAFORDELEREN,
    KONTOSTRENG,
    MANUEL_BESKRIVELSE_DOKUMENTSTI,
    MANUEL_BESKRIVELSE_FLERE_CPR,
    MANUEL_BESKRIVELSE_FOR_MANGE_LINJER,
    MANUEL_BESKRIVELSE_INGEN_CPR,
    MANUEL_BESKRIVELSE_OIOUBL,
    MANUEL_BESKRIVELSE_UGYLDIGT_CPR,
    MAX_KONTERINGSLINJER,
    POSTERINGSTEKST_DATOFORMAT,
    POSTERINGSTEKST_SEPARATOR,
    PRISME_CREDENTIAL,
    PRISME_DOMAIN_SUFFIX,
    STANDARD_ENHED,
    STATUS_CODE_MANUEL_DOKUMENTSTI,
    STATUS_CODE_MANUEL_FLERE_CPR,
    STATUS_CODE_MANUEL_FOR_MANGE_LINJER,
    STATUS_CODE_MANUEL_INGEN_CPR,
    STATUS_CODE_MANUEL_OIOUBL,
    STATUS_CODE_MANUEL_UGYLDIGT_CPR,
    STATUS_MANUEL,
    UDFOER_KONTERING,
    ENABLE_GODKENDELSE,
)


logger = logging.getLogger(__name__)


# ==========================================================
# BEHANDLING AF ÉT ITEM
# ==========================================================

async def behandel_page(
    item,
):
    """
    Behandler ét faktura-item.

    Returnerer:
        None:
            Normal behandling er gennemført.

        Dictionary:
            Manuel behandling er nødvendig.
            Resultatet indeholder status og
            status_code til main.py.
    """

    from q_haderslev_vbo.automation_server.ats_update_item_data import (
        update_item_data,
    )

    data = item.data

    # ==========================================================
    # STATES
    # ==========================================================

    class States:
        HENT_FAKTURA = (
            "1.0 Faktura og dokumenter hentet"
        )

        LAES_OIOUBL = (
            "1.1 OIOUBL læst"
        )

        FIND_CPR = (
            "1.2 CPR fundet"
        )

        BYG_KONTERINGSLINJER = (
            "1.3 Konteringslinjer bygget"
        )

        KONTER_FAKTURA = (
            "2.0 Faktura konteret"
        )

        GODKEND_FAKTURA = (
            "3.0 Faktura godkendt"
        )

        MANUEL_OIOUBL = (
            "8.1 Manuel - OIOUBL kunne ikke "
            "findes entydigt"
        )

        MANUEL_DOKUMENTSTI = (
            "8.2 Manuel - Dokumentsti mangler"
        )

        MANUEL_INGEN_CPR = (
            "8.3 Manuel - Intet CPR på fakturalinje"
        )

        MANUEL_FLERE_CPR = (
            "8.4 Manuel - Flere CPR på fakturalinje"
        )

        MANUEL_FOR_MANGE_LINJER = (
            "8.5 Manuel - For mange "
            "konteringslinjer"
        )

        MANUEL_UGYLDIGT_CPR = (
            "8.6 Manuel - CPR kunne ikke valideres"
        )

    # ==========================================================
    # KLARGØR ITEM.DATA
    # ==========================================================

    if not isinstance(
        data,
        dict,
    ):
        raise TypeError(
            "item.data skal være en dictionary."
        )

    data.setdefault(
        "box",
        {},
    )

    data.setdefault(
        "state",
        [],
    )

    if not isinstance(
        data["box"],
        dict,
    ):
        raise TypeError(
            'item.data["box"] skal være en dictionary.'
        )

    if not isinstance(
        data["state"],
        list,
    ):
        raise TypeError(
            'item.data["state"] skal være en liste.'
        )

    box = data["box"]

    header_reference = str(
        box.get(
            "header_reference",
            "",
        )
        or ""
    ).strip()

    if not header_reference:
        raise ValueError(
            "Itemet mangler header_reference i box."
        )

    # ==========================================================
    # STATE-HJÆLPERE
    # ==========================================================

    def har_state(
        state,
    ):
        """
        Kontrollerer om en state findes.

        Funktionen er bevaret, men bruges
        ikke aktivt lige nu.
        """

        return any(
            state in str(
                existing_state
            )
            for existing_state in data.get(
                "state",
                [],
            )
        )

    def mangler_state(
        state,
        step,
    ):
        """
        Kontrollerer om et procestrin mangler.

        Funktionen er bevaret, men bruges
        ikke aktivt lige nu.
        """

        if har_state(
            state
        ):
            log_step(
                step,
                f'Skip "{state}"',
            )

            return False

        return True

    def set_state(
        state,
    ):
        """
        Gemmer en state som sporbarhed.
        """

        update_item_data(
            data,
            item=item,
            state=state,
        )

    def log_step(
        step,
        text,
    ):
        """
        Skriver procestrin til loggen.
        """

        logger.info(
            "[%s] %s",
            step,
            text,
        )

    def manuel_behandling(
        state,
        step,
        status_code,
        note,
        fakturabeskrivelse,
    ):
        """
        Opdaterer Prisme og returnerer
        manuel slutstatus til main.py.

        Status sættes ikke i behandel.py.
        """

        log_step(
            step,
            note,
        )

        _opdater_fakturabeskrivelse(
            rec_id_loc=box.get(
                "rec_id_loc"
            ),
            beskrivelse=fakturabeskrivelse,
        )

        box["manuel_aarsag"] = note

        update_item_data(
            data,
            item=item,
        )

        set_state(
            state
        )

        return {
            "status": STATUS_MANUEL,
            "status_code": status_code,
        }

    # ==========================================================
    # DATA-HJÆLPERE
    # ==========================================================

    def hent_faktura():
        """
        Henter faktura, detaljer og dokumenter.
        """

        return _hent_faktura_med_dokumenter(
            header_reference=header_reference,
        )

    def hent_parserdata():
        """
        Læser OIOUBL og returnerer parserdata.
        """

        dokumentsti = str(
            box.get(
                "dokumentsti",
                "",
            )
            or ""
        ).strip()

        if not dokumentsti:
            raise ValueError(
                "Dokumentstien mangler i item.box."
            )

        parsed_invoice = (
            OIOUBLParser().parse(
                dokumentsti
            )
        )

        fakturalinjer = (
            _hent_fakturalinjer(
                parsed_invoice
            )
        )

        return (
            parsed_invoice,
            fakturalinjer,
        )

    # ==========================================================
    # INITIALISÉR PRISME
    # ==========================================================

    initialiser_prisme(
        PRISME_CREDENTIAL
    )

    faktura = None
    parsed_invoice = None
    fakturalinjer = []
    konteringslinjer = []

    # ==========================================================
    # HENT FAKTURA
    # ==========================================================

    step = "HENT_FAKTURA"

    state = getattr(
        States,
        step,
    )

    # STATE-KONTROL ER DEAKTIVERET.
    #
    # Aktivér senere ved at erstatte:
    #
    #     if True:
    #
    # med:
    #
    #     if mangler_state(state, step):
    #
    # if mangler_state(
    #     state,
    #     step,
    # ):
    if True:
        log_step(
            step,
            "Start",
        )

        faktura = hent_faktura()

        rec_id_loc = faktura.get(
            "RecIdLoc"
        )

        if rec_id_loc in (
            None,
            "",
        ):
            raise ValueError(
                "Fakturaens RecIdLoc mangler."
            )

        dokumenter = faktura.get(
            "Vedhæftede dokumenter",
            [],
        )

        if dokumenter is None:
            dokumenter = []

        if not isinstance(
            dokumenter,
            list,
        ):
            raise TypeError(
                "Feltet 'Vedhæftede dokumenter' "
                "skal være en liste."
            )

        oioubl_dokumenter = [
            dokument
            for dokument in dokumenter
            if (
                isinstance(
                    dokument,
                    dict,
                )
                and str(
                    dokument.get(
                        "TypeId",
                        "",
                    )
                    or ""
                ).strip().casefold()
                == "oioubl"
            )
        ]

        box["rec_id_loc"] = rec_id_loc

        box["antal_dokumenter"] = len(
            dokumenter
        )

        box["antal_oioubl_dokumenter"] = len(
            oioubl_dokumenter
        )

        # Leverandørnavnet kommer oprindeligt
        # fra queue-itemet.
        #
        # Hvis feltet mangler i box, bruges
        # fakturaresultatet som reserve.
        leverandoernavn = str(
            box.get(
                "leverandoernavn",
                "",
            )
            or faktura.get(
                "Leverandørnavn",
                "",
            )
            or ""
        ).strip()

        if not leverandoernavn:
            raise ValueError(
                "Itemet mangler leverandoernavn "
                "i box."
            )

        box["leverandoernavn"] = (
            leverandoernavn
        )

        update_item_data(
            data,
            item=item,
        )

        if len(
            oioubl_dokumenter
        ) != 1:
            return manuel_behandling(
                state=States.MANUEL_OIOUBL,
                step="MANUEL_OIOUBL",
                status_code=(
                    STATUS_CODE_MANUEL_OIOUBL
                ),
                note=(
                    "Der blev fundet "
                    f"{len(oioubl_dokumenter)} "
                    "OIOUBL-dokumenter. "
                    "Der forventes præcis ét."
                ),
                fakturabeskrivelse=(
                    MANUEL_BESKRIVELSE_OIOUBL
                ),
            )

        oioubl_dokument = (
            oioubl_dokumenter[0]
        )

        dokumentsti = str(
            oioubl_dokument.get(
                "Dokumentsti",
                "",
            )
            or ""
        ).strip()

        dokumentplacering_status = str(
            oioubl_dokument.get(
                "DokumentplaceringStatus",
                "",
            )
            or ""
        ).strip()

        if (
            dokumentplacering_status != "hentet"
            or not dokumentsti
        ):
            return manuel_behandling(
                state=States.MANUEL_DOKUMENTSTI,
                step="MANUEL_DOKUMENTSTI",
                status_code=(
                    STATUS_CODE_MANUEL_DOKUMENTSTI
                ),
                note=(
                    "OIOUBL-dokumentets sti "
                    "kunne ikke bruges. "
                    "DokumentplaceringStatus: "
                    f"{dokumentplacering_status or 'mangler'}."
                ),
                fakturabeskrivelse=(
                    MANUEL_BESKRIVELSE_DOKUMENTSTI
                ),
            )

        box["dokumentsti"] = dokumentsti

        update_item_data(
            data,
            item=item,
        )

        set_state(
            state
        )

        log_step(
            step,
            (
                "Faktura og dokumenter hentet. "
                f"Dokumenter: {len(dokumenter)}."
            ),
        )

    # ==========================================================
    # LÆS OIOUBL
    # ==========================================================

    step = "LAES_OIOUBL"

    state = getattr(
        States,
        step,
    )

    # STATE-KONTROL ER DEAKTIVERET.
    #
    # if mangler_state(
    #     state,
    #     step,
    # ):
    if True:
        log_step(
            step,
            "Start",
        )

        (
            parsed_invoice,
            fakturalinjer,
        ) = hent_parserdata()

        box["antal_fakturalinjer"] = len(
            fakturalinjer
        )

        update_item_data(
            data,
            item=item,
        )

        set_state(
            state
        )

        log_step(
            step,
            (
                "OIOUBL læst. "
                f"Fakturalinjer: "
                f"{len(fakturalinjer)}."
            ),
        )

    # ==========================================================
    # FIND CPR
    # ==========================================================

    step = "FIND_CPR"

    state = getattr(
        States,
        step,
    )

    # STATE-KONTROL ER DEAKTIVERET.
    #
    # if mangler_state(
    #     state,
    #     step,
    # ):
    if True:
        log_step(
            step,
            "Start",
        )

        if not fakturalinjer:
            (
                parsed_invoice,
                fakturalinjer,
            ) = hent_parserdata()

        cpr_numre = []

        linjer_uden_cpr = 0
        linjer_med_flere_cpr = 0

        for fakturalinje in fakturalinjer:
            linjens_cpr = fakturalinje.get(
                "cpr",
                [],
            )

            if not isinstance(
                linjens_cpr,
                list,
            ):
                raise TypeError(
                    "Parserens felt 'cpr' skal "
                    "være en liste."
                )

            if len(
                linjens_cpr
            ) == 0:
                linjer_uden_cpr += 1
                continue

            if len(
                linjens_cpr
            ) > 1:
                linjer_med_flere_cpr += 1
                continue

            cpr_nummer = str(
                linjens_cpr[0]
            ).strip()

            if not cpr_nummer:
                linjer_uden_cpr += 1
                continue

            cpr_numre.append(
                cpr_nummer
            )

        box["antal_cpr_numre"] = len(
            cpr_numre
        )

        box["linjer_uden_cpr"] = (
            linjer_uden_cpr
        )

        box["linjer_med_flere_cpr"] = (
            linjer_med_flere_cpr
        )

        if linjer_uden_cpr:
            update_item_data(
                data,
                item=item,
            )

            return manuel_behandling(
                state=States.MANUEL_INGEN_CPR,
                step="MANUEL_INGEN_CPR",
                status_code=(
                    STATUS_CODE_MANUEL_INGEN_CPR
                ),
                note=(
                    "En eller flere fakturalinjer "
                    "mangler CPR. "
                    "Linjer uden CPR: "
                    f"{linjer_uden_cpr}."
                ),
                fakturabeskrivelse=(
                    MANUEL_BESKRIVELSE_INGEN_CPR
                ),
            )

        if linjer_med_flere_cpr:
            update_item_data(
                data,
                item=item,
            )

            return manuel_behandling(
                state=States.MANUEL_FLERE_CPR,
                step="MANUEL_FLERE_CPR",
                status_code=(
                    STATUS_CODE_MANUEL_FLERE_CPR
                ),
                note=(
                    "En eller flere fakturalinjer "
                    "har flere CPR-numre. "
                    "Linjer med flere CPR: "
                    f"{linjer_med_flere_cpr}."
                ),
                fakturabeskrivelse=(
                    MANUEL_BESKRIVELSE_FLERE_CPR
                ),
            )

        # ------------------------------------------------------
        # DATAFORDELEREN
        # ------------------------------------------------------

        antal_ugyldige_cpr = 0

        if ENABLE_DATAFORDELEREN:
            log_step(
                step,
                "Validerer CPR via Datafordeleren",
            )

            for cpr in cpr_numre:
                result = (
                    get_aktuel_navn_og_adresse(
                        cpr
                    )
                )

                if not result.get(
                    "findes"
                ):
                    antal_ugyldige_cpr += 1

            box[
                "datafordeler_opslag_udfoert"
            ] = True

            box["antal_gyldige_cpr"] = (
                len(cpr_numre)
                - antal_ugyldige_cpr
            )

            box["antal_ugyldige_cpr"] = (
                antal_ugyldige_cpr
            )

            update_item_data(
                data,
                item=item,
            )

            if antal_ugyldige_cpr:
                return manuel_behandling(
                    state=(
                        States.MANUEL_UGYLDIGT_CPR
                    ),
                    step="MANUEL_UGYLDIGT_CPR",
                    status_code=(
                        STATUS_CODE_MANUEL_UGYLDIGT_CPR
                    ),
                    note=(
                        "Et eller flere CPR-numre "
                        "findes ikke i "
                        "Datafordeleren. "
                        "Antal ugyldige: "
                        f"{antal_ugyldige_cpr}."
                    ),
                    fakturabeskrivelse=(
                        MANUEL_BESKRIVELSE_UGYLDIGT_CPR
                    ),
                )

        else:
            box[
                "datafordeler_opslag_udfoert"
            ] = False

            box.pop(
                "antal_gyldige_cpr",
                None,
            )

            box.pop(
                "antal_ugyldige_cpr",
                None,
            )

            update_item_data(
                data,
                item=item,
            )

            log_step(
                step,
                "Datafordeler-opslag er slået fra",
            )

        set_state(
            state
        )

        log_step(
            step,
            (
                "CPR fundet. "
                f"Antal: {len(cpr_numre)}."
            ),
        )

    # ==========================================================
    # BYG KONTERINGSLINJER
    # ==========================================================

    step = "BYG_KONTERINGSLINJER"

    state = getattr(
        States,
        step,
    )

    # STATE-KONTROL ER DEAKTIVERET.
    #
    # if mangler_state(
    #     state,
    #     step,
    # ):
    if True:
        log_step(
            step,
            "Start",
        )

        if faktura is None:
            faktura = hent_faktura()

        if not fakturalinjer:
            (
                parsed_invoice,
                fakturalinjer,
            ) = hent_parserdata()

        # Skal altid ligge uden for:
        #
        # if not fakturalinjer:
        #
        konteringslinjer = (
            _byg_konteringslinjer(
                faktura=faktura,
                fakturalinjer=fakturalinjer,
                leverandoernavn=str(
                    box.get(
                        "leverandoernavn",
                        "",
                    )
                    or ""
                ).strip(),
            )
        )

        if len(
            konteringslinjer
        ) > MAX_KONTERINGSLINJER:
            return manuel_behandling(
                state=(
                    States.MANUEL_FOR_MANGE_LINJER
                ),
                step="MANUEL_FOR_MANGE_LINJER",
                status_code=(
                    STATUS_CODE_MANUEL_FOR_MANGE_LINJER
                ),
                note=(
                    "Fakturaen har "
                    f"{len(konteringslinjer)} "
                    "konteringslinjer. "
                    "Grænsen er "
                    f"{MAX_KONTERINGSLINJER}."
                ),
                fakturabeskrivelse=(
                    MANUEL_BESKRIVELSE_FOR_MANGE_LINJER
                ),
            )

        samlet_konteringsbeloeb = sum(
            (
                linje["Bruttobeløb"]
                for linje in konteringslinjer
            ),
            start=Decimal("0.00"),
        )

        box["antal_konteringslinjer"] = len(
            konteringslinjer
        )

        box["konteringsbeloeb_i_alt"] = str(
            samlet_konteringsbeloeb
        )

        update_item_data(
            data,
            item=item,
        )

        set_state(
            state
        )

        log_step(
            step,
            (
                "Konteringslinjer bygget. "
                f"Antal: "
                f"{len(konteringslinjer)}."
            ),
        )

    # ==========================================================
    # KONTER FAKTURA
    # ==========================================================

    step = "KONTER_FAKTURA"

    state = getattr(
        States,
        step,
    )

    # STATE-KONTROL ER DEAKTIVERET.
    #
    # VIGTIGT:
    # Samme item kan konteres igen, hvis
    # samme item behandles igen.
    #
    # if mangler_state(
    #     state,
    #     step,
    # ):
    if True:
        log_step(
            step,
            "Start",
        )

        if faktura is None:
            faktura = hent_faktura()

        if not fakturalinjer:
            (
                parsed_invoice,
                fakturalinjer,
            ) = hent_parserdata()

        if not konteringslinjer:
            konteringslinjer = (
                _byg_konteringslinjer(
                    faktura=faktura,
                    fakturalinjer=fakturalinjer,
                    leverandoernavn=str(
                        box.get(
                            "leverandoernavn",
                            "",
                        )
                        or ""
                    ).strip(),
                )
            )

        if len(
            konteringslinjer
        ) > MAX_KONTERINGSLINJER:
            return manuel_behandling(
                state=(
                    States.MANUEL_FOR_MANGE_LINJER
                ),
                step="MANUEL_FOR_MANGE_LINJER",
                status_code=(
                    STATUS_CODE_MANUEL_FOR_MANGE_LINJER
                ),
                note=(
                    "Fakturaen har "
                    f"{len(konteringslinjer)} "
                    "konteringslinjer. "
                    "Grænsen er "
                    f"{MAX_KONTERINGSLINJER}."
                ),
                fakturabeskrivelse=(
                    MANUEL_BESKRIVELSE_FOR_MANGE_LINJER
                ),
            )

        konter_faktura(
            header_reference=header_reference,
            konteringslinjer=konteringslinjer,
            cpr_numre_valideret=(
                CPR_NUMRE_VALIDERET_TIL_KONTERING
            ),
            udfoer=UDFOER_KONTERING,
        )

        box["kontering_udfoert"] = True

        update_item_data(
            data,
            item=item,
        )

        set_state(
            state
        )

        log_step(
            step,
            "Faktura konteret",
        )

    # ==========================================================
    # GODKEND FAKTURA
    # ==========================================================

    step = "GODKEND_FAKTURA"

    state = getattr(
        States,
        step,
    )

    # STATE-KONTROL ER DEAKTIVERET.
    #
    # Aktivér senere ved at erstatte:
    #
    #     if True:
    #
    # med:
    #
    #     if mangler_state(
    #         state,
    #         step,
    #     ):
    #
    # if mangler_state(
    #     state,
    #     step,
    # ):
    if ENABLE_GODKENDELSE:

        log_step(
            step,
            "Start",
        )

        if faktura is None:
            faktura = hent_faktura()

        if not fakturalinjer:
            (
                parsed_invoice,
                fakturalinjer,
            ) = hent_parserdata()

        if not konteringslinjer:
            konteringslinjer = (
                _byg_konteringslinjer(
                    faktura=faktura,
                    fakturalinjer=fakturalinjer,
                    leverandoernavn=str(
                        box.get(
                            "leverandoernavn",
                            "",
                        )
                        or ""
                    ).strip(),
                )
            )

        fakturabeloeb = _to_decimal(
            faktura.get(
                "Importeret fakturabeløb"
            )
        )

        samlet_konteringsbeloeb = sum(
            (
                linje["Bruttobeløb"]
                for linje in konteringslinjer
            ),
            start=Decimal("0.00"),
        )

        approve_faktura(
            rec_id_loc=int(
                box["rec_id_loc"]
            ),
            fakturabeloeb=fakturabeloeb,
            konteringslinjer_totalbeloeb=(
                samlet_konteringsbeloeb
            ),
            godkender_1="DIRXFB",
            afdeling=AFDELING,
        )

        box["godkendelse_udfoert"] = True

        update_item_data(
            data,
            item=item,
        )

        set_state(
            state
        )

        log_step(
            step,
            "Faktura godkendt",
        )

    else:
        log_step(
            step,
            "Godkendelse er slået fra i konfiguration.py",
        )

    # Ingen særlig slutstatus.
    # main.py markerer itemet som færdigt.
    return None

# ==========================================================
# HENT FAKTURA
# ==========================================================

def _hent_faktura_med_dokumenter(
    header_reference: str,
) -> dict[str, Any]:
    """
    Henter præcis én faktura med detaljer,
    dokumenter og dokumentplacering.
    """

    fakturaer = search_fakturaer(
        header_reference=header_reference,
        hent_detaljer=True,
        hent_dokumenter=True,
        hent_dokumentplacering=True,
        dokument_domain_suffix=(
            PRISME_DOMAIN_SUFFIX
        ),
        top=2,
    )

    if not isinstance(
        fakturaer,
        list,
    ):
        raise TypeError(
            "search_fakturaer skal returnere "
            "en liste."
        )

    if not fakturaer:
        raise LookupError(
            "Fakturaen blev ikke fundet i Prisme. "
            f"HeaderReference: {header_reference}"
        )

    if len(
        fakturaer
    ) != 1:
        raise LookupError(
            "Fakturaopslaget var ikke entydigt. "
            f"HeaderReference: {header_reference}. "
            f"Antal fakturaer: {len(fakturaer)}."
        )

    faktura = fakturaer[0]

    if not isinstance(
        faktura,
        dict,
    ):
        raise TypeError(
            "Fakturaen skal være en dictionary."
        )

    return faktura


# ==========================================================
# BEREGN FAKTURAMÅNED OG ÅR
# ==========================================================

def _beregn_fakturamaaned_og_aar(
    fakturadato: Any,
    leverandoernavn: str,
) -> str:
    """
    Returnerer fakturamåned og år.

    Almindelige leverandører bruger
    fakturadatoens måned.

    Apopro Online Apotek bruger den
    konfigurerede månedsforskydning.
    """

    if fakturadato in (
        None,
        "",
    ):
        raise ValueError(
            "Fakturaens Dato mangler. "
            "Posteringsteksten kan ikke beregnes."
        )

    if isinstance(
        fakturadato,
        datetime,
    ):
        dato = fakturadato

    else:
        dato_tekst = str(
            fakturadato
        ).strip()

        try:
            dato = datetime.fromisoformat(
                dato_tekst.replace(
                    "Z",
                    "+00:00",
                )
            )

        except ValueError as error:
            raise ValueError(
                "Fakturaens Dato kan ikke "
                "fortolkes. "
                f"Modtaget værdi: "
                f"{fakturadato!r}"
            ) from error

    maanedsforskydning = 0

    if (
        leverandoernavn.strip().casefold()
        == APOPRO_LEVERANDOERNAVN.casefold()
    ):
        maanedsforskydning = (
            APOPRO_MAANEDSFORSKYDNING
        )

    samlet_maanedsnummer = (
        dato.year * 12
        + dato.month
        - 1
        + maanedsforskydning
    )

    aar, maaned_fra_nul = divmod(
        samlet_maanedsnummer,
        12,
    )

    beregnet_dato = datetime(
        year=aar,
        month=maaned_fra_nul + 1,
        day=1,
    )

    return beregnet_dato.strftime(
        POSTERINGSTEKST_DATOFORMAT
    )


# ==========================================================
# HENT FAKTURALINJER
# ==========================================================

def _hent_fakturalinjer(
    parsed_invoice: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Henter parserens normaliserede fakturalinjer.
    """

    if not isinstance(
        parsed_invoice,
        dict,
    ):
        raise TypeError(
            "Parserresultatet skal være "
            "en dictionary."
        )

    fakturalinjer = parsed_invoice.get(
        "lines",
        [],
    )

    if not isinstance(
        fakturalinjer,
        list,
    ):
        raise TypeError(
            "Parserens felt 'lines' skal "
            "være en liste."
        )

    if not fakturalinjer:
        raise ValueError(
            "OIOUBL indeholder ingen "
            "fakturalinjer."
        )

    for index, fakturalinje in enumerate(
        fakturalinjer
    ):
        if not isinstance(
            fakturalinje,
            dict,
        ):
            raise TypeError(
                "Alle fakturalinjer skal være "
                "dictionaries. "
                f"Ugyldig linje på indeks {index}."
            )

    return fakturalinjer


# ==========================================================
# BYG KONTERINGSLINJER
# ==========================================================

def _byg_konteringslinjer(
    faktura: dict[str, Any],
    fakturalinjer: list[dict[str, Any]],
    leverandoernavn: str,
) -> list[dict[str, Any]]:
    """
    Bygger én konteringslinje pr.
    normaliseret OIOUBL-fakturalinje.

    Leverandørnavnet kommer fra item.box.
    """

    rec_id_loc = faktura.get(
        "RecIdLoc"
    )

    if rec_id_loc in (
        None,
        "",
    ):
        raise ValueError(
            "Fakturaens RecIdLoc mangler."
        )

    kreditorkonto = str(
        faktura.get(
            "Kreditorkonto",
            "",
        )
        or ""
    ).strip()

    if not kreditorkonto:
        raise ValueError(
            "Fakturaens Kreditorkonto mangler."
        )

    afdeling = str(
        faktura.get(
            "Afdeling",
            "",
        )
        or AFDELING
    ).strip()

    leverandoernavn = str(
        leverandoernavn
        or ""
    ).strip()

    if not leverandoernavn:
        raise ValueError(
            "Itemet mangler leverandoernavn "
            "i box."
        )

    fakturadato = faktura.get(
        "Dato"
    )

    fakturamaaned_og_aar = (
        _beregn_fakturamaaned_og_aar(
            fakturadato=fakturadato,
            leverandoernavn=leverandoernavn,
        )
    )

    posteringstekst = (
        fakturamaaned_og_aar
        + POSTERINGSTEKST_SEPARATOR
        + leverandoernavn
    )[:60]

    konteringslinjer = []

    for fakturalinje in fakturalinjer:
        cpr_numre = fakturalinje.get(
            "cpr",
            [],
        )

        if not isinstance(
            cpr_numre,
            list,
        ):
            raise TypeError(
                "Parserens felt 'cpr' skal "
                "være en liste."
            )

        if len(
            cpr_numre
        ) != 1:
            raise ValueError(
                "Hver fakturalinje skal have "
                "præcis ét CPR-nummer."
            )

        cpr_nummer = str(
            cpr_numre[0]
        ).strip()

        if not cpr_nummer:
            raise ValueError(
                "Fakturalinjens CPR-nummer "
                "er tomt."
            )

        beloeb = _to_decimal(
            fakturalinje.get(
                "line_amount"
            )
        )

        konteringslinjer.append(
            {
                "RecIdLoc": rec_id_loc,
                "Kontostreng": KONTOSTRENG,
                "Bruttobeløb": beloeb,
                "Ydelsesmodtager": cpr_nummer,
                "Enhed": STANDARD_ENHED,
                (
                    "Afdeling fakturaen "
                    "er tilknyttet"
                ): afdeling,
                "Posteringstekst": (
                    posteringstekst
                ),
                "Kreditorkonto": (
                    kreditorkonto
                ),
            }
        )

    return konteringslinjer


# ==========================================================
# OPDATÉR FAKTURABESKRIVELSE
# ==========================================================

def _opdater_fakturabeskrivelse(
    rec_id_loc: Any,
    beskrivelse: str,
) -> None:
    """
    Opdaterer fakturabeskrivelsen i Prisme.
    """

    if rec_id_loc in (
        None,
        "",
    ):
        raise ValueError(
            "RecIdLoc mangler. "
            "Fakturabeskrivelsen kan derfor "
            "ikke opdateres."
        )

    update_faktura_beskrivelse(
        rec_id_loc=int(
            rec_id_loc
        ),
        fakturabeskrivelse=beskrivelse,
        verificer=True,
    )


# ==========================================================
# BELØB
# ==========================================================

def _to_decimal(
    value: Any,
) -> Decimal:
    """
    Konverterer et beløb til Decimal.
    """

    if isinstance(
        value,
        Decimal,
    ):
        return value

    if value in (
        None,
        "",
    ):
        raise ValueError(
            "Fakturalinjens line_amount mangler."
        )

    if isinstance(
        value,
        bool,
    ):
        raise ValueError(
            "En boolsk værdi kan ikke bruges "
            "som beløb."
        )

    text = str(
        value
    ).strip()

    if "," in text:
        text = text.replace(
            ".",
            "",
        )

        text = text.replace(
            ",",
            ".",
        )

    try:
        return Decimal(
            text
        )

    except InvalidOperation as error:
        raise ValueError(
            "Fakturalinjens line_amount kan "
            f"ikke fortolkes som beløb: {value!r}"
        ) from error