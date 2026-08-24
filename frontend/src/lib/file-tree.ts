export type FileTreeNode = {
  name: string;
  path: string;
  isFile: boolean;
  children: FileTreeNode[];
};

/** Converts a flat list of relative paths (as returned by DraftResponse.files
 * — design.md §4.1's package layout, potentially nested under tests/,
 * examples/) into a nested tree for display. Directories are synthesized
 * from path segments; there's no separate "create empty folder" concept
 * since the backend only stores files (drafts/store.py has no directory
 * entities of its own). */
export function buildFileTree(paths: string[]): FileTreeNode[] {
  const root: FileTreeNode = { name: "", path: "", isFile: false, children: [] };

  for (const path of [...paths].sort()) {
    const segments = path.split("/");
    let cursor = root;
    let accumulated = "";
    segments.forEach((segment, i) => {
      accumulated = accumulated ? `${accumulated}/${segment}` : segment;
      const isFile = i === segments.length - 1;
      let child = cursor.children.find((c) => c.name === segment);
      if (!child) {
        child = { name: segment, path: accumulated, isFile, children: [] };
        cursor.children.push(child);
      }
      cursor = child;
    });
  }

  return root.children;
}

/** Every distinct directory implied by `paths` (e.g. `["schemas/input.json"]`
 * -> `["schemas"]`), sorted — used to offer "create in…"/"drop in…" folder
 * targets without the backend needing a separate directory concept. */
export function listFolderPaths(paths: string[]): string[] {
  const folders = new Set<string>();
  for (const path of paths) {
    const segments = path.split("/");
    let accumulated = "";
    for (let i = 0; i < segments.length - 1; i++) {
      accumulated = accumulated ? `${accumulated}/${segments[i]}` : segments[i];
      folders.add(accumulated);
    }
  }
  return Array.from(folders).sort();
}
