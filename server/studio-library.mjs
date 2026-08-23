import { access, mkdir, rename } from "node:fs/promises";
import path from "node:path";

export const STUDIO_LIBRARY_DIRECTORY = "Studio Library";
export const LEGACY_RUNTIME_DIRECTORY = "runtime";

export function studioLibraryRoot(dataRoot) {
  return path.join(path.resolve(dataRoot), STUDIO_LIBRARY_DIRECTORY);
}

async function exists(target) {
  try {
    await access(target);
    return true;
  } catch {
    return false;
  }
}

export async function prepareStudioLibrary(dataRoot) {
  const root = path.resolve(dataRoot);
  const libraryRoot = studioLibraryRoot(root);
  const legacyRoot = path.join(root, LEGACY_RUNTIME_DIRECTORY);
  await mkdir(root, { recursive: true });

  if (!(await exists(libraryRoot)) && await exists(legacyRoot)) {
    await rename(legacyRoot, libraryRoot);
    return { library_root: libraryRoot, migrated: true, legacy_root: legacyRoot };
  }

  await mkdir(libraryRoot, { recursive: true });
  return { library_root: libraryRoot, migrated: false, legacy_root: legacyRoot };
}
