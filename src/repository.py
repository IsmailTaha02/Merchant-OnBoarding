"""Small storage ports with in-memory and AWS implementations."""
from __future__ import annotations
from copy import deepcopy
import os
import threading

class MemoryRepository:
    def __init__(self): self.rows = {}; self._lock=threading.RLock()
    def get(self, pk, sk):
        with self._lock: return deepcopy(self.rows.get((pk, sk)))
    def put(self, item, expected_version=None):
        key=(item["PK"],item["SK"])
        with self._lock:
            old=self.rows.get(key)
            if expected_version is not None and (not old or old.get("version") != expected_version): raise ConflictError("Application changed; reload and try again")
            self.rows[key]=deepcopy(item)
    def query(self, pk):
        with self._lock: return [deepcopy(v) for (p,_),v in self.rows.items() if p==pk]
    def commit_submission(self, application, submission, expected_version):
        key=(application["PK"],application["SK"])
        with self._lock:
            old=self.rows.get(key)
            if not old or old.get("version")!=expected_version or old.get("status")!="DRAFT": raise ConflictError("Application changed; reload and try again")
            self.rows[key]=deepcopy(application)
            self.rows[(submission["PK"],submission["SK"])]=deepcopy(submission)
    def create_application(self, application, idempotency=None):
        with self._lock:
            app_key=(application["PK"],application["SK"])
            idem_key=(idempotency["PK"],idempotency["SK"]) if idempotency else None
            if app_key in self.rows or (idem_key and idem_key in self.rows): raise ConflictError("Idempotency key already used")
            self.rows[app_key]=deepcopy(application)
            if idempotency: self.rows[idem_key]=deepcopy(idempotency)

class ConflictError(Exception): pass
class RepositoryLimitError(Exception): pass

class DynamoRepository:
    def __init__(self, table): self.table=table
    def get(self, pk, sk):
        result=self.table.get_item(Key={"PK":pk,"SK":sk},ConsistentRead=True)
        return result.get("Item")
    def put(self, item, expected_version=None):
        from decimal import Decimal
        def safe(value):
            if isinstance(value, float): return Decimal(str(value))
            if isinstance(value, dict): return {k:safe(v) for k,v in value.items()}
            if isinstance(value, list): return [safe(v) for v in value]
            return value
        item=safe(item)
        kwargs={"Item":item}
        if expected_version is not None:
            kwargs["ConditionExpression"]="attribute_exists(PK) AND #v = :v"
            kwargs["ExpressionAttributeNames"]={"#v":"version"}
            kwargs["ExpressionAttributeValues"]={":v":expected_version}
        elif item["SK"] == "META":
            kwargs["ConditionExpression"]="attribute_not_exists(PK)"
        try: self.table.put_item(**kwargs)
        except Exception as exc:
            if exc.__class__.__name__ == "ConditionalCheckFailedException": raise ConflictError("Application changed; reload and try again") from exc
            raise
    def query(self, pk):
        from boto3.dynamodb.conditions import Key
        result=self.table.query(KeyConditionExpression=Key("PK").eq(pk),ConsistentRead=True,Limit=101)
        if "LastEvaluatedKey" in result or len(result.get("Items", []))>100: raise RepositoryLimitError("Application has too many records for this prototype")
        return result.get("Items", [])
    def commit_submission(self, application, submission, expected_version):
        from decimal import Decimal
        from boto3.dynamodb.types import TypeSerializer
        serializer=TypeSerializer()
        def safe(value):
            if isinstance(value,float): return Decimal(str(value))
            if isinstance(value,dict): return {k:safe(v) for k,v in value.items()}
            if isinstance(value,list): return [safe(v) for v in value]
            return value
        item={k:serializer.serialize(v) for k,v in safe(submission).items()}
        status_history=serializer.serialize(safe(application.get("statusHistory",[])))
        try:
            self.table.meta.client.transact_write_items(TransactItems=[
                {"Update":{"TableName":self.table.name,"Key":{"PK":{"S":application["PK"]},"SK":{"S":"META"}},"UpdateExpression":"SET #status = :submitted, #version = :next, updatedAt = :updated, actorSource = :actor, actorSub = :actorSub, requestId = :request, statusHistory = :history","ConditionExpression":"#version = :expected AND #status = :draft","ExpressionAttributeNames":{"#status":"status","#version":"version"},"ExpressionAttributeValues":{":submitted":{"S":"SUBMITTED"},":draft":{"S":"DRAFT"},":next":{"N":str(application["version"])},":expected":{"N":str(expected_version)},":updated":{"S":application["updatedAt"]},":actor":{"S":application["actorSource"]},":actorSub":{"S":application["actorSub"]},":request":{"S":application["requestId"]},":history":status_history}}},
                {"Put":{"TableName":self.table.name,"Item":item}},
            ])
        except Exception as exc:
            if exc.__class__.__name__ in {"TransactionCanceledException","ConditionalCheckFailedException"}: raise ConflictError("Application changed; reload and try again") from exc
            raise
    def create_application(self, application, idempotency=None):
        if not idempotency:
            self.put(application)
            return
        from boto3.dynamodb.types import TypeSerializer
        serializer=TypeSerializer()
        items=[{"Put":{"TableName":self.table.name,"Item":{k:serializer.serialize(v) for k,v in application.items()},"ConditionExpression":"attribute_not_exists(PK)"}},
               {"Put":{"TableName":self.table.name,"Item":{k:serializer.serialize(v) for k,v in idempotency.items()},"ConditionExpression":"attribute_not_exists(PK)"}}]
        try: self.table.meta.client.transact_write_items(TransactItems=items)
        except Exception as exc:
            if exc.__class__.__name__ in {"TransactionCanceledException","ConditionalCheckFailedException"}: raise ConflictError("Idempotency key already used") from exc
            raise

def aws_clients():
    import boto3
    from botocore.config import Config
    cfg=Config(connect_timeout=2,read_timeout=3,retries={"max_attempts":0})
    region=os.environ.get("AWS_REGION")
    dynamodb=boto3.resource("dynamodb",region_name=region,config=cfg).Table(os.environ["TABLE_NAME"])
    s3=boto3.client("s3",region_name=region,config=cfg)
    return DynamoRepository(dynamodb),s3
