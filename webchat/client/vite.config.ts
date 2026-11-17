import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { notices } from "./notices";

export default defineConfig({
  plugins: [react(), notices()],
  server: {
    port: 5173, strictPort: true,
    proxy: { "/api": "http://127.0.0.1:5174" },
  },
});
