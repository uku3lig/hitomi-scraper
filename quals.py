from __future__ import print_function

import itertools
import json
import os.path
import sys

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

TOKEN_FILE = 'token.json'
CREDENTIALS_FILE = 'credentials.json'

MAPS_AMOUNT = 10


def get_sheet_data(spreadsheet_id: str, range_name: str, scopes: [str]) -> [[str]]:
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, scopes)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, scopes)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())

    try:
        print(f"getting google sheet info on range `{range_name}`")
        service = build('sheets', 'v4', credentials=creds)

        # Call the Sheets API
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
        return result.get('values', [])
    except HttpError as err:
        print(err)
        sys.exit(1)


def get_player_data(player: int) -> dict:
    with open("osu-token.txt", "r") as f:
        token = f.readline()
        response = requests.get(f"https://osu.ppy.sh/api/get_user?k={token}&u={player}&m=0").json()
        return response[0]


def get_z_sums(values: [[str]]) -> [float]:
    for row in [r for r in values if len(r) == MAPS_AMOUNT]:
        yield sum([float(e) for e in row]) / MAPS_AMOUNT


def get_teams(values: [[str]], sums: [[str]], players: [[str]]) -> [object]:
    mods = [m[0:2] for m in values[0]]
    ids = values[1]
    sums_avg = list(get_z_sums(sums))

    # first 2 rows are mods (NM1 etc.) and each row has team name + each map score (MAPS + 1)
    for row, z_sum in zip([r for r in values[2:] if len(r) == (MAPS_AMOUNT + 1)], sums_avg):
        player_ids = [int(team_info[1]) for team_info in players if team_info[0] == row[0]]
        player_infos = []
        for player in player_ids:
            data = get_player_data(player)
            print(f"getting player info for {data['username']}")
            player_infos.append({
                "id": player,
                "Rank": int(data["pp_rank"]),
                "country_code": data["country"],
                "Username": data["username"],
                "CoverUrl": "https://example.com"
            })

        seeding_results = []
        # groups maps by mod, skips first column (= team name)
        # tpl is the (int, str) tuple given by enumerate, tpl[0] = column index
        groups = itertools.groupby(enumerate(row[1:], start=1), key=lambda tpl: mods[tpl[0]])
        for mod, scores in groups:
            beatmaps = []
            for bi, score in scores:
                # bi <=> tpl[0]
                beatmaps.append({
                    "ID": int(ids[bi]),
                    "Seed": -1,
                    "Score": int(score)
                })
            seeding_results.append({
                "Mod": mod,
                "Seed": -1,
                "Beatmaps": beatmaps
            })
        yield {
            "FullName": row[0],
            "Seed": -1,
            "_ZSUM": z_sum,
            "SeedingResults": seeding_results,
            "Players": player_infos,
            "FlagName": player_infos[0]["country_code"]
        }


def main():
    spreadsheet_id = '13scxhWmkQrXd23kIB-nC_vfXMrf78791vM5qXj2frVc'
    scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly']

    values = get_sheet_data(spreadsheet_id, 'Quals Calcs!AM:AW', scopes)
    sums = get_sheet_data(spreadsheet_id, 'Quals Calcs!BT3:CC', scopes)
    players = get_sheet_data(spreadsheet_id, 'Quals Calcs!E3:F', scopes)

    if not values or not sums:
        print('No data found.')
        return

    teams = list(get_teams(values, sums, players))
    teams = sorted(teams, key=lambda t: t["_ZSUM"], reverse=True)

    mod_sums = {mod: [] for mod in ["NM", "HD", "HR", "DT"]}
    map_sums = {map_id: [] for map_id in values[1][1:]}

    for team in teams:
        for result in team["SeedingResults"]:
            mod_scores = [b["Score"] for b in result["Beatmaps"]]
            mod_sums[result["Mod"]].append(sum(mod_scores))
            for m in result["Beatmaps"]:
                map_sums[str(m["ID"])].append(m["Score"])

    for mod, mod_sum in mod_sums.items():
        mod_sums[mod] = sorted(mod_sum, reverse=True)

    for b_id, map_sum in map_sums.items():
        map_sums[b_id] = sorted(map_sum, reverse=True)

    for i, team in enumerate(teams):
        team["Seed"] = i + 1
        for result in team["SeedingResults"]:
            mod_score = sum([b["Score"] for b in result["Beatmaps"]])
            result["Seed"] = mod_sums[result["Mod"]].index(mod_score) + 1
            for beatmap in result["Beatmaps"]:
                beatmap["Seed"] = map_sums[str(beatmap["ID"])].index(beatmap["Score"]) + 1

    with open("bracket.json", "r") as f:
        bracket = json.load(f)
        bracket["Teams"] = teams
        with open("bracket_new.json", "w") as new:
            json.dump(bracket, new, indent=2)


if __name__ == '__main__':
    main()
