import { readFile, realpath, stat } from "node:fs/promises";
import path from "node:path";

export const GLOBAL_CHROME_CONTRACT_ROLE = "global_chrome_contract";

const STANDARD_GLOBAL_CHROME_CONTRACT_NAMES = [
  "全稿标题系统合同.json",
  "global_chrome_contract.json",
];

function inside(root, target) {
  const relative = path.relative(root, target);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

function registeredContractPaths(sources) {
  if (!Array.isArray(sources)) return [];
  return sources
    .filter((source) => source?.role === GLOBAL_CHROME_CONTRACT_ROLE)
    .map((source) => source?.path)
    .filter((value) => typeof value === "string" && path.isAbsolute(value));
}

function looksLikeAuthorizedGlobalChromeContract(value) {
  return Boolean(
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Number.isInteger(value.global_chrome_contract_version) &&
    value.authorization?.status === "authorized" &&
    value.deck_title_system?.enabled === true,
  );
}

async function authorizedContract(candidate, projectRoot) {
  try {
    const [rootReal, candidateReal] = await Promise.all([
      realpath(projectRoot),
      realpath(candidate),
    ]);
    if (!inside(rootReal, candidateReal)) return null;
    const info = await stat(candidateReal);
    if (!info.isFile()) return null;
    const parsed = JSON.parse(await readFile(candidateReal, "utf8"));
    return looksLikeAuthorizedGlobalChromeContract(parsed) ? candidateReal : null;
  } catch {
    return null;
  }
}

export async function discoverProjectGenerationSources({
  projectRoot,
  outlinePath,
  registeredSources = [],
}) {
  if (
    typeof projectRoot !== "string" ||
    !path.isAbsolute(projectRoot) ||
    typeof outlinePath !== "string" ||
    !path.isAbsolute(outlinePath)
  ) return [];

  const directories = [
    ...new Set([path.dirname(outlinePath), projectRoot].map((value) => path.resolve(value))),
  ];
  const candidates = [
    ...registeredContractPaths(registeredSources),
    ...directories.flatMap((directory) =>
      STANDARD_GLOBAL_CHROME_CONTRACT_NAMES.map((name) => path.join(directory, name))),
  ];

  for (const candidate of [...new Set(candidates.map((value) => path.resolve(value)))]) {
    const contractPath = await authorizedContract(candidate, projectRoot);
    if (contractPath) {
      return [{
        role: GLOBAL_CHROME_CONTRACT_ROLE,
        scope: "deck",
        path: contractPath,
      }];
    }
  }
  return [];
}

export function sameProjectGenerationSources(left, right) {
  return JSON.stringify(Array.isArray(left) ? left : []) ===
    JSON.stringify(Array.isArray(right) ? right : []);
}
