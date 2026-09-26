/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";

/*
 * Spec 003, decision 14. The build is the package's static directory; the
 * server serves it from memory under a strict CSP:
 * - emptyOutDir: the directory is entirely Vite output.
 * - assetsInlineLimit 0: no data: URLs, so the CSP needs no `data:`.
 * - modulePreload.polyfill false: no inline script in index.html.
 * - sourcemap false: no .map files ship (X3).
 * - no public/: every shipped file is referenced by index.html and hashed.
 * JSX is compiled by Vite's built-in transform; no React plugin (no fast
 * refresh is needed for a bundle that is committed, not developed live).
 */
export default defineConfig({
  base: "/",
  publicDir: false,
  oxc: {
    jsx: { runtime: "automatic" },
  },
  build: {
    outDir: "../src/tablewatch/webapp/static",
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
    assetsInlineLimit: 0,
    modulePreload: { polyfill: false },
    reportCompressedSize: false,
    // Keep the dependencies' `@license` comments in the shipped bundle.
    rolldownOptions: {
      output: {
        comments: { legal: true },
        minify: { codegen: { legalComments: "inline" } },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // Tests assert absolute times in a fixed zone (O4).
    env: { TZ: "Asia/Singapore" },
    // Process CSS so `?raw` imports return the real stylesheet (the contrast
    // test reads tokens.css; the source-rule test reads every file).
    css: true,
    restoreMocks: true,
    unstubGlobals: true,
  },
});
