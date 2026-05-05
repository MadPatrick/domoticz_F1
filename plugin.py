"""
<plugin key="F1Info" name="F1 Race Info" author="Converted from dzVents" version="1.0.0"
        externallink="https://api.jolpi.ca/ergast/">
    <description>
        Fetches next F1 race info and qualifying results from the Jolpi/Ergast API.
        Creates two text devices: 'F1 Race' and 'F1 Kwalificatie'.
    </description>
    <params>
        <param field="Mode1" label="Timezone offset (1=CET, 2=CEST)" width="50px" required="true" default="2"/>
        <param field="Mode2" label="Poll interval (minutes)" width="50px" required="true" default="5"/>
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
import json
import urllib.request
import threading

BASE_URL   = "https://api.jolpi.ca/ergast/f1"
UNIT_RACE  = 1
UNIT_QUALY = 2


class BasePlugin:
    def __init__(self):
        self.offset       = 2
        self.pollInterval = 5
        self.heartbeatCount = 0
        self.lastRaceText  = ""

    # ------------------------------------------------------------------
    def onStart(self):
        if Parameters["Mode6"] == "Debug":
            Domoticz.Debugging(1)

        self.offset       = int(Parameters["Mode1"])
        self.pollInterval = int(Parameters["Mode2"])

        # Create devices if they don't exist yet
        if UNIT_RACE not in Devices:
            Domoticz.Device(Name="F1 Race", Unit=UNIT_RACE, TypeName="Text").Create()
            Domoticz.Log("Device 'F1 Race' created.")

        if UNIT_QUALY not in Devices:
            Domoticz.Device(Name="F1 Kwalificatie", Unit=UNIT_QUALY, TypeName="Text").Create()
            Domoticz.Log("Device 'F1 Kwalificatie' created.")

        Domoticz.Heartbeat(60)  # called every 60 seconds
        Domoticz.Log("F1 Info plugin started.")

    # ------------------------------------------------------------------
    def onHeartbeat(self):
        self.heartbeatCount += 1
        # Only fetch every <pollInterval> minutes
        if self.heartbeatCount % self.pollInterval != 0:
            return

        Domoticz.Debug("Heartbeat: fetching next race info.")
        t = threading.Thread(target=self._fetchNextRace)
        t.daemon = True
        t.start()

    # ------------------------------------------------------------------
    # ---------- network helpers (run in background thread) -------------
    def _fetchNextRace(self):
        url = f"{BASE_URL}/current/next.json"
        Domoticz.Debug(f"GET {url}")
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            Domoticz.Error(f"Failed to fetch next race: {e}")
            return

        try:
            races  = data["MRData"]["RaceTable"]["Races"]
            season = data["MRData"]["RaceTable"]["season"]
            round_ = data["MRData"]["RaceTable"]["round"]

            if not races:
                Domoticz.Log("No upcoming race data returned.")
                return

            race     = races[0]
            name     = race["raceName"]
            datepure = race["date"]          # "YYYY-MM-DD"
            timepure = race.get("time", "00:00:00Z")

            y, m, d = datepure.split("-")
            fecha   = f"{d}/{m}/{y}"

            h, mi = timepure[:5].split(":")
            hora  = f"{int(h) + self.offset}:{mi}"

            location = race.get("Circuit", {}).get("Location", {})
            locality = location.get("locality", "")
            country  = location.get("country", "")
            circuit  = f"{locality}, {country}" if locality and country else locality or country

            race_text = f"{name}\n{circuit}\n{fecha} {hora}"

            if race_text != self.lastRaceText:
                Devices[UNIT_RACE].Update(nValue=0, sValue=race_text)
                self.lastRaceText = race_text
                Domoticz.Log(f"Race device updated: {race_text}")

            # Now fetch qualifying results for this race
            qualy_url = f"{BASE_URL}/{season}/{round_}/qualifying.json"
            Domoticz.Log(f"Find qualify at {qualy_url}")
            self._fetchQualifying(qualy_url)

        except (KeyError, IndexError, ValueError) as e:
            Domoticz.Error(f"Error parsing race data: {e}")

    # ------------------------------------------------------------------
    def _fetchQualifying(self, url):
        Domoticz.Debug(f"GET {url}")
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            Domoticz.Error(f"Failed to fetch qualifying: {e}")
            return

        try:
            race_list = data["MRData"]["RaceTable"]["Races"]
            Domoticz.Log(f"Number of records for Qualify = {len(race_list)}")

            if not race_list:
                Domoticz.Log("No qualifying results available yet.")
                return

            qr = race_list[0]["QualifyingResults"]

            def to_sec(t):
                if not t:
                    return float("inf")
                parts = t.split(":")
                if len(parts) == 2:
                    return float(parts[0]) * 60 + float(parts[1])
                return float("inf")

            def get_best(result):
                driver = result["Driver"]["familyName"]
                con    = result["Constructor"]["name"]
                q1     = result.get("Q1", "")
                q2     = result.get("Q2", "")
                q3     = result.get("Q3", "")
                times  = [(to_sec(q1), q1), (to_sec(q2), q2), (to_sec(q3), q3)]
                best   = min(times, key=lambda x: x[0])[1] or q1
                return driver, con, best

            lines = []
            for i in range(min(6, len(qr))):
                drv, con, best = get_best(qr[i])
                Domoticz.Debug(f"P{i+1} Best = {best}")
                lines.append(f"{i+1}. {drv} ({con}) - {best}")

            q_text   = "\n".join(lines)
            prev_val = Devices[UNIT_QUALY].sValue

            Domoticz.Log(q_text)

            if q_text != prev_val:
                Devices[UNIT_QUALY].Update(nValue=0, sValue=q_text)
                Domoticz.Log("Qualifying device updated.")

        except (KeyError, IndexError) as e:
            Domoticz.Error(f"Error parsing qualifying data: {e}")

    # ------------------------------------------------------------------
    def onStop(self):
        Domoticz.Log("F1 Info plugin stopped.")


# Domoticz plugin entry points
_plugin = BasePlugin()

def onStart():           _plugin.onStart()
def onStop():            _plugin.onStop()
def onHeartbeat():       _plugin.onHeartbeat()
