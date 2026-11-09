"""HTTP client with one method for each route in table 30."""

import base64
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from .protocol import encode_xml


class ApiClient:
    """Return the HTTP status and parsed XML for every request."""

    def __init__(self, url, username, password):
        self.url = url.rstrip("/")
        token = base64.b64encode(f"{username}:{password}".encode("utf-8"))
        self.auth = f"Basic {token.decode('ascii')}"

    def request(self, method, path, tag=None, fields=None):
        body = encode_xml(tag, fields) if tag is not None else None
        req = Request(self.url + "/public/api/" + path, body, method=method)
        req.add_header("Authorization", self.auth)
        if body is not None:
            req.add_header("Content-Type", "application/xml; charset=utf-8")
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.code, ET.fromstring(response.read())

    def public_api_new_person(self, **fields):
        return self.request("POST", "new/person", "person", fields)

    def public_api_terminate_person(self, key):
        return self.request("DELETE", f"terminate/person/{key}")

    def public_api_search_person(self, **filters):
        return self.request("POST", "search/person", "search", filters)

    def public_api_single_person(self, key):
        return self.request("GET", "single/person?" + urlencode({"key": key}))

    def public_api_new_message(self, **fields):
        return self.request("POST", "new/message", "message", fields)

    def public_api_terminate_message(self, key):
        return self.request("DELETE", f"terminate/message/{key}")

    def public_api_search_message(self, person, **filters):
        return self.request(
            "POST", f"search/message/{person}", "search", filters
        )

    def public_api_single_message(self, key):
        return self.request("GET", "single/message?" + urlencode({"key": key}))

    def public_api_search_feedback(self, message, **filters):
        return self.request(
            "POST", f"search/feedback/{message}", "search", filters
        )

    def public_api_single_feedback(self, key):
        return self.request(
            "GET", "single/feedback?" + urlencode({"key": key})
        )

    def public_api_search_report(self):
        return self.request("POST", "search/report")
