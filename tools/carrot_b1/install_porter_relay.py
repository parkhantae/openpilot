"""Explicit, parked-only installation of the bundled Porter relay image. No lamp test."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import zipfile

BUNDLE = Path(__file__).with_name('releases') / 'porter-relay-review.zip'
EXPECTED_APP_SHA256 = 'a93dafe606c8427a0292f40b9289ff51d232d5925030c68a3f2d6e836aef0bf8'


def image_bytes():
  with zipfile.ZipFile(BUNDLE) as archive:
    manifest = json.loads(archive.read('manifest.json'))
    image = archive.read('bench-only/CarrotB1Relay-UNCONFIRMED-WIRING.ino.bin')
  actual = hashlib.sha256(image).hexdigest()
  if actual != EXPECTED_APP_SHA256 or actual != manifest['app_sha256']:
    raise ValueError('Bundled application SHA-256 mismatch')
  if hashlib.sha256(image[:-32]).digest() != image[-32:]:
    raise ValueError('ESP application image checksum mismatch')
  if b'carrot-b1-relay-release=1' not in image:
    raise ValueError('Not the expected relay image')
  return image


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--vehicle-contacts-disconnected', action='store_true',
                      help='Confirm both relay contact channels are disconnected from the vehicle')
  parser.add_argument('--check-image', action='store_true', help='Validate files only; no device access')
  args = parser.parse_args()
  image = image_bytes()
  print('Image verified:', EXPECTED_APP_SHA256, flush=True)
  print('Relay profile: GPIO4=left, GPIO5=right, HIGH=ON; max 10s.', flush=True)
  if args.check_image:
    return
  if not args.vehicle_contacts_disconnected:
    parser.error('Disconnect BOTH vehicle relay contact channels before installation')
  if not Path('/TICI').is_file():
    raise RuntimeError('Run this installer on the comma through SSH')
  from .comma_update import update
  # Existing updater enforces offroad OR fresh Park/standstill/disengagement,
  # authenticates the manifest and verifies every acknowledged flash offset.
  # Quiet-bus mode also supports the original CAN firmware, with CAN disconnected.
  asyncio.run(update(image, quiet_bus=True))
  print('OTA transfer verified. Restart comma normally to load the matching BLE v3 host code.', flush=True)
  print('Keep vehicle contact channels disconnected. No relay ON test was issued.', flush=True)


if __name__ == '__main__':
  main()
