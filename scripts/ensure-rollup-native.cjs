#!/usr/bin/env node

const { execFileSync } = require("node:child_process");
const { createRequire } = require("node:module");
const path = require("node:path");
const process = require("node:process");

const workspacePath = process.argv[2] || "apps/web";

if (process.platform !== "linux") {
  process.exit(0);
}

const packageBaseByArch = {
  arm: {
    gnu: "linux-arm-gnueabihf",
    musl: "linux-arm-musleabihf",
  },
  arm64: {
    gnu: "linux-arm64-gnu",
    musl: "linux-arm64-musl",
  },
  loong64: {
    gnu: "linux-loong64-gnu",
    musl: "linux-loong64-musl",
  },
  ppc64: {
    gnu: "linux-ppc64-gnu",
    musl: "linux-ppc64-musl",
  },
  riscv64: {
    gnu: "linux-riscv64-gnu",
    musl: "linux-riscv64-musl",
  },
  s390x: {
    gnu: "linux-s390x-gnu",
  },
  x64: {
    gnu: "linux-x64-gnu",
    musl: "linux-x64-musl",
  },
};

function isMusl() {
  try {
    const previousExcludeNetwork = process.report.excludeNetwork;
    process.report.excludeNetwork = true;
    const header = process.report.getReport().header;
    process.report.excludeNetwork = previousExcludeNetwork;
    return !header.glibcVersionRuntime;
  } catch {
    return false;
  }
}

const libc = isMusl() ? "musl" : "gnu";
const packageBase = packageBaseByArch[process.arch]?.[libc];

if (!packageBase) {
  process.exit(0);
}

const nativePackageName = `@rollup/rollup-${packageBase}`;
const workspaceRequire = createRequire(
  path.resolve(workspacePath, "package.json"),
);

try {
  workspaceRequire(nativePackageName);
} catch (error) {
  if (error?.code !== "MODULE_NOT_FOUND") {
    throw error;
  }

  const rollupVersion = workspaceRequire("rollup/package.json").version;

  execFileSync(
    "npm",
    [
      "install",
      "--no-save",
      "--package-lock=false",
      "--include=optional",
      `${nativePackageName}@${rollupVersion}`,
    ],
    { stdio: "inherit" },
  );
}
