"""HTTP endpoints for variant 30."""

import argparse
import base64
import hmac
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Lock
from urllib.parse import parse_qs, urlsplit
from xml.etree.ElementTree import ParseError

from .jobs import Jobs, PENDING
from .protocol import CREATE, FIELDS, MAX_BODY, as_integer, encode_xml
from .protocol import xml_fields
from .storage import FileStorage


REPORT_WINDOW = 8 * 60
PREFIX = "/public/api/"
UNAUTHORIZED = HTTPStatus.UNAUTHORIZED
NOT_FOUND = HTTPStatus.NOT_FOUND
UNSCOPED_PARTS = 2
SCOPED_PARTS = 3
ROUTES = {
    ("POST", "new", "person", False): "create",
    ("DELETE", "terminate", "person", True): "terminate",
    ("POST", "search", "person", False): "search",
    ("GET", "single", "person", False): "single",
    ("POST", "new", "message", False): "create",
    ("DELETE", "terminate", "message", True): "terminate",
    ("POST", "search", "message", True): "search",
    ("GET", "single", "message", False): "single",
    ("POST", "search", "feedback", True): "search",
    ("GET", "single", "feedback", False): "single",
    ("POST", "search", "report", False): "report",
}
SCOPE = {"message": "person", "feedback": "message"}


class ApiError(Exception):
    """An error with an HTTP status."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def credentials(username, password):
    """Return the UTF-8 user-id/password octets."""
    return f"{username}:{password}".encode("utf-8")


def authorized(header, expected):
    """Validate the Basic authentication scheme and credential bytes."""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        actual = base64.b64decode(token.strip(), validate=True)
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


def now():
    return int(time.time())


def route(method, path):
    """Resolve a method and path according to table 30."""
    if not path.startswith(PREFIX):
        raise ApiError(NOT_FOUND, "route not found")
    parts = path[len(PREFIX):].split("/")
    if len(parts) not in (UNSCOPED_PARTS, SCOPED_PARTS):
        raise ApiError(NOT_FOUND, "route not found")
    action, entity, *tail = parts
    operation = ROUTES.get((method, action, entity, bool(tail)))
    if operation is None:
        raise ApiError(NOT_FOUND, "route not found")
    return operation, entity, as_integer(tail[0]) if tail else None


def required(values, fields):
    if not fields <= values.keys():
        raise ValueError("missing fields: " + ", ".join(
            sorted(fields - values.keys())
        ))


class Handler(BaseHTTPRequestHandler):
    """Dispatch XML requests to the configured data storage."""

    def dispatch(self):
        try:
            if not authorized(self.headers.get("Authorization", ""),
                              self.server.expected):
                raise ApiError(UNAUTHORIZED, "valid credentials required")
            url = urlsplit(self.path)
            operation, entity, key = route(self.command, url.path)
            with self.server.lock:
                tag, rows = getattr(self, operation)(entity, key, url.query)
        except ApiError as error:
            self.reply(error.status, "error", {"message": str(error)})
        except (ValueError, ParseError) as error:
            self.reply(HTTPStatus.BAD_REQUEST, "error",
                       {"message": str(error)})
        else:
            self.reply(HTTPStatus.OK, tag, rows)

    do_GET = dispatch
    do_POST = dispatch
    do_DELETE = dispatch

    def reply(self, status, tag, rows):
        body = encode_xml(tag, rows)
        self.send_response(status)
        if status == UNAUTHORIZED:
            self.send_header("WWW-Authenticate",
                             'Basic realm="Variant 30", charset="UTF-8"')
        self.send_header("Content-Type", "application/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_fields(self, tag, fields):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= MAX_BODY:
            raise ValueError("invalid XML body length")
        return xml_fields(self.rfile.read(length), tag, fields)

    def find(self, entity, key):
        row = self.server.storage.get(entity, key)
        if row is None:
            raise ApiError(NOT_FOUND, f"{entity} {key} not found")
        return row

    def create(self, entity, key, query):
        values = self.read_fields(entity, CREATE[entity])
        values.setdefault("datetime", now())
        if entity == "person":
            required(values, {"platform", "user_agent"})
            return entity, self.server.storage.add(entity, values)
        return entity, self.create_message(values)

    def create_message(self, values):
        required(values, {"person", "data"})
        self.find("person", values["person"])
        values.setdefault("tags", "")
        values.update(started=PENDING, done=PENDING)
        row = self.server.storage.add("message", values)
        self.server.jobs.submit(row["key"])
        return row

    def terminate(self, entity, key, query):
        self.find(entity, key)
        self.server.storage.delete(entity, key)
        return entity, {"key": key}

    def search(self, entity, key, query):
        scope = SCOPE.get(entity)
        fields = FIELDS[entity] - {scope}
        filters = self.read_fields("search", fields)
        if scope is not None:
            filters[scope] = key
        return "results", (entity, self.server.storage.search(entity, filters))

    def single(self, entity, key, query):
        params = parse_qs(query, keep_blank_values=True, strict_parsing=True)
        keys = params.get("key", [])
        if set(params) != {"key"} or len(keys) != 1:
            raise ValueError("expected exactly one key query parameter")
        return entity, self.find(entity, as_integer(keys[0]))

    def report(self, entity, key, query):
        rows = self.server.storage.report(now() - REPORT_WINDOW)
        return "report", ("row", rows)

    def log_message(self, format, *args):
        if not self.server.test_mode:
            super().log_message(format, *args)


class ApiServer(HTTPServer):
    """HTTP server with an injected storage engine and a test mode."""

    def __init__(self, address, auth, storage, test_mode=False):
        self.expected = auth
        self.storage = storage
        self.test_mode = test_mode
        self.lock = Lock()
        self.jobs = Jobs(storage, self.lock, now, test_mode)
        super().__init__(address, Handler)

    def serve_forever(self, poll_interval=0.5):
        self.jobs.start()
        try:
            super().serve_forever(poll_interval)
        finally:
            self.jobs.stop()


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("password")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default="variant30.shelf")
    parser.add_argument("--test-mode", action="store_true")
    args = parser.parse_args()
    if not args.username or ":" in args.username:
        parser.error("username must be nonempty and cannot contain ':'")
    return args


def main():
    args = arguments()
    storage = FileStorage(args.db)
    try:
        auth = credentials(args.username, args.password)
        with ApiServer((args.host, args.port), auth, storage,
                       args.test_mode) as server:
            print(f"Listening on http://{args.host}:{server.server_port}",
                  flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        storage.close()


if __name__ == "__main__":
    main()
