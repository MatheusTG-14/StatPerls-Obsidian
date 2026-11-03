// Copies the built plugin into the vault (vault/.obsidian/plugins/statpearls/). The user enables it in Obsidian.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dest = join(root, "..", "vault", ".obsidian", "plugins", "statpearls");
mkdirSync(dest, { recursive: true });
for (const f of ["main.js", "manifest.json", "styles.css"]) {
  if (existsSync(join(root, f))) copyFileSync(join(root, f), join(dest, f));
}
console.log(`installed to ${dest}`);
