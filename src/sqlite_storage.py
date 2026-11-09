"""SQLite data access with SQLAlchemy ORM."""

from sqlalchemy import ForeignKey, URL, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    """Common declarative base for the three entities."""

    key: Mapped[int] = mapped_column(primary_key=True)
    datetime: Mapped[int]
    __table_args__ = {"sqlite_autoincrement": True}

    def record(self):
        return {column.key: getattr(self, column.key)
                for column in self.__table__.columns}


class Person(Base):
    """Client platform and user agent."""

    __tablename__ = "person"
    platform: Mapped[str]
    user_agent: Mapped[str]


class Message(Base):
    """Task input and execution timestamps."""

    __tablename__ = "message"
    data: Mapped[str]
    person: Mapped[int] = mapped_column(
        ForeignKey("person.key", ondelete="CASCADE"), index=True,
    )
    tags: Mapped[str]
    done: Mapped[int]
    started: Mapped[int]


class Feedback(Base):
    """Execution result for a message."""

    __tablename__ = "feedback"
    response: Mapped[str]
    status: Mapped[str]
    failure: Mapped[str]
    message: Mapped[int] = mapped_column(
        ForeignKey("message.key", ondelete="CASCADE"), index=True,
    )


MODELS = {"person": Person, "message": Message, "feedback": Feedback}


def enforce_foreign_keys(connection, _record):
    connection.execute("PRAGMA foreign_keys=ON")


class SQLiteStorage:
    """Persist each write in a transaction and query with ORM models."""

    def __init__(self, path):
        url = URL.create("sqlite", database=str(path))
        self.engine = create_engine(url)
        event.listen(self.engine, "connect", enforce_foreign_keys)
        Base.metadata.create_all(self.engine)

    def close(self):
        self.engine.dispose()

    def add(self, entity, values):
        with Session(self.engine) as session, session.begin():
            item = MODELS[entity](**values)
            session.add(item)
            session.flush()
            return item.record()

    def start_message(self, key, stamp):
        with Session(self.engine) as session, session.begin():
            session.get(Message, key).started = stamp

    def finish_message(self, key, feedback):
        with Session(self.engine) as session, session.begin():
            session.get(Message, key).done = feedback["datetime"]
            session.add(Feedback(message=key, **feedback))

    def get(self, entity, key):
        with Session(self.engine) as session:
            item = session.get(MODELS[entity], key)
            return item.record() if item is not None else None

    def delete(self, entity, key):
        with Session(self.engine) as session, session.begin():
            session.delete(session.get(MODELS[entity], key))

    def search(self, entity, filters):
        model = MODELS[entity]
        query = select(model).filter_by(**filters).order_by(model.key)
        with Session(self.engine) as session:
            return [item.record() for item in session.scalars(query)]

    def report(self, cutoff):
        query = (
            select(Message.data, Person.platform)
            .join(Person, Person.key == Message.person)
            .where(Message.datetime > cutoff)
            .distinct()
            .order_by(Message.data, Person.platform)
        )
        with Session(self.engine) as session:
            return [dict(row) for row in session.execute(query).mappings()]
