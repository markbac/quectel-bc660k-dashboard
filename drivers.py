"""Per-module serving-cell commands and parsers.

Each supported module family answers a different command for the serving cell
and neighbours. A driver names that command and turns the reply into a
``CellInfo``; the dashboard does the rest. The driver is chosen from the model
named in the ``ATI`` reply.

Status of the formats:

- ``Bc660kDriver``: ``AT+QENG=0`` as documented in the BC660K-GL AT manual V1.3.
- ``QuectelServingCellDriver``: ``AT+QENG="servingcell"`` as documented for the
  BG95/BG96 and EC25/EG25 families.
- ``SimcomCpsiDriver``: ``AT+CPSI?`` as documented for the SIM7000 and SIM7600
  families (RSRQ, RSRP and RSSI in tenths of a dB or dBm).

Only the BC660K-GL has been used on a real board. The other two parsers are
written from the vendors' manuals and covered by tests built from the
documented field lists, not from captures.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Pattern


@dataclass
class CellInfo:
    """Serving-cell facts a driver could read from one reply.

    ``cell_id`` and ``tac`` are hexadecimal strings. Fields the module did not
    report stay ``None`` and leave the dashboard's previous value alone.
    ``neighbours`` is ``None`` when the reply carried no neighbour section.
    """

    rat: str = "--"
    cell_id: Optional[str] = None
    tac: Optional[str] = None
    mcc: Optional[str] = None
    mnc: Optional[str] = None
    pci: Optional[int] = None
    earfcn: Optional[int] = None
    band: Optional[str] = None
    rsrp: Optional[int] = None
    rsrq: Optional[int] = None
    rssi: Optional[int] = None
    sinr: Optional[int] = None
    operation_mode: Optional[str] = None
    neighbours: Optional[List[Dict]] = field(default=None)


def optional_int(text: str) -> Optional[int]:
    """Parse an optional integer field; empty or non-numeric gives None."""
    try:
        return int(text.strip())
    except ValueError:
        return None


def _tenths(text: str) -> Optional[int]:
    """A value in tenths (``-1166``) as a rounded whole number (``-117``)."""
    number = optional_int(text)
    return None if number is None else int(round(number / 10))


def _fields(line: str, prefix: str) -> List[str]:
    return [f.strip().strip('"') for f in line[len(prefix):].split(",")]


class ModuleDriver:
    """Base class: subclasses set ``name``, ``cell_command`` and ``model_pattern``."""

    name = ""
    cell_command = ""
    model_pattern: Pattern[str] = re.compile(r"(?!)")

    def matches(self, ati_text: str) -> bool:
        """True if the ``ATI`` reply names a module this driver handles."""
        return bool(self.model_pattern.search(ati_text))

    def model_name(self, ati_text: str) -> str:
        """The model as printed by the module, for display."""
        match = self.model_pattern.search(ati_text)
        return match.group(0).upper() if match else self.name

    def parse_cell(self, resp: str) -> Optional[CellInfo]:
        """Parse a reply to ``cell_command``; ``None`` if it holds no cell data."""
        raise NotImplementedError


class Bc660kDriver(ModuleDriver):
    """Quectel BC660K-GL (NB-IoT): ``AT+QENG=0``.

    ::

        +QENG: 0,<earfcn>,<earfcn_offset>,<pci>,<cell_id>,[<rsrp>],[<rsrq>],
               [<rssi>],[<sinr>],<band>,<tac>,[<ecl>],[<tx_pwr>],<operation_mode>
        +QENG: 1,<earfcn>,<pci>,<rsrp>,<rsrq>          (one per neighbour)
    """

    name = "BC660K-GL"
    cell_command = "AT+QENG=0"
    model_pattern = re.compile(r"BC660K(?:-GL)?", re.I)

    def parse_cell(self, resp: str) -> Optional[CellInfo]:
        if "+QENG:" not in resp:
            return None
        info: Optional[CellInfo] = None
        neighbours: List[Dict] = []
        for line in resp.splitlines():
            line = line.strip()
            if not line.startswith("+QENG:"):
                continue
            fields = _fields(line, "+QENG:")
            if fields[0] == "0" and len(fields) >= 11:
                info = CellInfo(
                    rat="NB-IoT",
                    earfcn=optional_int(fields[1]),
                    pci=optional_int(fields[3]),
                    cell_id=fields[4],
                    rsrp=optional_int(fields[5]), rsrq=optional_int(fields[6]),
                    rssi=optional_int(fields[7]), sinr=optional_int(fields[8]),
                    band=fields[9],
                    tac=fields[10],
                    operation_mode=fields[13] if len(fields) >= 14 else None,
                )
            elif fields[0] == "1" and len(fields) >= 5:
                earfcn, pci, rsrp, rsrq = (optional_int(f) for f in fields[1:5])
                if earfcn is not None and pci is not None:
                    neighbours.append({"rat": "NB-IoT", "earfcn": earfcn, "pci": pci, "rsrp": rsrp, "rsrq": rsrq})
        info = info or CellInfo()
        info.neighbours = neighbours
        return info


class QuectelServingCellDriver(ModuleDriver):
    """Quectel BG95/BG96 and EC25/EG25: ``AT+QENG="servingcell"``.

    ::

        +QENG: "servingcell",<state>,"LTE",<is_tdd>,<mcc>,<mnc>,<cellid>,<pcid>,<earfcn>,
               <band>,<ul_bw>,<dl_bw>,<tac>,<rsrp>,<rsrq>,<rssi>,<sinr>,<srxlev>
        +QENG: "neighbourcell intra","LTE",<earfcn>,<pcid>,<rsrq>,<rsrp>,<rssi>,<sinr>,...

    Replies for 2G and 3G cells use other layouts and are ignored.
    """

    name = "Quectel LTE"
    cell_command = 'AT+QENG="servingcell"'
    model_pattern = re.compile(r"(?<![A-Za-z0-9])(?:BG9[56](?:-\w+)?|E[CG]2[0-9]\w*|EG9[15]\w*)", re.I)
    _LTE_RATS = ("LTE", "CAT-M", "CAT-M1", "CAT-NB1", "CAT-NB2", "NB-IOT", "eMTC")

    def parse_cell(self, resp: str) -> Optional[CellInfo]:
        info: Optional[CellInfo] = None
        neighbours: List[Dict] = []
        seen = False
        for line in resp.splitlines():
            line = line.strip()
            if line.startswith("+QENG:"):
                fields = _fields(line, "+QENG:")
            else:
                continue
            kind = fields[0].lower()
            if kind == "servingcell" and len(fields) >= 17 and fields[2].upper() in map(str.upper, self._LTE_RATS):
                seen = True
                info = CellInfo(
                    rat=fields[2],
                    mcc=fields[4], mnc=fields[5],
                    cell_id=fields[6],
                    pci=optional_int(fields[7]),
                    earfcn=optional_int(fields[8]),
                    band=fields[9],
                    tac=fields[12],
                    rsrp=optional_int(fields[13]), rsrq=optional_int(fields[14]),
                    rssi=optional_int(fields[15]), sinr=optional_int(fields[16]),
                    operation_mode=fields[1],
                )
            elif kind.startswith("neighbourcell") and len(fields) >= 6 and fields[1].upper() in map(str.upper, self._LTE_RATS):
                seen = True
                earfcn, pci, rsrq, rsrp = (optional_int(f) for f in fields[2:6])
                if earfcn is not None and pci is not None:
                    neighbours.append({"rat": fields[1], "earfcn": earfcn, "pci": pci, "rsrp": rsrp, "rsrq": rsrq})
        if not seen:
            return None
        info = info or CellInfo()
        info.neighbours = neighbours
        return info


class SimcomCpsiDriver(ModuleDriver):
    """SIMCom SIM7000 and SIM7600: ``AT+CPSI?``.

    ::

        +CPSI: <mode>,<state>,<mcc>-<mnc>,<tac>,<cellid>,<pcid>,<band>,<earfcn>,
               <dlbw>,<ulbw>,<rsrq>,<rsrp>,<rssi>,<sinr>

    ``tac`` is hexadecimal with a ``0x`` prefix, ``cellid`` decimal, and the
    RSRQ, RSRP and RSSI are in tenths. Only LTE modes are parsed.
    """

    name = "SIMCom LTE"
    cell_command = "AT+CPSI?"
    model_pattern = re.compile(r"SIM7[0-9]{3}\w*", re.I)

    def parse_cell(self, resp: str) -> Optional[CellInfo]:
        for line in resp.splitlines():
            line = line.strip()
            if not line.startswith("+CPSI:"):
                continue
            fields = _fields(line, "+CPSI:")
            if len(fields) < 14 or not fields[0].upper().startswith("LTE"):
                return None
            plmn = re.fullmatch(r"(\d{3})-(\d{2,3})", fields[2])
            cell_dec = optional_int(fields[4])
            band = re.search(r"(\d+)$", fields[6])
            return CellInfo(
                rat=fields[0],
                mcc=plmn.group(1) if plmn else None,
                mnc=plmn.group(2) if plmn else None,
                tac=re.sub(r"^0[xX]", "", fields[3]) or None,
                cell_id=format(cell_dec, "X") if cell_dec is not None else None,
                pci=optional_int(fields[5]),
                band=band.group(1) if band else None,
                earfcn=optional_int(fields[7]),
                rsrq=_tenths(fields[10]), rsrp=_tenths(fields[11]), rssi=_tenths(fields[12]),
                sinr=optional_int(fields[13]),
                operation_mode=fields[1],
            )
        return None


BC660K = Bc660kDriver()
DRIVERS: List[ModuleDriver] = [BC660K, QuectelServingCellDriver(), SimcomCpsiDriver()]
DEFAULT_DRIVER = BC660K


def detect_driver(ati_text: str) -> Optional[ModuleDriver]:
    """The driver whose model pattern matches the ``ATI`` reply, or ``None``."""
    for driver in DRIVERS:
        if driver.matches(ati_text):
            return driver
    return None
