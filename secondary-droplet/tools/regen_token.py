#!/usr/bin/env python3
# regen_token.py — headless local-server OAuth (SSH tunnel required if remote)
import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES=["https://www.googleapis.com/auth/youtube.readonly","https://www.googleapis.com/auth/youtube"]
CLIENT_SECRET="client_secret.json"
TOKEN="token.json"

def main():
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
    print("Abra este URL no seu browser:")
    print(flow.authorization_url(access_type='offline', include_granted_scopes='true')[0])
    creds = flow.run_local_server(port=8080, open_browser=False,
        authorization_prompt_message="Depois de autorizar, será redirecionado para http://localhost:8080 (via túnel SSH).")
    with open(TOKEN, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    print(f"[OK] Token gravado em {TOKEN}")
    yt=build("youtube","v3",credentials=creds, cache_discovery=False)
    me=yt.channels().list(part="id", mine=True, maxResults=1).execute()
    print("[WHOAMI] ->", me.get("pageInfo",{}), "items:", len(me.get("items",[])))

if __name__ == "__main__":
    main()
