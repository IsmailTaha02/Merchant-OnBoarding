import json
import sys
import unittest
import hashlib,base64
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import app
from repository import MemoryRepository

def request(method,path,body=None,subject="merchant-test",groups=None):
    context={"http":{"method":method},"requestId":"test-request-123"}
    if subject:
        claims={"sub":subject}
        if groups is not None: claims["cognito:groups"]=groups
        context["authorizer"]={"jwt":{"claims":claims}}
    return {"requestContext":context,"rawPath":path,"body":json.dumps(body or {})}

def parsed(response): return response["statusCode"],json.loads(response["body"])

class FakeBody:
    def __init__(self,data): self.data=data
    def read(self,limit=-1): return self.data[:limit]

class FakeS3:
    data=b"%PDF-1.7\nsample onboarding file"
    def generate_presigned_post(self,**kwargs):
        self.fields=kwargs["Fields"]
        return {"url":"https://upload.invalid","fields":{"key":kwargs["Key"],**kwargs["Fields"]}}
    def head_object(self,**kwargs): return {"ContentLength":len(self.data),"ContentType":"application/pdf","VersionId":"version-1","ChecksumSHA256":base64.b64encode(hashlib.sha256(self.data).digest()).decode()}
    def get_object(self,**kwargs): return {"Body":FakeBody(self.data)}

class WorkflowTests(unittest.TestCase):
    def setUp(self): app.configure(MemoryRepository())
    def call(self,method,path,body=None): return parsed(app.handler(request(method,path,body),None))

    def test_document_completion_retry_is_idempotent(self):
        _,created=self.call("POST","/v1/applications")
        base=f"/v1/applications/{created['applicationId']}"
        _,pre=self.call("POST",base+"/documents/presign",{"documentType":"government_id","contentType":"application/pdf","sizeBytes":100,"fileName":"sample.pdf"})
        first=self.call("POST",base+f"/documents/{pre['documentId']}/complete")
        second=self.call("POST",base+f"/documents/{pre['documentId']}/complete")
        self.assertEqual(first[0],200); self.assertEqual(second[0],200); self.assertTrue(second[1]["resumed"])
        record=app._repo.get(f"APP#{created['applicationId']}",f"DOC#{pre['documentId']}")
        self.assertEqual([h["to"] for h in record["statusHistory"]].count("RECEIVED"),1)

    def test_authenticated_audit_records_actor_sub(self):
        _,created=parsed(app.handler(request("POST","/v1/applications",{},"merchant-a"),None))
        row=app._repo.get(f"APP#{created['applicationId']}","META")
        self.assertEqual(row["actorSub"],"merchant-a")
        self.assertEqual(row["actorSource"],"cognito-authenticated-api")

    def test_application_is_private_to_authenticated_owner(self):
        created_status,created=parsed(app.handler(request("POST","/v1/applications",{},"merchant-a"),None))
        self.assertEqual(created_status,201)
        path=f"/v1/applications/{created['applicationId']}"
        owner_status,_=parsed(app.handler(request("GET",path,{},"merchant-a"),None))
        stranger_status,stranger=parsed(app.handler(request("GET",path,{},"merchant-b"),None))
        self.assertEqual(owner_status,200)
        self.assertEqual(stranger_status,404)
        self.assertEqual(stranger["message"],"Application not found")

    def test_application_create_rejects_missing_authenticated_subject(self):
        status,result=parsed(app.handler(request("POST","/v1/applications",{},subject=""),None))
        self.assertEqual(status,401)
        self.assertEqual(result["error"],"unauthorized")

    def test_document_upload_records_are_capped_per_application(self):
        _,created=self.call("POST","/v1/applications",{})
        app_id=created["applicationId"]
        for index in range(app.MAX_DOCUMENT_RECORDS):
            app._repo.put({"PK":f"APP#{app_id}","SK":f"DOC#{index:02d}","documentId":str(index)})
        status,result=self.call("POST",f"/v1/applications/{app_id}/documents/presign",{"documentType":"business_registration","contentType":"application/pdf","fileName":"registration.pdf","sizeBytes":100})
        self.assertEqual(status,400)
        self.assertIn("at most",result["message"])

    def test_evaluation_snapshots_are_capped_per_application(self):
        _,created=self.call("POST","/v1/applications",{})
        app_id=created["applicationId"]
        for index in range(app.MAX_EVALUATION_RECORDS):
            app._repo.put({"PK":f"APP#{app_id}","SK":f"EVAL#{index:02d}","result":{}})
        status,result=self.call("POST",f"/v1/applications/{app_id}/evaluate",{})
        self.assertEqual(status,400)
        self.assertIn("evaluation snapshots",result["message"])

    def test_incomplete_submit_remains_available_at_evaluation_snapshot_cap(self):
        _,created=self.call("POST","/v1/applications",{})
        app_id=created["applicationId"]
        for index in range(app.MAX_EVALUATION_RECORDS):
            app._repo.put({"PK":f"APP#{app_id}","SK":f"EVAL#{index:02d}","result":{}})
        status,result=self.call("POST",f"/v1/applications/{app_id}/submit",{"finalAttestation":True,"termsVersion":"v1"})
        self.assertEqual(status,422)
        self.assertEqual(result["error"],"incomplete_application")

    def test_full_create_resume_upload_classify_evaluate_submit(self):
        status,created=self.call("POST","/v1/applications",{"idempotencyKey":"sample-1"})
        self.assertEqual(status,201); app_id=created["applicationId"]; base=f"/v1/applications/{app_id}"
        application=self.call("GET",base)[1]
        self.assertEqual(application["requestId"],"test-request-123")
        self.assertEqual(application["statusHistory"][0]["to"],"DRAFT")
        status,again=self.call("POST","/v1/applications",{"idempotencyKey":"sample-1"})
        self.assertEqual(status,200); self.assertEqual(again["applicationId"],app_id)
        status,_=self.call("PATCH",base+"/business",{"legalName":"Northstar Coffee Ltd","entityType":"Limited company","formationCountry":"United Kingdom","registrationLast4":"A1B2","registeredAddress":"10 Sample Road, London, SW1A 1AA, United Kingdom","registeredAddressLine1":"10 Sample Road","registeredAddressCity":"London","registeredAddressPostalCode":"SW1A 1AA","registeredAddressCountry":"United Kingdom","description":"Coffee shop selling hot drinks","industry":"Coffee shop","annualCardVolume":"120000","averageTicket":"8","highestTicket":"40","monthlyTransactions":"1250","cardPresentPercent":"60","cardNotPresentPercent":"40","ecommercePercent":"30","licenseRequired":"No","settlementAccountHolder":"Northstar Coffee Ltd","settlementBankName":"Sample Bank","settlementAccountLast4":"5678","currentMonthlyVolume":"10000","currentFees":"180"})
        self.assertEqual(status,200)
        owner_id="a1111111-1111-4111-8111-111111111111"
        status,_=self.call("PATCH",base+"/applicant",{"firstName":"Casey","lastName":"Example","dateOfBirth":"1990-05-12","residentialAddressLine1":"1 Sample Street","residentialCity":"London","residentialPostalCode":"SW1A 1AA","residentialCountry":"United Kingdom","email":"casey@example.test","phone":"+442071234567","role":"Owner","ownershipPercent":"60","idType":"Passport","beneficialOwners":[{"ownerId":owner_id,"firstName":"Jordan","middleName":"R.","lastName":"Example","dateOfBirth":"1988-03-21","residentialAddress":{"line1":"2 Sample Street","city":"London","postalCode":"SW1A 2AA","country":"United Kingdom"},"email":"jordan@example.test","phone":"+442071234568","role":"Director","ownershipPercent":"40","idType":"Passport","idLast4":"9876"}],"consentAt":"2026-10-08T10:00:00Z","termsVersion":"v1","idLast4":"1234"})
        self.assertEqual(status,200)
        saved_applicant=self.call("GET",base)[1]["applicant"]
        self.assertEqual(saved_applicant["beneficialOwners"][0]["residentialAddress"]["postalCode"],"SW1A 2AA")
        docs=[]
        for kind,subject in (("government_id","primary"),("government_id",owner_id),("business_registration",None),("bank_evidence",None)):
            metadata={"documentType":kind,"contentType":"application/pdf","sizeBytes":1000,"fileName":"sample.pdf"}
            if subject: metadata["ownerId"]=subject
            status,data=self.call("POST",base+"/documents/presign",metadata)
            self.assertEqual(status,201); doc_id=data["documentId"]; docs.append(doc_id)
            self.assertEqual(self.call("POST",base+f"/documents/{doc_id}/complete")[0],200)
        self.assertEqual(self.call("PATCH",base+"/applicant",{"beneficialOwners":[]})[0],409)
        status,classification=self.call("POST",base+"/classify",{"selectedCode":"5814"})
        self.assertEqual(status,200); self.assertEqual(classification["candidates"][0]["code"],"5814")
        status,evaluation=self.call("POST",base+"/evaluate")
        self.assertEqual(status,200); result=evaluation["evaluation"]
        self.assertEqual(result["rateAnalysis"]["effectiveRatePercent"],1.8)
        self.assertEqual(result["businessSummary"]["source"],"deterministic-mock")
        self.assertFalse(result["businessSummary"]["verified"])
        self.assertFalse([f for f in result["flags"] if f["code"].startswith("missing_")])
        # A saved evaluation must never authorize submission after later edits.
        self.assertEqual(self.call("PATCH",base+"/business",{"description":""})[0],200)
        self.assertEqual(self.call("POST",base+"/submit",{"finalAttestation":True,"termsVersion":"v1"})[0],422)
        self.assertEqual(self.call("PATCH",base+"/business",{"description":"Coffee shop selling hot drinks"})[0],200)
        status,submitted=self.call("POST",base+"/submit",{"finalAttestation":True,"termsVersion":"v1"})
        self.assertEqual(status,201); self.assertEqual(submitted["submission"]["decisionStatus"],"PENDING_HUMAN_REVIEW")
        self.assertTrue(submitted["submission"]["attestation"]["accepted"])
        self.assertEqual(self.call("GET",base)[0],200)
        self.assertEqual(self.call("PATCH",base+"/business",{"legalName":"Changed"})[0],409)
        submitted_state=self.call("GET",base)[1]
        self.assertEqual(submitted_state["statusHistory"][-1]["to"],"SUBMITTED")
        self.assertEqual(submitted_state["statusHistory"][-1]["requestId"],"test-request-123")
        saved_submission=app._repo.get(f"APP#{app_id}",f"SUBMISSION#{submitted_state['version']}")
        self.assertTrue(saved_submission["payload"]["attestation"]["accepted"])
        review_path=base+f"/documents/{docs[0]}/review"
        reviewer_read=parsed(app.handler(request("GET",base,subject="reviewer-7",groups=["underwriting-reviewer"]),None))
        self.assertEqual(reviewer_read[0],200)
        self.assertEqual(reviewer_read[1]["applicationId"],app_id)
        self.assertEqual(parsed(app.handler(request("POST",review_path,{"reviewStatus":"PROCESSING"}),None))[0],401)
        reviewer=lambda body: parsed(app.handler(request("POST",review_path,body,"reviewer-7",["underwriting-reviewer"]),None))
        document_before_review=app._repo.get(f"APP#{app_id}",f"DOC#{docs[0]}")
        self.assertEqual(document_before_review["version"],2)
        self.assertEqual(reviewer({"reviewStatus":"NEEDS_REVIEW"})[0],400)
        status,needs_review=reviewer({"reviewStatus":"NEEDS_REVIEW","reason":"Please check image quality"})
        self.assertEqual(status,200,needs_review); self.assertEqual(needs_review["reviewStatus"],"NEEDS_REVIEW")
        status,processing=reviewer({"reviewStatus":"PROCESSING"})
        self.assertEqual(status,200); self.assertEqual(processing["status"],"PROCESSING")
        status,accepted=reviewer({"reviewStatus":"ACCEPTED"})
        self.assertEqual(status,200); self.assertEqual(accepted["status"],"ACCEPTED")
        retry=reviewer({"reviewStatus":"ACCEPTED"})
        self.assertEqual(retry[0],200); self.assertTrue(retry[1]["resumed"])
        self.assertEqual(reviewer({"reviewStatus":"REJECTED","reason":"Bad state"})[0],409)
        reviewed=self.call("GET",base)[1]["documents"][0]
        self.assertEqual([h["to"] for h in reviewed["statusHistory"]].count("ACCEPTED"),1)
        self.assertEqual(reviewed["statusHistory"][-1]["actorSub"],"reviewer-7")

    def test_business_profile_fields_persist_and_appear_in_evaluation(self):
        status, created=self.call("POST", "/v1/applications", {"idempotencyKey":"profile-test"})
        self.assertEqual(status, 201)
        app_id=created["applicationId"]
        profile={"operatingCountries":"United Kingdom, Ireland", "fulfillmentModel":"Physical goods", "recurringPayments":"Yes", "customerType":"Consumers"}
        status, saved=self.call("PATCH", f"/v1/applications/{app_id}/business", profile)
        self.assertEqual(status, 200)
        self.assertEqual({k:saved["business"][k] for k in profile}, profile)
        status, evaluated=self.call("POST", f"/v1/applications/{app_id}/evaluate", {})
        self.assertEqual(status, 200)
        summary=evaluated["evaluation"]["businessSummary"]
        self.assertEqual(summary["geography"], "United Kingdom, Ireland")
        self.assertEqual(summary["fulfillmentModel"], "Physical goods")
        self.assertEqual(summary["recurringPayments"], "Yes")
        self.assertEqual(summary["customerType"], "Consumers")

    def test_mcc_search_http_route_returns_matches_and_rejects_wrong_query_type(self):
        event=request("GET","/v1/mcc")
        event["queryStringParameters"]={"query":"coffee"}
        status,result=parsed(app.handler(event,None))
        self.assertEqual(status,200)
        self.assertTrue(any(row["code"]=="5814" for row in result["items"]))
        event["queryStringParameters"]={"query":"3221"}
        status,result=parsed(app.handler(event,None))
        self.assertEqual(status,200)
        self.assertEqual(result["items"][0]["description"],"TAME")
        event["queryStringParameters"]={"query":["coffee"]}
        self.assertEqual(parsed(app.handler(event,None))[0],400)

    def test_beneficial_owner_validation_rejects_incomplete_address(self):
        _,created=self.call("POST","/v1/applications")
        base=f"/v1/applications/{created['applicationId']}/applicant"
        owner={"ownerId":"a1111111-1111-4111-8111-111111111111","firstName":"Jordan","lastName":"Example","dateOfBirth":"1988-03-21","residentialAddress":{"line1":"2 Sample Street","city":"London","postalCode":"SW1A 2AA","country":"United Kingdom"},"email":"jordan@example.test","phone":"+442071234568","role":"Director","idType":"Passport","idLast4":"1234","ownershipPercent":"45"}
        self.assertEqual(self.call("PATCH",base,{"beneficialOwners":[owner]})[0],200)
        invalid={**owner,"residentialAddress":{"line1":"","city":"London","postalCode":"SW1A 2AA","country":"United Kingdom"}}
        self.assertEqual(self.call("PATCH",base,{"beneficialOwners":[invalid]})[0],400)
        invalid_role={**owner,"role":"unrecognized role"}
        self.assertEqual(self.call("PATCH",base,{"beneficialOwners":[invalid_role]})[0],400)

    def test_submit_blocks_missing_items_with_explainable_sources(self):
        _,created=self.call("POST","/v1/applications")
        status,result=self.call("POST",f"/v1/applications/{created['applicationId']}/submit",{"finalAttestation":True,"termsVersion":"v1"})
        self.assertEqual(status,422)
        self.assertTrue(all(flag.get("source") for flag in result["evaluation"]["flags"]))

    def test_submit_requires_final_attestation(self):
        _,created=self.call("POST","/v1/applications")
        status,result=self.call("POST",f"/v1/applications/{created['applicationId']}/submit",{})
        self.assertEqual(status,400)
        self.assertIn("Confirm the final accuracy statement",result["message"])

    def test_sensitive_unmasked_fields_are_not_accepted(self):
        _,created=self.call("POST","/v1/applications")
        status,result=self.call("PATCH",f"/v1/applications/{created['applicationId']}/applicant",{"governmentIdNumber":"123456789"})
        self.assertEqual(status,400); self.assertEqual(result["error"],"validation_error")

    def test_request_logs_include_timing_without_logging_personal_payload(self):
        _,created=self.call("POST","/v1/applications")
        event=request("PATCH",f"/v1/applications/{created['applicationId']}/applicant",{"firstName":"PrivatePersonName"})
        with self.assertLogs(app.log,level="INFO") as captured, patch("builtins.print") as printed:
            self.assertEqual(parsed(app.handler(event,None))[0],200)
        output="\n".join(captured.output)
        metric_output="\n".join(str(call.args[0]) for call in printed.call_args_list)
        metric=json.loads(metric_output)
        self.assertIn("request_completed",output)
        self.assertIn("duration_ms",output)
        self.assertEqual(metric["_aws"]["CloudWatchMetrics"][0]["Namespace"],"GWEB/MerchantOnboarding")
        self.assertEqual(metric["RequestCount"],1)
        self.assertEqual(metric["ErrorCount"],0)
        self.assertIn("DurationMs",{m["Name"] for m in metric["_aws"]["CloudWatchMetrics"][0]["Metrics"]})
        self.assertNotIn("PrivatePersonName",output)
        self.assertNotIn("PrivatePersonName",metric_output)

    def test_json_responses_include_browser_security_headers(self):
        response=app._response(200,{"ok":True})
        headers=response["headers"]
        self.assertEqual(headers["x-content-type-options"],"nosniff")
        self.assertEqual(headers["x-frame-options"],"DENY")
        self.assertEqual(headers["referrer-policy"],"no-referrer")
        self.assertIn("frame-ancestors 'none'",headers["content-security-policy"])
        self.assertEqual(headers["strict-transport-security"],"max-age=31536000")

    def test_invalid_json_and_base64_return_client_errors(self):
        raw={"requestContext":{"http":{"method":"POST"}},"rawPath":"/v1/applications","body":"{"}
        self.assertEqual(parsed(app.handler(raw,None))[0],400)
        encoded={"requestContext":{"http":{"method":"POST"}},"rawPath":"/v1/applications","body":"%%%","isBase64Encoded":True}
        self.assertEqual(parsed(app.handler(encoded,None))[0],400)
        oversized={"requestContext":{"http":{"method":"POST"}},"rawPath":"/v1/applications","body":"A"*88_001,"isBase64Encoded":True}
        self.assertEqual(parsed(app.handler(oversized,None))[0],400)
        unicode_oversized={"requestContext":{"http":{"method":"POST"}},"rawPath":"/v1/applications","body":"é"*32_001}
        self.assertEqual(parsed(app.handler(unicode_oversized,None))[0],400)

    def test_parallel_retries_with_same_idempotency_key_share_one_application(self):
        event=request("POST","/v1/applications",{"idempotencyKey":"parallel-create"})
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:parsed(app.handler(event,None)),range(8)))
        ids={body["applicationId"] for _,body in results}
        self.assertEqual(len(ids),1)
        self.assertTrue(all(status in {200,201} for status,_ in results))

    def test_invalid_upload_is_rejected_before_signing(self):
        _,created=self.call("POST","/v1/applications")
        status,result=self.call("POST",f"/v1/applications/{created['applicationId']}/documents/presign",{"documentType":"government_id","contentType":"text/plain","sizeBytes":20})
        self.assertEqual(status,400); self.assertIn("PDF",result["message"])

    def test_upload_filename_extension_must_match_mime(self):
        _,created=self.call("POST","/v1/applications")
        base=f"/v1/applications/{created['applicationId']}"
        status,result=self.call("POST",base+"/documents/presign",{"documentType":"government_id","contentType":"application/pdf","sizeBytes":20,"fileName":"passport.png"})
        self.assertEqual(status,400)
        self.assertIn("extension",result["message"])

    def test_additional_evidence_requires_and_persists_reason(self):
        _,created=self.call("POST","/v1/applications",{"idempotencyKey":"additional-evidence"})
        app_id=created["applicationId"]
        path=f"/v1/applications/{app_id}/documents/presign"
        request_body={"documentType":"additional_evidence","contentType":"application/pdf","sizeBytes":100,"fileName":"invoice.pdf"}
        status,error=self.call("POST",path,request_body)
        self.assertEqual(status,400)
        self.assertIn("Explain why",error["message"])
        request_body["reasonRequested"]="Support the stated supplier relationship"
        status,result=self.call("POST",path,request_body)
        self.assertEqual(status,201)
        _,state=self.call("GET",f"/v1/applications/{app_id}")
        record=next(d for d in state["documents"] if d["documentId"]==result["documentId"])
        self.assertEqual(record["reasonRequested"],request_body["reasonRequested"])

    def test_upload_completion_marks_expired_link_and_blocks_it(self):
        _,created=self.call("POST","/v1/applications")
        base=f"/v1/applications/{created['applicationId']}"
        _,presign=self.call("POST",base+"/documents/presign",{"documentType":"government_id","contentType":"application/pdf","sizeBytes":100,"fileName":"id.pdf"})
        doc=app._repo.get(f"APP#{created['applicationId']}",f"DOC#{presign['documentId']}")
        doc["uploadExpiresAt"]=0; app._repo.put(doc)
        status,result=self.call("POST",base+f"/documents/{presign['documentId']}/complete")
        self.assertEqual(status,410); self.assertEqual(result["error"],"upload_expired")
        saved=app._repo.get(f"APP#{created['applicationId']}",f"DOC#{presign['documentId']}")
        self.assertEqual(saved["status"],"UPLOAD_EXPIRED")

    def test_replacing_document_marks_previous_record_superseded(self):
        _,created=self.call("POST","/v1/applications")
        base=f"/v1/applications/{created['applicationId']}"
        doc_ids=[]
        for _ in range(2):
            _,pre=self.call("POST",base+"/documents/presign",{"documentType":"business_registration","contentType":"application/pdf","sizeBytes":100,"fileName":"registration.pdf"})
            doc_ids.append(pre["documentId"])
            self.assertEqual(self.call("POST",base+f"/documents/{pre['documentId']}/complete")[0],200)
        old=app._repo.get(f"APP#{created['applicationId']}",f"DOC#{doc_ids[0]}")
        latest=app._repo.get(f"APP#{created['applicationId']}",f"DOC#{doc_ids[1]}")
        self.assertEqual(old["status"],"SUPERSEDED")
        self.assertEqual(old["statusHistory"][-1]["to"],"SUPERSEDED")
        self.assertEqual(latest["status"],"RECEIVED")

    def test_business_channel_mix_cannot_be_bypassed_with_separate_patches(self):
        _,created=self.call("POST","/v1/applications")
        base=f"/v1/applications/{created['applicationId']}/business"
        self.assertEqual(self.call("PATCH",base,{"cardPresentPercent":"60","cardNotPresentPercent":"40","ecommercePercent":"20"})[0],200)
        self.assertEqual(self.call("PATCH",base,{"cardNotPresentPercent":"30"})[0],400)

    def test_provider_specific_policy_is_persisted_and_explained(self):
        _,created=self.call("POST","/v1/applications")
        base=f"/v1/applications/{created['applicationId']}"
        status,result=self.call("POST",base+"/classify",{"selectedCode":"7995","providerId":"example_acquirer"})
        self.assertEqual(status,200)
        self.assertEqual(result["policyTag"],"restricted/unsupported")
        self.assertEqual(result["policyVersion"],"assessment-example-1")
        evaluation=self.call("POST",base+"/evaluate")[1]["evaluation"]
        flag=next(f for f in evaluation["flags"] if f["code"]=="policy_review")
        self.assertIn("restricted/unsupported",flag["message"])
        self.assertEqual(flag["source"],"classification.selectedCode and classification.providerId")
        self.assertEqual(self.call("POST",base+"/classify",{"providerId":"not-configured"})[0],400)

    def test_statement_parser_persists_only_normalized_values(self):
        _,created=self.call("POST","/v1/applications")
        raw=(ROOT/"tests/fixtures/sample_statement.txt").read_text(encoding="utf-8")
        status,result=self.call("POST",f"/v1/applications/{created['applicationId']}/statement/parse",{"text":raw})
        self.assertEqual(status,200)
        self.assertEqual(result["normalized"]["currentFees"],190.0)
        saved=self.call("GET",f"/v1/applications/{created['applicationId']}")[1]
        self.assertEqual(saved["business"]["currentMonthlyVolume"],10000.0)
        self.assertNotIn(raw,str(saved))

    def test_aws_upload_completion_pins_version_and_persists_sha256(self):
        repo=MemoryRepository(); app.configure(repo,FakeS3())
        _,created=self.call("POST","/v1/applications")
        base=f"/v1/applications/{created['applicationId']}"
        with patch.dict("os.environ",{"DOCUMENT_BUCKET":"test-bucket"}):
            expected=base64.b64encode(hashlib.sha256(FakeS3.data).digest()).decode()
            status,presign=self.call("POST",base+"/documents/presign",{"documentType":"business_registration","contentType":"application/pdf","sizeBytes":len(FakeS3.data),"checksumSha256":expected,"fileName":"registration.pdf"})
            self.assertEqual(status,201)
            status,_=self.call("POST",base+f"/documents/{presign['documentId']}/complete")
        self.assertEqual(status,200)
        document=repo.get(f"APP#{created['applicationId']}",f"DOC#{presign['documentId']}")
        self.assertEqual(document["checksumSha256"],expected)
        self.assertEqual(document["versionId"],"version-1")
        self.assertEqual(document["fileExtension"],"pdf")
        self.assertEqual([x["to"] for x in document["statusHistory"]],["UPLOADING","RECEIVED"])
        self.assertEqual(document["requestId"],"test-request-123")

if __name__=="__main__": unittest.main()
