"""AWS Lambda HTTP API entry point. Stateless orchestration with bounded calls."""
from __future__ import annotations
import base64, json, logging, os, re, time, uuid
from datetime import datetime, timezone
from decimal import Decimal
from domain import (ALLOWED_TYPES, MAX_DOCUMENT_BYTES, MAX_DOCUMENT_RECORDS, MAX_EVALUATION_RECORDS, MCCS, ValidationError,
                    evaluate, policy_providers, policy_tags, risk_policy_version, suggest_mcc, submission_payload,
                    utc_now, validate_application_id, validate_patch)
from repository import ConflictError, DynamoRepository, MemoryRepository, RepositoryLimitError, aws_clients
from statement import parse_statement

log=logging.getLogger(); log.setLevel(logging.INFO)
_memory=MemoryRepository()
_repo=_memory; _s3=None

def configure(repo, s3=None):
    global _repo,_s3
    _repo,_s3=repo,s3

def _response(status, body):
    def clean(v):
        if isinstance(v, Decimal): return float(v)
        if isinstance(v, dict): return {k:clean(x) for k,x in v.items()}
        if isinstance(v, list): return [clean(x) for x in v]
        return v
    return {"statusCode":status,"headers":{"content-type":"application/json","cache-control":"no-store","x-content-type-options":"nosniff","x-frame-options":"DENY","referrer-policy":"no-referrer","strict-transport-security":"max-age=31536000","content-security-policy":"default-src 'none'; frame-ancestors 'none'; base-uri 'none'","permissions-policy":"camera=(), microphone=(), geolocation=()"},"body":json.dumps(clean(body),separators=(",",":"))}

def _emit_request_metrics(method: str, status: int, duration_ms: int):
    """Emit low-cardinality CloudWatch Embedded Metric Format; never include app or user data."""
    metric={
        "_aws":{"Timestamp":int(time.time()*1000),"CloudWatchMetrics":[{"Namespace":"GWEB/MerchantOnboarding","Dimensions":[["Method","StatusCode"]],"Metrics":[{"Name":"RequestCount","Unit":"Count"},{"Name":"DurationMs","Unit":"Milliseconds"},{"Name":"ErrorCount","Unit":"Count"}]}]},
        "Method":method,"StatusCode":str(status),"RequestCount":1,"DurationMs":duration_ms,"ErrorCount":1 if status>=400 else 0,
    }
    # Keep EMF as a standalone JSON stdout event so CloudWatch can extract it
    # even when Lambda's managed logger wraps standard logging records as JSON.
    print(json.dumps(metric,separators=(",",":")))

def _body(event):
    raw=event.get("body") or "{}"
    if not isinstance(raw,str): raise ValidationError("Request body must be text")
    if len(raw)>88_000: raise ValidationError("Request body is too large")
    if event.get("isBase64Encoded"):
        try: raw=base64.b64decode(raw,validate=True).decode("utf-8")
        except (ValueError,UnicodeDecodeError): raise ValidationError("Request body must be valid base64-encoded UTF-8")
    if len(raw.encode("utf-8"))>64_000: raise ValidationError("Request body is too large")
    try: value=json.loads(raw)
    except (ValueError,TypeError): raise ValidationError("Request body must be valid JSON")
    if not isinstance(value,dict): raise ValidationError("Request body must be a JSON object")
    return value

def _app(app_id):
    validate_application_id(app_id)
    item=_repo.get(f"APP#{app_id}","META")
    if not item: return None
    return item

def _docs(app_id):
    return [r for r in _repo.query(f"APP#{app_id}") if r.get("SK","").startswith("DOC#")]

def _audit(event):
    context=event.get("requestContext",{})
    request_id=context.get("requestId") or "local-request"
    claims=context.get("authorizer",{}).get("jwt",{}).get("claims",{})
    subject=claims.get("sub")
    return {"actorSource":"cognito-authenticated-api" if subject else "local-test","actorSub":str(subject)[:128] if subject else None,"requestId":str(request_id)[:128]}

class AuthenticationError(Exception):
    pass

def _principal(event):
    """Return the authenticated Cognito subject; fail closed if auth context is absent."""
    claims=(event.get("requestContext",{}).get("authorizer",{}).get("jwt",{}).get("claims",{}))
    subject=claims.get("sub")
    if not isinstance(subject,str) or not subject.strip():
        raise AuthenticationError("Authentication is required")
    return subject

def _is_reviewer(event):
    claims=event.get("requestContext",{}).get("authorizer",{}).get("jwt",{}).get("claims",{})
    groups=claims.get("cognito:groups",[])
    if isinstance(groups,str): groups=[groups]
    return isinstance(groups,list) and "underwriting-reviewer" in groups

def _touch(item,event):
    item["updatedAt"]=utc_now()
    item.update(_audit(event))
    return item

def _history(status,event,previous=None):
    return {"from":previous,"to":status,"at":utc_now(),**_audit(event)}

def _route(method,path,event):
    path=re.sub(r"/+$","",path) or "/"
    if method=="POST" and path=="/v1/applications":
        body=_body(event); idem=body.get("idempotencyKey"); principal=_principal(event)
        if idem and (not isinstance(idem,str) or len(idem)>128): raise ValidationError("Invalid idempotency key")
        if idem:
            idem_id=str(uuid.uuid5(uuid.NAMESPACE_URL,principal+":"+idem))
            found=_repo.get(f"IDEMPOTENCY#{idem_id}","META")
            if found: return 200,{"applicationId":found["applicationId"],"resumed":True}
        app_id=str(uuid.uuid4()); audit=_audit(event); created=utc_now(); item={"PK":f"APP#{app_id}","SK":"META","applicationId":app_id,"ownerSub":principal,"status":"DRAFT","version":1,"createdAt":created,"updatedAt":created,**audit,"statusHistory":[{"from":None,"to":"DRAFT","at":created,**audit}]}
        idem_item={"PK":f"IDEMPOTENCY#{idem_id}","SK":"META","applicationId":app_id,"expiresAt":int(time.time())+86400} if idem else None
        try: _repo.create_application(item,idem_item)
        except ConflictError:
            if idem:
                found=_repo.get(idem_item["PK"],idem_item["SK"])
                if found: return 200,{"applicationId":found["applicationId"],"resumed":True}
            raise
        return 201,{"applicationId":app_id,"status":"DRAFT","version":1}
    if method=="GET" and path=="/v1/mcc":
        query=(event.get("queryStringParameters") or {}).get("query") or ""
        if not isinstance(query,str): raise ValidationError("MCC search query must be text")
        query=query.strip().lower()
        results=[r for r in MCCS if not query or query in (r["code"]+" "+r["description"]+" "+" ".join(r["keywords"])).lower()]
        return 200,{"items":results[:50]}
    match=re.fullmatch(r"/v1/applications/([^/]+)(.*)",path)
    if not match: return 404,{"error":"not_found","message":"Route not found"}
    app_id,suffix=match.groups(); item=_app(app_id); principal=_principal(event)
    review_route=bool(re.fullmatch(r"/documents/([^/]+)/review",suffix))
    reviewer=_is_reviewer(event)
    if item is None or (item.get("ownerSub")!=principal and not (reviewer and (method=="GET" or review_route))): return 404,{"error":"not_found","message":"Application not found"}
    if item.get("status")=="SUBMITTED" and method in {"PATCH","POST"} and not review_route:
        raise ConflictError("This application has been submitted and is locked")
    if method=="GET" and suffix=="":
        records=_repo.query(f"APP#{app_id}"); docs=[x for x in records if x.get("SK","").startswith("DOC#")]
        evals=sorted([x for x in records if x.get("SK","").startswith("EVAL#")],key=lambda x:x.get("createdAt",""))
        return 200,{"applicationId":app_id,"status":item["status"],"version":item["version"],"createdAt":item["createdAt"],"updatedAt":item["updatedAt"],"actorSource":item.get("actorSource"),"actorSub":item.get("actorSub"),"requestId":item.get("requestId"),"statusHistory":item.get("statusHistory",[]),"applicant":item.get("applicant",{}),"business":item.get("business",{}),"documents":docs,"classification":item.get("classification"),"evaluation":evals[-1].get("result") if evals else None}
    if method=="GET" and suffix=="/evaluation":
        evals=sorted([x for x in _repo.query(f"APP#{app_id}") if x.get("SK","").startswith("EVAL#")],key=lambda x:x.get("createdAt",""))
        return (200,{"evaluation":evals[-1]["result"]}) if evals else (404,{"error":"not_found","message":"No evaluation yet"})
    if method=="POST" and suffix=="/statement/parse":
        body=_body(event)
        result=parse_statement(body.get("text")); normalized=result["normalized"]
        business=dict(item.get("business",{})); business.update({k:normalized[k] for k in ("processor","statementPeriod","currentMonthlyVolume","currentFees") if normalized.get(k) is not None}); business["statementExtraction"]={k:v for k,v in normalized.items() if k not in {"processor","statementPeriod","currentMonthlyVolume","currentFees"}}
        next_item=dict(item); next_item["business"]=business; next_item["version"]=item["version"]+1; _touch(next_item,event); _repo.put(next_item,expected_version=item["version"])
        return 200,result
    if method=="PATCH" and suffix in ("/applicant","/business"):
        section=suffix[1:]; patch=validate_patch(section,_body(event))
        if section=="business":
            merged_business={**item.get("business",{}),**patch}
            channel_fields={key:merged_business[key] for key in ("cardPresentPercent","cardNotPresentPercent","ecommercePercent") if key in merged_business}
            if channel_fields: validate_patch("business",channel_fields)
        if section=="applicant" and "beneficialOwners" in patch:
            next_ids={owner["ownerId"] for owner in patch["beneficialOwners"]}
            removed_ids={owner.get("ownerId") for owner in item.get("applicant",{}).get("beneficialOwners",[])}-next_ids
            linked_ids={doc.get("ownerId") for doc in _docs(app_id) if doc.get("documentType")=="government_id" and doc.get("ownerId")}
            if removed_ids & linked_ids: raise ConflictError("A person with an uploaded government ID cannot be removed until its documents are deleted through an authorized retention workflow")
        next_item=dict(item); next_item[section]={**item.get(section,{}),**patch}; next_item["version"]=item["version"]+1; _touch(next_item,event); _repo.put(next_item,expected_version=item["version"])
        return 200,{"version":next_item["version"],section:next_item[section]}
    if method=="POST" and suffix=="/documents/presign":
        if len(_docs(app_id))>=MAX_DOCUMENT_RECORDS:
            raise ValidationError(f"An application can contain at most {MAX_DOCUMENT_RECORDS} document records")
        body=_body(event); kind=body.get("documentType"); mime=body.get("contentType"); size=body.get("sizeBytes")
        if kind not in {"government_id","business_registration","business_license","bank_evidence","processing_statement","additional_evidence"}: raise ValidationError("Unsupported document type")
        owner_id=body.get("ownerId","primary")
        reason_requested=body.get("reasonRequested")
        if kind=="additional_evidence":
            if not isinstance(reason_requested,str) or not reason_requested.strip() or len(reason_requested)>500:
                raise ValidationError("Explain why the additional underwriting evidence is being provided")
        if kind=="government_id":
            known={owner.get("ownerId") for owner in item.get("applicant",{}).get("beneficialOwners",[])}
            if owner_id!="primary" and owner_id not in known: raise ValidationError("Government ID must be linked to an applicant or saved beneficial owner")
        elif "ownerId" in body: raise ValidationError("Only government ID documents can be linked to a person")
        if mime not in ALLOWED_TYPES: raise ValidationError("Only PDF, JPEG, or PNG files are allowed")
        file_name=body.get("fileName")
        if not isinstance(file_name,str) or len(file_name)>255 or not re.fullmatch(r"[^/\\]+\.(?:pdf|jpe?g|png)",file_name,re.IGNORECASE): raise ValidationError("A valid PDF, JPG, or PNG file name is required")
        extension=file_name.rsplit(".",1)[1].lower()
        expected_type={"pdf":"application/pdf","jpg":"image/jpeg","jpeg":"image/jpeg","png":"image/png"}[extension]
        if mime!=expected_type: raise ValidationError("File extension does not match the declared content type")
        try: size=int(size)
        except (TypeError,ValueError): raise ValidationError("File size is required")
        if size<1 or size>MAX_DOCUMENT_BYTES: raise ValidationError("File must be at most 10 MB")
        doc_id=str(uuid.uuid4()); key=f"applications/{app_id}/{doc_id}"; checksum=body.get("checksumSha256")
        if _s3:
            if not isinstance(checksum,str) or not re.fullmatch(r"[A-Za-z0-9+/]{43}=",checksum): raise ValidationError("A SHA-256 file checksum is required")
            fields={"Content-Type":mime,"x-amz-checksum-algorithm":"SHA256","x-amz-checksum-sha256":checksum}
            conditions=[["content-length-range",1,MAX_DOCUMENT_BYTES],{"Content-Type":mime},{"x-amz-checksum-algorithm":"SHA256"},{"x-amz-checksum-sha256":checksum}]
            result=_s3.generate_presigned_post(Bucket=os.environ["DOCUMENT_BUCKET"],Key=key,Fields=fields,Conditions=conditions,ExpiresIn=300)
            upload={"url":result["url"],"fields":result["fields"]}
        else: upload={"url":"","fields":{},"demo":True}
        created=utc_now(); doc={"PK":f"APP#{app_id}","SK":f"DOC#{doc_id}","documentId":doc_id,"documentType":kind,"contentType":mime,"fileExtension":extension,"sizeBytes":size,"checksumSha256":checksum,"s3Key":key,"status":"UPLOADING","reviewStatus":"PENDING_REVIEW","version":1,"createdAt":created,"uploadExpiresAt":int(time.time())+300,"statusHistory":[{"from":None,"to":"UPLOADING","at":created,**_audit(event)}],**_audit(event)}
        if kind=="government_id": doc["ownerId"]=owner_id
        if kind=="additional_evidence": doc["reasonRequested"]=reason_requested.strip()
        _repo.put(doc)
        return 201,{"documentId":doc_id,"upload":upload,"expiresInSeconds":300,"status":"UPLOADING"}
    complete=re.fullmatch(r"/documents/([^/]+)/complete",suffix)
    if method=="POST" and complete:
        doc_id=complete.group(1); doc=_repo.get(f"APP#{app_id}",f"DOC#{doc_id}")
        if not doc: return 404,{"error":"not_found","message":"Document not found"}
        if doc.get("status")!="UPLOADING":
            if any(row.get("to")=="RECEIVED" for row in doc.get("statusHistory",[])):
                return 200,{"documentId":doc_id,"status":doc.get("status"),"resumed":True}
            raise ConflictError("This document is no longer awaiting upload completion")
        if int(time.time())>int(doc.get("uploadExpiresAt",0)):
            doc["statusHistory"]=[*doc.get("statusHistory",[]),_history("UPLOAD_EXPIRED",event,doc.get("status"))]; doc["status"]="UPLOAD_EXPIRED"; doc.update(_audit(event)); _repo.put(doc)
            return 410,{"error":"upload_expired","message":"The upload window expired. Request a new upload link and try again."}
        if _s3:
            obj=_s3.head_object(Bucket=os.environ["DOCUMENT_BUCKET"],Key=doc["s3Key"],ChecksumMode="ENABLED")
            if obj["ContentLength"]!=doc["sizeBytes"] or obj.get("ContentType")!=doc["contentType"]: raise ValidationError("Uploaded file does not match the declared size or type")
            if obj.get("ChecksumSHA256")!=doc.get("checksumSha256"): raise ValidationError("Uploaded file checksum does not match")
            sample=_s3.get_object(Bucket=os.environ["DOCUMENT_BUCKET"],Key=doc["s3Key"],VersionId=obj.get("VersionId"),Range="bytes=0-7")["Body"].read(8)
            signatures={"application/pdf":sample.startswith(b"%PDF-"),"image/jpeg":sample.startswith(b"\xff\xd8\xff"),"image/png":sample.startswith(b"\x89PNG\r\n\x1a\n")}
            if not signatures.get(doc["contentType"],False): raise ValidationError("File contents do not match the selected file type")
            doc["etag"]=obj.get("ETag","").strip('"'); doc["versionId"]=obj.get("VersionId","")
        for previous in _docs(app_id):
            same_person=(previous.get("ownerId") or "primary")== (doc.get("ownerId") or "primary")
            if previous.get("documentId")!=doc_id and previous.get("documentType")==doc.get("documentType") and same_person and previous.get("status") in {"RECEIVED","NEEDS_REVIEW","ACCEPTED"}:
                previous["statusHistory"]=[*previous.get("statusHistory",[]),_history("SUPERSEDED",event,previous.get("status"))]; previous["status"]="SUPERSEDED"; previous.update(_audit(event)); _repo.put(previous)
        previous_version=doc["version"]; doc["statusHistory"]=[*doc.get("statusHistory",[]),_history("RECEIVED",event,doc.get("status"))]; doc["status"]="RECEIVED"; doc["reviewStatus"]="PENDING_REVIEW"; doc["uploadedAt"]=utc_now(); doc["version"]=previous_version+1; doc.update(_audit(event))
        try: _repo.put(doc,expected_version=previous_version)
        except ConflictError:
            latest=_repo.get(f"APP#{app_id}",f"DOC#{doc_id}")
            if latest and any(row.get("to")=="RECEIVED" for row in latest.get("statusHistory",[])):
                return 200,{"documentId":doc_id,"status":latest.get("status"),"resumed":True}
            raise
        return 200,{"documentId":doc_id,"status":"RECEIVED"}
    if method=="POST" and review_route:
        if not reviewer: raise AuthenticationError("Underwriting reviewer access is required")
        if item.get("status")!="SUBMITTED": raise ConflictError("Documents can only be reviewed after the application is submitted")
        doc_id=re.fullmatch(r"/documents/([^/]+)/review",suffix).group(1)
        doc=_repo.get(f"APP#{app_id}",f"DOC#{doc_id}")
        if not doc: return 404,{"error":"not_found","message":"Document not found"}
        body=_body(event); next_status=body.get("reviewStatus"); reason=body.get("reason")
        allowed={"RECEIVED":{"PROCESSING","ACCEPTED","NEEDS_REVIEW","REJECTED"},"PROCESSING":{"ACCEPTED","NEEDS_REVIEW","REJECTED"},"NEEDS_REVIEW":{"PROCESSING","ACCEPTED","REJECTED"}}
        if isinstance(next_status,str) and next_status==doc.get("status") and (reason is None or reason==doc.get("reviewReason")):
            return 200,{"documentId":doc_id,"status":next_status,"reviewStatus":next_status,"resumed":True}
        if not isinstance(next_status,str) or next_status not in allowed.get(doc.get("status"),set()): raise ConflictError("Invalid document review status transition")
        if reason is not None and (not isinstance(reason,str) or len(reason)>500): raise ValidationError("Review reason must be text of up to 500 characters")
        if next_status in {"NEEDS_REVIEW","REJECTED"} and (not isinstance(reason,str) or not reason.strip() or len(reason)>500): raise ValidationError("Provide a review reason of up to 500 characters")
        previous=doc.get("status"); previous_version=doc["version"]; doc["status"]=next_status; doc["reviewStatus"]=next_status; doc["statusHistory"]=[*doc.get("statusHistory",[]),_history(next_status,event,previous)]
        if reason: doc["reviewReason"]=reason.strip()
        doc["version"]=previous_version+1; doc.update(_audit(event)); _repo.put(doc,expected_version=previous_version)
        return 200,{"documentId":doc_id,"status":next_status,"reviewStatus":next_status}
    if method=="POST" and suffix=="/classify":
        b=item.get("business",{}); candidates=suggest_mcc(b.get("industry"),b.get("description")); body=_body(event); chosen=body.get("selectedCode"); provider=body.get("providerId")
        valid={x["code"] for x in MCCS}
        if chosen not in (None,"") and (not isinstance(chosen,str) or chosen not in valid): raise ValidationError("Selected MCC must exist in the catalog")
        if provider and provider not in policy_providers(): raise ValidationError("Unsupported provider policy")
        classification={"candidates":candidates,"selectedCode":chosen,"providerId":provider,"policyTag":policy_tags(chosen,provider) if chosen else None,"policyVersion":risk_policy_version(),"confirmedByApplicant":bool(chosen),"updatedAt":utc_now()}
        next_item=dict(item); next_item["classification"]=classification; next_item["version"]=item["version"]+1; _touch(next_item,event); _repo.put(next_item,expected_version=item["version"])
        return 200,classification
    if method=="POST" and suffix=="/evaluate":
        records=_repo.query(f"APP#{app_id}")
        if sum(1 for record in records if record.get("SK","").startswith("EVAL#"))>=MAX_EVALUATION_RECORDS:
            raise ValidationError(f"An application can contain at most {MAX_EVALUATION_RECORDS} evaluation snapshots")
        docs=[record for record in records if record.get("SK","").startswith("DOC#")]; result=evaluate(item,docs); eval_id=str(uuid.uuid4()); _repo.put({"PK":f"APP#{app_id}","SK":f"EVAL#{eval_id}","createdAt":result["createdAt"],"result":result,**_audit(event)})
        return 200,{"evaluation":result}
    if method=="POST" and suffix=="/submit":
        attestation=_body(event)
        if attestation.get("finalAttestation") is not True or attestation.get("termsVersion")!="v1":
            raise ValidationError("Confirm the final accuracy statement and current terms before submission")
        records=_repo.query(f"APP#{app_id}"); docs=[record for record in records if record.get("SK","").startswith("DOC#")]; result=evaluate(item,docs)
        evaluation_count=sum(1 for record in records if record.get("SK","").startswith("EVAL#"))
        if evaluation_count<MAX_EVALUATION_RECORDS:
            eval_id=str(uuid.uuid4()); _repo.put({"PK":f"APP#{app_id}","SK":f"EVAL#{eval_id}","createdAt":result["createdAt"],"applicationVersion":item["version"],"result":result,**_audit(event)})
        if any(f["code"].startswith("missing_") for f in result["flags"]): return 422,{"error":"incomplete_application","message":"Complete required information and documents before submitting.","evaluation":result}
        version=item["version"]+1; payload=submission_payload(item,docs,result,version); payload["attestation"]={"accepted":True,"termsVersion":"v1","acceptedAt":utc_now()}; payload["audit"]=_audit(event); new=dict(item); new["statusHistory"]=[*new.get("statusHistory",[]),_history("SUBMITTED",event,item.get("status"))]; new["status"]="SUBMITTED"; new["version"]=version; _touch(new,event); _repo.commit_submission(new,{"PK":f"APP#{app_id}","SK":f"SUBMISSION#{version}","payload":payload,"createdAt":payload["submittedAt"],**_audit(event)},expected_version=item["version"])
        return 201,{"status":"SUBMITTED","submission":payload}
    return 404,{"error":"not_found","message":"Route not found"}

def handler(event, context):
    started=time.monotonic(); hard_budget=float(os.environ.get("INTERNAL_DEADLINE_SECONDS","35"))
    request_id=event.get("requestContext",{}).get("requestId","unknown")
    method=event.get("requestContext",{}).get("http",{}).get("method",event.get("httpMethod","GET"))
    def finish(status, body):
        duration=round((time.monotonic()-started)*1000)
        _emit_request_metrics(method,status,duration)
        return _response(status,body)
    try:
        if os.environ.get("TABLE_NAME") and not isinstance(_repo,DynamoRepository):
            repo,s3=aws_clients(); configure(repo,s3)
        if time.monotonic()-started>hard_budget: return finish(504,{"error":"deadline_exceeded","message":"Request deadline exceeded; retry safely."})
        path=event.get("rawPath",event.get("path","/"))
        status,body=_route(method,path,event)
        if time.monotonic()-started>hard_budget: return finish(504,{"error":"deadline_exceeded","message":"Request deadline exceeded; retry safely."})
        log.info("request_completed request_id=%s method=%s status=%s duration_ms=%s",str(request_id)[:128],method,status,round((time.monotonic()-started)*1000))
        return finish(status,body)
    except AuthenticationError as exc:
        log.info("request_rejected request_id=%s category=authentication duration_ms=%s",str(request_id)[:128],round((time.monotonic()-started)*1000))
        return finish(401,{"error":"unauthorized","message":str(exc)})
    except ValidationError as exc:
        log.info("request_rejected request_id=%s category=validation duration_ms=%s",str(request_id)[:128],round((time.monotonic()-started)*1000))
        return finish(400,{"error":"validation_error","message":str(exc)})
    except ConflictError as exc:
        log.info("request_rejected request_id=%s category=conflict duration_ms=%s",str(request_id)[:128],round((time.monotonic()-started)*1000))
        return finish(409,{"error":"conflict","message":str(exc)})
    except RepositoryLimitError as exc:
        log.info("request_rejected request_id=%s category=record_limit duration_ms=%s",str(request_id)[:128],round((time.monotonic()-started)*1000))
        return finish(422,{"error":"record_limit","message":str(exc)})
    except Exception as exc:
        # Do not log event/body: they can contain personal or financial information.
        log.error("request_failed request_id=%s exception_type=%s duration_ms=%s",str(request_id)[:128],type(exc).__name__,round((time.monotonic()-started)*1000))
        return finish(500,{"error":"internal_error","message":"The request could not be completed. Retry safely."})
