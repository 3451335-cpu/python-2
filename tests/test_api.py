"""Compare HTTP API responses to an independent in-memory model."""

from http import HTTPStatus
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic, sleep
from unittest.mock import patch

from hypothesis import settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, rule

from src.client import ApiClient
from src.server import ApiServer, credentials
from src.storage import FileStorage


NOW = 1_800_000_000
CUTOFF = NOW - 480
TEXT = st.text(alphabet="ABCабв<&", min_size=1, max_size=10)
DATA = st.sampled_from((
    '{"file_b64":"YWJj","salt_b64":"c2FsdA==","iterations":1}',
    '{"file_b64":"","salt_b64":"cw==","iterations":2}',
    "invalid",
))
POLL_TIMEOUT = 3
POLL_INTERVAL = 0.005
OK = HTTPStatus.OK
MISSING = HTTPStatus.NOT_FOUND
BAD = HTTPStatus.BAD_REQUEST


def fields(node):
    return {child.tag: child.text or "" for child in node}


def xml_values(row):
    return {key: str(value) for key, value in row.items()}


class ApiModel(RuleBasedStateMachine):
    """Exercise every route and keep expected records outside the server."""

    storage_type = FileStorage

    def __init__(self):
        super().__init__()
        self.directory = TemporaryDirectory()
        self.storage = self.storage_type(Path(self.directory.name) / "db")
        self.clock = patch("src.server.now", return_value=NOW)
        self.clock.start()
        self.server = ApiServer(
            ("127.0.0.1", 0), credentials("student", "pass:word"),
            self.storage, test_mode=True,
        )
        self.thread = Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.thread.start()
        url = f"http://127.0.0.1:{self.server.server_port}"
        self.api = ApiClient(url, "student", "pass:word")
        self.wrong = ApiClient(url, "student", "wrong")
        self.people = {}
        self.messages = {}
        self.feedback = {}

    def teardown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.clock.stop()
        self.storage.close()
        self.directory.cleanup()

    def check_row(self, result, tag, expected):
        status, root = result
        assert (status, root.tag) == (OK, tag)
        assert fields(root) == xml_values(expected)

    def check_list(self, result, expected, tag="results", item=None):
        status, root = result
        assert (status, root.tag) == (OK, tag)
        if item is not None:
            assert all(row.tag == item for row in root)
        actual = [fields(row) for row in root]
        wanted = [xml_values(row) for row in expected]
        assert sorted(map(sorted_fields, actual)) == sorted(
            map(sorted_fields, wanted)
        )

    def add_person(self, platform, agent):
        values = dict(platform=platform, user_agent=agent)
        result = self.api.public_api_new_person(**values)
        assert result[0] == OK
        key = int(result[1].findtext("key"))
        assert key not in self.people
        row = dict(values, key=key, datetime=NOW)
        self.people[key] = row
        self.check_row(result, "person", row)
        return key

    def add_message(self, person, data, stamp):
        values = dict(person=person, data=data, datetime=stamp)
        result = self.api.public_api_new_message(**values)
        assert result[0] == OK
        key = int(result[1].findtext("key"))
        assert key not in self.messages
        row = dict(values, key=key, tags="", started=NOW, done=NOW)
        self.messages[key] = row
        self.check_row(result, "message", dict(row, started=0, done=0))
        root = self.await_feedback(key)
        feedback_key = int(root[0].findtext("key"))
        assert feedback_key not in self.feedback
        self.feedback[feedback_key] = dict(
            key=feedback_key, message=key, datetime=NOW,
            response="test-mode", status="success", failure="",
        )
        self.check_feedback(key)
        return key

    def await_feedback(self, message):
        deadline = monotonic() + POLL_TIMEOUT
        while monotonic() < deadline:
            status, root = self.api.public_api_search_feedback(message)
            assert (status, root.tag) == (OK, "results")
            if len(root):
                assert len(root) == 1
                return root
            sleep(POLL_INTERVAL)
        raise AssertionError("feedback did not arrive")

    def check_feedback(self, message):
        rows = [row for row in self.feedback.values()
                if row["message"] == message]
        result = self.api.public_api_search_feedback(
            message, status="success"
        )
        self.check_list(result, rows, item="feedback")
        for row in rows:
            self.check_row(self.api.public_api_single_feedback(row["key"]),
                           "feedback", row)

    def check_person(self, key):
        person = self.people[key]
        self.check_row(self.api.public_api_single_person(key),
                       "person", person)
        platform = person["platform"]
        self.check_list(
            self.api.public_api_search_person(platform=platform),
            [row for row in self.people.values()
             if row["platform"] == platform], item="person",
        )

    def check_messages(self, person):
        rows = [row for row in self.messages.values()
                if row["person"] == person]
        self.check_list(self.api.public_api_search_message(person, tags=""),
                        rows, item="message")
        for row in rows:
            self.check_row(self.api.public_api_single_message(row["key"]),
                           "message", row)

    def check_report(self):
        projected = {
            (row["data"], self.people[row["person"]]["platform"])
            for row in self.messages.values()
            if row["datetime"] > CUTOFF
        }
        self.check_list(
            self.api.public_api_search_report(),
            [dict(data=data, platform=platform)
             for data, platform in projected], "report", "row",
        )

    def delete_message(self, key):
        result = self.api.public_api_terminate_message(key)
        self.check_row(result, "message", {"key": key})
        person = self.messages.pop(key)["person"]
        self.forget_feedback(key)
        assert self.api.public_api_single_message(key)[0] == MISSING
        self.check_feedback(key)
        self.check_messages(person)
        self.check_report()

    def forget_feedback(self, message):
        for key, row in list(self.feedback.items()):
            if row["message"] == message:
                del self.feedback[key]
                assert self.api.public_api_single_feedback(key)[0] == MISSING

    def delete_person(self, key):
        result = self.api.public_api_terminate_person(key)
        self.check_row(result, "person", {"key": key})
        del self.people[key]
        for message, row in list(self.messages.items()):
            if row["person"] == key:
                del self.messages[message]
                self.forget_feedback(message)
                result = self.api.public_api_single_message(message)
                assert result[0] == MISSING
        assert self.api.public_api_single_person(key)[0] == MISSING
        self.check_messages(key)
        self.check_report()

    @initialize(platform=TEXT, agent=TEXT, data=DATA)
    def exercise_routes(self, platform, agent, data):
        self.check_report()
        first = self.add_person(platform, agent)
        second = self.add_person(platform, agent)
        self.check_person(first)
        recent = self.add_message(first, data, CUTOFF + 1)
        self.add_message(second, data, NOW)
        self.add_message(first, "at boundary", CUTOFF)
        self.add_message(second, "outside window", CUTOFF - 1)
        self.check_messages(first)
        self.check_report()
        self.delete_message(recent)
        self.delete_person(first)

    @rule(platform=TEXT, agent=TEXT)
    def create_person(self, platform, agent):
        self.check_person(self.add_person(platform, agent))

    @rule(draw=st.data(), data=DATA, stamp=st.integers(CUTOFF - 5, NOW))
    def create_message(self, draw, data, stamp):
        if self.people:
            person = draw.draw(st.sampled_from(sorted(self.people)))
            self.add_message(person, data, stamp)
            self.check_messages(person)
        self.check_report()

    @rule(draw=st.data())
    def remove_person(self, draw):
        if self.people:
            self.delete_person(draw.draw(st.sampled_from(sorted(self.people))))

    @rule(draw=st.data())
    def remove_message(self, draw):
        if self.messages:
            keys = st.sampled_from(sorted(self.messages))
            self.delete_message(draw.draw(keys))

    @initialize(platform=TEXT, agent=TEXT, data=DATA)
    def cancel_pending(self, platform, agent, data):
        person = self.add_person(platform, agent)
        entered, release = Event(), Event()

        def blocked_compute(_data, _mode):
            entered.set()
            if not release.wait(POLL_TIMEOUT):
                raise AssertionError("worker was not released")
            return "test-mode", ""

        with patch("src.jobs.compute", side_effect=blocked_compute):
            try:
                running = self.submit_pending(person, data)
                assert entered.wait(POLL_TIMEOUT)
                queued = self.submit_pending(person, data)
                self.cancel(running)
                self.cancel(queued)
            finally:
                release.set()
        self.add_message(person, data, NOW)
        for key in (running, queued):
            self.check_list(self.api.public_api_search_feedback(key), [])

    def submit_pending(self, person, data):
        status, root = self.api.public_api_new_message(
            person=person, data=data,
        )
        assert (status, root.tag) == (OK, "message")
        assert root.findtext("done") == "0"
        return int(root.findtext("key"))

    def cancel(self, key):
        self.check_row(self.api.public_api_terminate_message(key),
                       "message", {"key": key})
        assert self.api.public_api_single_message(key)[0] == MISSING
        self.check_list(self.api.public_api_search_feedback(key), [])

    @initialize()
    def reject_errors(self):
        self.check_auth()
        self.check_bad_xml()
        invalid = [
            self.api.public_api_new_person(platform="missing agent"),
            self.api.public_api_new_message(person=-1, data="[1]"),
            self.api.public_api_new_message(person=-1),
            self.api.public_api_search_person(unknown="field"),
            self.api.public_api_search_person(datetime=2 ** 63),
            self.api.request("POST", "search/person", "wrong", {}),
            self.api.request("POST", "search/person"),
            self.api.request("GET", "single/person"),
            self.api.request("GET", "single/person/1/2"),
            self.api.request("GET", "unknown/person"),
        ]
        statuses = [BAD, MISSING, BAD, BAD, BAD, BAD, BAD, BAD,
                    MISSING, MISSING]
        assert [(status, xml.tag) for status, xml in invalid] == [
            (status, "error") for status in statuses
        ]

    def check_bad_xml(self):
        for raw in (
            b"<!DOCTYPE search><search/>",
            b"<search><platform><value/></platform></search>",
            b"<search><platform></search>",
        ):
            with patch("src.client.encode_xml", return_value=raw):
                status, root = self.api.public_api_search_person()
            assert (status, root.tag) == (BAD, "error")

    def check_auth(self):
        for value in ("Basic bad!", "Bearer wrong", self.wrong.auth):
            self.wrong.auth = value
            status, xml = self.wrong.public_api_search_report()
            assert (status, xml.tag) == (HTTPStatus.UNAUTHORIZED, "error")


def sorted_fields(row):
    return sorted(row.items())


TestFileApi = ApiModel.TestCase
TestFileApi.settings = settings(
    max_examples=30, stateful_step_count=14, deadline=None,
    derandomize=True,
)
