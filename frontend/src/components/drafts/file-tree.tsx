"use client";

import { File, FilePlus, Folder, FolderOpen, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { buildFileTree, listFolderPaths, type FileTreeNode } from "@/lib/file-tree";
import { cn } from "@/lib/utils";

// Radix Select rejects an empty-string item value, so root is represented
// by this sentinel in the folder picker and translated back to "" (i.e. no
// prefix) wherever a path gets built from it.
const ROOT_FOLDER = "/";

async function readDroppedFiles(fileList: FileList): Promise<{ name: string; content: string }[]> {
  return Promise.all(
    Array.from(fileList).map(async (file) => ({ name: file.name, content: await file.text() })),
  );
}

/**
 * ui-design.md §9 item 6, §11.1. A plain recursive tree rather than
 * react-arborist — our file sets are small (design.md §4.1's package layout
 * tops out around a dozen files), so virtualization/drag-drop machinery
 * would be pure overhead for no real benefit; native buttons/inputs keep
 * this fully keyboard-accessible without extra work.
 */
export function FileTree({
  files,
  activePath,
  onSelect,
  onCreate,
  onDelete,
  onUploadFile,
  readOnly = false,
}: {
  files: string[];
  activePath: string | null;
  onSelect: (path: string) => void;
  onCreate?: (path: string) => void;
  onDelete?: (path: string) => void;
  /** Fired once per file dropped from the OS onto the tree (or a folder
   * within it) — `path` already has the target folder prefixed on. */
  onUploadFile?: (path: string, content: string) => void;
  readOnly?: boolean;
}) {
  const tree = buildFileTree(files);
  const folderPaths = listFolderPaths(files);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newFolder, setNewFolder] = useState(ROOT_FOLDER);
  const [dragOverFolder, setDragOverFolder] = useState<string | null>(null);

  function submitCreate() {
    const name = newName.trim();
    if (name && onCreate) {
      onCreate(newFolder === ROOT_FOLDER ? name : `${newFolder}/${name}`);
    }
    setNewName("");
    setNewFolder(ROOT_FOLDER);
    setCreating(false);
  }

  async function dropFilesInto(fileList: FileList, folder: string) {
    if (!onUploadFile) return;
    for (const { name, content } of await readDroppedFiles(fileList)) {
      onUploadFile(folder === ROOT_FOLDER ? name : `${folder}/${name}`, content);
    }
  }

  return (
    <div
      className={cn(
        "flex h-full flex-col border-r border-border bg-sidebar",
        dragOverFolder === ROOT_FOLDER && "bg-brand/5",
      )}
      onDragOver={(e) => {
        if (!onUploadFile) return;
        e.preventDefault();
        setDragOverFolder(ROOT_FOLDER);
      }}
      onDragLeave={() => setDragOverFolder((prev) => (prev === ROOT_FOLDER ? null : prev))}
      onDrop={(e) => {
        if (!onUploadFile) return;
        e.preventDefault();
        setDragOverFolder(null);
        void dropFilesInto(e.dataTransfer.files, ROOT_FOLDER);
      }}
    >
      <div className="flex items-center justify-between border-b border-sidebar-border px-3 py-2">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Files
        </span>
        {!readOnly && (
          <Button
            variant="ghost"
            size="icon"
            className="size-6"
            aria-label="New File"
            onClick={() => setCreating(true)}
          >
            <FilePlus className="size-3.5" />
          </Button>
        )}
      </div>

      {creating && (
        <form
          className="space-y-1.5 border-b border-sidebar-border p-2"
          onSubmit={(e) => {
            e.preventDefault();
            submitCreate();
          }}
        >
          {folderPaths.length > 0 && (
            <Select value={newFolder} onValueChange={setNewFolder}>
              <SelectTrigger className="h-7 w-full text-xs" size="sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ROOT_FOLDER}>/ (root)</SelectItem>
                {folderPaths.map((folder) => (
                  <SelectItem key={folder} value={folder} className="font-mono">
                    {folder}/
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <Input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onBlur={submitCreate}
            placeholder="filename.yaml"
            className="h-7 text-xs"
          />
        </form>
      )}

      <div className="flex-1 overflow-y-auto p-1.5">
        {tree.length === 0 ? (
          <p className="p-2 text-xs text-muted-foreground">
            No files yet.{onUploadFile && " Drag files here to add them."}
          </p>
        ) : (
          tree.map((node) => (
            <TreeRow
              key={node.path}
              node={node}
              depth={0}
              activePath={activePath}
              onSelect={onSelect}
              onDelete={onDelete}
              readOnly={readOnly}
              onDropFiles={onUploadFile ? dropFilesInto : undefined}
              dragOverFolder={dragOverFolder}
              setDragOverFolder={setDragOverFolder}
            />
          ))
        )}
      </div>
    </div>
  );
}

function TreeRow({
  node,
  depth,
  activePath,
  onSelect,
  onDelete,
  readOnly,
  onDropFiles,
  dragOverFolder,
  setDragOverFolder,
}: {
  node: FileTreeNode;
  depth: number;
  activePath: string | null;
  onSelect: (path: string) => void;
  onDelete?: (path: string) => void;
  readOnly: boolean;
  onDropFiles?: (fileList: FileList, folder: string) => void;
  dragOverFolder: string | null;
  setDragOverFolder: (folder: string | null) => void;
}) {
  const [open, setOpen] = useState(true);

  if (!node.isFile) {
    return (
      <div>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className={cn(
            "flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-sm text-sidebar-foreground/80 hover:bg-sidebar-accent",
            dragOverFolder === node.path && "bg-brand/10 ring-1 ring-inset ring-brand/40",
          )}
          style={{ paddingLeft: `${depth * 14 + 8}px` }}
          onDragOver={(e) => {
            if (!onDropFiles) return;
            e.preventDefault();
            e.stopPropagation();
            setDragOverFolder(node.path);
          }}
          onDragLeave={() => setDragOverFolder(null)}
          onDrop={(e) => {
            if (!onDropFiles) return;
            e.preventDefault();
            e.stopPropagation();
            setDragOverFolder(null);
            onDropFiles(e.dataTransfer.files, node.path);
          }}
        >
          {open ? <FolderOpen className="size-3.5" /> : <Folder className="size-3.5" />}
          {node.name}
        </button>
        {open &&
          node.children.map((child) => (
            <TreeRow
              key={child.path}
              node={child}
              depth={depth + 1}
              activePath={activePath}
              onSelect={onSelect}
              onDelete={onDelete}
              readOnly={readOnly}
              onDropFiles={onDropFiles}
              dragOverFolder={dragOverFolder}
              setDragOverFolder={setDragOverFolder}
            />
          ))}
      </div>
    );
  }

  const active = node.path === activePath;
  const parentFolder = node.path.includes("/")
    ? node.path.slice(0, node.path.lastIndexOf("/"))
    : ROOT_FOLDER;
  return (
    <div
      className={cn(
        "group flex items-center justify-between rounded px-2 py-1 text-sm",
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground"
          : "text-sidebar-foreground/80 hover:bg-sidebar-accent",
        dragOverFolder === parentFolder && "bg-brand/10 ring-1 ring-inset ring-brand/40",
      )}
      style={{ paddingLeft: `${depth * 14 + 8}px` }}
      onDragOver={(e) => {
        if (!onDropFiles) return;
        e.preventDefault();
        e.stopPropagation();
        setDragOverFolder(parentFolder);
      }}
      onDragLeave={() => setDragOverFolder(null)}
      onDrop={(e) => {
        if (!onDropFiles) return;
        e.preventDefault();
        e.stopPropagation();
        setDragOverFolder(null);
        onDropFiles(e.dataTransfer.files, parentFolder);
      }}
    >
      <button
        type="button"
        onClick={() => onSelect(node.path)}
        className="flex flex-1 items-center gap-1.5 truncate text-left"
      >
        <File className="size-3.5 shrink-0" />
        <span className="truncate">{node.name}</span>
      </button>
      {!readOnly && onDelete && (
        <button
          type="button"
          aria-label={`Delete ${node.name}`}
          className="hidden text-muted-foreground hover:text-danger group-hover:block"
          onClick={() => onDelete(node.path)}
        >
          <Trash2 className="size-3.5" />
        </button>
      )}
    </div>
  );
}
