// design.md §4.1's canonical package layout (manifest.yaml, schema.json,
// permissions.yaml, dependencies.yaml, prompt.md, executor.py/js/wasm,
// README.md, changelog.md) plus the handful of other text formats likely to
// show up under tests/ or examples/ once dragged/created — each maps to one
// of Monaco's built-in tokenizers so keywords/strings/comments actually get
// distinct colors instead of falling back to flat "plaintext".
const EXTENSION_LANGUAGE: Record<string, string> = {
  yaml: "yaml",
  yml: "yaml",
  json: "json",
  py: "python",
  js: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  jsx: "javascript",
  ts: "typescript",
  tsx: "typescript",
  md: "markdown",
  mdx: "markdown",
  sh: "shell",
  bash: "shell",
  toml: "ini",
  ini: "ini",
  cfg: "ini",
  sql: "sql",
  html: "html",
  css: "css",
  scss: "css",
  xml: "xml",
  rst: "restructuredtext",
  txt: "plaintext",
  wasm: "plaintext",
};

// Files matched by exact name rather than extension — most have none.
const BASENAME_LANGUAGE: Record<string, string> = {
  dockerfile: "dockerfile",
  makefile: "shell",
};

export function languageForPath(path: string): string {
  const basename = (path.split("/").pop() ?? "").toLowerCase();
  if (BASENAME_LANGUAGE[basename]) return BASENAME_LANGUAGE[basename];
  const ext = basename.includes(".") ? basename.split(".").pop()! : "";
  return EXTENSION_LANGUAGE[ext] ?? "plaintext";
}
