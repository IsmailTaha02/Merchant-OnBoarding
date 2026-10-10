"""Validate a source MCC CSV and refresh the catalog plus provenance metadata.

CSV headers: code,description. Existing curated keywords are preserved by code.
Usage: python scripts/import_mcc.py input.csv --edition "April 2026" --source-url https://...
"""
import argparse
import csv
import json
import re
from pathlib import Path


def import_catalog(source: Path, catalog_path: Path, metadata_path: Path, edition: str | None = None, source_url: str | None = None, complete_source: bool = False):
    existing=json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.exists() else []
    metadata=json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {"schemaVersion":1,"source":"Visa Merchant Data Standards Manual"}
    keywords={row["code"]:row.get("keywords",[]) for row in existing}
    rows={}
    with source.open(newline="",encoding="utf-8-sig") as stream:
        reader=csv.DictReader(stream)
        headers={name.strip().lower() for name in (reader.fieldnames or [])}
        if not {"code","description"}.issubset(headers):
            raise ValueError("CSV must have code and description headers")
        for raw in reader:
            row={key.strip().lower():value.strip() for key,value in raw.items() if key and value}
            code=row.get("code","").zfill(4); description=row.get("description","")
            if not re.fullmatch(r"\d{4}",code) or not description:
                raise ValueError("Every MCC row must contain a four-digit code and a description")
            if code in rows and rows[code]!=description:
                raise ValueError(f"Conflicting descriptions for MCC {code}")
            rows[code]=description
    if not rows: raise ValueError("No valid MCC rows found")
    catalog=[{"code":code,"description":description,"keywords":keywords.get(code,[])} for code,description in sorted(rows.items())]
    metadata["rowCount"]=len(catalog)
    metadata["isComplete"]=bool(complete_source)
    if edition:
        metadata["sourceEdition"]=edition
        slug=re.sub(r"[^a-z0-9]+","-",edition.lower()).strip("-")
        metadata["catalogVersion"]=f"visa-mdsm-{slug}"
    if source_url: metadata["sourceUrl"]=source_url
    metadata["notes"]="Catalog refreshed from the cited source edition. Completeness is claimed only when --complete-source is supplied. Activity keywords are curated separately and may not cover every MCC; provider-specific acceptance policy is not part of this catalog."
    catalog_path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return len(catalog)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path",type=Path)
    parser.add_argument("--edition",help="Source manual edition, e.g. 'April 2026'")
    parser.add_argument("--source-url",help="Canonical URL of the source document")
    parser.add_argument("--complete-source",action="store_true",help="Assert that the CSV is the complete source catalog")
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    count=import_catalog(args.csv_path,root/"src"/"mcc_catalog.json",root/"src"/"mcc_catalog_metadata.json",args.edition,args.source_url,args.complete_source)
    print(f"Wrote {count} MCC codes and updated provenance metadata")


if __name__=="__main__": main()
