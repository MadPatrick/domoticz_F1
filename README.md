# Domoticz F1 Race Info Plugin

A [Domoticz](https://www.domoticz.com/) plugin that displays the upcoming Formula 1 race weekend schedule as a text device.

## Description

This plugin fetches the F1 calendar from the [motorsportcalendars.com](https://files-f1.motorsportcalendars.com) ICS feed and displays the sessions of the next race weekend in a Domoticz Text device. The device name is automatically updated to reflect the location (Grand Prix name) of the upcoming race weekend.

Sessions are shown with their local date and time (adjusted for your UTC offset), for example:

```
Thu 22 May 17:30 : Practice 1
Fri 23 May 17:00 : Practice 2
Sat 24 May 17:00 : Practice 3
Sat 24 May 20:00 : Qualifying
Sun 25 May 15:00 : Grand Prix
```

## Installation

1. Copy or clone this repository into the Domoticz plugins folder:
   ```
   cd domoticz/plugins
   git clone https://github.com/MadPatrick/Domoticz_F1
   ```
2. Restart Domoticz.
3. Go to **Setup → Hardware** and add a new hardware item of type **F1 Race Info**.
4. Configure the settings (see below) and click **Add**.

## Settings

| Parameter | Description | Default |
|-----------|-------------|---------|
| **UTC offset in hours** | Your local UTC offset (e.g. `1` for CET, `2` for CEST). Used to convert session times from UTC to local time. | `1` |
| **Poll interval minutes** | How often (in minutes) the plugin fetches the calendar to check for updates. | `60` |
| **Show sessions** | Filter which sessions are displayed in the device. See options below. | Training / Sprint / Race |
| **Debug** | Enable or disable debug logging in the Domoticz log. | False |

### Show sessions options

| Option | Description |
|--------|-------------|
| **Training / Sprint / Race** | Show all sessions: practice, qualifying, sprint, and race. |
| **Sprint / Race** | Show only qualifying, sprint, and race sessions (hides practice/training). |
| **Race** | Show only the Grand Prix race session. |

## Device

The plugin creates one Domoticz device:

| Device name | Type | Description |
|-------------|------|-------------|
| *Grand Prix location* (e.g. `Monaco`) | Text | Lists the upcoming race weekend sessions with their local date and time. The device name automatically updates to the Grand Prix location. |

## Requirements

- Domoticz with Python plugin support enabled.
- Internet access to reach `files-f1.motorsportcalendars.com`.

## Version history

| Version | Notes |
|---------|-------|
| 0.1.3 | Current release |

## Author

[MadPatrick](https://github.com/MadPatrick)
