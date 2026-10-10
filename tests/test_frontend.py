import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class FormContract(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids=[]
        self.named_fields={}
        self.panels=[]
        self.stack=[]

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        panel=attrs.get("data-panel")
        inherited=next((entry[1] for entry in reversed(self.stack) if entry[1]),None)
        current=panel or inherited
        if panel: self.panels.append(panel)
        if "id" in attrs: self.ids.append(attrs["id"])
        if tag in {"input","select","textarea"} and "name" in attrs:
            self.named_fields.setdefault(attrs["name"],set()).add(current)
        if tag not in {"area","base","br","col","embed","hr","img","input","link","meta","param","source","track","wbr"}:
            self.stack.append((tag,current))

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1,-1,-1):
            if self.stack[index][0]==tag:
                del self.stack[index:]
                break


class FrontendContractTests(unittest.TestCase):
    def test_form_fields_steps_and_javascript_selectors_are_consistent(self):
        html=(ROOT/"frontend"/"index.html").read_text(encoding="utf-8")
        js=(ROOT/"frontend"/"app.js").read_text(encoding="utf-8")
        parser=FormContract(); parser.feed(html)
        self.assertEqual(len(parser.ids),len(set(parser.ids)),"HTML ids must be unique")
        self.assertTrue({"business","owner","documents","category","review"}<=set(parser.panels))
        for name in ("operatingCountries","fulfillmentModel","recurringPayments","customerType"):
            self.assertIn("business",parser.named_fields.get(name,set()),f"{name} must be inside the business step")
        self.assertIn("documents",parser.named_fields.get("reasonRequested",set()))
        html_ids=set(parser.ids)
        js_ids=set(re.findall(r'\$\("#([A-Za-z][\w-]*)"\)',js))
        self.assertFalse(js_ids-html_ids,f"JavaScript references missing HTML ids: {sorted(js_ids-html_ids)}")
        for field in ("operatingCountries","fulfillmentModel","recurringPayments","customerType"):
            self.assertIn(f'"{field}"',js,"Business profile fields must be saved by the frontend")

    def test_review_continue_stays_clickable_and_submission_remains_server_gated(self):
        js=(ROOT/"frontend"/"app.js").read_text(encoding="utf-8")
        self.assertIn('disabled=app?.status==="SUBMITTED"',js)
        self.assertNotIn('disabled=key==="review"',js)
        self.assertNotIn('disabled=flags.some(f=>f.code.startsWith("missing_"))',js)
        self.assertIn('if(!$("[name=finalConsent]").checked)',js)
        self.assertIn('/submit`,{finalAttestation:true',js)

    def test_user_supplied_document_labels_are_escaped_before_html_rendering(self):
        js=(ROOT/"frontend"/"app.js").read_text(encoding="utf-8")
        self.assertIn("${esc(label||docLabels[type])}",js)
        self.assertNotIn("${label||docLabels[type]}",js)

    def test_static_frontend_has_a_restrictive_content_security_policy(self):
        html=(ROOT/"frontend"/"index.html").read_text(encoding="utf-8")
        self.assertIn('http-equiv="Content-Security-Policy"',html)
        self.assertIn("script-src 'self'",html)
        self.assertIn("object-src 'none'",html)
        self.assertIn('name="referrer" content="no-referrer"',html)


if __name__=="__main__": unittest.main()
