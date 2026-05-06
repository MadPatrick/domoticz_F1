# -*- coding: utf-8 -*-
"""
<plugin key="F1Info" name="F1 Race Info" author="MadPatrick" version="0.1.3"
        externallink="https://files-f1.motorsportcalendars.com">
    <description>
        Fetches the upcoming F1 race weekend schedule from the motorsportcalendars.com ICS feed.
        Displays the sessions of the next race weekend filtered by type.
        The device name is automatically updated with the location of the Grand Prix.
    </description>
    <params>
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

ICS_URL = "https://files-f1.motorsportcalendars.com/nl/f1-calendar_p1_p2_p3_qualifying_sprint_gp.ics"
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


class BasePlugin:
    def __init__(self):
        self.offset = 1
        self.pollInterval = 60
        self.sessionFilter = "all"
        self.nextEventDays = 3
        self.heartbeatCount = 0
        self.lastText = ""
        self.lastLocation = ""
        self.lastNextEvent = ""

    def onStart(self):
        if Parameters["Mode6"] == "Debug":
            Domoticz.Debugging(1)

        self.offset = int(Parameters["Mode1"])
        self.pollInterval = int(Parameters["Mode2"])
        self.sessionFilter = Parameters.get("Mode3", "all")
        self.nextEventDays = int(Parameters.get("Mode4", "3"))

        if UNIT_WEEKEND not in Devices:
            Domoticz.Device(
                Name="F1 Weekend",
                Unit=UNIT_WEEKEND,
                TypeName="Text",
                Used=1
            ).Create()
            Domoticz.Log("Device F1 Weekend created.")

        if UNIT_NEXT_EVENT not in Devices:
            Domoticz.Device(
                Name="Next Event",
                Unit=UNIT_NEXT_EVENT,
                TypeName="Text",
                Used=1
            ).Create()
            Domoticz.Log("Device Next Event created.")

        Domoticz.Heartbeat(60)
        Domoticz.Log("F1 Info plugin started.")

        self._fetchCalendar()

    def onHeartbeat(self):
        self.heartbeatCount += 1

        if self.heartbeatCount % self.pollInterval != 0:
            return

        Domoticz.Debug("Heartbeat: fetching ICS calendar.")
        self._fetchCalendar()

    def _fetchCalendar(self):
        Domoticz.Debug("GET " + ICS_URL)

        try:
            req = urllib.request.Request(
                ICS_URL,
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
            text, location = self._buildWeekendText(events)
            next_event = self._buildNextEventText(events)

            device_name = location if location else "F1 Weekend"

            if text and (text != self.lastText or location != self.lastLocation):
                Devices[UNIT_WEEKEND].Update(
                    nValue=0,
                    sValue=text,
                    Name=device_name
                )

                self.lastText = text
                self.lastLocation = location

                Domoticz.Log("Weekend device updated (" + device_name + "):\n" + text)

            elif not text:
                Domoticz.Log("No upcoming race weekend found.")

            if next_event != self.lastNextEvent:
                Devices[UNIT_NEXT_EVENT].Update(
                    nValue=0,
                    sValue=next_event
                )
                self.lastNextEvent = next_event
                Domoticz.Log("Next Event device updated: " + next_event)

        except Exception as e:
            Domoticz.Error("Error processing ICS: " + str(e))

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
                            (
                                p[5:]
                                for p in prop.split(";")
                                if p.startswith("TZID=")
                            ),
                            "LOCAL"
                        )
                        ev["DTSTART_TZID"] = tzid

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

        lines = []

        for dt, session in filtered_events:
            weekday = DAYS_EN[dt.weekday()]
            month_en = MONTHS_EN[dt.month]
            time_str = dt.strftime("%H:%M")

            lines.append(
                weekday + " " +
                str(dt.day) + " " +
                month_en + " " +
                time_str + " : " +
                session
            )

        return "\n".join(lines), race_location

    def _buildNextEventText(self, events):
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=self.offset)
        cutoff = now + datetime.timedelta(days=self.nextEventDays)

        parsed = []

        for ev in events:
            dt = self._parseDT(ev["DTSTART"], ev["DTSTART_TZID"])
            session, location = self._parseSummary(ev["SUMMARY"])
            parsed.append((dt, session, location))

        parsed.sort(key=lambda x: x[0])

        for dt, session, location in parsed:
            if dt < now:
                continue
            if not self._sessionPassesFilter(session.lower()):
                continue
            if dt > cutoff:
                return ""
            weekday = DAYS_EN[dt.weekday()]
            month_en = MONTHS_EN[dt.month]
            time_str = dt.strftime("%H:%M")
            line = (
                weekday + " " +
                str(dt.day) + " " +
                month_en + " " +
                time_str + " : " +
                session
            )
            if location:
                line += " | " + location
            return line

        return ""

    def onStop(self):
        Domoticz.Log("F1 Info plugin stopped.")


_plugin = BasePlugin()


def onStart():
    _plugin.onStart()


def onStop():
    _plugin.onStop()


def onHeartbeat():
    _plugin.onHeartbeat()
