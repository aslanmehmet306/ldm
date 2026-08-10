// The parser lives inside docs/index.html and must stay there: the page is published as a
// single self-contained file with no external references. Rather than split it into a module
// and break that guarantee, the tests extract the pure-logic half of the script block —
// everything before the rendering section, which is the first code to touch the DOM — write
// it to a temporary module, and import that.
import {readFileSync, writeFileSync, mkdtempSync} from "node:fs";
import {fileURLToPath, pathToFileURL} from "node:url";
import {dirname, join} from "node:path";
import {tmpdir} from "node:os";

const here = dirname(fileURLToPath(import.meta.url));
export const PARSER_FILE = join(here, "..", "docs", "index.html");

const RENDER_MARKER = "/* ------------------------------------------------------------------ rendering */";
const EXPORTS = ["parseLDM","parseSI","parseBlock","parseFlightRecord","normalise","validate",
                 "CLASS_LABELS","LOAD_CATEGORIES"];

function extract(){
  const html = readFileSync(PARSER_FILE, "utf8");
  const block = html.match(/<script>([\s\S]*?)<\/script>/);
  if(!block) throw new Error("no <script> block found in docs/index.html");
  const cut = block[1].indexOf(RENDER_MARKER);
  if(cut === -1) throw new Error("rendering marker not found — has the file been restructured?");
  return block[1].slice(0, cut);
}

const dir = mkdtempSync(join(tmpdir(), "ldm-parser-"));
const mod = join(dir, "parser.mjs");
writeFileSync(mod, extract() + "\nexport {" + EXPORTS.join(", ") + "};\n");

export const parser = await import(pathToFileURL(mod).href);
export const {parseLDM} = parser;

// Convenience: parse and return the single destination block alongside the full result.
export function only(raw){
  const p = parseLDM(raw);
  if(p.result.destinations.length !== 1)
    throw new Error("expected exactly one destination block, got " +
      p.result.destinations.length);
  return {...p, d: p.result.destinations[0]};
}

// Did any check of this level mention the given text?
export function checkFor(p, level, text){
  return p.checks.some(([lvl,msg]) => lvl===level && msg.includes(text));
}
