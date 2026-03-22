#!/bin/bash
set -e

SIGN_IDENTITY="Developer ID Application: Ian Mironov (WHY6PAKA5V)"
NOTARYTOOL_PROFILE="ouroboros-notarize"
ENTITLEMENTS="entitlements.plist"

APP_PATH="dist/Ouroboros.app"
DMG_NAME="Ouroboros-$(cat VERSION | tr -d '[:space:]').dmg"
DMG_PATH="dist/$DMG_NAME"

echo "=== Building Ouroboros.app ==="

if [ ! -f "python-standalone/bin/python3" ]; then
    echo "ERROR: python-standalone/ not found."
    echo "Run first: bash scripts/download_python_standalone.sh"
    exit 1
fi

echo "--- Installing launcher dependencies ---"
pip install -q -r requirements-launcher.txt

echo "--- Installing agent dependencies into python-standalone ---"
python-standalone/bin/pip3 install -q -r requirements.txt

echo "--- Normalizing python-standalone symlinks for PyInstaller ---"
python3 - <<'PY'
import pathlib
import shutil

root = pathlib.Path("python-standalone")
replaced = 0

for path in sorted(root.rglob("*")):
    if not path.is_symlink():
        continue
    target = path.resolve()
    path.unlink()
    if target.is_dir():
        shutil.copytree(target, path)
    else:
        shutil.copy2(target, path)
    replaced += 1

print(f"Replaced {replaced} symlinks in python-standalone")
PY

rm -rf build dist

export PYINSTALLER_CONFIG_DIR="$PWD/.pyinstaller-cache"
mkdir -p "$PYINSTALLER_CONFIG_DIR"

echo "--- Running PyInstaller ---"
python3 -m PyInstaller Ouroboros.spec --clean --noconfirm

echo ""
echo "=== Signing Ouroboros.app ==="

echo "--- Finding and signing all Mach-O binaries ---"
find "$APP_PATH" -type f | while read -r f; do
    if file "$f" | grep -q "Mach-O"; then
        codesign -s "$SIGN_IDENTITY" --timestamp --force --options runtime \
            --entitlements "$ENTITLEMENTS" "$f" 2>&1 || true
    fi
done
echo "Signed embedded binaries"

echo "--- Signing the app bundle ---"
codesign -s "$SIGN_IDENTITY" --timestamp --force --options runtime \
    --entitlements "$ENTITLEMENTS" "$APP_PATH"

echo "--- Verifying signature ---"
codesign -dvv "$APP_PATH"
codesign --verify --strict "$APP_PATH"
echo "Signature OK"

echo ""
echo "=== Notarizing app ==="

echo "--- Creating ZIP for notarization ---"
ditto -c -k --keepParent "$APP_PATH" dist/Ouroboros-notarize.zip

echo "--- Submitting to Apple (this may take several minutes) ---"
xcrun notarytool submit dist/Ouroboros-notarize.zip \
    --keychain-profile "$NOTARYTOOL_PROFILE" \
    --wait

echo "--- Stapling notarization ticket to app ---"
xcrun stapler staple "$APP_PATH"

rm -f dist/Ouroboros-notarize.zip

echo ""
echo "=== Creating DMG ==="
hdiutil create -volname Ouroboros -srcfolder "$APP_PATH" -ov -format UDZO "$DMG_PATH"

codesign -s "$SIGN_IDENTITY" --timestamp "$DMG_PATH"

echo "--- Notarizing DMG ---"
xcrun notarytool submit "$DMG_PATH" \
    --keychain-profile "$NOTARYTOOL_PROFILE" \
    --wait

xcrun stapler staple "$DMG_PATH"

echo ""
echo "=== Done ==="
echo "Signed & notarized app: $APP_PATH"
echo "Signed & notarized DMG: $DMG_PATH"
