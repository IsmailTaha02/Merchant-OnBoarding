"""Pure onboarding rules. No network calls or cloud dependencies live here."""
from __future__ import annotations
import json
import math
import re
from typing import NotRequired, TypedDict
from datetime import datetime, timezone
from pathlib import Path
from providers import default_analysis_provider

ROOT = Path(__file__).parent
MCCS = json.loads((ROOT / "mcc_catalog.json").read_text(encoding="utf-8"))
RISK_POLICY = json.loads((ROOT / "risk_policy.json").read_text(encoding="utf-8"))
REQUIRED_DOCUMENTS = {"government_id", "business_registration", "bank_evidence"}
ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/png"}
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_DOCUMENT_RECORDS = 50
MAX_EVALUATION_RECORDS = 40

class Address(TypedDict):
    line1: str
    line2: NotRequired[str]
    city: str
    stateOrProvince: NotRequired[str]
    postalCode: str
    country: str

class BeneficialOwner(TypedDict):
    ownerId: str
    firstName: str
    middleName: NotRequired[str]
    lastName: str
    dateOfBirth: str
    residentialAddress: Address
    email: str
    phone: str
    role: str
    ownershipPercent: NotRequired[float]
    idType: str
    idLast4: str
    idExpiresAt: NotRequired[str]

class Applicant(TypedDict):
    firstName: str
    middleName: NotRequired[str]
    lastName: str
    dateOfBirth: str
    residentialAddress: NotRequired[str]
    residentialAddressLine1: str
    residentialAddressLine2: NotRequired[str]
    residentialCity: str
    residentialStateOrProvince: NotRequired[str]
    residentialPostalCode: str
    residentialCountry: str
    email: str
    phone: NotRequired[str]
    role: str
    ownershipPercent: NotRequired[float]
    idType: str
    idLast4: str
    idExpiresAt: NotRequired[str]
    consentAt: str
    termsVersion: str
    beneficialOwners: NotRequired[list[BeneficialOwner]]

class Business(TypedDict):
    legalName: str
    tradeName: NotRequired[str]
    entityType: str
    formationCountry: str
    formationRegion: NotRequired[str]
    registrationLast4: NotRequired[str]
    registeredAddress: str
    registeredAddressLine1: NotRequired[str]
    registeredAddressLine2: NotRequired[str]
    registeredAddressCity: NotRequired[str]
    registeredAddressRegion: NotRequired[str]
    registeredAddressPostalCode: NotRequired[str]
    registeredAddressCountry: NotRequired[str]
    operatingAddress: NotRequired[str]
    operatingCountries: NotRequired[str]
    fulfillmentModel: NotRequired[str]
    recurringPayments: NotRequired[str]
    customerType: NotRequired[str]
    website: NotRequired[str]
    description: str
    startDate: NotRequired[str]
    annualCardVolume: str
    averageTicket: NotRequired[str]
    highestTicket: NotRequired[str]
    monthlyTransactions: NotRequired[str]
    cardPresentPercent: NotRequired[str]
    cardNotPresentPercent: NotRequired[str]
    ecommercePercent: NotRequired[str]
    industry: NotRequired[str]
    licenseRequired: NotRequired[str]
    businessLicenseType: NotRequired[str]
    businessLicenseIssuer: NotRequired[str]
    businessLicenseNumberLast4: NotRequired[str]
    businessLicenseExpiry: NotRequired[str]
    settlementAccountHolder: NotRequired[str]
    settlementBankName: NotRequired[str]
    settlementAccountLast4: NotRequired[str]

class DocumentRecord(TypedDict):
    documentId: str
    documentType: str
    status: str
    reviewStatus: str
    contentType: str
    fileExtension: str
    sizeBytes: int
    checksumSha256: NotRequired[str]
    s3Key: str
    ownerId: NotRequired[str]
    uploadedAt: NotRequired[str]
    expiresAt: NotRequired[str]
    versionId: NotRequired[str]

class Application(TypedDict):
    applicationId: str
    status: str
    version: int
    applicant: NotRequired[Applicant]
    business: NotRequired[Business]
    classification: NotRequired[dict]
    createdAt: str
    updatedAt: str
    actorSource: str
    requestId: str

class ValidationError(ValueError):
    pass

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def validate_application_id(value: str):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f-]{36}", value):
        raise ValidationError("Invalid application ID")

def validate_patch(section: str, data: dict):
    if not isinstance(data, dict) or not data:
        raise ValidationError("Provide at least one field")
    allowed = {
        "applicant": {"firstName", "middleName", "lastName", "email", "phone", "role", "ownershipPercent", "dateOfBirth", "residentialAddress", "residentialAddressLine1", "residentialAddressLine2", "residentialCity", "residentialStateOrProvince", "residentialPostalCode", "residentialCountry", "idType", "idLast4", "idExpiresAt", "consentAt", "termsVersion", "beneficialOwners"},
        "business": {"legalName", "tradeName", "entityType", "formationCountry", "formationRegion", "registrationLast4", "registeredAddress", "registeredAddressLine1", "registeredAddressLine2", "registeredAddressCity", "registeredAddressRegion", "registeredAddressPostalCode", "registeredAddressCountry", "operatingAddress", "operatingCountries", "fulfillmentModel", "recurringPayments", "customerType", "website", "description", "startDate", "annualCardVolume", "averageTicket", "highestTicket", "monthlyTransactions", "cardPresentPercent", "cardNotPresentPercent", "ecommercePercent", "industry", "processor", "currentMonthlyVolume", "currentFees", "statementPeriod", "settlementAccountHolder", "settlementBankName", "settlementAccountLast4", "bankStatementDate", "licenseRequired", "businessLicenseType", "businessLicenseIssuer", "businessLicenseNumberLast4", "businessLicenseExpiry"},
    }
    if section not in allowed or set(data) - allowed[section]:
        raise ValidationError("One or more fields are not supported")
    if section == "applicant" and "beneficialOwners" in data:
        owners = data["beneficialOwners"]
        owner_fields = {"ownerId", "firstName", "middleName", "lastName", "dateOfBirth", "residentialAddress", "email", "phone", "role", "ownershipPercent", "idType", "idLast4", "idExpiresAt"}
        required_owner_fields = {"ownerId", "firstName", "lastName", "dateOfBirth", "residentialAddress", "email", "phone", "role", "idType", "idLast4"}
        if not isinstance(owners, list) or len(owners) > 20:
            raise ValidationError("Provide no more than 20 additional owners or controllers")
        owner_ids=set()
        for index, owner in enumerate(owners, start=1):
            if not isinstance(owner, dict) or set(owner) - owner_fields:
                raise ValidationError(f"Additional person {index} contains unsupported fields")
            if required_owner_fields - set(owner):
                raise ValidationError(f"Additional person {index} is missing required fields")
            address = owner["residentialAddress"]
            address_fields = {"line1", "line2", "city", "stateOrProvince", "postalCode", "country"}
            if not isinstance(address, dict) or set(address) - address_fields or {"line1", "city", "postalCode", "country"} - set(address):
                raise ValidationError(f"Additional person {index} needs a complete residential address")
            if not isinstance(owner.get("ownerId"),str) or not re.fullmatch(r"[0-9a-f-]{36}",owner["ownerId"]):
                raise ValidationError(f"Additional person {index} needs a valid owner reference")
            if owner["ownerId"] in owner_ids: raise ValidationError("Each additional person must have a unique owner reference")
            owner_ids.add(owner["ownerId"])
            if not all(isinstance(address.get(k), str) and address[k].strip() for k in ("line1", "city", "postalCode", "country")):
                raise ValidationError(f"Additional person {index} needs non-empty address details")
            if any(not isinstance(v, str) or len(v) > 300 for v in address.values()):
                raise ValidationError(f"Additional person {index} address contains an invalid value")
            if not all(isinstance(owner[k], str) and owner[k].strip() for k in ("firstName", "lastName", "dateOfBirth", "email", "phone", "role")):
                raise ValidationError(f"Additional person {index} has an empty required field")
            if owner["role"] not in {"Owner","Director","Partner","Controller","Other"}:
                raise ValidationError(f"Additional person {index} needs a supported role")
            try:
                if datetime.fromisoformat(owner["dateOfBirth"]).date()>datetime.now(timezone.utc).date(): raise ValidationError(f"Additional person {index} date of birth cannot be in the future")
            except ValueError: raise ValidationError(f"Additional person {index} date of birth must be an ISO date")
            if owner.get("idExpiresAt"):
                try: datetime.fromisoformat(owner["idExpiresAt"])
                except ValueError: raise ValidationError(f"Additional person {index} ID expiry must be an ISO date")
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", owner["email"]):
                raise ValidationError(f"Additional person {index} needs a valid email")
            if owner["idType"] not in {"Passport", "Driver's license", "National ID", "Other"}:
                raise ValidationError(f"Additional person {index} needs a supported ID type")
            if not re.fullmatch(r"\d{4}", str(owner["idLast4"])):
                raise ValidationError(f"Additional person {index} ID must contain only its last four digits")
            if owner.get("ownershipPercent") not in (None, ""):
                try: ownership = float(owner["ownershipPercent"])
                except (TypeError, ValueError): raise ValidationError(f"Additional person {index} ownership must be a number")
                if not math.isfinite(ownership): raise ValidationError(f"Additional person {index} ownership must be a finite number")
                if ownership < 0 or ownership > 100: raise ValidationError(f"Additional person {index} ownership must be between 0 and 100")
    for key, value in data.items():
        if isinstance(value, str) and len(value) > 2000:
            raise ValidationError(f"{key} is too long")
        if key in {"idLast4", "settlementAccountLast4"} and value and not re.fullmatch(r"\d{4}", str(value)):
            raise ValidationError(f"{key} must contain exactly four digits")
        if key in {"registrationLast4", "businessLicenseNumberLast4"} and value and not re.fullmatch(r"[A-Za-z0-9]{4}", str(value)):
            raise ValidationError(f"{key} must contain exactly four letters or digits")
        if key=="idType" and value not in (None, "", "Passport", "Driver's license", "National ID", "Other"):
            raise ValidationError("Choose a supported government ID type")
        if key in {"dateOfBirth", "businessLicenseExpiry", "idExpiresAt", "bankStatementDate", "startDate"} and value not in (None, ""):
            if not isinstance(value,str): raise ValidationError(f"{key} must be an ISO date")
            try:
                parsed_date=datetime.fromisoformat(value).date()
                if key=="dateOfBirth" and parsed_date>datetime.now(timezone.utc).date(): raise ValidationError("Date of birth cannot be in the future")
            except ValueError: raise ValidationError(f"{key} must be an ISO date")
        if key == "email" and value and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", str(value)):
            raise ValidationError("Enter a valid email address")
        if key == "entityType" and value not in (None,"","Limited company","Sole proprietor","Partnership","Corporation","Nonprofit","Other"):
            raise ValidationError("Choose a supported business structure")
        if key == "role" and value not in (None,"","Owner","Director","Partner","Controller","Other"):
            raise ValidationError("Choose a supported applicant role")
        if key == "licenseRequired" and value not in (None,"","Yes","No","Unsure"):
            raise ValidationError("Choose whether a business license is required")
        if key == "recurringPayments" and value not in (None,"","Yes","No"):
            raise ValidationError("Choose whether you offer recurring payments")
        if key == "customerType" and value not in (None,"","Consumers","Businesses","Both"):
            raise ValidationError("Choose the customer type")
        if key == "fulfillmentModel" and value not in (None,"","Physical goods","Digital goods","In-person services","Remote services","Mixed","Other"):
            raise ValidationError("Choose a supported fulfillment model")
        if key == "website" and value and not re.fullmatch(r"https?://[A-Za-z0-9.-]+(?::\d+)?(?:/[^\s]*)?",value):
            raise ValidationError("Website must be a valid HTTP or HTTPS address")
        if key in {"ownershipPercent", "cardPresentPercent", "cardNotPresentPercent", "ecommercePercent"} and value not in (None, ""):
            try: number = float(value)
            except (TypeError, ValueError): raise ValidationError(f"{key} must be a number")
            if not math.isfinite(number): raise ValidationError(f"{key} must be a finite number")
            if number < 0 or number > 100: raise ValidationError(f"{key} must be between 0 and 100")
        if key in {"annualCardVolume", "averageTicket", "highestTicket", "monthlyTransactions", "currentMonthlyVolume", "currentFees"} and value not in (None, ""):
            try: number = float(value)
            except (TypeError, ValueError): raise ValidationError(f"{key} must be a number")
            if not math.isfinite(number): raise ValidationError(f"{key} must be a finite number")
            if number < 0: raise ValidationError(f"{key} cannot be negative")
    if section == "business" and "cardPresentPercent" in data and "cardNotPresentPercent" in data:
        try:
            if abs(float(data["cardPresentPercent"]) + float(data["cardNotPresentPercent"]) - 100) > 0.01:
                raise ValidationError("Card-present and card-not-present percentages must total 100")
        except (TypeError, ValueError):
            raise ValidationError("Card-present and card-not-present percentages must be numbers")
    if section == "business" and data.get("ecommercePercent") not in (None, "") and data.get("cardNotPresentPercent") not in (None, ""):
        if float(data["ecommercePercent"]) > float(data["cardNotPresentPercent"]):
            raise ValidationError("E-commerce sales cannot exceed card-not-present sales")
    return data

def suggest_mcc(industry: str, description: str):
    text = f"{industry or ''} {description or ''}".lower()
    results = []
    for row in MCCS:
        hits = sum(1 for term in row["keywords"] if term in text)
        if hits:
            results.append({"code": row["code"], "description": row["description"], "confidence": min(.99, .62 + .12 * hits), "reason": f"Matched business activity terms: {', '.join(t for t in row['keywords'] if t in text)}"})
    # Do not substitute a default MCC when the curated activity keywords do not match.
    # The complete catalog remains searchable; a human/applicant can choose the correct entry.
    results.sort(key=lambda item: item["confidence"], reverse=True)
    return results[:3]

def policy_tags(code: str, provider_id: str | None = None):
    """Read versioned policy separately from the network MCC catalog."""
    default=RISK_POLICY["default"].get(code,"standard")
    return RISK_POLICY.get("providerOverrides",{}).get(provider_id,{}).get(code,default)

def policy_providers():
    return sorted(RISK_POLICY.get("providerOverrides",{}))

def risk_policy_version():
    return RISK_POLICY["version"]

def evaluate(app, docs):
    applicant, business = app.get("applicant", {}), app.get("business", {})
    flags = []
    needed = [("applicant.firstName", applicant.get("firstName")), ("applicant.lastName", applicant.get("lastName")), ("applicant.dateOfBirth", applicant.get("dateOfBirth")), ("applicant.idType", applicant.get("idType")), ("applicant.idLast4", applicant.get("idLast4")), ("applicant.residentialAddressLine1", applicant.get("residentialAddressLine1") or applicant.get("residentialAddress")), ("applicant.residentialCity", applicant.get("residentialCity") or applicant.get("residentialAddress")), ("applicant.residentialPostalCode", applicant.get("residentialPostalCode") or applicant.get("residentialAddress")), ("applicant.residentialCountry", applicant.get("residentialCountry") or applicant.get("residentialAddress")), ("applicant.email", applicant.get("email")), ("applicant.phone", applicant.get("phone")), ("applicant.role", applicant.get("role")), ("applicant.consentAt", applicant.get("consentAt")), ("applicant.termsVersion", applicant.get("termsVersion")), ("business.legalName", business.get("legalName")), ("business.entityType", business.get("entityType")), ("business.formationCountry", business.get("formationCountry")), ("business.registrationLast4", business.get("registrationLast4")), ("business.registeredAddressLine1", business.get("registeredAddressLine1")), ("business.registeredAddressCity", business.get("registeredAddressCity")), ("business.registeredAddressPostalCode", business.get("registeredAddressPostalCode")), ("business.registeredAddressCountry", business.get("registeredAddressCountry")), ("business.operatingAddress", business.get("operatingAddress") or business.get("registeredAddress")), ("business.description", business.get("description")), ("business.annualCardVolume", business.get("annualCardVolume")), ("business.averageTicket", business.get("averageTicket")), ("business.highestTicket", business.get("highestTicket")), ("business.monthlyTransactions", business.get("monthlyTransactions")), ("business.cardPresentPercent", business.get("cardPresentPercent")), ("business.cardNotPresentPercent", business.get("cardNotPresentPercent")), ("business.ecommercePercent", business.get("ecommercePercent")), ("business.licenseRequired", business.get("licenseRequired")), ("business.settlementAccountHolder", business.get("settlementAccountHolder")), ("business.settlementBankName", business.get("settlementBankName")), ("business.settlementAccountLast4", business.get("settlementAccountLast4"))]
    for field, value in needed:
        if value in (None, ""):
            flags.append({"code":"missing_field", "severity":"warning", "message":f"Required information is missing: {field}", "source":field})
    owners = applicant.get("beneficialOwners", [])
    if applicant.get("role") in {"Owner", "Partner"} and applicant.get("ownershipPercent") in (None, ""):
        flags.append({"code":"missing_field", "severity":"warning", "message":"Enter the primary applicant's ownership percentage or change the role if this person has no equity ownership.", "source":"applicant.ownershipPercent and applicant.role"})
    dated_people=[("primary","applicant",applicant.get("idExpiresAt"))]+[(owner.get("ownerId"),f"beneficial owner/controller {i}",owner.get("idExpiresAt")) for i,owner in enumerate(owners,start=1)]
    for _,label,expiry in dated_people:
        if expiry:
            try:
                from datetime import date
                if date.fromisoformat(expiry)<date.today(): flags.append({"code":"expired_id_review","severity":"review","message":f"The entered government ID expiry date for {label} is in the past; confirm current identification with the reviewer.","source":f"applicant.{label}.idExpiresAt"})
            except (TypeError,ValueError): flags.append({"code":"invalid_id_expiry","severity":"review","message":f"The government ID expiry date for {label} could not be read.","source":f"applicant.{label}.idExpiresAt"})
    try: ownership_total = float(applicant.get("ownershipPercent") or 0)
    except (TypeError, ValueError): ownership_total = 0.0
    ownership_total_incomplete=applicant.get("role") in {"Owner", "Partner"} and applicant.get("ownershipPercent") in (None, "")
    for index, owner in enumerate(owners, start=1):
        prefix=f"applicant.beneficialOwners[{index - 1}]"
        for name in ("firstName", "lastName", "dateOfBirth", "email", "phone", "role"):
            if not owner.get(name):
                field=f"{prefix}.{name}"
                flags.append({"code":"missing_field", "severity":"warning", "message":f"Additional owner/controller {index} is missing {name}.", "source":field})
        addr=owner.get("residentialAddress", {})
        for name in ("line1", "city", "postalCode", "country"):
            if not addr.get(name):
                field=f"{prefix}.residentialAddress.{name}"
                flags.append({"code":"missing_field", "severity":"warning", "message":f"Additional owner/controller {index} has an incomplete address.", "source":field})
        try: ownership_total += float(owner.get("ownershipPercent") or 0)
        except (TypeError, ValueError): pass
        if owner.get("role") in {"Owner", "Partner"} and owner.get("ownershipPercent") in (None, ""):
            field=f"{prefix}.ownershipPercent"
            flags.append({"code":"missing_field", "severity":"warning", "message":f"Owner/controller {index} has an ownership role but no ownership percentage.", "source":field})
            ownership_total_incomplete=True
    if ownership_total > 100.01:
        flags.append({"code":"ownership_total_review", "severity":"review", "message":"Recorded beneficial ownership percentages total more than 100%; confirm the ownership structure.", "source":"applicant.ownershipPercent and applicant.beneficialOwners[].ownershipPercent"})
    elif ownership_total_incomplete or 0 < ownership_total < 99.99:
        flags.append({"code":"ownership_total_review", "severity":"review", "message":"Recorded ownership is below 100%; confirm whether all owners are disclosed and distinguish non-equity controllers.", "source":"applicant.ownershipPercent and applicant.beneficialOwners[].ownershipPercent"})
    present = {doc.get("documentType") for doc in docs if doc.get("status") in {"RECEIVED", "NEEDS_REVIEW", "ACCEPTED"}}
    for doc_type in sorted((REQUIRED_DOCUMENTS - {"government_id"}) - present):
        flags.append({"code":"missing_document", "severity":"warning", "message":f"Required document not received: {doc_type.replace('_',' ')}", "source":f"documents.{doc_type}"})
    has_license="business_license" in present
    if business.get("licenseRequired")=="Yes" and not has_license:
        flags.append({"code":"missing_document", "severity":"warning", "message":"A business license was declared as required but no license document has been received.", "source":"business.licenseRequired and documents.business_license"})
    if business.get("licenseRequired")=="Yes" and not business.get("businessLicenseExpiry"):
        flags.append({"code":"missing_field", "severity":"warning", "message":"Enter the expiry date for the required business license.", "source":"business.businessLicenseExpiry"})
    if business.get("licenseRequired")=="Yes":
        for key in ("businessLicenseType", "businessLicenseIssuer", "businessLicenseNumberLast4"):
            if not business.get(key):
                flags.append({"code":"missing_field", "severity":"warning", "message":f"Enter the required business-license detail: {key}.", "source":f"business.{key}"})
    if business.get("licenseRequired")=="Unsure":
        flags.append({"code":"license_requirement_review", "severity":"review", "message":"Confirm whether the business activity requires a local or professional license.", "source":"business.licenseRequired"})
    if business.get("businessLicenseExpiry"):
        try:
            from datetime import date
            expires=date.fromisoformat(business["businessLicenseExpiry"])
            if expires < date.today(): flags.append({"code":"expired_license_review", "severity":"review", "message":"The entered business license expiry date is in the past; verify the current license evidence.", "source":"business.businessLicenseExpiry"})
        except (TypeError,ValueError): flags.append({"code":"invalid_license_expiry", "severity":"review", "message":"The business license expiry date could not be read; confirm it with the document.", "source":"business.businessLicenseExpiry"})
    received_ids={doc.get("ownerId") or "primary" for doc in docs if doc.get("documentType")=="government_id" and doc.get("status") in {"RECEIVED", "NEEDS_REVIEW", "ACCEPTED"}}
    required_ids=[("primary","applicant")]+[(owner.get("ownerId"),f"beneficial owner/controller {i}") for i,owner in enumerate(owners,start=1)]
    for owner_id,label in required_ids:
        if owner_id not in received_ids:
            flags.append({"code":"missing_document", "severity":"warning", "message":f"Required government ID not received for {label}.", "source":f"documents.government_id.{owner_id}"})
    try:
        expected, actual = float(business.get("annualCardVolume") or 0), float(business.get("currentMonthlyVolume") or 0) * 12
        if expected and actual and abs(expected-actual) / max(expected, actual) > .3:
            flags.append({"code":"volume_mismatch", "severity":"review", "message":"Annual volume differs by more than 30% from the uploaded statement's annualized monthly volume.", "source":"business.annualCardVolume and business.currentMonthlyVolume"})
    except (TypeError, ValueError): pass
    try:
        annual=float(business.get("annualCardVolume") or 0)
        average=float(business.get("averageTicket") or 0)
        transactions=float(business.get("monthlyTransactions") or 0)
        estimated=average*transactions*12
        if annual and estimated and abs(annual-estimated)/max(annual,estimated)>.3:
            flags.append({"code":"transaction_estimate_mismatch","severity":"review","message":"Expected annual card sales differ by more than 30% from average transaction × monthly transaction count × 12; confirm the estimates.","source":"business.annualCardVolume, business.averageTicket, and business.monthlyTransactions"})
        highest=float(business.get("highestTicket") or 0)
        if average and highest and highest<average:
            flags.append({"code":"ticket_order_mismatch","severity":"review","message":"The stated largest transaction is below the average transaction; confirm both estimates.","source":"business.averageTicket and business.highestTicket"})
    except (TypeError,ValueError): pass
    code = app.get("classification", {}).get("selectedCode")
    classification=app.get("classification", {})
    if not code:
        flags.append({"code":"missing_classification", "severity":"warning", "message":"Choose and confirm a business category before submission.", "source":"classification.selectedCode"})
    else:
        candidates=classification.get("candidates", [])
        suggested=next((candidate for candidate in candidates if candidate.get("code")==code),None)
        try: confidence=float(suggested.get("confidence") or 0) if suggested else 0
        except (TypeError,ValueError): confidence=0
        if candidates and (suggested is None or not math.isfinite(confidence) or confidence<0.5):
            flags.append({"code":"mcc_activity_mismatch", "severity":"review", "message":f"Selected MCC {code} is not strongly supported by the activity-based suggestions; confirm the business description and category with a reviewer.", "source":"business.industry, business.description, and classification.selectedCode"})
    provider_id=app.get("classification",{}).get("providerId")
    tag=policy_tags(code,provider_id) if code else "standard"
    if code and tag != "standard":
        flags.append({"code":"policy_review", "severity":"review", "message":f"Selected MCC {code} has the '{tag}' policy tag for {provider_id or 'default intake'}; route for human review.", "source":"classification.selectedCode and classification.providerId" if provider_id else "classification.selectedCode"})
    try:
        average, highest = float(business.get("averageTicket") or 0), float(business.get("highestTicket") or 0)
        if highest > 5000 or (average and highest > 10 * average):
            flags.append({"code":"ticket_size_review", "severity":"review", "message":"The highest expected transaction is unusually large compared with the average; confirm the estimate and supporting evidence.", "source":"business.highestTicket and business.averageTicket"})
    except (TypeError, ValueError): pass
    if business.get("industry") and business.get("description") and business["industry"].lower() not in business["description"].lower():
        flags.append({"code":"activity_mismatch", "severity":"review", "message":"The description may not match the selected industry; confirm the business activity.", "source":"business.industry and business.description"})
    rate = None
    if business.get("currentMonthlyVolume") not in (None, "", 0, "0") and business.get("currentFees") not in (None, ""):
        try:
            volume, fees = float(business["currentMonthlyVolume"]), float(business["currentFees"])
            rate = {"monthlyVolume":volume, "monthlyFees":fees, "effectiveRatePercent":round(fees / volume * 100, 4) if volume else None, "method":"monthly fees ÷ monthly volume × 100", "source":"business.currentMonthlyVolume and business.currentFees"}
        except (ValueError, TypeError): pass
    analysis=default_analysis_provider().summarize(business)
    return {"status":"READY_FOR_REVIEW" if not any(f["code"].startswith("missing_") for f in flags) else "INCOMPLETE", "flags":flags, "rateAnalysis":rate, "businessSummary":analysis, "summary":"Automated intake checks completed. A human reviewer must make the underwriting decision.", "createdAt":utc_now()}

def submission_payload(app, docs, evaluation, version):
    return {"applicationId":app["applicationId"], "submissionVersion":version, "submittedAt":utc_now(), "decisionStatus":"PENDING_HUMAN_REVIEW", "applicant":app.get("applicant", {}), "business":app.get("business", {}), "documents":[{k:d.get(k) for k in ("documentId","documentType","status","contentType","sizeBytes","checksumSha256","uploadedAt","s3Key","versionId")} for d in docs], "classification":app.get("classification"), "evaluation":evaluation, "note":"This payload is intake support; it is not an approval decision."}
