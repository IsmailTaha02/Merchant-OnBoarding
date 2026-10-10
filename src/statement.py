"""Parse a deliberately narrow, synthetic statement fixture without persisting raw text."""
from __future__ import annotations
import re
from decimal import Decimal, InvalidOperation
from domain import ValidationError

MAX_STATEMENT_TEXT_CHARS=20_000
PATTERNS={
    "processor": r"^Processor:\s*(.{1,100})\s*$",
    "statementPeriod": r"^Statement period:\s*(.{1,80})\s*$",
    "currentMonthlyVolume": r"^(?:Card sales volume|Monthly card volume):\s*(?:GBP|USD|EUR|£|\$|€)?\s*([\d,]+(?:\.\d{1,2})?)\s*$",
    "discountFee": r"^Discount / processing fees:\s*(?:GBP|USD|EUR|£|\$|€)?\s*([\d,]+(?:\.\d{1,2})?)\s*$",
    "transactionFees": r"^Transaction fees:\s*(?:GBP|USD|EUR|£|\$|€)?\s*([\d,]+(?:\.\d{1,2})?)\s*$",
    "monthlyServiceFees": r"^Monthly service fees:\s*(?:GBP|USD|EUR|£|\$|€)?\s*([\d,]+(?:\.\d{1,2})?)\s*$",
    "chargebackFees": r"^Chargeback fees:\s*(?:GBP|USD|EUR|£|\$|€)?\s*([\d,]+(?:\.\d{1,2})?)\s*$",
    "transactions": r"^Transactions:\s*([\d,]+)\s*$",
}

def _number(value: str) -> Decimal:
    try: result=Decimal(value.replace(",", ""))
    except InvalidOperation: raise ValidationError("Statement contains an invalid amount")
    if result<0 or result>Decimal("1000000000000"): raise ValidationError("Statement amount is outside the supported range")
    return result

def parse_statement(text: str) -> dict:
    if not isinstance(text,str) or not text.strip(): raise ValidationError("Paste sanitized statement text to extract")
    if len(text)>MAX_STATEMENT_TEXT_CHARS: raise ValidationError("Statement text is too long; provide only the relevant totals")
    captured={}
    for line in text.splitlines():
        for name,pattern in PATTERNS.items():
            match=re.match(pattern,line.strip(),flags=re.IGNORECASE)
            if match: captured[name]=match.group(1).strip()
    if "currentMonthlyVolume" not in captured: raise ValidationError("Could not find a Card sales volume or Monthly card volume line")
    fee_keys=("discountFee","transactionFees","monthlyServiceFees","chargebackFees")
    if not any(k in captured for k in fee_keys): raise ValidationError("Could not find any supported fee lines")
    breakdown={k:float(_number(captured[k])) if k in captured else 0.0 for k in fee_keys}
    total=sum(_number(captured[k]) for k in fee_keys if k in captured)
    volume=_number(captured["currentMonthlyVolume"])
    normalized={"processor":captured.get("processor"),"statementPeriod":captured.get("statementPeriod"),"currentMonthlyVolume":float(volume),"currentFees":float(total),"transactionCount":int(captured["transactions"].replace(",", "")) if "transactions" in captured else None,"feeBreakdown":breakdown,"effectiveRatePercent":round(float(total/volume*100),4) if volume else None,"confidence":0.9,"source":"fixture-text-parser","verified":False}
    return {"normalized":normalized,"extractedFields":sorted(captured.keys()),"rawTextStored":False,"note":"Rule-based extraction from sanitized text. Confirm every value against the original statement."}
