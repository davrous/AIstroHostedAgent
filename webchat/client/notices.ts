import { readFileSync } from "node:fs";
import type { Plugin } from "vite";

export function notices(): Plugin {
  return {
    name: "aistro-viewer-notices",
    apply: "build",
    generateBundle() {
      const source = ["@babylonjs/core/license.md", "zod/LICENSE"]
        .map(name => `${name}\n\n${readFileSync(new URL(`../node_modules/${name}`, import.meta.url), "utf8")}`)
        .join("\n\n----------------------------------------\n\n");
      this.emitFile({ type: "asset", fileName: "viewer-licenses.txt", source });
    },
  };
}
