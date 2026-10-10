#!/usr/bin/env python3
from __future__ import annotations
import argparse, base64, hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def sha256(data:bytes)->str: return hashlib.sha256(data).hexdigest()

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--output',required=True); args=ap.parse_args()
    m=json.loads((ROOT/'capture-manifest.json').read_text(encoding='utf-8'))
    chunks=[]
    for part in m['parts']:
        encoded=''
        for seg in part['segments']:
            raw=(ROOT/seg['path']).read_bytes()
            if len(raw)!=seg['encoded_bytes'] or sha256(raw)!=seg['sha256']:
                raise SystemExit(f"archive segment mismatch: {seg['path']}")
            encoded += raw.decode('ascii')
        data=base64.b64decode(''.join(encoded.split()),validate=True)
        if len(data)!=part['decoded_bytes'] or sha256(data)!=part['decoded_sha256']:
            raise SystemExit(f"decoded archive part mismatch: {part['name']}")
        chunks.append(data)
    archive=b''.join(chunks); expected=m['archive']
    if len(archive)!=expected['bytes'] or sha256(archive)!=expected['sha256']:
        raise SystemExit('reconstructed archive identity mismatch')
    Path(args.output).write_bytes(archive); return 0
if __name__=='__main__': raise SystemExit(main())
