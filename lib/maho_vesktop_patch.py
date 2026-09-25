#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

SECOND_INSTANCE_OLD = (
    'H.app.on("second-instance",(a,c,p,u)=>{u.IS_DEV?H.app.quit():U&&'
    '(U.isMinimized()&&U.restore(),U.isVisible()||U.show(),U.focus())})'
)
SECOND_INSTANCE_NEW = (
    'H.app.on("second-instance",(a,c,p,u)=>{u.IS_DEV?H.app.quit():'
    'globalThis.__mahoVesktopActivate()})'
)

OWNER_ANCHOR = 'Es=!0;H.app.requestSingleInstanceLock({IS_DEV:!1})?zO():'
OWNER_REPLACEMENT = (
    'Es=!0;'
    'globalThis.__mahoVesktopActivate=()=>{U&&'
    '(U.isMinimized()&&U.restore(),U.isVisible()||U.show(),U.focus())};'
    'globalThis.__mahoVesktopSetupControl=()=>{'
    'try{'
    'let n=require("net"),f=require("fs"),s=process.env.MAHO_VESKTOP_CONTROL_SOCKET,'
    'o=process.env.MAHO_VESKTOP_OWNER_FILE;'
    'if(!s)return;'
    'if(f.existsSync(s)){console.error("Maho Vesktop control socket already exists:",s);'
    'process.exit(79)}'
    'let v=n.createServer(c=>{let b="";c.setEncoding("utf8");'
    'c.on("data",d=>{b+=d;if(b.length>8192)c.destroy()});'
    'c.on("end",()=>{try{let q=JSON.parse(b||"{}");'
    'if(q.action==="ping"){c.end(JSON.stringify({ok:true,pid:process.pid})+"\\n");return}'
    'if(q.action==="state"){c.end(JSON.stringify({ok:true,pid:process.pid,'
    'visible:!!U&&U.isVisible(),minimized:!!U&&U.isMinimized()})+"\\n");return}'
    'if(q.action==="hide"){if(U)U.hide();c.end(JSON.stringify({ok:true,pid:process.pid})+"\\n");return}'
    'if(q.action==="minimize"){if(U)U.minimize();c.end(JSON.stringify({ok:true,pid:process.pid})+"\\n");return}'
    'if(q.action==="close"){if(U)U.close();c.end(JSON.stringify({ok:true,pid:process.pid})+"\\n");return}'
    'if(q.action==="activate"){globalThis.__mahoVesktopActivate();'
    'if(typeof q.url==="string"&&q.url.startsWith("discord://")&&U){try{Mc(q.url)}catch{}};'
    'c.end(JSON.stringify({ok:true,pid:process.pid,activated:true})+"\\n");return}'
    'c.end(JSON.stringify({ok:false,error:"unsupported_action"})+"\\n")}'
    'catch(e){c.end(JSON.stringify({ok:false,error:"bad_request"})+"\\n")}})});'
    'globalThis.__mahoVesktopControlServer=v;'
    'v.on("error",e=>{console.error("Maho Vesktop control socket error",e);process.exit(80)});'
    'v.listen(s,()=>{try{f.chmodSync(s,384)}catch{};'
    'console.log("Maho Vesktop control socket listening at",s)});'
    'let x=()=>{try{v.close()}catch{};try{f.unlinkSync(s)}catch{};'
    'if(o)try{f.unlinkSync(o)}catch{}};'
    'H.app.on("before-quit",x);process.on("exit",x)'
    '}catch(e){console.error("Maho Vesktop control setup failed",e);process.exit(80)}};'
    'H.app.requestSingleInstanceLock({IS_DEV:!1})?'
    '(globalThis.__mahoVesktopSetupControl(),zO()):'
)


def patch_main(source: str) -> str:
    if source.count(SECOND_INSTANCE_OLD) != 1:
        raise RuntimeError("unexpected Vesktop second-instance handler shape")
    if source.count(OWNER_ANCHOR) != 1:
        raise RuntimeError("unexpected Vesktop single-instance bootstrap shape")
    patched = source.replace(SECOND_INSTANCE_OLD, SECOND_INSTANCE_NEW, 1)
    patched = patched.replace(OWNER_ANCHOR, OWNER_REPLACEMENT, 1)
    if patched == source:
        raise RuntimeError("Vesktop patch made no changes")
    return patched


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply Maho's bounded Vesktop activation/control patch."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    raw = args.source.read_bytes()
    source = raw.decode("utf-8")
    patched = patch_main(source).encode("utf-8")
    if args.check:
        print(f"source_sha256={sha256_bytes(raw)}")
        print(f"patched_sha256={sha256_bytes(patched)}")
        print(f"source_bytes={len(raw)}")
        print(f"patched_bytes={len(patched)}")
        return 0

    if args.output is None:
        parser.error("output is required unless --check is used")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(patched)
    print(f"source_sha256={sha256_bytes(raw)}")
    print(f"patched_sha256={sha256_bytes(patched)}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
