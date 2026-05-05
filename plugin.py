"""
<plugin key="F1Info" name="F1 Race Info" author="MadPatrick" version="2.0.0"
        externallink="https://files-f1.motorsportcalendars.com">
    <description>
        Haalt het aankomende F1 race weekend schema op uit de motorsportcalendars.com ICS feed.
        Toont alle sessies (VT1/VT2/VT3/Sprint/Kwalificatie/Race) in één tekst device.
    </description>
    <params>
        <param field="Mode1" label="Tijdzone offset (1=CET, 2=CEST)" width="50px" required="true" default="2"/>
        <param field="Mode2" label="Poll interval (minuten)" width="50px" required="true" default="60"/>
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
SESSION_SEP  = " - "   # separator between race name and session type in ICS SUMMARY
WINDOW_HOURS = 4       # how many hours after a session starts it still counts as "upcoming"

DAYS_NL   = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]
MONTHS_NL = ["", "jan", "feb", "mrt", "apr", "mei", "jun",
             "jul", "aug", "sep", "okt", "nov", "dec"]


class BasePlugin:
    def __init__(self):
        self.offset         = 2
        self.pollInterval   = 60
        self.heartbeatCount = 0
        self.lastText       = ""

    # ------------------------------------------------------------------
    def onStart(self):
        if Parameters["Mode6"] == "Debug":
            Domoticz.Debugging(1)

        self.offset       = int(Parameters["Mode1"])
        self.pollInterval = int(Parameters["Mode2"])

        if UNIT_WEEKEND not in Devices:
            Domoticz.Device(Name="F1 Weekend", Unit=UNIT_WEEKEND, TypeName="Text").Create()
            Domoticz.Log("Device 'F1 Weekend' aangemaakt.")

        Domoticz.Heartbeat(60)
        Domoticz.Log("F1 Info plugin gestart.")

        t = threading.Thread(target=self._fetchCalendar)
        t.daemon = True
        t.start()

    # ------------------------------------------------------------------
    def onHeartbeat(self):
        self.heartbeatCount += 1
        if self.heartbeatCount % self.pollInterval != 0:
            return

        Domoticz.Debug("Heartbeat: ICS kalender ophalen.")
        t = threading.Thread(target=self._fetchCalendar)
        t.daemon = True
        t.start()

    # ------------------------------------------------------------------
    def _fetchCalendar(self):
        Domoticz.Debug(f"GET {ICS_URL}")
        try:
            with urllib.request.urlopen(ICS_URL, timeout=10) as resp:
                ics_text = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            Domoticz.Error(f"ICS ophalen mislukt: {e}")
            return

        try:
            events = self._parseICS(ics_text)
            text   = self._buildWeekendText(events)
            if text and text != self.lastText:
                Devices[UNIT_WEEKEND].Update(nValue=0, sValue=text)
                self.lastText = text
                Domoticz.Log(f"Weekend device bijgewerkt:\n{text}")
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
    def _buildWeekendText(self, events):
        """Zoek het eerstvolgende race weekend en formatteer alle sessies."""
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=self.offset)

        parsed = []
        for ev in events:
            dt = self._parseDT(ev["DTSTART"], ev["DTSTART_TZID"])
            parsed.append((dt, ev["SUMMARY"]))

        parsed.sort(key=lambda x: x[0])

        # Zoek het eerste event dat nog niet meer dan WINDOW_HOURS uur geleden begon
        future_idx = None
        for i, (dt, _) in enumerate(parsed):
            if dt >= now - datetime.timedelta(hours=WINDOW_HOURS):
                future_idx = i
                break

        if future_idx is None:
            return ""

        # Bepaal de race-prefix: alles vóór SESSION_SEP in het eerste aankomende event
        first_summary = parsed[future_idx][1]
        if SESSION_SEP in first_summary:
            race_prefix = first_summary.rsplit(SESSION_SEP, 1)[0]
        else:
            race_prefix = first_summary

        # Verzamel alle sessies van dit race weekend
        weekend_events = [
            (dt, summ) for dt, summ in parsed
            if summ.startswith(race_prefix)
        ]

        if not weekend_events:
            return ""

        # Maak een leesbare naam: verwijder "Formule 1 " en het jaartal
        race_name = race_prefix
        race_name = re.sub(r"^Formule 1\s+", "", race_name)
        race_name = re.sub(r"\s+\d{4}$", "", race_name)

        lines = [race_name]
        for dt, summ in weekend_events:
            weekday  = DAYS_NL[dt.weekday()]
            month_nl = MONTHS_NL[dt.month]
            time_str = dt.strftime("%H:%M")
            session  = summ.rsplit(SESSION_SEP, 1)[-1] if SESSION_SEP in summ else summ
            lines.append(f"{weekday} {dt.day} {month_nl}  {time_str}  {session}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    def onStop(self):
        Domoticz.Log("F1 Info plugin gestopt.")


# Domoticz plugin entry points
_plugin = BasePlugin()

def onStart():     _plugin.onStart()
def onStop():      _plugin.onStop()
def onHeartbeat(): _plugin.onHeartbeat()
