"""Thin wrapper around the Trello REST API, with retry/backoff on HTTP 429, 5xx and
network errors.

Credentials go in the Authorization header, never in the URL, so that they cannot leak
into error messages or logs.
"""
import time

import requests

API = "https://api.trello.com/1"

FOCUS_CARD_FIELDS = "name,idList,pos,cardRole,mirrorSourceId,dueComplete,closed"
SOURCE_CARD_FIELDS = "name,idBoard,idList,due,start,dueComplete,shortUrl,cardRole,closed"


class TrelloError(Exception):
    def __init__(self, method, path, status, text):
        where = f"HTTP {status}" if status is not None else "network error"
        super().__init__(f"{method} {path} -> {where}: {text[:200]}")
        self.status = status


class TrelloClient:
    def __init__(self, key, token, session=None, max_retries=5, sleep=time.sleep):
        self.headers = {"Authorization": f'OAuth oauth_consumer_key="{key}", oauth_token="{token}"'}
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.sleep = sleep

    def request(self, method, path, **params):
        for attempt in range(self.max_retries + 1):
            last = attempt == self.max_retries
            try:
                r = self.session.request(method, f"{API}{path}", params=params,
                                         headers=self.headers, timeout=30)
            except (requests.ConnectionError, requests.Timeout) as e:
                # e.g. no network yet after waking up; the message never includes the URL
                if last:
                    raise TrelloError(method, path, None, type(e).__name__) from None
                self.sleep(2 ** attempt)
                continue
            if (r.status_code == 429 or r.status_code >= 500) and not last:
                self.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            if not r.ok:
                raise TrelloError(method, path, r.status_code, r.text)
            return r.json() if r.text else None

    # --- reads

    def open_boards(self):
        return self.request("GET", "/members/me/boards", fields="name", filter="open")

    def board_lists(self, board_id):
        return self.request("GET", f"/boards/{board_id}/lists", fields="name")

    def board_cards(self, board_id, fields, which="open"):
        return self.request("GET", f"/boards/{board_id}/cards/{which}", fields=fields)

    def list_cards(self, list_id, fields):
        return self.request("GET", f"/lists/{list_id}/cards", fields=fields)

    def card(self, card_id, fields):
        """One card, or None if it no longer exists."""
        try:
            return self.request("GET", f"/cards/{card_id}", fields=fields)
        except TrelloError as e:
            if e.status == 404:
                return None
            raise

    # --- writes

    def create_mirror(self, list_id, source_short_url, pos="bottom"):
        return self.request("POST", "/cards", idList=list_id, name=source_short_url,
                            cardRole="mirror", pos=pos)

    def update_card(self, card_id, **fields):
        fields = {k: str(v).lower() if isinstance(v, bool) else v for k, v in fields.items()}
        return self.request("PUT", f"/cards/{card_id}", **fields)

    def delete_card(self, card_id):
        return self.request("DELETE", f"/cards/{card_id}")
