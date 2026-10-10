import re
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class InfrastructureContractTests(unittest.TestCase):
    def test_compute_is_lambda_only_and_timeout_budget_has_headroom(self):
        template=(ROOT/"template.yaml").read_text(encoding="utf-8")
        compute_types=re.findall(r"^\s+Type:\s+(AWS::(?:Serverless::Function|Lambda::Function|EC2::Instance|ECS::Service|EKS::Cluster|AppRunner::Service))\s*$",template,re.M)
        self.assertGreaterEqual(compute_types.count("AWS::Serverless::Function"),2)
        self.assertFalse(any(kind!="AWS::Serverless::Function" for kind in compute_types))
        self.assertRegex(template,r"(?m)^\s+Timeout:\s+40\s*$")
        self.assertIn("INTERNAL_DEADLINE_SECONDS: '35'",template)
        repository=(ROOT/"src"/"repository.py").read_text(encoding="utf-8")
        self.assertIn("connect_timeout=2,read_timeout=3,retries={\"max_attempts\":0}",repository)

    def test_required_aws_services_private_storage_and_reviewer_group_exist(self):
        template=(ROOT/"template.yaml").read_text(encoding="utf-8")
        for token in ("AWS::Serverless::HttpApi","AWS::DynamoDB::Table","AWS::S3::Bucket","AWS::Cognito::UserPoolGroup","GroupName: underwriting-reviewer","BlockPublicAcls: true","BlockPublicPolicy: true","RestrictPublicBuckets: true","SSEAlgorithm: AES256","Status: Enabled","aws:SecureTransport: 'false'"):
            with self.subTest(token=token): self.assertIn(token,template)
        self.assertIn("Resource: !Sub '${DocumentBucket.Arn}/applications/*'",template)
        self.assertIn("Action: [dynamodb:GetItem, dynamodb:PutItem, dynamodb:Query, dynamodb:TransactWriteItems]",template)
        self.assertNotRegex(template,r"(?s)Effect: Allow\s+Action:\s+\[?\*\]?")

    def test_required_docs_and_openapi_include_cleanup_and_reviewer_lifecycle(self):
        readme=(ROOT/"README.md").read_text(encoding="utf-8")
        architecture=(ROOT/"docs"/"architecture.md").read_text(encoding="utf-8")
        openapi=(ROOT/"openapi.yaml").read_text(encoding="utf-8")
        self.assertIn("sam delete --stack-name",readme)
        self.assertIn("flowchart",architecture)
        self.assertIn("/v1/applications/{applicationId}/documents/{documentId}/review",openapi)
        for status in ("PROCESSING","ACCEPTED","NEEDS_REVIEW","REJECTED"):
            self.assertIn(status,openapi)


if __name__=="__main__": unittest.main()
