import json,re,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from domain import MCCS,ValidationError,evaluate,policy_tags,suggest_mcc,validate_patch

class DomainTests(unittest.TestCase):
    def test_business_profile_fields_are_validated_and_used_in_summary(self):
        from providers import MockAnalysisProvider
        validate_patch("business", {"fulfillmentModel":"Physical goods", "recurringPayments":"Yes", "customerType":"Consumers", "operatingCountries":"UK, Ireland"})
        summary=MockAnalysisProvider().summarize({"formationCountry":"United Kingdom", "operatingCountries":"UK, Ireland", "fulfillmentModel":"Physical goods", "recurringPayments":"Yes", "customerType":"Consumers", "description":"Coffee beans"})
        self.assertEqual(summary["geography"], "UK, Ireland")
        self.assertEqual(summary["fulfillmentModel"], "Physical goods")
        self.assertEqual(summary["recurringPayments"], "Yes")
        self.assertEqual(summary["customerType"], "Consumers")
        self.assertIn("customerType", summary["sourceFields"])
        for field, value in (("fulfillmentModel", "instant approval"), ("recurringPayments", "sometimes"), ("customerType", "everyone")):
            with self.subTest(field=field), self.assertRaises(ValidationError): validate_patch("business", {field:value})
    def test_catalog_has_four_digit_real_categories(self):
        self.assertTrue(MCCS)
        self.assertTrue(all(len(x["code"])==4 and x["code"].isdigit() for x in MCCS))
        metadata=json.loads((Path(__file__).resolve().parents[1]/"src"/"mcc_catalog_metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["rowCount"],len(MCCS))
        self.assertGreaterEqual(len(MCCS),900)
        self.assertTrue(metadata["isComplete"])
        self.assertEqual(len({row["code"] for row in MCCS}),len(MCCS))
        self.assertEqual(next(row["description"] for row in MCCS if row["code"]=="3221"),"TAME")

    def test_mcc_suggestion_uses_catalog_and_explains_match(self):
        result=suggest_mcc("Coffee shop","Cafe selling coffee and pastries")
        self.assertEqual(result[0]["code"],"5812")
        self.assertTrue(result[0]["reason"])

    def test_unknown_activity_gets_no_fabricated_default_code(self):
        self.assertEqual(suggest_mcc("Unusual service", "novel activity with no curated terms"), [])

    def test_evaluation_flags_selected_mcc_not_supported_by_activity_suggestions(self):
        app={"applicant":{},"business":{"industry":"Coffee shop","description":"Sells coffee and pastries"},"classification":{"selectedCode":"7011","candidates":[{"code":"5812","confidence":0.86}]}}
        result=evaluate(app,[])
        flag=next(f for f in result["flags"] if f["code"]=="mcc_activity_mismatch")
        self.assertIn("business.description",flag["source"])
        self.assertIn("classification.selectedCode",flag["source"])

    def test_evaluation_does_not_flag_selected_supported_mcc(self):
        app={"applicant":{},"business":{"industry":"Coffee shop","description":"Sells coffee and pastries"},"classification":{"selectedCode":"5812","candidates":[{"code":"5812","confidence":0.86}]}}
        result=evaluate(app,[])
        self.assertNotIn("mcc_activity_mismatch",{f["code"] for f in result["flags"]})

    def test_browser_demo_mcc_seed_matches_backend_catalog(self):
        source=(Path(__file__).resolve().parents[1]/"frontend"/"app.js").read_text(encoding="utf-8")
        match=re.search(r"const demoMccCatalog=(\[[\s\S]*?\]);",source)
        self.assertIsNotNone(match,"demo MCC catalog was not found")
        browser_catalog=json.loads(match.group(1))
        backend_catalog=[[row["code"],row["description"],row["keywords"]] for row in MCCS]
        self.assertEqual(browser_catalog,backend_catalog)
        self.assertGreaterEqual(len(browser_catalog),900)
        self.assertIn('path.startsWith("/v1/mcc")',source,"demo MCC search route is not implemented")
        self.assertIn('id="mccSearchQuery"',(Path(__file__).resolve().parents[1]/"frontend"/"index.html").read_text(encoding="utf-8"))

    def test_masked_identifier_and_percentage_validation(self):
        with self.assertRaises(ValidationError): validate_patch("applicant",{"idLast4":"12345"})
        with self.assertRaises(ValidationError): validate_patch("applicant",{"ownershipPercent":120})
        with self.assertRaises(ValidationError): validate_patch("business",{"annualCardVolume":"NaN"})
        with self.assertRaises(ValidationError): validate_patch("business",{"entityType":"imaginary entity"})
        with self.assertRaises(ValidationError): validate_patch("business",{"website":"javascript:alert(1)"})

    def test_card_present_and_card_not_present_mix_must_total_one_hundred(self):
        with self.assertRaises(ValidationError): validate_patch("business",{"cardPresentPercent":"60","cardNotPresentPercent":"30"})
        self.assertEqual(validate_patch("business",{"cardPresentPercent":"60","cardNotPresentPercent":"40"})["cardNotPresentPercent"],"40")
        with self.assertRaises(ValidationError): validate_patch("business",{"cardNotPresentPercent":"30","ecommercePercent":"40"})

    def test_evaluation_flags_name_their_sources(self):
        result=evaluate({"applicant":{},"business":{}},[])
        self.assertTrue(result["flags"])
        self.assertTrue(all(flag["source"] for flag in result["flags"]))

    def test_evaluation_requires_structured_registered_address_and_volume_inputs(self):
        result=evaluate({"applicant":{},"business":{}},[])
        sources={flag["source"] for flag in result["flags"]}
        for field in ("business.registrationLast4","business.registeredAddressLine1","business.registeredAddressCity","business.registeredAddressPostalCode","business.registeredAddressCountry","business.averageTicket","business.highestTicket","business.monthlyTransactions","business.cardPresentPercent","business.cardNotPresentPercent","business.ecommercePercent","business.licenseRequired","business.settlementAccountHolder","business.settlementBankName","business.settlementAccountLast4"):
            self.assertIn(field,sources)

    def test_owner_shares_over_one_hundred_percent_are_flagged(self):
        owner={"ownerId":"a1111111-1111-4111-8111-111111111111","firstName":"Jordan","lastName":"Example","dateOfBirth":"1988-03-21","residentialAddress":{"line1":"2 Sample Street","city":"London","postalCode":"SW1A 2AA","country":"United Kingdom"},"email":"jordan@example.test","phone":"+442071234568","role":"Director","idType":"Passport","idLast4":"1234","ownershipPercent":"45"}
        result=evaluate({"applicant":{"ownershipPercent":"60","beneficialOwners":[owner]},"business":{}},[])
        flag=next(f for f in result["flags"] if f["code"]=="ownership_total_review")
        self.assertEqual(flag["source"],"applicant.ownershipPercent and applicant.beneficialOwners[].ownershipPercent")

    def test_owner_roles_need_percentages_and_partial_disclosure_is_flagged(self):
        app={"applicant":{"role":"Owner","beneficialOwners":[{"ownerId":"owner-2","role":"Owner","firstName":"A","lastName":"B","ownershipPercent":"35"}]},"business":{}}
        result=evaluate(app,[])
        missing=[f for f in result["flags"] if f["code"]=="missing_field" and "ownershipPercent" in f["source"]]
        self.assertTrue(any(f["source"]=="applicant.ownershipPercent and applicant.role" for f in missing))
        self.assertIn("ownership_total_review",{f["code"] for f in result["flags"]})

    def test_business_license_metadata_is_required_when_license_is_required(self):
        result=evaluate({"applicant":{},"business":{"licenseRequired":"Yes"}},[])
        sources={f["source"] for f in result["flags"]}
        for field in ("business.businessLicenseType","business.businessLicenseIssuer","business.businessLicenseNumberLast4","business.businessLicenseExpiry"):
            self.assertIn(field,sources)

    def test_registration_and_license_last_four_accept_alphanumeric_only(self):
        validate_patch("business",{"registrationLast4":"A1B2","businessLicenseNumberLast4":"L942"})
        with self.assertRaises(ValidationError): validate_patch("business",{"registrationLast4":"AB/2"})
        with self.assertRaises(ValidationError): validate_patch("business",{"businessLicenseNumberLast4":"12345"})

    def test_provider_policy_overrides_are_separate_and_configured(self):
        self.assertEqual(policy_tags("7995"),"enhanced-review")
        self.assertEqual(policy_tags("7995","example_acquirer"),"restricted/unsupported")
        self.assertEqual(policy_tags("5812","example_acquirer"),"standard")
        self.assertEqual(policy_tags("5812","unknown-provider"),"standard")

    def test_evaluation_flags_inconsistent_transaction_estimates_with_sources(self):
        result=evaluate({"applicant":{},"business":{"annualCardVolume":"120000","averageTicket":"25","monthlyTransactions":"100","highestTicket":"10"}},[])
        codes={flag["code"] for flag in result["flags"]}
        self.assertIn("transaction_estimate_mismatch",codes)
        self.assertIn("ticket_order_mismatch",codes)
        self.assertTrue(all(flag.get("source") for flag in result["flags"]))

if __name__=="__main__": unittest.main()
