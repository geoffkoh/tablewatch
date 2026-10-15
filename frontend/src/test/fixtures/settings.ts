/**
 * `GET /api/v1/settings`'s shape (spec 040 S-D1), typed against the
 * generated contract so a wire change breaks `tsc` here.
 */
import type { Settings } from "../../api/types";

/** A clean, fully-configured project: the base every test starts from and overrides. */
export const baseSettings: Settings = {
  project: {
    name: "retail-example",
    version: "0.1.0",
    loaded_at: "2026-09-26T06:56:50.000000+00:00",
    checks_path: "checks",
  },
  datasources: [
    { name: "lake", type: "duckdb", datasets: 3, checks: 18 },
    { name: "lake2", type: "postgresql", datasets: 0, checks: 0 },
  ],
  notifiers: [
    { name: "ops", type: "slack", url_variable: "OPS_SLACK" },
    { name: "hook", type: "webhook", url_variable: "HOOK_URL" },
  ],
  results: {
    dialect: "sqlite",
    schema: "current",
    revision: "a1b2c3d4e5f6",
    head: "a1b2c3d4e5f6",
    migrate: "auto",
    sync: "on_run",
  },
  checks: { active: 16, disabled: 2, retired: 0 },
};
