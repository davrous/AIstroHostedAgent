import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import { notices } from "./notices";

export default defineConfig({
  publicDir: false,
  plugins: [notices()],
  build: {
    outDir: "dist/teams-widget/v1", emptyOutDir: true,
    lib: {
      entry: fileURLToPath(new URL("./widget/main.ts", import.meta.url)),
      formats: ["iife"], name: "AIstroWidget", fileName: () => "widget.js",
    },
    rollupOptions: { output: { assetFileNames: "widget.[ext]", inlineDynamicImports: true } },
  },
});
