/**
 * electron-builder afterPack hook.
 *
 * We disable electron-builder's built-in ``signAndEditExecutable`` because
 * its winCodeSign extraction step requires admin-level privileges on
 * Windows (it tries to materialize macOS .dylib symlinks during 7-Zip
 * extraction). That flag also gates icon embedding, so without it the
 * shipped .exe carries the default Electron icon and the taskbar shows
 * the wrong logo.
 *
 * This hook runs after electron-builder has produced the unpacked .exe
 * but before NSIS bundles it into the installer. It invokes
 * ``app-builder rcedit`` (already shipped inside ``app-builder-bin``) to
 * embed the project icon into the .exe icon resources, which Windows
 * uses for the taskbar / start menu / file explorer entries.
 */

const path = require("node:path");
const fs = require("node:fs");

module.exports = async function embedIcon(context) {
  if (process.platform !== "win32" && context.electronPlatformName !== "win32") {
    return;
  }

  const exeName = `${context.packager.appInfo.productFilename}.exe`;
  const exePath = path.join(context.appOutDir, exeName);
  if (!fs.existsSync(exePath)) {
    console.warn(`[embed-icon] skipped — exe not found at ${exePath}`);
    return;
  }

  const repoRoot = path.resolve(__dirname, "..", "..");
  const iconPath = path.join(repoRoot, "packaging", "NexGen-BBPro.ico");
  if (!fs.existsSync(iconPath)) {
    console.warn(`[embed-icon] skipped — icon not found at ${iconPath}`);
    return;
  }

  // Standalone rcedit npm package — bundles rcedit-x64.exe directly so we
  // skip electron-builder's winCodeSign download (which requires admin to
  // extract macOS dylib symlinks via 7-Zip). v5 is ESM-only, so we use
  // dynamic import from this CommonJS hook.
  const { rcedit } = await import("rcedit");
  const productName = context.packager.appInfo.productName;
  console.log(
    `[embed-icon] embedding ${path.basename(iconPath)} into ${exeName}`,
  );
  await rcedit(exePath, {
    icon: iconPath,
    "version-string": {
      ProductName: productName,
      FileDescription: productName,
    },
  });
};
