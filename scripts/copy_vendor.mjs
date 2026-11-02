// Copia as bibliotecas de front-end para static/vendor (servidas localmente, sem CDN).
// Usa copyFileSync porque o cpSync do Node 24 falha no Windows ao sobrescrever um arquivo.
import { copyFileSync, mkdirSync } from "node:fs";

const target = "static/vendor";
const font = "node_modules/@fontsource-variable/inter/files";
const displayFont = "node_modules/@fontsource-variable/space-grotesk/files";
mkdirSync(`${target}/fonts`, { recursive: true });

copyFileSync("node_modules/htmx.org/dist/htmx.min.js", `${target}/htmx.min.js`);
copyFileSync("node_modules/alpinejs/dist/cdn.min.js", `${target}/alpine.min.js`);
copyFileSync(`${font}/inter-latin-wght-normal.woff2`, `${target}/fonts/inter-latin-wght-normal.woff2`);
copyFileSync(`${font}/inter-latin-ext-wght-normal.woff2`, `${target}/fonts/inter-latin-ext-wght-normal.woff2`);
for (const file of ["space-grotesk-latin-wght-normal.woff2", "space-grotesk-latin-ext-wght-normal.woff2"]) {
  copyFileSync(`${displayFont}/${file}`, `${target}/fonts/${file}`);
}
