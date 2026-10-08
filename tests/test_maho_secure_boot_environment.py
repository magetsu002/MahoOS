#!/usr/bin/env python3
from pathlib import Path
import hashlib,sys,tempfile,unittest,uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from maho_secure_boot import EFI_GLOBAL_GUID,EFI_IMAGE_SECURITY_DATABASE_GUID,inspect_boot_environment
SHA_GUID='c1c41626-504c-4092-aca9-41f936934328'

def signature_list(data=b'd'*32,kind=SHA_GUID):
    size=16+len(data)
    return uuid.UUID(kind).bytes_le+(28+size).to_bytes(4,'little')+b'\0'*4+size.to_bytes(4,'little')+uuid.UUID(int=0).bytes_le+data

def put(root,name,namespace,payload):
    (root/(name+'-'+namespace)).write_bytes(b'\7\0\0\0'+payload)

class BootEnvironmentInspectionContracts(unittest.TestCase):
    def test_firmware_database_namespaces_are_distinct_and_exact(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw)
            for name in ('PK','KEK'):put(root,name,EFI_GLOBAL_GUID,signature_list())
            for name in ('db','dbx'):
                put(root,name,EFI_IMAGE_SECURITY_DATABASE_GUID,signature_list())
                put(root,name,EFI_GLOBAL_GUID,signature_list(b'x'*32))
            state=inspect_boot_environment(efivar_root=root)
            expected=('efi-signature:'+SHA_GUID+':sha256:'+hashlib.sha256(b'd'*32).hexdigest(),)
            self.assertEqual(state.db_fingerprints,expected);self.assertEqual(state.dbx_fingerprints,expected)
            self.assertEqual(state.pk_fingerprints,expected);self.assertEqual(state.kek_fingerprints,expected)
            self.assertIsNone(state.actual_efi_image)
    def test_global_namespace_shadows_cannot_supply_missing_image_databases(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);put(root,'db',EFI_GLOBAL_GUID,signature_list())
            state=inspect_boot_environment(efivar_root=root)
            self.assertIsNone(state.db_fingerprints);self.assertIn('db_fingerprints',state.missing_evidence)
    def test_malformed_or_invalid_certificates_remain_missing_evidence(self):
        for payload in (b'truncated',signature_list()[:-1],signature_list(b'not-an-x509','a5c059a1-94e4-4aa7-87b5-ab155c2bf072')):
            with self.subTest(payload=payload),tempfile.TemporaryDirectory() as raw:
                root=Path(raw);put(root,'db',EFI_IMAGE_SECURITY_DATABASE_GUID,payload)
                state=inspect_boot_environment(efivar_root=root)
                self.assertIsNone(state.db_fingerprints);self.assertIn('db_fingerprints',state.missing_evidence)

if __name__=='__main__':unittest.main(verbosity=2)
