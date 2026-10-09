#!/usr/bin/env python3
"""Materialize the 2026-10-09 integrity-rigor capture and preserve raw artifacts."""
from __future__ import annotations
import base64, gzip, hashlib, io, json, os, tarfile, urllib.error, urllib.request, zipfile
from pathlib import Path

CAPTURE_ROOT=Path("audit/captures/2026-10-09-integrity-rigor")
PAYLOAD_SHA256="9a1ca6a0ebbf48bb28f74e5eb23e68b7936aeec499b159c68a9ab3b72bc597b8"
PART_SHA256={
 "payload.part00":"0313b034f4839f952c9cb0098d5755416047f44030ef786f73053cd329039eb0",
 "payload.part01":"4b514a3abe5cde60e06e73a96698213c2bd5401464c62b09bc5ac1732bc99897",
 "payload.part02":"ed0048fc9cccad58846b6b360cc4df3d24a0774b648e8fc22bb84fbd6b0e8f28",
 "payload.part03a":"10cbf7feebace34d6418506fb7e25381b2c8462866bc6e082962dd17e1b79a65",
 "payload.part03b":"2c59f57fa216a7282209392dee6be886d369365ae1159c4f960c2b8ca1bcff7f",
 "payload.part03c":"190dd71b26c75611b15b4a149c267459dec55472ff6d4d065a862a7b61c357dc",
 "payload.part03d":"6fcfaf15029c6eb2f12921e4504260d6b1939f5e9e478c228ba5a2bd768a8375",
}
ARTIFACTS=[
 (11610847746,"theorem-closure-receipts.zip","2beb37eaafacbdecdfa157cc1a240d1eb0f80ce6e9a0ef56aa91f1c6a4fb9dfd"),
 (11610594316,"landau-siegel-geometric-kernel-probe.zip","e35075f41fa1b2ec69ae5c0fcca13f4838dc7764f4e2c843325a20a2069c7b19"),
 (11611870569,"landau-siegel-analytic-kernel-probe.zip","93ba2588dcc0b1957204967794266850a606301d10d54838089c5a8a1095628d"),
 (11607286790,"path-encoding-integrity.zip","1aad39d47fe308570f4a5180ccee269257626d764b1be2a2427535a023401b18"),
 (11606943374,"genesis-rigor-scan-v2.zip","3a605158f4237f7adc35886286dd5454b341a5e67f836ea24d3afcea870586a6"),
]

def sha(data:bytes)->str: return hashlib.sha256(data).hexdigest()

def extract_payload()->None:
    parts=[CAPTURE_ROOT / name for name in sorted(PART_SHA256)]
    names=[p.name for p in parts]
    if names!=sorted(PART_SHA256):
        raise SystemExit(f"embedded payload part set mismatch: {names}")
    texts=[]; observations=[]
    for p in parts:
        text=p.read_text(encoding="ascii").strip()
        digest=sha(text.encode("ascii"))
        observations.append({"name":p.name,"characters":len(text),"sha256":digest,"expected_sha256":PART_SHA256[p.name]})
        texts.append(text)
    print(json.dumps({"payload_parts":observations},indent=2,sort_keys=True))
    mismatches=[item for item in observations if item["sha256"]!=item["expected_sha256"]]
    if mismatches:
        raise SystemExit(f"embedded payload part digest mismatch: {json.dumps(mismatches,sort_keys=True)}")
    encoded="".join(texts)
    encoded += "=" * (-len(encoded) % 4)
    compressed=base64.b64decode(encoded,validate=True)
    if sha(compressed)!=PAYLOAD_SHA256: raise SystemExit("embedded payload digest mismatch")
    raw=gzip.decompress(compressed)
    with tarfile.open(fileobj=io.BytesIO(raw),mode="r:") as tf:
        for member in tf.getmembers():
            if not member.isfile() or Path(member.name).is_absolute() or ".." in Path(member.name).parts:
                raise SystemExit(f"unsafe embedded member: {member.name}")
        tf.extractall(CAPTURE_ROOT,filter="data")

def download_artifacts()->list[dict[str,object]]:
    repo=os.environ["GITHUB_REPOSITORY"]; token=os.environ["GITHUB_TOKEN"]
    out=CAPTURE_ROOT/"raw-workflow-artifacts"; out.mkdir(parents=True,exist_ok=True)
    records=[]
    for aid,name,expected in ARTIFACTS:
        url=f"https://api.github.com/repos/{repo}/actions/artifacts/{aid}/zip"
        req=urllib.request.Request(url,headers={"Authorization":f"Bearer {token}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"grwtsk-audit-capture"})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        opener=urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(req,timeout=240) as response:
                data=response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in {301,302,303,307,308} or not exc.headers.get("Location"):
                raise
            location=exc.headers["Location"]
            with urllib.request.urlopen(location,timeout=240) as response:
                data=response.read()
        actual=sha(data)
        if actual!=expected: raise SystemExit(f"{name} digest mismatch: {actual} != {expected}")
        (out/name).write_bytes(data)
        records.append({"artifact_id":aid,"name":name,"bytes":len(data),"sha256":actual,"source_url":url})
    (out/"manifest.json").write_text(json.dumps({"schema_version":"RawWorkflowArtifactCapture/1","repository":repo,"records":records},indent=2,sort_keys=True)+"\n")
    return records

def build_release_bundle(records:list[dict[str,object]])->None:
    bundle=CAPTURE_ROOT/"integrity-rigor-capture-bundle.zip"
    with zipfile.ZipFile(bundle,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(CAPTURE_ROOT.rglob("*")):
            if not p.is_file() or p==bundle or p.parent.name=="raw-workflow-artifacts" or p.name.startswith("payload.part"): continue
            info=zipfile.ZipInfo(p.relative_to(CAPTURE_ROOT).as_posix(),(1980,1,1,0,0,0)); info.compress_type=zipfile.ZIP_DEFLATED; info.external_attr=0o100644<<16
            z.writestr(info,p.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    assets=[*records,{"name":bundle.name,"bytes":bundle.stat().st_size,"sha256":sha(bundle.read_bytes())}]
    (CAPTURE_ROOT/"RELEASE_ASSET_MANIFEST.json").write_text(json.dumps({"schema_version":"AuditCaptureReleaseAssets/1","assets":assets},indent=2,sort_keys=True)+"\n")

if __name__=="__main__":
    extract_payload(); records=download_artifacts(); build_release_bundle(records)
    print(json.dumps({"capture_root":str(CAPTURE_ROOT),"payload_sha256":PAYLOAD_SHA256,"artifacts":records},indent=2,sort_keys=True))
