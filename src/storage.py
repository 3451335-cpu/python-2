"""File-backed storage for the three API entities."""

import shelve
from dbm import dumb

PARENT = {"message": "person", "feedback": "message"}


class FileStorage:
    """Store records and identifiers in a standard-library shelf."""

    def __init__(self, path):
        self.shelf = shelve.Shelf(dumb.open(str(path)))
        self.rows, self.keys = self.shelf.get("state", ({}, {}))

    def close(self):
        self.shelf.close()

    def save(self):
        self.shelf["state"] = self.rows, self.keys
        self.shelf.sync()

    def add(self, entity, values):
        row = self.insert(entity, values)
        self.save()
        return row.copy()

    def insert(self, entity, values):
        key = self.keys.get(entity, 0) + 1
        self.keys[entity] = key
        row = dict(values, key=key)
        self.rows.setdefault(entity, {})[key] = row
        return row

    def start_message(self, key, stamp):
        self.rows["message"][key]["started"] = stamp
        self.save()

    def finish_message(self, key, feedback):
        self.rows["message"][key]["done"] = feedback["datetime"]
        self.insert("feedback", dict(feedback, message=key))
        self.save()

    def get(self, entity, key):
        row = self.rows.get(entity, {}).get(key)
        return row.copy() if row is not None else None

    def delete(self, entity, key):
        self.remove(entity, key)
        self.save()

    def remove(self, entity, key):
        self.rows[entity].pop(key)
        for child, parent in PARENT.items():
            if parent == entity:
                for row in self.search(child, {parent: key}):
                    self.remove(child, row["key"])

    def search(self, entity, filters):
        return [
            row.copy()
            for row in self.rows.get(entity, {}).values()
            if all(row[field] == value for field, value in filters.items())
        ]

    def report(self, cutoff):
        pairs = {
            (row["data"], self.get("person", row["person"])["platform"])
            for row in self.search("message", {})
            if row["datetime"] > cutoff
        }
        return [
            dict(data=data, platform=platform)
            for data, platform in sorted(pairs)
        ]
