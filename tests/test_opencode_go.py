"""Synthetic sessions only; never reads the user's credentials."""
import importlib.util
import io
import json
import pathlib
import sqlite3
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("go", pathlib.Path(__file__).parents[1] / "providers/opencode-go/fetch.py")
go = importlib.util.module_from_spec(spec)
spec.loader.exec_module(go)

class GoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = pathlib.Path(self.temp.name) / "opencode.db"
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.db.execute("CREATE TABLE credential (integration_id TEXT, active INTEGER, time_updated INTEGER, value TEXT)")
        self.value = {"type":"oauth", "access":"synthetic-access", "refresh":"synthetic-refresh", "expires":2000000,
                      "metadata":{"orgID":"test-org", "server":go.SERVER}}
    def insert(self, value=None, active=1, integration="opencode"):
        self.db.execute("INSERT INTO credential VALUES (?, ?, 1, ?)",(integration,active,json.dumps(value or self.value)))
        self.db.commit()
    def payload(self):
        return {"access":{"endsAt":"2026-12-01T00:00:00Z", "meters":{
            key:{"limitMicroCents":"1000", "usedMicroCents":"10", "resetsAt":"2026-11-20T00:00:00+00:00"}
            for key in ("fiveHour","week","month")}}}
    def test_active_oauth_only_and_read_only(self):
        self.insert(active=0)
        self.insert({"type":"key","key":"synthetic-key"},integration="opencode-go")
        with self.assertRaises(go.Failure) as result: go.credential(self.path,1000)
        self.assertEqual(result.exception.code,"not_configured")
        self.insert()
        before = self.path.read_bytes()
        self.assertEqual(go.credential(self.path,1000),("synthetic-access","test-org"))
        self.assertEqual(self.path.read_bytes(),before)
    def test_expired_does_not_refresh(self):
        self.value["expires"]=1
        self.insert()
        with self.assertRaises(go.Failure) as result: go.credential(self.path,1000)
        self.assertEqual(result.exception.code,"expired")
    def test_untrusted_server_rejected(self):
        self.value["metadata"]["server"]="https://example.com"
        self.insert()
        with self.assertRaises(go.Failure): go.credential(self.path,1000)
    def test_wal_session_read_without_copy(self):
        self.db.execute("PRAGMA journal_mode=WAL")
        self.insert()
        self.assertEqual(go.credential(self.path,1000)[0],"synthetic-access")
    def test_request_and_output_do_not_export_secrets(self):
        self.insert()
        payload=self.payload()
        class Client:
            def open(client,req,timeout):
                self.assertEqual(req.full_url,go.SERVER+"/api/go/status")
                self.assertEqual(req.get_header("Authorization"),"Bearer synthetic-access")
                self.assertEqual(req.get_header("X-org-id"),"test-org")
                return io.BytesIO(json.dumps(payload).encode())
        result=go.fetch(self.path,1000,Client())
        self.assertEqual(result["windows"][0]["usedPercent"],1)
        self.assertIsNone(result["windows"][2]["periodSeconds"])
        self.assertNotIn("synthetic",json.dumps(result))
    def test_errors_do_not_leak_response(self):
        self.insert()
        for status,code in [(401,"auth"),(403,"auth"),(404,"no_plan"),(429,"rate_limited"),(500,"server")]:
            class Client:
                def open(client,req,timeout):
                    raise urllib.error.HTTPError(req.full_url,status,"synthetic-secret",{},None)
            with self.assertRaises(go.Failure) as result: go.fetch(self.path,1000,Client())
            self.assertEqual(result.exception.code,code)
    def test_invalid_meter_is_not_zero_usage(self):
        for value in [None,"bad",True,-1,float("nan"),float("inf")]:
            data=self.payload();data["access"]["meters"]["week"]["usedMicroCents"]=value
            with self.assertRaises(go.Failure): go.normalize(data)
    def test_missing_subscription_and_malformed_payload(self):
        for value,code in [({"access":None},"no_plan"),([],"parse"),({"access":{}},"parse")]:
            with self.assertRaises(go.Failure) as result: go.normalize(value)
            self.assertEqual(result.exception.code,code)
    def test_redirects_disabled(self):
        self.assertIsNone(go.NoRedirect().redirect_request(None,None,302,"",{},"https://example.com"))
    def test_main_redacts_unexpected_exceptions(self):
        with patch.object(go,"fetch",side_effect=RuntimeError("synthetic-secret")), patch("sys.stdout",new_callable=io.StringIO) as out:
            go.main()
        self.assertEqual(json.loads(out.getvalue()),{"error":"parse"})

if __name__ == "__main__": unittest.main()
