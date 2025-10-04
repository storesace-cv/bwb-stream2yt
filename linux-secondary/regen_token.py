#!/usr/bin/env python3
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES=["https://www.googleapis.com/auth/youtube.readonly","https://www.googleapis.com/auth/youtube"]

def main():
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    creds = flow.run_local_server(port=8080, open_browser=True)
    with open("token.json","w",encoding="utf-8") as f:
        f.write(creds.to_json())
    print("[OK] token.json criado.")

    yt=build("youtube","v3",credentials=creds, cache_discovery=False)
    me = yt.channels().list(part="id", mine=True).execute()
    print("[WHOAMI]", me.get("pageInfo",{}))

if __name__=="__main__":
    main()
