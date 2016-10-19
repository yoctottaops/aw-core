from typing import Optional, List
from datetime import datetime
import json

from peewee import Model, CharField, DateTimeField
from peewee import *
from playhouse.sqlite_ext import SqliteExtDatabase

from aw_core.models import Event

from . import logger, AbstractStorage

# TODO: Make dependent on testing variable in constructor
db = SqliteExtDatabase('peewee-sqlite.db')


class BaseModel(Model):
    class Meta:
        database = db


class BucketModel(BaseModel):
    id = CharField(unique=True)
    created = DateTimeField(default=datetime.now)
    name = CharField(null=True)
    type = CharField()
    client = CharField()
    hostname = CharField()

    def json(self):
        return {"id": self.id, "created": self.created,
                "name": self.name, "type": self.type, "client": self.client,
                "hostname": self.hostname}


class EventModel(BaseModel):
    bucket_id = CharField(index=True)
    timestamp = DateTimeField(index=True, default=datetime.now)
    jsonstr = CharField()

    @classmethod
    def from_event(cls, bucket_id, event: Event):
        return cls(bucket_id=bucket_id, timestamp=event.timestamp, jsonstr=event.to_json_str())

    def json(self):
        return json.loads(self.jsonstr)


class PeeweeStorage(AbstractStorage):
    def __init__(self, testing):
        self.logger = logger.getChild("peewee")
        db.connect()
        db.create_tables([BucketModel, EventModel])

    def buckets(self):
        buckets = {bucket.id: bucket.json() for bucket in BucketModel.select()}
        return buckets

    def create_bucket(self, bucket_id: str, type: str, client: str, hostname: str,
                      created: datetime, name: str):
        BucketModel.create(id=bucket_id, type=type, client=client,
                           hostname=hostname, created=created, name=name)

    def delete_bucket(self, bucket_id: str):
        BucketModel.delete().where(BucketModel.id == bucket_id).execute()
        EventModel.delete().where(EventModel.bucket_id == bucket_id).execute()

    def get_metadata(self, bucket_id: str):
        return BucketModel.get(BucketModel.id == bucket_id).json()

    def insert_one(self, bucket_id: str, event: Event):
        e = EventModel.from_event(bucket_id, event)
        e.save()

    def insert_many(self, bucket_id, events: List[Event]):
        event_models = map(lambda e: EventModel.from_event(bucket_id, e), events)
        # TODO: Do in a transaction
        for e in event_models:
            e.save()

    def replace_last(self, bucket_id, event):
        e = EventModel.select().order_by(EventModel.timestamp.desc()).limit(1).get()
        e.timestamp = event.timestamp
        e.jsonstr = event.to_json_str()
        e.save()

    def get_events(self, bucket_id: str, limit: int,
                   starttime: Optional[datetime]=None, endtime: Optional[datetime]=None):
        """Returns events in sorted order (latest first)"""
        q = EventModel.select() \
                      .where(EventModel.bucket_id == bucket_id) \
                      .order_by(EventModel.timestamp.desc()) \
                      .limit(limit)
        if starttime:
            q = q.where(starttime < EventModel.timestamp)
        if endtime:
            q = q.where(EventModel.timestamp < endtime)
        return [Event(**e) for e in list(map(EventModel.json, q.execute()))]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        # Save (commit) the changes
        self.conn.commit()

        # We can also close the connection if we are done with it.
        # Just be sure any changes have been committed or they will be lost.
        self.conn.close()
