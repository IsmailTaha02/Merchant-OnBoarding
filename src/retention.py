"""Bounded cleanup for applications covered by an explicitly configured policy.

The default deployment policy is empty, which disables deletion until a retention
period has been approved. Each scheduled invocation handles at most one app.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

log=logging.getLogger()
log.setLevel(logging.INFO)
CURSOR_KEY={"PK":"SYSTEM#RETENTION","SK":"CURSOR"}
MAX_PAGE=100
MAX_S3_VERSIONS=500


def parse_policy(raw: str) -> dict[str,int]:
    try: policy=json.loads(raw or "{}")
    except (TypeError,ValueError) as exc: raise ValueError("RETENTION_POLICY_JSON must be a JSON object") from exc
    if not isinstance(policy,dict): raise ValueError("RETENTION_POLICY_JSON must be a JSON object")
    allowed={"DRAFT","SUBMITTED"}
    if set(policy)-allowed: raise ValueError("Retention policy supports only DRAFT and SUBMITTED statuses")
    for status,days in policy.items():
        if isinstance(days,bool) or not isinstance(days,int) or not 1<=days<=3650:
            raise ValueError(f"Retention days for {status} must be an integer from 1 to 3650")
    return policy


def _save_cursor(table, cursor):
    if cursor:
        table.put_item(Item={**CURSOR_KEY,"lastEvaluatedKey":cursor})
    else:
        table.delete_item(Key=CURSOR_KEY)


def _delete_app_data(table, s3, bucket: str, app_id: str, deadline: float) -> bool:
    """Delete S3 versions first, then DynamoDB children, and META last."""
    prefix=f"applications/{app_id}/"
    if time.monotonic()>=deadline: return False
    listing=s3.list_object_versions(Bucket=bucket,Prefix=prefix,MaxKeys=MAX_S3_VERSIONS)
    objects=[{"Key":x["Key"],"VersionId":x["VersionId"]} for x in [*listing.get("Versions",[]),*listing.get("DeleteMarkers",[])]]
    if objects:
        if time.monotonic()>=deadline: return False
        result=s3.delete_objects(Bucket=bucket,Delete={"Objects":objects,"Quiet":True})
        if result.get("Errors"): return False
    # Revisit this same application next run before dropping metadata if any
    # additional version pages remain (including an unusual empty truncated page).
    if listing.get("IsTruncated"): return False

    if time.monotonic()>=deadline: return False
    from boto3.dynamodb.conditions import Key
    response=table.query(KeyConditionExpression=Key("PK").eq(f"APP#{app_id}"),ConsistentRead=True,Limit=MAX_PAGE+1)
    rows=response.get("Items",[])
    if response.get("LastEvaluatedKey") or len(rows)>MAX_PAGE:
        log.error("retention_application_exceeds_record_cap status=deferred")
        return False
    children=[row for row in rows if row.get("SK")!="META"]
    client=table.meta.client
    for offset in range(0,len(children),25):
        if time.monotonic()>=deadline: return False
        requests=[{"DeleteRequest":{"Key":{"PK":{"S":row["PK"]},"SK":{"S":row["SK"]}}}} for row in children[offset:offset+25]]
        if not requests: continue
        result=client.batch_write_item(RequestItems={table.name:requests})
        if result.get("UnprocessedItems",{}).get(table.name): return False
    if time.monotonic()>=deadline: return False
    table.delete_item(Key={"PK":f"APP#{app_id}","SK":"META"})
    return True


def cleanup_one(table, s3, bucket: str, policy: dict[str,int], now: datetime, deadline: float) -> dict:
    if not policy: return {"status":"disabled","deleted":0}
    if now.tzinfo is None: raise ValueError("now must be timezone-aware")
    earliest=min(policy.values())
    cutoff=(now.astimezone(timezone.utc)-timedelta(days=earliest)).isoformat()
    cursor=table.get_item(Key=CURSOR_KEY,ConsistentRead=True).get("Item",{}).get("lastEvaluatedKey")
    from boto3.dynamodb.conditions import Attr
    kwargs={
        "FilterExpression":Attr("SK").eq("META") & Attr("status").is_in(list(policy)) & Attr("updatedAt").lt(cutoff),
        "ProjectionExpression":"#pk,#sk,#status,#updated",
        "ExpressionAttributeNames":{"#pk":"PK","#sk":"SK","#status":"status","#updated":"updatedAt"},
        "Limit":MAX_PAGE,
    }
    if cursor: kwargs["ExclusiveStartKey"]=cursor
    page=table.scan(**kwargs)
    next_cursor=page.get("LastEvaluatedKey")
    candidate=None
    for row in page.get("Items",[]):
        if time.monotonic()>=deadline: return {"status":"deadline","deleted":0}
        status=row.get("status"); days=policy.get(status)
        if not days: continue
        try: updated=datetime.fromisoformat(row["updatedAt"].replace("Z","+00:00"))
        except (KeyError,TypeError,ValueError): continue
        if updated.tzinfo is not None and updated.astimezone(timezone.utc)<=now.astimezone(timezone.utc)-timedelta(days=days):
            candidate=row; break
    if candidate:
        match=re.fullmatch(r"APP#([0-9a-f-]{36})",candidate.get("PK",""))
        if not match: return {"status":"invalid_record","deleted":0}
        app_id=match.group(1)
        if not _delete_app_data(table,s3,bucket,app_id,deadline):
            return {"status":"partial","deleted":0}
        _save_cursor(table,next_cursor)
        # Redacted log: no merchant or owner fields are read or emitted.
        log.info("retention_application_deleted status=%s request_id=scheduled",status)
        return {"status":"deleted","deleted":1}
    _save_cursor(table,next_cursor)
    return {"status":"scanned","deleted":0,"more":bool(next_cursor)}


def handler(event, context):
    started=time.monotonic(); deadline=started+30
    try:
        policy=parse_policy(os.environ.get("RETENTION_POLICY_JSON","{}"))
        if not policy: return {"status":"disabled","deleted":0}
        import boto3
        from botocore.config import Config
        cfg=Config(connect_timeout=2,read_timeout=3,retries={"max_attempts":0})
        table=boto3.resource("dynamodb",region_name=os.environ.get("AWS_REGION"),config=cfg).Table(os.environ["TABLE_NAME"])
        s3=boto3.client("s3",region_name=os.environ.get("AWS_REGION"),config=cfg)
        result=cleanup_one(table,s3,os.environ["DOCUMENT_BUCKET"],policy,datetime.now(timezone.utc),deadline)
        log.info("retention_sweep status=%s deleted=%s duration_ms=%s request_id=%s",result["status"],result["deleted"],round((time.monotonic()-started)*1000),getattr(context,"aws_request_id","scheduled"))
        return result
    except Exception as exc:
        log.error("retention_sweep_failed exception_type=%s duration_ms=%s request_id=%s",type(exc).__name__,round((time.monotonic()-started)*1000),getattr(context,"aws_request_id","scheduled"))
        raise
