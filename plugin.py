"""
<plugin key="F1Info" name="F1 Race Info" author="MadPatrick" version="2.1.1"
        externallink="https://files-f1.motorsportcalendars.com">
    <description>
        Haalt het aankomende F1 race weekend schema op uit de motorsportcalendars.com ICS feed.
        Toont de sessies van het komende race weekend gefilterd op type.
        De device-naam wordt automatisch bijgewerkt met de locatie van de Grand Prix.
    </description>
    <params>
        <param field="Mode1" label="UTC offset in uren (bijv. 1, 2, -5)" width="75px" required="true" default="1"/>
        <param field="Mode2" label="Poll interval (minuten)" width="50px" required="true" default="60"/>
        <param field="Mode3" label="Sessies weergeven" width="200px">
            <options>
                <option label="Training / Sprint / Race" value="all" default="true"/>
                <option label="Sprint / Race" value="sprint_race"/>
                <option label="Race" value="race"/>
            </options>
        </param>
        <param field="Mode6" label="Debug" width="75px">
            <options>
                <option label="True" value="Debug"/>
                <option label="False" value="Normal" default="true"/>
            </options>
        </param>
    </params>
</plugin>
"""

import Domoticz
import datetime
import re
import urllib.request
import threading

ICS_URL      = "https://files-f1.motorsportcalendars.com/nl/f1-calendar_p1_p2_p3_qualifying_sprint_gp.ics"
UNIT_WEEKEND = 1
SESSION_SEP  = " - "   # separator between race name and session type in ICS SUMMARY (old format)
WINDOW_HOURS = 4       # how many hours after a session starts it still counts as "upcoming"
FETCH_TIMEOUT = 10     # seconds for urlopen timeout

DAYS_NL   = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]
MONTHS_NL = ["", "jan", "feb", "mrt", "apr", "mei", "jun",
             "jul", "aug", "sep", "okt", "nov", "dec"]


class BasePlugin:
    def __init__(self):
        self.offset         = 1
        self.pollInterval   = 60
        self.sessionFilter  = "all"
        self.heartbeatCount = 0
        self.lastText       = ""
        self.lastLocation   = ""
        self._stopEvent     = threading.Event()
        self._threads       = []

    # ------------------------------------------------------------------
    def onStart(self):
        if Parameters["Mode6"] == "Debug":
            Domoticz.Debugging(1)

        self.offset        = int(Parameters["Mode1"])
        self.pollInterval  = int(Parameters["Mode2"])
        self.sessionFilter = Parameters.get("Mode3", "all")

        if UNIT_WEEKEND not in Devices:
            Domoticz.Device(Name="F1 Weekend", Unit=UNIT_WEEKEND, TypeName="Text").Create()
            Domoticz.Log("Device 'F1 Weekend' aangemaakt.")

        Domoticz.Heartbeat(60)
        Domoticz.Log("F1 Info plugin gestart.")

        self._stopEvent.clear()
        self._startFetchThread()

    # ------------------------------------------------------------------
    def _startFetchThread(self):
        """Start een nieuwe fetch-thread en registreer hem."""
        # Verwijder afgeronde threads uit de lijst
        self._threads = [t for t in self._threads if t.is_alive()]
        t = threading.Thread(target=self._fetchCalendar, daemon=True)
        self._threads.append(t)
        t.start()

    # ------------------------------------------------------------------
    def onHeartbeat(self):
        self.heartbeatCount += 1
        if self.heartbeatCount % self.pollInterval != 0:
            return

        Domoticz.Debug("Heartbeat: ICS kalender ophalen.")
        self._startFetchThread()

    # ------------------------------------------------------------------
    def _fetchCalendar(self):
        if self._stopEvent.is_set():
            return
        Domoticz.Debug(f"GET {ICS_URL}")
        try:
            req = urllib.request.Request(
                ICS_URL,
                headers={"User-Agent": "Mozilla/5.0 (compatible; Domoticz F1 plugin)"}
            )
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
                ics_text = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            Domoticz.Error(f"ICS ophalen mislukt: {e}")
            return

        try:
            events = self._parseICS(ics_text)
            text, location = self._buildWeekendText(events)
            device_name = location if location else "F1 Weekend"
            if text and (text != self.lastText or location != self.lastLocation):
                Devices[UNIT_WEEKEND].Update(nValue=0, sValue=text, Name=device_name)
                self.lastText     = text
                self.lastLocation = location
                Domoticz.Log(f"Weekend device bijgewerkt ({device_name}):\n{text}")
            elif not text:
                Domoticz.Log("Geen aankomend race weekend gevonden.")
        except Exception as e:
            Domoticz.Error(f"Fout bij verwerken ICS: {e}")

    # ------------------------------------------------------------------
    def _parseICS(self, ics_text):
        """Parse ICS tekst en geef lijst van event-dicts terug (SUMMARY + DTSTART)."""
        # Vouw vervolgregels uit (RFC 5545: regels die beginnen met spatie/tab)
        lines = ics_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        unfolded = []
        for line in lines:
            if line and line[0] in (" ", "\t") and unfolded:
                unfolded[-1] += line[1:]
            else:
                unfolded.append(line)

        events    = []
        in_event  = False
        ev        = {}

        for line in unfolded:
            if line == "BEGIN:VEVENT":
                in_event = True
                ev       = {}
            elif line == "END:VEVENT":
                if in_event and "SUMMARY" in ev and "DTSTART" in ev:
                    events.append(ev)
                in_event = False
            elif in_event:
                if line.startswith("SUMMARY:"):
                    ev["SUMMARY"] = line[8:]
                elif line.upper().startswith("DTSTART"):
                    colon = line.find(":")
                    if colon == -1:
                        continue
                    prop  = line[:colon].upper()
                    value = line[colon + 1:]
                    ev["DTSTART"] = value
                    if value.endswith("Z"):
                        ev["DTSTART_TZID"] = "UTC"
                    else:
                        tzid = next(
                            (p[5:] for p in prop.split(";") if p.startswith("TZID=")),
                            "LOCAL"
                        )
                        ev["DTSTART_TZID"] = tzid

        return events

    # ------------------------------------------------------------------
    def _parseDT(self, dt_str, tzid):
        """Zet ICS datetime string om naar naïeve lokale datetime."""
        dt_str = dt_str.rstrip("Z")
        if "T" in dt_str:
            dt = datetime.datetime.strptime(dt_str, "%Y%m%dT%H%M%S")
        else:
            dt = datetime.datetime.strptime(dt_str, "%Y%m%d")

        # UTC-tijden omzetten naar lokale tijd met de ingestelde offset
        if tzid == "UTC":
            dt = dt + datetime.timedelta(hours=self.offset)
        # TZID-tijden zijn al in lokale tijd
        return dt

    # ------------------------------------------------------------------
    def _parseSummary(self, summary):
        """Extraheer (session_type, location) uit een SUMMARY string.

        Ondersteunde formaten:
          - "F1: Vrije Training 1 (Grand Prix van Canada)"
          - "Formule 1 Grand Prix van Canada 2025 - Vrije Training 1"
        """
        # Formaat: "F1: <Session> (<Location>)"
        m = re.match(r'^F1:\s*(.+?)\s*\((.+)\)\s*$', summary)
        if m:
            return m.group(1).strip(), m.group(2).strip()

        # Formaat: "Formule 1 <Location> <Year> - <Session>" of "<Location> - <Session>"
        if SESSION_SEP in summary:
            left, session = summary.rsplit(SESSION_SEP, 1)
            location = re.sub(r'^Formule\s+1\s+', '', left.strip())
            location = re.sub(r'\s+\d{4}$', '', location.strip())
            return session.strip(), location.strip()

        return summary.strip(), ""

    # ------------------------------------------------------------------
    def _sessionPassesFilter(self, session_lower):
        """Controleer of een sessie voldoet aan het ingestelde filter."""
        is_training = "training" in session_lower

        if self.sessionFilter == "all":
            return True
        elif self.sessionFilter == "sprint_race":
            return not is_training
        elif self.sessionFilter == "race":
            return "grand prix" in session_lower
        return True

    # ------------------------------------------------------------------
    def _buildWeekendText(self, events):
        """Zoek het eerstvolgende race weekend en formatteer de gefilterde sessies.

        Geeft een tuple (tekst, locatie) terug.
        """
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=self.offset)

        parsed = []
        for ev in events:
            dt = self._parseDT(ev["DTSTART"], ev["DTSTART_TZID"])
            session, location = self._parseSummary(ev["SUMMARY"])
            parsed.append((dt, session, location))

        parsed.sort(key=lambda x: x[0])

        # Zoek het eerste event dat nog niet meer dan WINDOW_HOURS uur geleden begon
        future_idx = None
        for i, (dt, _session, _loc) in enumerate(parsed):
            if dt >= now - datetime.timedelta(hours=WINDOW_HOURS):
                future_idx = i
                break

        if future_idx is None:
            return "", ""

        # Bepaal de locatie van het eerste aankomende event
        race_location = parsed[future_idx][2]

        # Verzamel alle sessies van dit race weekend (zelfde locatie)
        weekend_events = [
            (dt, session) for dt, session, loc in parsed
            if loc == race_location
        ]

        if not weekend_events:
            return "", ""

        # Filter op sessie-type
        filtered_events = [
            (dt, session) for dt, session in weekend_events
            if self._sessionPassesFilter(session.lower())
        ]

        if not filtered_events:
            return "", ""

        lines = []
        for dt, session in filtered_events:
            weekday  = DAYS_NL[dt.weekday()]
            month_nl = MONTHS_NL[dt.month]
            time_str = dt.strftime("%H:%M")
            lines.append(f"{weekday} {dt.day} {month_nl} {time_str} : {session}")

        return "\n".join(lines), race_location

    # ------------------------------------------------------------------
    def onStop(self):
        Domoticz.Log("F1 Info plugin gestopt.")
        self._stopEvent.set()
        for t in self._threads:
            t.join(timeout=FETCH_TIMEOUT + 1)
        self._threads.clear()


# Domoticz plugin entry points
_plugin = BasePlugin()

def onStart():     _plugin.onStart()
def onStop():      _plugin.onStop()
def onHeartbeat(): _plugin.onHeartbeat()
