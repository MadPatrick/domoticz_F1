# -*- coding: utf-8 -*-
"""
<plugin key="F1Info" name="F1 Race Info" author="MadPatrick" version="0.1.4"
        wikilink="https://files-f1.motorsportcalendars.com"
        externallink="https://github.com/MadPatrick/Domoticz_F1">
    <description>
        <h2>F1 Race Info</h2>
        <p>Version 0.1.4</p>
        Fetches the upcoming F1 race weekend schedule from the motorsportcalendars.com ICS feed.
        Displays the sessions of the next race weekend filtered by type.
        The device name is automatically updated with the location of the Grand Prix.
    </description>
    <params>
        <param field="Address" label="Language" width="150px">
            <options>
                <option label="English" value="en" default="true"/>
                <option label="Nederlands" value="nl"/>
            </options>
        </param>
        <param field="Mode1" label="UTC offset in hours" width="75px" required="true" default="1"/>
        <param field="Mode2" label="Poll interval minutes" width="50px" required="true" default="60"/>
        <param field="Mode3" label="Show sessions" width="200px">
            <options>
                <option label="Training / Sprint / Race" value="all" default="true"/>
                <option label="Sprint / Race" value="sprint_race"/>
                <option label="Race" value="race"/>
            </options>
        </param>
        <param field="Mode4" label="Next Event visible days ahead" width="75px" required="true" default="3" min="0"/>
        <param field="Mode5" label="Next Event: text when no event found" width="200px" required="false" default=""/>
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

ICS_URL_EN = "https://files-f1.motorsportcalendars.com/f1-calendar_p1_p2_p3_qualifying_sprint_gp.ics"
ICS_URL_NL = "https://files-f1.motorsportcalendars.com/nl/f1-calendar_p1_p2_p3_qualifying_sprint_gp.ics"
UNIT_WEEKEND = 1
UNIT_NEXT_EVENT = 2
SESSION_SEP = " - "
WINDOW_HOURS = 4
FETCH_TIMEOUT = 5

DAYS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS_EN = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
]

DAYS_NL = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]
MONTHS_NL = [
    "", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
    "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"
]


class BasePlugin:
    def __init__(self):
        self.ics_url = ICS_URL_EN
        self.language = "en"
        self.offset = 1
        self.pollInterval = 60
        self.sessionFilter = "all"
        self.nextEventDays = 3
        self.noEventText = ""
        self.heartbeatCount = 0
        self.lastText = ""
        self.lastLocation = ""
        self.lastNextEvent = None
        self.cachedEvents = []
        self.imageID = 0

    def _load_device_icon(self):
        creating_new_icon = "f1logo" not in Images
        try:
            Domoticz.Image("f1logo.zip").Create()
        except Exception as e:
            Domoticz.Error(f"Unable to load icon pack 'f1logo.zip': {e}")
            return
        if "f1logo" in Images:
            self.imageID = Images["f1logo"].ID
            Domoticz.Log("Icons created and loaded." if creating_new_icon else
                         f"Icons found in database (ImageID={self.imageID}).")
        else:
            Domoticz.Error("Unable to load icon pack 'f1logo.zip'")

    def _apply_device_icon(self):
        if not self.imageID:
            return
        for unit in (UNIT_WEEKEND, UNIT_NEXT_EVENT):
            if unit in Devices and Devices[unit].Image != self.imageID:
                device = Devices[unit]
                device.Update(nValue=device.nValue, sValue=device.sValue, Image=self.imageID)

    def onStart(self):
        if Parameters["Mode6"] == "Debug":
            Domoticz.Debugging(1)

        language = Parameters.get("Address", "en")
        self.language = language
        self.ics_url = ICS_URL_NL if language == "nl" else ICS_URL_EN

        self.offset = int(Parameters["Mode1"])
        self.pollInterval = int(Parameters["Mode2"])
        self.sessionFilter = Parameters.get("Mode3", "all")
        self.nextEventDays = int(Parameters.get("Mode4", "3"))
        self.noEventText = Parameters.get("Mode5", "")

        self._load_device_icon()

        if UNIT_WEEKEND not in Devices:
            Domoticz.Device(Name="F1 Weekend", Unit=UNIT_WEEKEND, TypeName="Text",
                            Image=self.imageID, Used=1).Create()
            Domoticz.Log("Device F1 Weekend created.")

        if UNIT_NEXT_EVENT not in Devices:
            Domoticz.Device(Name="Next Event", Unit=UNIT_NEXT_EVENT, TypeName="Text",
                            Image=self.imageID, Used=1).Create()
            Domoticz.Log("Device Next Event created.")

        self._apply_device_icon()

        Domoticz.Heartbeat(60)
        Domoticz.Log("F1 Info plugin started.")

        self._fetchCalendar()

    def onHeartbeat(self):
        self.heartbeatCount += 1

        if self.cachedEvents:
            self._updateNextEventDevice()

        if self.heartbeatCount % self.pollInterval != 0:
            return

        Domoticz.Debug("Heartbeat: fetching ICS calendar.")
        self._fetchCalendar()

    def _fetchCalendar(self):
        Domoticz.Debug("GET " + self.ics_url)

        try:
            req = urllib.request.Request(
                self.ics_url,
                headers={
                    "User-Agent": "Mozilla/5.0 compatible Domoticz F1 plugin"
                }
            )

            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
                ics_text = resp.read().decode("utf-8", errors="replace")

        except Exception as e:
            Domoticz.Error("Failed to fetch ICS: " + str(e))
            return

        try:
            events = self._parseICS(ics_text)
            self.cachedEvents = events
            text, location = self._buildWeekendText(events)

            device_name = location if location else "F1 Weekend"

            if text and (text != self.lastText or location != self.lastLocation):
                Devices[UNIT_WEEKEND].Update(
                    nValue=0,
                    sValue=text,
                    Name=device_name
                )

                self.lastText = text
                self.lastLocation = location

                Domoticz.Log("Weekend device updated (" + device_name + ")")

            elif not text:
                Domoticz.Log("No upcoming race weekend found.")

            self._updateNextEventDevice()

        except Exception as e:
            Domoticz.Error("Error processing ICS: " + str(e))

    def _updateNextEventDevice(self):
        try:
            next_event = self._buildNextEventText(self.cachedEvents)

            if next_event != self.lastNextEvent:
                Devices[UNIT_NEXT_EVENT].Update(
                    nValue=0,
                    sValue=next_event
                )
                self.lastNextEvent = next_event
                Domoticz.Log("Next Event device updated")

        except Exception as e:
            Domoticz.Error("Error updating Next Event device: " + str(e))

    def _parseICS(self, ics_text):
        lines = ics_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

        unfolded = []
        for line in lines:
            if line and line[0] in (" ", "\t") and unfolded:
                unfolded[-1] += line[1:]
            else:
                unfolded.append(line)

        events = []
        in_event = False
        ev = {}

        for line in unfolded:
            if line == "BEGIN:VEVENT":
                in_event = True
                ev = {}

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
                    prop = line[:colon].upper()
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

                # --- NIEUW: DTEND inlezen ---
                elif line.upper().startswith("DTEND"):
                    colon = line.find(":")
                    if colon == -1:
                        continue
                    prop = line[:colon].upper()
                    value = line[colon + 1:]
                    ev["DTEND"] = value
                    if value.endswith("Z"):
                        ev["DTEND_TZID"] = "UTC"
                    else:
                        tzid = next(
                            (p[5:] for p in prop.split(";") if p.startswith("TZID=")),
                            "LOCAL"
                        )
                        ev["DTEND_TZID"] = tzid

        return events

    def _parseDT(self, dt_str, tzid):
        dt_str = dt_str.rstrip("Z")

        if "T" in dt_str:
            dt = datetime.datetime.strptime(dt_str, "%Y%m%dT%H%M%S")
        else:
            dt = datetime.datetime.strptime(dt_str, "%Y%m%d")

        if tzid == "UTC":
            dt = dt + datetime.timedelta(hours=self.offset)

        return dt

    def _parseSummary(self, summary):
        m = re.match(r'^F1:\s*(.+?)\s*\((.+)\)\s*$', summary)
        if m:
            return m.group(1).strip(), m.group(2).strip()

        if SESSION_SEP in summary:
            left, session = summary.rsplit(SESSION_SEP, 1)
            location = re.sub(r'^Formula\s+1\s+', '', left.strip())
            location = re.sub(r'\s+\d{4}$', '', location.strip())
            return session.strip(), location.strip()

        return summary.strip(), ""

    def _sessionPassesFilter(self, session_lower):
        is_training = "training" in session_lower

        if self.sessionFilter == "all":
            return True
        if self.sessionFilter == "sprint_race":
            return not is_training
        if self.sessionFilter == "race":
            return "grand prix" in session_lower

        return True

    def _buildWeekendText(self, events):
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=self.offset)

        parsed = []
        for ev in events:
            dt = self._parseDT(ev["DTSTART"], ev["DTSTART_TZID"])
            session, location = self._parseSummary(ev["SUMMARY"])
            parsed.append((dt, session, location))

        parsed.sort(key=lambda x: x[0])

        future_idx = None
        for i, item in enumerate(parsed):
            dt = item[0]
            if dt >= now - datetime.timedelta(hours=WINDOW_HOURS):
                future_idx = i
                break

        if future_idx is None:
            return "", ""

        race_location = parsed[future_idx][2]

        weekend_events = [
            (dt, session)
            for dt, session, loc in parsed
            if loc == race_location
        ]

        if not weekend_events:
            return "", ""

        filtered_events = [
            (dt, session)
            for dt, session in weekend_events
            if self._sessionPassesFilter(session.lower())
        ]

        if not filtered_events:
            return "", ""

        days = DAYS_NL if self.language == "nl" else DAYS_EN
        months = MONTHS_NL if self.language == "nl" else MONTHS_EN

        lines = []
        for dt, session in filtered_events:
            weekday = days[dt.weekday()]
            month_en = months[dt.month]
            time_str = dt.strftime("%H:%M")
            lines.append(
                weekday + " " + str(dt.day) + " " + month_en + " " +
                time_str + " : " + session
            )

        return "\n".join(lines), race_location

    def _buildNextEventText(self, events):
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=self.offset)
        cutoff = now + datetime.timedelta(days=self.nextEventDays)

        parsed = []
        for ev in events:
            dt_start = self._parseDT(ev["DTSTART"], ev["DTSTART_TZID"])
            session, location = self._parseSummary(ev["SUMMARY"])

            # --- NIEUW: eindtijd gebruiken als die beschikbaar is ---
            if "DTEND" in ev:
                dt_end = self._parseDT(ev["DTEND"], ev.get("DTEND_TZID", ev["DTSTART_TZID"]))
            else:
                # Geen DTEND: val terug op starttijd + 2 uur als buffer
                dt_end = dt_start + datetime.timedelta(hours=2)

            parsed.append((dt_start, dt_end, session, location))

        parsed.sort(key=lambda x: x[0])

        for dt_start, dt_end, session, location in parsed:
            # Sessie is voorbij als de eindtijd verstreken is
            if now >= dt_end:
                continue
            if not self._sessionPassesFilter(session.lower()):
                continue
            if dt_start > cutoff:
                return self.noEventText

            days = DAYS_NL if self.language == "nl" else DAYS_EN
            months = MONTHS_NL if self.language == "nl" else MONTHS_EN
            weekday = days[dt_start.weekday()]
            month_str = months[dt_start.month]
            time_str = dt_start.strftime("%H:%M")
            date_line = (
                weekday + " " + str(dt_start.day) + " " + month_str + " " +
                time_str + " : " + session
            )
            if location:
                return location + "<br>" + date_line
            return date_line

        return self.noEventText

    def onStop(self):
        Domoticz.Log("F1 Info plugin stopped.")


_plugin = BasePlugin()


def onStart():
    _plugin.onStart()


def onStop():
    _plugin.onStop()


def onHeartbeat():
    _plugin.onHeartbeat()
